"""Meeting CRUD API endpoints."""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.models.database import Meeting, PreGeneratedAnswer, TranscriptEntry, User, get_db
from app.models.schemas import (
    MeetingCreate, MeetingResponse, MeetingUpdate, TranscriptEntryResponse,
    PreGenQuestionCreate, PreGenQuestionUpdate, PreGenQuestionResponse,
)
from app.api.auth import get_optional_user

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


def _meeting_id() -> str:
    now = datetime.now()
    return now.strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:6]


def _get_owned_meeting(meeting_id: str, user: User | None, db: Session) -> Meeting:
    """Fetch meeting and verify the caller has access."""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    if user and meeting.user_id and meeting.user_id != user.id:
        raise HTTPException(403, "Access denied")
    return meeting


@router.post("", response_model=MeetingResponse, status_code=201)
def create_meeting(body: MeetingCreate, request: Request, db: Session = Depends(get_db)):
    user = get_optional_user(request, db)
    meeting = Meeting(
        id=_meeting_id(),
        user_id=user.id if user else None,
        name=body.name,
        mode=body.mode,
        language=body.language,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    return _to_response(meeting)


@router.get("", response_model=list[MeetingResponse])
def list_meetings(request: Request, db: Session = Depends(get_db)):
    user = get_optional_user(request, db)
    q = db.query(Meeting)
    if user:
        q = q.filter(Meeting.user_id == user.id)
    meetings = q.order_by(Meeting.created_at.desc()).all()
    return [_to_response(m) for m in meetings]


@router.get("/{meeting_id}", response_model=MeetingResponse)
def get_meeting(meeting_id: str, request: Request, db: Session = Depends(get_db)):
    user = get_optional_user(request, db)
    meeting = _get_owned_meeting(meeting_id, user, db)
    return _to_response(meeting)


@router.patch("/{meeting_id}", response_model=MeetingResponse)
def update_meeting(meeting_id: str, body: MeetingUpdate, request: Request, db: Session = Depends(get_db)):
    user = get_optional_user(request, db)
    meeting = _get_owned_meeting(meeting_id, user, db)
    if body.name is not None:
        meeting.name = body.name
    if body.mode is not None:
        meeting.mode = body.mode
    if body.status is not None:
        meeting.status = body.status
    meeting.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(meeting)
    return _to_response(meeting)


@router.delete("/{meeting_id}", status_code=204)
def delete_meeting(meeting_id: str, request: Request, db: Session = Depends(get_db)):
    user = get_optional_user(request, db)
    meeting = _get_owned_meeting(meeting_id, user, db)
    db.delete(meeting)
    db.commit()


@router.get("/{meeting_id}/transcript", response_model=list[TranscriptEntryResponse])
def get_transcript(meeting_id: str, request: Request, source: str | None = None, db: Session = Depends(get_db)):
    user = get_optional_user(request, db)
    _get_owned_meeting(meeting_id, user, db)
    q = db.query(TranscriptEntry).filter(TranscriptEntry.meeting_id == meeting_id)
    if source:
        q = q.filter(TranscriptEntry.source == source)
    entries = q.order_by(TranscriptEntry.timestamp).all()
    return entries


@router.get("/{meeting_id}/transcript/export")
def export_transcript(meeting_id: str, request: Request, format: str = "txt", db: Session = Depends(get_db)):
    user = get_optional_user(request, db)
    meeting = _get_owned_meeting(meeting_id, user, db)
    entries = (
        db.query(TranscriptEntry)
        .filter(TranscriptEntry.meeting_id == meeting_id)
        .order_by(TranscriptEntry.timestamp)
        .all()
    )
    if format == "html":
        html_parts = [
            "<!DOCTYPE html><html><head><meta charset='utf-8'>",
            "<style>body{font-family:system-ui;max-width:800px;margin:40px auto;padding:0 20px;background:#fafafa;color:#333}",
            ".entry{padding:8px 12px;margin:4px 0;border-radius:8px;background:#fff;border:1px solid #eee}",
            ".speaker{font-weight:600;color:#2563eb;font-size:12px;margin-bottom:2px}",
            ".time{color:#999;font-size:10px;float:right}",
            ".text{font-size:14px;line-height:1.6}",
            ".vi{font-size:12px;color:#888;margin-top:2px}",
            "h1{font-size:20px;border-bottom:2px solid #2563eb;padding-bottom:8px}</style></head><body>",
            f"<h1>{meeting.name}</h1>",
        ]
        for e in entries:
            html_parts.append(f'<div class="entry">')
            html_parts.append(f'<div class="speaker">{e.speaker} <span class="time">{e.timestamp}</span></div>')
            html_parts.append(f'<div class="text">{e.text}</div>')
            if e.translation_vi:
                html_parts.append(f'<div class="vi">[VI] {e.translation_vi}</div>')
            html_parts.append('</div>')
        html_parts.append("</body></html>")
        return {"html": "\n".join(html_parts), "filename": f"transcript_{meeting_id}.html"}
    else:
        lines = []
        for e in entries:
            prefix = f"[{e.speaker}] " if e.speaker else ""
            lines.append(f"{prefix}{e.text}")
            if e.translation_vi:
                lines.append(f"  [VI] {e.translation_vi}")
        return {"text": "\n".join(lines), "filename": f"transcript_{meeting_id}.txt"}


@router.post("/{meeting_id}/strategy-chat")
def strategy_chat(meeting_id: str, request: Request, body: dict, db: Session = Depends(get_db)):
    """AI-powered strategy chat with meeting context."""
    user = get_optional_user(request, db)
    _get_owned_meeting(meeting_id, user, db)

    from app.core.config import settings
    valid = [m for m in settings.MODEL_REGISTRY if m.is_valid()]
    if not valid:
        raise HTTPException(503, "No LLM configured")

    model = valid[0]
    from openai import AzureOpenAI
    client = AzureOpenAI(
        api_key=model.key, azure_endpoint=model.endpoint,
        api_version="2025-01-01-preview",
    )

    message = body.get("message", "")
    context = body.get("context", {})
    history = body.get("history", [])

    system = (
        "You are a meeting strategy advisor. Based on the meeting context, "
        "help the user prepare answers, develop talking points, and strategize. "
        "Be concise and actionable. Answer in the same language the user uses."
    )
    if context.get("transcript"):
        system += f"\n\nRecent transcript:\n{context['transcript'][:3000]}"
    if context.get("notes"):
        system += f"\n\nUser notes:\n{context['notes'][:2000]}"
    if context.get("company"):
        system += f"\n\nCompany/JD info:\n{context['company'][:2000]}"

    messages = [{"role": "system", "content": system}]
    for h in history[-10:]:
        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})

    try:
        resp = client.chat.completions.create(
            model=model.deployment,
            messages=messages,
            max_completion_tokens=800,
            temperature=0.7,
        )
        reply = resp.choices[0].message.content or ""
    except Exception as e:
        err = str(e).lower()
        if "temperature" in err or "unsupported" in err:
            resp = client.chat.completions.create(
                model=model.deployment,
                messages=messages,
                max_completion_tokens=800,
            )
            reply = resp.choices[0].message.content or ""
        else:
            raise HTTPException(500, f"LLM error: {str(e)[:100]}")

    return {"reply": reply}


# ── PreGen Question CRUD ─────────────────────────────────────

@router.get("/{meeting_id}/pregen")
def list_pregen(meeting_id: str, request: Request, db: Session = Depends(get_db)):
    user = get_optional_user(request, db)
    _get_owned_meeting(meeting_id, user, db)
    rows = db.query(PreGeneratedAnswer).filter(
        PreGeneratedAnswer.meeting_id == meeting_id,
    ).order_by(PreGeneratedAnswer.id).all()
    return [
        PreGenQuestionResponse(
            id=r.id,
            question=r.question_ja,
            language=r.language or "ja-JP",
            has_answer=bool(r.answer_romaji or r.answer_vi),
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post("/{meeting_id}/pregen", status_code=201)
def add_pregen(meeting_id: str, body: PreGenQuestionCreate, request: Request, db: Session = Depends(get_db)):
    user = get_optional_user(request, db)
    _get_owned_meeting(meeting_id, user, db)
    entry = PreGeneratedAnswer(
        meeting_id=meeting_id,
        question_ja=body.question,
        language=body.language,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return PreGenQuestionResponse(
        id=entry.id,
        question=entry.question_ja,
        language=entry.language or "ja-JP",
        has_answer=False,
        created_at=entry.created_at,
    )


@router.put("/{meeting_id}/pregen/{question_id}")
def update_pregen(meeting_id: str, question_id: int, body: PreGenQuestionUpdate, request: Request, db: Session = Depends(get_db)):
    user = get_optional_user(request, db)
    _get_owned_meeting(meeting_id, user, db)
    entry = db.query(PreGeneratedAnswer).filter(
        PreGeneratedAnswer.id == question_id,
        PreGeneratedAnswer.meeting_id == meeting_id,
    ).first()
    if not entry:
        raise HTTPException(404, "Question not found")
    if body.question is not None:
        entry.question_ja = body.question
        entry.answer_romaji = ""
        entry.answer_vi = ""
        entry.embedding = None
    if body.language is not None:
        entry.language = body.language
    db.commit()
    db.refresh(entry)
    return PreGenQuestionResponse(
        id=entry.id,
        question=entry.question_ja,
        language=entry.language or "ja-JP",
        has_answer=bool(entry.answer_romaji or entry.answer_vi),
        created_at=entry.created_at,
    )


@router.delete("/{meeting_id}/pregen/{question_id}", status_code=204)
def delete_pregen(meeting_id: str, question_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_optional_user(request, db)
    _get_owned_meeting(meeting_id, user, db)
    entry = db.query(PreGeneratedAnswer).filter(
        PreGeneratedAnswer.id == question_id,
        PreGeneratedAnswer.meeting_id == meeting_id,
    ).first()
    if not entry:
        raise HTTPException(404, "Question not found")
    db.delete(entry)
    db.commit()
    return None


@router.post("/{meeting_id}/pregen/defaults")
def load_pregen_defaults(meeting_id: str, request: Request, body: dict, db: Session = Depends(get_db)):
    """Load default questions for a language, skipping duplicates."""
    user = get_optional_user(request, db)
    _get_owned_meeting(meeting_id, user, db)
    language = body.get("language", "ja-JP")

    from app.services.pregen import get_default_questions
    defaults = get_default_questions(language)

    existing = db.query(PreGeneratedAnswer.question_ja).filter(
        PreGeneratedAnswer.meeting_id == meeting_id,
    ).all()
    existing_set = {q[0] for q in existing}

    added = []
    for q in defaults:
        if q not in existing_set:
            entry = PreGeneratedAnswer(
                meeting_id=meeting_id, question_ja=q, language=language,
            )
            db.add(entry)
            added.append(q)
    db.commit()
    return {"added": len(added), "total": len(defaults)}


@router.post("/{meeting_id}/pregen/generate")
def generate_pregen_answers(meeting_id: str, request: Request, db: Session = Depends(get_db)):
    """Trigger background generation of answers for all unanswered questions."""
    user = get_optional_user(request, db)
    meeting = _get_owned_meeting(meeting_id, user, db)

    import threading
    from app.services.pregen import PreGenEngine
    from app.core.config import settings as app_settings

    engine = PreGenEngine(meeting_id, language=meeting.language)

    valid_models = [m for m in app_settings.MODEL_REGISTRY if m.is_valid()]
    if not valid_models:
        raise HTTPException(503, "No LLM configured")

    def _bg():
        try:
            system_prompt = (
                "You are a helpful interview preparation assistant. "
                "Generate a concise, professional answer for the given question."
            )
            engine.generate_common(system_prompt=system_prompt)
        except Exception as e:
            import sys
            print(f"  [PREGEN-API] generate error: {e}", file=sys.stderr)

    threading.Thread(target=_bg, daemon=True, name="pregen-api-gen").start()
    return {"status": "generating"}


def _to_response(m: Meeting) -> MeetingResponse:
    return MeetingResponse(
        id=m.id,
        name=m.name,
        mode=m.mode,
        language=m.language,
        status=m.status,
        created_at=m.created_at,
        updated_at=m.updated_at,
        transcript_count=len(m.transcript_entries),
    )
