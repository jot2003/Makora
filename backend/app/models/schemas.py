"""Pydantic schemas for API request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


# ── Meeting ───────────────────────────────────────────────────

class MeetingCreate(BaseModel):
    name: str
    mode: Literal["interview", "meeting"] = "interview"
    language: str = "ja-JP"


class MeetingUpdate(BaseModel):
    name: str | None = None
    mode: Literal["interview", "meeting"] | None = None
    status: Literal["created", "active", "completed"] | None = None


class MeetingResponse(BaseModel):
    id: str
    name: str
    mode: str
    language: str
    status: str
    created_at: datetime
    updated_at: datetime
    transcript_count: int = 0

    class Config:
        from_attributes = True


# ── Transcript ────────────────────────────────────────────────

class TranscriptEntryResponse(BaseModel):
    id: int
    timestamp: datetime
    speaker: str
    language: str
    source: str
    text: str
    romaji: str
    translation_vi: str
    answer_vi: str
    answer_romaji: str

    class Config:
        from_attributes = True


# ── Intelligence (Phase 4) ────────────────────────────────────

class Decision(BaseModel):
    decision: str
    reason: str = ""
    context: str = ""


class ActionItem(BaseModel):
    task: str
    owner: str = ""
    deadline: str = ""
    priority: Literal["high", "medium", "low"] = "medium"


class TimelineSegment(BaseModel):
    time: str
    duration: str = ""
    topic: str
    summary: str = ""


class MeetingSummary(BaseModel):
    overview: str
    key_topics: list[str] = []
    decisions: list[Decision] = []
    risks: list[str] = []
    next_steps: list[str] = []


# ── RAG Chat (Phase 5) ───────────────────────────────────────

class ChatRequest(BaseModel):
    query: str
    meeting_ids: list[str] | None = None


class SourceCitation(BaseModel):
    meeting_id: str
    meeting_name: str = ""
    speaker: str = ""
    time: str = ""
    text: str = ""


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceCitation] = []


class SearchRequest(BaseModel):
    query: str


class SearchResult(BaseModel):
    meeting_id: str
    meeting_name: str = ""
    speaker: str = ""
    time: str = ""
    text: str = ""
    score: float = 0.0
