"""Context / Notes / Glossary / Documents API for per-session data."""

import os
import shutil
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import DOCS_DIR
from app.models.database import (
    Meeting, SessionNote, GlossaryEntry, SessionDocument, get_db,
)
from app.services.documents import extract_text_from_file

router = APIRouter(prefix="/api/meetings/{meeting_id}", tags=["context"])


def _get_meeting(meeting_id: str, db: Session) -> Meeting:
    m = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not m:
        raise HTTPException(404, "Meeting not found")
    return m


# ── Notes ─────────────────────────────────────────────────────

class NoteBody(BaseModel):
    content: str


class NoteResponse(BaseModel):
    id: int
    category: str
    content: str

    class Config:
        from_attributes = True


@router.get("/notes", response_model=list[NoteResponse])
def list_notes(meeting_id: str, db: Session = Depends(get_db)):
    _get_meeting(meeting_id, db)
    notes = db.query(SessionNote).filter(SessionNote.meeting_id == meeting_id).all()
    return notes


@router.get("/notes/{category}", response_model=NoteResponse)
def get_note(meeting_id: str, category: str, db: Session = Depends(get_db)):
    _get_meeting(meeting_id, db)
    note = db.query(SessionNote).filter(
        SessionNote.meeting_id == meeting_id, SessionNote.category == category
    ).first()
    if not note:
        note = SessionNote(meeting_id=meeting_id, category=category, content="")
        db.add(note)
        db.commit()
        db.refresh(note)
    return note


@router.put("/notes/{category}", response_model=NoteResponse)
def update_note(meeting_id: str, category: str, body: NoteBody, db: Session = Depends(get_db)):
    _get_meeting(meeting_id, db)
    note = db.query(SessionNote).filter(
        SessionNote.meeting_id == meeting_id, SessionNote.category == category
    ).first()
    if not note:
        note = SessionNote(meeting_id=meeting_id, category=category, content=body.content)
        db.add(note)
    else:
        note.content = body.content
        note.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(note)
    return note


# ── Glossary ──────────────────────────────────────────────────

class GlossaryBody(BaseModel):
    jp: str
    reading: str = ""
    vi: str = ""


class GlossaryResponse(BaseModel):
    id: int
    jp: str
    reading: str
    vi: str

    class Config:
        from_attributes = True


@router.get("/glossary", response_model=list[GlossaryResponse])
def list_glossary(meeting_id: str, db: Session = Depends(get_db)):
    _get_meeting(meeting_id, db)
    return db.query(GlossaryEntry).filter(GlossaryEntry.meeting_id == meeting_id).all()


@router.post("/glossary", response_model=GlossaryResponse, status_code=201)
def add_glossary(meeting_id: str, body: GlossaryBody, db: Session = Depends(get_db)):
    _get_meeting(meeting_id, db)
    entry = GlossaryEntry(meeting_id=meeting_id, jp=body.jp, reading=body.reading, vi=body.vi)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/glossary/{entry_id}", status_code=204)
def delete_glossary(meeting_id: str, entry_id: int, db: Session = Depends(get_db)):
    _get_meeting(meeting_id, db)
    entry = db.query(GlossaryEntry).filter(
        GlossaryEntry.id == entry_id, GlossaryEntry.meeting_id == meeting_id
    ).first()
    if not entry:
        raise HTTPException(404, "Glossary entry not found")
    db.delete(entry)
    db.commit()


# ── Documents ─────────────────────────────────────────────────

class DocumentResponse(BaseModel):
    id: int
    filename: str
    category: str
    uploaded_at: datetime

    class Config:
        from_attributes = True


@router.get("/documents", response_model=list[DocumentResponse])
def list_documents(meeting_id: str, db: Session = Depends(get_db)):
    _get_meeting(meeting_id, db)
    return db.query(SessionDocument).filter(SessionDocument.meeting_id == meeting_id).all()


@router.post("/documents", response_model=DocumentResponse, status_code=201)
async def upload_document(
    meeting_id: str,
    file: UploadFile = File(...),
    category: str = Form("personal"),
    db: Session = Depends(get_db),
):
    _get_meeting(meeting_id, db)

    meeting_dir = DOCS_DIR / meeting_id
    meeting_dir.mkdir(parents=True, exist_ok=True)
    filepath = meeting_dir / file.filename
    with open(filepath, "wb") as f:
        content = await file.read()
        f.write(content)

    extracted = extract_text_from_file(str(filepath))

    doc = SessionDocument(
        meeting_id=meeting_id,
        filename=file.filename,
        category=category,
        extracted_text=extracted,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(meeting_id: str, doc_id: int, db: Session = Depends(get_db)):
    _get_meeting(meeting_id, db)
    doc = db.query(SessionDocument).filter(
        SessionDocument.id == doc_id, SessionDocument.meeting_id == meeting_id
    ).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    filepath = DOCS_DIR / meeting_id / doc.filename
    if filepath.exists():
        filepath.unlink()
    db.delete(doc)
    db.commit()
