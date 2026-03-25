"""Meeting CRUD API endpoints."""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.models.database import Meeting, TranscriptEntry, get_db
from app.models.schemas import MeetingCreate, MeetingResponse, MeetingUpdate, TranscriptEntryResponse
from app.api.auth import get_optional_user

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


def _meeting_id() -> str:
    now = datetime.now()
    return now.strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:6]


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
def get_meeting(meeting_id: str, db: Session = Depends(get_db)):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    return _to_response(meeting)


@router.patch("/{meeting_id}", response_model=MeetingResponse)
def update_meeting(meeting_id: str, body: MeetingUpdate, db: Session = Depends(get_db)):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(404, "Meeting not found")
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
def delete_meeting(meeting_id: str, db: Session = Depends(get_db)):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    db.delete(meeting)
    db.commit()


@router.get("/{meeting_id}/transcript", response_model=list[TranscriptEntryResponse])
def get_transcript(meeting_id: str, source: str | None = None, db: Session = Depends(get_db)):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    q = db.query(TranscriptEntry).filter(TranscriptEntry.meeting_id == meeting_id)
    if source:
        q = q.filter(TranscriptEntry.source == source)
    entries = q.order_by(TranscriptEntry.timestamp).all()
    return entries


@router.get("/{meeting_id}/transcript/export")
def export_transcript(meeting_id: str, format: str = "txt", db: Session = Depends(get_db)):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(404, "Meeting not found")
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
