"""Post-meeting intelligence API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.models.database import Meeting, TranscriptEntry, get_db
from app.models.schemas import MeetingSummary, ActionItem, TimelineSegment, Decision
from app.services.intelligence import (
    generate_summary,
    extract_action_items,
    generate_timeline,
    extract_decisions,
)

router = APIRouter(prefix="/api/meetings", tags=["intelligence"])


def _get_transcript_dicts(meeting_id: str, db: Session) -> list[dict]:
    entries = (
        db.query(TranscriptEntry)
        .filter(TranscriptEntry.meeting_id == meeting_id)
        .order_by(TranscriptEntry.timestamp)
        .all()
    )
    return [
        {
            "time": str(e.timestamp),
            "speaker": e.speaker,
            "text": e.text,
            "romaji": e.romaji,
            "translation_vi": e.translation_vi,
        }
        for e in entries
    ]


@router.post("/{meeting_id}/summary", response_model=MeetingSummary)
def get_summary(meeting_id: str, db: Session = Depends(get_db)):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    entries = _get_transcript_dicts(meeting_id, db)
    if not entries:
        raise HTTPException(400, "No transcript entries to analyze")
    result = generate_summary(entries, mode=meeting.mode)
    return MeetingSummary(**result)


@router.post("/{meeting_id}/actions", response_model=list[ActionItem])
def get_actions(meeting_id: str, db: Session = Depends(get_db)):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    entries = _get_transcript_dicts(meeting_id, db)
    if not entries:
        raise HTTPException(400, "No transcript entries to analyze")
    return extract_action_items(entries)


@router.post("/{meeting_id}/timeline", response_model=list[TimelineSegment])
def get_timeline(meeting_id: str, db: Session = Depends(get_db)):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    entries = _get_transcript_dicts(meeting_id, db)
    if not entries:
        raise HTTPException(400, "No transcript entries to analyze")
    return generate_timeline(entries)


@router.post("/{meeting_id}/decisions", response_model=list[Decision])
def get_decisions(meeting_id: str, db: Session = Depends(get_db)):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    entries = _get_transcript_dicts(meeting_id, db)
    if not entries:
        raise HTTPException(400, "No transcript entries to analyze")
    return extract_decisions(entries)
