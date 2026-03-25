"""WebSocket event schemas for realtime communication."""

from __future__ import annotations
from typing import Literal

from pydantic import BaseModel


# ── Client → Server ──────────────────────────────────────────

class StartMeetingEvent(BaseModel):
    type: Literal["start_meeting"] = "start_meeting"
    meeting_id: str
    language: str = "ja-JP"
    mode: Literal["interview", "meeting"] = "interview"


class StopMeetingEvent(BaseModel):
    type: Literal["stop_meeting"] = "stop_meeting"


class ManualAnswerEvent(BaseModel):
    type: Literal["manual_answer"] = "manual_answer"
    text: str
    ai_refine: bool = True
    context_only: bool = False


class SwitchLanguageEvent(BaseModel):
    type: Literal["switch_language"] = "switch_language"
    language: str


class PinSuggestionEvent(BaseModel):
    type: Literal["pin_suggestion"] = "pin_suggestion"
    id: str


class DismissSuggestionEvent(BaseModel):
    type: Literal["dismiss_suggestion"] = "dismiss_suggestion"
    id: str


class RequestSuggestionEvent(BaseModel):
    type: Literal["request_suggestion"] = "request_suggestion"


class PingEvent(BaseModel):
    type: Literal["ping"] = "ping"


# ── Server → Client ──────────────────────────────────────────

class InterimEvent(BaseModel):
    type: Literal["interim"] = "interim"
    text: str
    romaji: str = ""
    speaker: str = ""
    confidence: Literal["partial", "stable"] = "partial"


class FinalEvent(BaseModel):
    type: Literal["final"] = "final"
    text: str
    romaji: str = ""
    speaker: str = ""
    confidence: Literal["final"] = "final"


class TranslationEvent(BaseModel):
    type: Literal["translation"] = "translation"
    vi: str
    speaker: str = ""
    confidence: Literal["final", "tentative"] = "final"


class SuggestionStartEvent(BaseModel):
    type: Literal["suggestion_start"] = "suggestion_start"


class SuggestionChunkEvent(BaseModel):
    type: Literal["suggestion_chunk"] = "suggestion_chunk"
    field: Literal["answer_romaji", "answer_vi"]
    chunk: str


class SuggestionDoneEvent(BaseModel):
    type: Literal["suggestion_done"] = "suggestion_done"
    id: str
    answer_romaji: str = ""
    answer_vi: str = ""


class SuggestionKeepEvent(BaseModel):
    type: Literal["suggestion_keep"] = "suggestion_keep"


class NowDiscussingEvent(BaseModel):
    type: Literal["now_discussing"] = "now_discussing"
    topic: str


class StatusEvent(BaseModel):
    type: Literal["status"] = "status"
    message: str


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str


class PongEvent(BaseModel):
    type: Literal["pong"] = "pong"
