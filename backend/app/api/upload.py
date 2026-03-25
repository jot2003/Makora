"""Upload API: accept audio/video files for offline transcription + full pipeline."""

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import AUDIO_DIR
from app.models.database import Meeting, TranscriptEntry, get_db
from app.services.transcribe_file import transcribe_file

router = APIRouter(prefix="/api", tags=["upload"])

ALLOWED_EXTENSIONS = {".mp4", ".mp3", ".wav", ".m4a", ".webm", ".mkv", ".avi", ".mov", ".flac", ".ogg"}


def _auto_index(meeting_id: str):
    """Background task: build FAISS index after transcription."""
    try:
        from app.services.embedding import chunk_transcript, build_faiss_index, save_index
        import app.models.database as _db

        db = _db.SessionLocal()
        entries = (
            db.query(_db.TranscriptEntry)
            .filter(_db.TranscriptEntry.meeting_id == meeting_id)
            .order_by(_db.TranscriptEntry.timestamp)
            .all()
        )
        if not entries:
            db.close()
            return

        dicts = [
            {"meeting_id": meeting_id, "speaker": e.speaker, "text": e.text, "time": str(e.timestamp)}
            for e in entries
        ]
        db.close()

        chunks = chunk_transcript(dicts)
        if chunks:
            index, metadata = build_faiss_index(chunks)
            save_index(meeting_id, index, metadata)
            print(f"  [AUTO-INDEX] {meeting_id}: {len(chunks)} chunks indexed")
    except Exception as e:
        print(f"  [AUTO-INDEX ERR] {meeting_id}: {e}")


@router.post("/upload")
async def upload_audio(
    file: UploadFile = File(...),
    meeting_id: str | None = Form(None),
    meeting_name: str | None = Form(None),
    language: str = Form("ja"),
    mode: str = Form("meeting"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
):
    """Upload audio/video → transcribe with speaker diarization → save to DB.

    Full pipeline: upload → convert → Azure STT (or Whisper fallback) → DB.
    """
    if not file.filename:
        raise HTTPException(400, "No filename")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported format: {ext}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}")

    if not meeting_id:
        meeting_id = f"upload_{uuid.uuid4().hex[:8]}"

    name = meeting_name or file.filename or "Uploaded Recording"

    existing = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not existing:
        meeting = Meeting(
            id=meeting_id,
            name=name,
            mode=mode,
            language=language,
            status="completed",
        )
        db.add(meeting)
        db.commit()

    save_path = AUDIO_DIR / f"{meeting_id}{ext}"
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    result = transcribe_file(str(save_path), meeting_id, language=language)

    if result["status"] == "error":
        raise HTTPException(500, result.get("message", "Transcription failed"))

    background_tasks.add_task(_auto_index, meeting_id)

    transcript_count = db.query(TranscriptEntry).filter(
        TranscriptEntry.meeting_id == meeting_id
    ).count()

    return {
        "meeting_id": meeting_id,
        "filename": file.filename,
        "segments": result.get("segments", 0),
        "duration": result.get("duration", 0.0),
        "method": result.get("method", "unknown"),
        "speakers": result.get("speakers", []),
        "transcript_count": transcript_count,
        "status": "transcribed",
    }


@router.get("/meetings/{meeting_id}/transcript/export")
def export_transcript(meeting_id: str, db: Session = Depends(get_db)):
    """Export transcript as formatted text."""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    entries = (
        db.query(TranscriptEntry)
        .filter(TranscriptEntry.meeting_id == meeting_id)
        .order_by(TranscriptEntry.timestamp)
        .all()
    )

    if not entries:
        raise HTTPException(400, "No transcript entries")

    lines = []
    lines.append(f"Meeting: {meeting.name}")
    lines.append(f"Mode: {meeting.mode}")
    lines.append(f"Language: {meeting.language}")
    lines.append(f"Entries: {len(entries)}")
    lines.append("=" * 60)
    lines.append("")

    current_speaker = None
    for entry in entries:
        if entry.speaker != current_speaker:
            lines.append("")
            lines.append(f"--- {entry.speaker} ---")
            current_speaker = entry.speaker
        lines.append(f"  {entry.text}")
        if entry.translation_vi:
            lines.append(f"  [VI] {entry.translation_vi}")

    return {"text": "\n".join(lines), "entries": len(entries)}
