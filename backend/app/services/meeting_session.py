"""MeetingSession: lifecycle manager for a realtime meeting.

Wires together Audio, STT, LLM and sends events to the WebSocket.
One session per WebSocket connection.
"""

import asyncio
import json
import re
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from app.services.stt import StreamingSTT
from app.services.audio import DualAudioCapture
from app.services.llm import LLMEngine
from app.services.stabilizer import StabilizedPipeline
from app.services.suggestion import SuggestionController, Turn
from app.services.diarizer import SpeakerDiarizer
from app.services.pregen import PreGenEngine
from app.core.config import settings
import app.models.database as _db_module

_LANGUAGES = {
    "ja-JP": {"name": "Japanese", "has_romaji": True},
    "en-US": {"name": "English", "has_romaji": False},
    "vi-VN": {"name": "Vietnamese", "has_romaji": False},
    "zh-CN": {"name": "Chinese", "has_romaji": False},
    "ko-KR": {"name": "Korean", "has_romaji": False},
}

_MERGE_GAP_S = 1.5  # legacy, unused in simplified mapper
_RARE_THRESHOLD = 0.10  # legacy, unused in simplified mapper

_OBVIOUS_QUESTION_JA = re.compile(
    r'(?:ですか|ますか|でしょうか|ください|お願いします|ませんか|'
    r'教えてください|聞かせてください|お話しください)[。？]?$|[？?]$'
)
_OBVIOUS_QUESTION_EN = re.compile(r'\?$')
_OBVIOUS_QUESTION_VI = re.compile(
    r'(?:là gì|như thế nào|ra sao|thế nào|được không|'
    r'chưa|không|chứ|nhỉ|hả|nhé|vậy|ạ)[.?]?$|[?]$'
)
_MIN_BYPASS_CHARS = 15


def _get_obvious_q_re(language: str) -> re.Pattern:
    if language.startswith("ja"):
        return _OBVIOUS_QUESTION_JA
    if language.startswith("vi"):
        return _OBVIOUS_QUESTION_VI
    return _OBVIOUS_QUESTION_EN

def _seed_default_questions(meeting_id: str, language: str, questions: list[str]):
    """Insert default questions into DB if none exist for this meeting+language."""
    try:
        db = _db_module.SessionLocal()
        existing = db.query(_db_module.PreGeneratedAnswer).filter(
            _db_module.PreGeneratedAnswer.meeting_id == meeting_id,
        ).count()
        if existing == 0:
            for q in questions:
                entry = _db_module.PreGeneratedAnswer(
                    meeting_id=meeting_id,
                    question_ja=q,
                    language=language,
                )
                db.add(entry)
            db.commit()
        db.close()
    except Exception as e:
        print(f"  [PREGEN] seed error: {e}", file=sys.stderr)


_COST_PER_1M: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-5.3-chat": (15.00, 60.00),
}
_DEFAULT_COST = (5.00, 15.00)


class SmartSpeakerMapper:
    """Maps Azure ConversationTranscriber speaker IDs to stable display labels.

    Uses direct 1:1 mapping — trusts Azure's speaker_id without merging.
    Only applies a max_speakers safety cap.
    """

    def __init__(self, mode: str = "interview", max_speakers: int = 0):
        self._mode = mode
        self._max_speakers = max_speakers or (2 if mode == "interview" else 5)
        self._id_to_label: dict[str, str] = {}
        self._label_counter = 0
        self._last_ts: dict[str, float] = {}

    def set_max_speakers(self, n: int):
        if n >= 1:
            self._max_speakers = n

    def map(self, speaker_id: str) -> str:
        if speaker_id == "me":
            return "me"

        now = time.time()
        self._last_ts[speaker_id] = now

        if speaker_id == "Unknown" and self._id_to_label:
            nearest = self._find_nearest_label(now)
            if nearest:
                return nearest

        if speaker_id in self._id_to_label:
            return self._id_to_label[speaker_id]

        unique_labels = set(self._id_to_label.values())
        if len(unique_labels) >= self._max_speakers:
            nearest = self._find_nearest_label(now)
            if nearest:
                self._id_to_label[speaker_id] = nearest
                return nearest

        self._label_counter += 1
        prefix = "Interviewer" if self._mode == "interview" else "Speaker"
        label = f"{prefix} {self._label_counter}"
        self._id_to_label[speaker_id] = label
        print(f"  [MAPPER] New speaker: {speaker_id} -> {label}", file=sys.stderr)
        return label

    def _find_nearest_label(self, now: float) -> str:
        best_label = ""
        best_gap = float("inf")
        seen: set[str] = set()
        for raw_id, lbl in self._id_to_label.items():
            if lbl in seen:
                continue
            seen.add(lbl)
            gap = now - self._last_ts.get(raw_id, 0)
            if gap < best_gap:
                best_gap = gap
                best_label = lbl
        return best_label


class MeetingSession:
    """Manages audio → STT → LLM pipeline for one meeting."""

    def __init__(self, send_fn, meeting_id: str, language: str = "ja-JP", mode: str = "interview"):
        self._send_fn = send_fn
        self.meeting_id = meeting_id
        self.language = language
        self.mode = mode

        self._stt: StreamingSTT | None = None
        self._audio: DualAudioCapture | None = None
        self._llm: LLMEngine | None = None
        self._stabilizer: StabilizedPipeline | None = None
        self._suggestion_ctrl: SuggestionController | None = None
        self._running = False
        self._suggestions_enabled = True
        self._current_is_auto = False

        self._diarizer: SpeakerDiarizer | None = None
        self._speaker_mapper = SmartSpeakerMapper(mode=mode)
        self._near_final_ts = 0.0
        self._suggestion_counter = 0
        self._active_line_id: str = ""
        self._loop: asyncio.AbstractEventLoop | None = None
        self._diarizer_pool: ThreadPoolExecutor | None = None
        self._obvious_q_re = _get_obvious_q_re(language)
        self._pregen: PreGenEngine | None = None

    # -- Public API --

    def start(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._running = True

        if not settings.AZURE_SPEECH_KEY or not settings.AZURE_SPEECH_REGION:
            self._emit({"type": "error", "message": "Missing Azure Speech credentials"})
            return

        self._stabilizer = StabilizedPipeline(
            emit_fn=self._emit,
            throttle_ms=300,
            min_change_chars=3,
            translation_final_only=True,
            merge_window_ms=3000,
            prefix_lock_ratio=0.6,
        )

        self._suggestion_ctrl = SuggestionController(
            mode=self.mode,
            on_suggest=self._on_suggest_turn,
            on_topic=lambda topic: self._emit({"type": "now_discussing", "topic": topic}) if self._suggestions_enabled else None,
            language=self.language,
            cooldown_ms=1500,
        )

        translator_key = settings.AZURE_TRANSLATOR_KEY
        translator_region = settings.AZURE_TRANSLATOR_REGION or settings.AZURE_SPEECH_REGION

        self._stt = StreamingSTT(
            settings.AZURE_SPEECH_KEY,
            settings.AZURE_SPEECH_REGION,
            source_language=self.language,
            translator_key=translator_key,
            translator_region=translator_region,
            on_interim=self._on_interim,
            on_final=self._on_final,
            on_near_final=self._on_near_final,
            on_translation=self._on_translation,
            on_status=lambda msg: self._emit({"type": "status", "message": msg}),
            on_error=lambda msg: self._emit({"type": "error", "message": msg}),
        )

        try:
            self._diarizer = SpeakerDiarizer(
                mode=self.mode,
                max_speakers=2 if self.mode == "interview" else 5,
            )
            self._emit({"type": "status", "message": "Speaker diarizer loading..."})
        except Exception as e:
            print(f"  [DIARIZER] Init failed, using heuristic fallback: {e}", file=sys.stderr)
            self._diarizer = None

        energy_threshold = settings.ENERGY_THRESHOLD
        self._audio = DualAudioCapture(
            self._stt.push_stream_lb,
            self._stt.push_stream_mic,
            push_stream_lb_shadow=self._stt.push_stream_lb_shadow,
            energy_threshold=energy_threshold,
            on_status=lambda msg: self._emit({"type": "status", "message": msg}),
            on_error=lambda msg: self._emit({"type": "error", "message": msg}),
            on_lb_audio=self._on_lb_audio,
            echo_gate_enabled=True,
        )

        if settings.AZURE_OPENAI_KEY and settings.AZURE_OPENAI_ENDPOINT and settings.AZURE_OPENAI_DEPLOYMENT:
            lang_info = _LANGUAGES.get(self.language, _LANGUAGES["ja-JP"])
            self._llm = LLMEngine(
                settings.AZURE_OPENAI_KEY,
                settings.AZURE_OPENAI_ENDPOINT,
                settings.AZURE_OPENAI_DEPLOYMENT,
                fast_deployment=settings.AZURE_OPENAI_FAST_DEPLOYMENT,
                on_tier2_result=self._on_tier2_result,
                on_answer_streaming=self._on_answer_streaming,
                on_manual_result=self._on_manual_result,
                on_error=lambda msg: self._emit({"type": "error", "message": msg}),
                on_usage=self._on_llm_usage,
            )
            self._llm.set_language(lang_info["name"], lang_info["has_romaji"])
            self._load_session_context()
            self._llm.start()
        else:
            self._emit({"type": "status", "message": "LLM disabled (no Azure OpenAI keys)"})

        self._stt.start()
        self._audio.start()

        self._start_pregen_for_language(self.language)

        self._emit({"type": "status", "message": f"Meeting {self.meeting_id} started ({self.mode}, {self.language})"})

    def stop(self):
        self._running = False

        audio, stt = self._audio, self._stt
        llm, diarizer = self._llm, self._diarizer
        pool = self._diarizer_pool

        self._audio = self._stt = self._llm = self._diarizer = None
        self._stabilizer = self._suggestion_ctrl = self._pregen = None
        self._diarizer_pool = None
        self._speaker_mapper = SmartSpeakerMapper(mode=self.mode)

        self._emit({"type": "status", "message": "Meeting stopped"})

        def _cleanup():
            for name, obj in [("audio", audio), ("stt", stt), ("llm", llm), ("diarizer", diarizer)]:
                if obj:
                    try:
                        obj.stop()
                    except Exception as e:
                        print(f"  [STOP] {name} cleanup: {e}", file=sys.stderr)
            if pool:
                try:
                    pool.shutdown(wait=False)
                except Exception:
                    pass

        threading.Thread(target=_cleanup, daemon=True, name="session-cleanup").start()

    def switch_language(self, new_language: str):
        if not self._stt or not self._audio:
            return
        if new_language == self.language:
            return

        self._emit({"type": "language_switching", "language": new_language})
        old_language = self.language
        self.language = new_language

        self._stt.switch_language(new_language)
        self._audio.update_streams(
            self._stt.push_stream_lb,
            self._stt.push_stream_mic,
            self._stt.push_stream_lb_shadow,
        )

        lang_info = _LANGUAGES.get(new_language, _LANGUAGES["ja-JP"])
        if self._llm:
            self._llm.set_language(lang_info["name"], lang_info["has_romaji"])

        self._obvious_q_re = _get_obvious_q_re(new_language)

        if self._suggestion_ctrl:
            self._suggestion_ctrl.set_language(new_language)

        if self._pregen:
            self._pregen = None
        self._start_pregen_for_language(new_language)

        self._emit({"type": "language_switched", "language": new_language})

    def _start_pregen_for_language(self, language: str):
        if not self._llm:
            return
        lang_info = _LANGUAGES.get(language, _LANGUAGES.get("ja-JP"))
        if not lang_info:
            return
        lang_name = lang_info["name"]
        self._pregen = PreGenEngine(self.meeting_id, language=language)
        sys_prompt = self._llm._build_system_prompt(lang_name)

        def _bg_pregen():
            try:
                if not self._running or not self._pregen:
                    return
                from app.services.pregen import get_default_questions
                _seed_default_questions(self.meeting_id, language, get_default_questions(language))
                self._pregen.load_from_db()
                if not self._running or not self._pregen:
                    return
                if not self._pregen.ready:
                    self._pregen.generate_common(
                        system_prompt=sys_prompt,
                        personal_info=self._llm._personal_info if self._llm else "",
                        company_info=self._llm._company_info if self._llm else "",
                    )
            except Exception as e:
                print(f"  [PREGEN] background error: {e}", file=sys.stderr)

        threading.Thread(target=_bg_pregen, daemon=True, name="pregen-init").start()

    def handle_manual_answer(self, text: str, ai_refine: bool = True):
        if self._llm:
            self._emit({"type": "suggestion_start", "line_id": ""})
            self._llm.enqueue_manual(text, ai_refine)

    def handle_elaborate(self, previous_answer: str, original_question: str):
        if self._llm:
            self._emit({"type": "suggestion_start", "line_id": "", "is_elaborate": True})
            self._llm.enqueue_elaborate(previous_answer, original_question)

    def handle_request_suggestion(self, text: str, romaji: str, line_id: str, length=None):
        """User explicitly requested a suggestion for a specific transcript line."""
        if not self._llm:
            self._emit({
                "type": "suggestion_done",
                "line_id": line_id,
                "id": f"sg_{line_id}",
                "answer_romaji": "",
                "answer_vi": "[LLM not available]",
            })
            return

        if not length and self._pregen and self._pregen.ready:
            cached = self._pregen.match_question(text)
            if cached:
                self._suggestion_counter += 1
                sg_id = f"sg_{self._suggestion_counter}"
                self._emit({"type": "suggestion_start", "line_id": line_id})
                if cached.get("answer_romaji"):
                    self._emit({"type": "suggestion_chunk", "line_id": line_id, "field": "answer_romaji", "chunk": cached["answer_romaji"]})
                if cached.get("answer_vi"):
                    self._emit({"type": "suggestion_chunk", "line_id": line_id, "field": "answer_vi", "chunk": cached["answer_vi"]})
                self._emit({"type": "suggestion_done", "line_id": line_id, "id": sg_id, "answer_romaji": cached.get("answer_romaji", ""), "answer_vi": cached.get("answer_vi", "")})
                return

        self._active_line_id = line_id
        self._current_is_auto = False
        self._emit({"type": "suggestion_start", "line_id": line_id})
        self._llm.enqueue(text, romaji, "")

    def switch_model(self, model_id: str) -> str:
        """Switch the LLM to a model from registry or a DB provider (db:<id>)."""
        if model_id.startswith("db:"):
            return self._switch_to_db_provider(int(model_id.split(":", 1)[1]))

        for m in settings.MODEL_REGISTRY:
            if m.deployment == model_id and m.is_valid():
                if self._llm:
                    self._llm.switch_model(m.key, m.endpoint, m.deployment)
                    self._emit({"type": "status", "message": f"Switched to {m.label}"})
                return m.deployment
        self._emit({"type": "error", "message": f"Model {model_id} not found"})
        return self._llm.get_active_model() if self._llm else ""

    def _switch_to_db_provider(self, provider_id: int) -> str:
        """Switch LLM to a user-configured provider stored in DB."""
        from app.models.database import AIProvider, SessionLocal
        db = SessionLocal()
        try:
            p = db.query(AIProvider).filter(AIProvider.id == provider_id).first()
            if not p or not p.api_key or not p.endpoint or not p.deployment:
                self._emit({"type": "error", "message": "Provider not found or incomplete"})
                return self._llm.get_active_model() if self._llm else ""
            if self._llm:
                self._llm.switch_model(p.api_key, p.endpoint, p.deployment)
                self._emit({"type": "status", "message": f"Switched to {p.name or p.deployment}"})
            return p.deployment
        finally:
            db.close()

    def set_suggestions_enabled(self, enabled: bool):
        self._suggestions_enabled = enabled
        print(f"  [AI TOGGLE] suggestions={'ON' if enabled else 'OFF'}", file=sys.stderr)
        if not enabled:
            self._current_is_auto = False
            if self._llm:
                self._llm._low_queue.clear()
                self._llm._low_cancel.set()
            if self._suggestion_ctrl:
                self._suggestion_ctrl.clear()

    def set_answer_length(self, length):
        if self._llm:
            self._llm.set_answer_length(length)
            self._emit({"type": "status", "message": f"Answer length: {length} sentences"})

    def set_jp_level(self, level: str):
        if self._llm:
            self._llm.set_jp_level(level)
            self._emit({"type": "status", "message": f"JP level: {level}"})

    def append_context_note(self, text: str):
        """Append text to the general session notes (context-only mode)."""
        try:
            db = _db_module.SessionLocal()
            from app.models.database import SessionNote
            note = db.query(SessionNote).filter(
                SessionNote.meeting_id == self.meeting_id,
                SessionNote.category == "general",
            ).first()
            if note:
                note.content = (note.content or "") + "\n" + text
            else:
                note = SessionNote(meeting_id=self.meeting_id, category="general", content=text)
                db.add(note)
            db.commit()
            db.close()
        except Exception as e:
            print(f"  [DB ERR] append context note: {e}", file=sys.stderr)

    def _load_session_context(self):
        """Load notes, glossary, and document keywords into LLM system prompt and STT phrase list."""
        try:
            db = _db_module.SessionLocal()
            from app.models.database import SessionNote, GlossaryEntry, SessionDocument
            from app.services.documents import extract_keywords

            notes = db.query(SessionNote).filter(SessionNote.meeting_id == self.meeting_id).all()
            glossary = db.query(GlossaryEntry).filter(GlossaryEntry.meeting_id == self.meeting_id).all()
            docs = db.query(SessionDocument).filter(SessionDocument.meeting_id == self.meeting_id).all()
            db.close()

            personal_text = ""
            company_text = ""
            general_context = ""
            for note in notes:
                if note.content and note.content.strip():
                    if note.category == "personal":
                        personal_text += note.content.strip() + "\n"
                    elif note.category == "company":
                        company_text += note.content.strip() + "\n"
                    else:
                        general_context += note.content.strip() + "\n"

            for doc in docs:
                if doc.extracted_text and doc.extracted_text.strip():
                    snippet = doc.extracted_text[:2000]
                    if doc.category == "personal":
                        personal_text += f"\n[{doc.filename}]\n{snippet}\n"
                    elif doc.category == "company":
                        company_text += f"\n[{doc.filename}]\n{snippet}\n"
                    else:
                        general_context += f"\n[{doc.filename}]\n{snippet}\n"

            glossary_dicts = [{"jp": g.jp, "reading": g.reading, "vi": g.vi} for g in glossary]

            if self._llm and (personal_text or company_text or glossary_dicts or general_context):
                self._llm.set_context(personal_text.strip(), company_text.strip(), glossary_dicts, general_context.strip())

            phrases = [g.jp for g in glossary if g.jp]
            all_doc_text = " ".join(d.extracted_text or "" for d in docs)
            phrases.extend(extract_keywords(all_doc_text, max_keywords=100))

            if phrases and self._stt and hasattr(self._stt, 'set_phrase_list'):
                self._stt.set_phrase_list(phrases)

            loaded = sum(1 for n in notes if n.content and n.content.strip())
            if loaded or glossary or docs:
                self._emit({"type": "status", "message": f"Loaded context: {loaded} notes, {len(glossary)} glossary, {len(docs)} docs"})
        except Exception as e:
            print(f"  [WARN] Could not load session context: {e}", file=sys.stderr)

    # -- Internal helpers --

    def set_max_speakers(self, n: int):
        self._speaker_mapper.set_max_speakers(n)
        if self._diarizer:
            self._diarizer.set_max_speakers(n)

    def _map_speaker_fast(self, speaker_id: str) -> str:
        """Fast mapping for interims -- direct 1:1 via SmartSpeakerMapper."""
        return self._speaker_mapper.map(speaker_id)

    def _map_speaker(self, speaker_id: str) -> str:
        """Full mapping for finals -- SmartSpeakerMapper + optional async diarizer for future improvement."""
        label = self._speaker_mapper.map(speaker_id)
        if self._diarizer and self._diarizer.ready and speaker_id != "me":
            if self._diarizer_pool is None:
                self._diarizer_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="diarizer")
            def _identify():
                try:
                    self._diarizer.identify_speaker(duration_s=3.0)
                except Exception as e:
                    print(f"  [DIARIZER] async identify error: {e}", file=sys.stderr)
            try:
                self._diarizer_pool.submit(_identify)
            except RuntimeError:
                pass
        return label

    def _on_lb_audio(self, pcm_bytes: bytes):
        """Feed loopback audio to the diarizer."""
        if self._diarizer:
            self._diarizer.push_audio(pcm_bytes)

    def _emit(self, data: dict):
        if not self._running and data.get("type") != "status":
            return
        try:
            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(self._send_fn(data), self._loop)
            else:
                loop = asyncio.get_running_loop()
                asyncio.run_coroutine_threadsafe(self._send_fn(data), loop)
        except Exception as e:
            if self._running:
                print(f"  [EMIT ERR] {data.get('type','?')}: {e}", file=sys.stderr)

    # -- STT callbacks (routed through stabilizer) --

    def _on_interim(self, text: str, romaji: str, speaker_id: str):
        if not self._running:
            return
        label = self._map_speaker_fast(speaker_id)
        if self._stabilizer:
            self._stabilizer.on_interim(text, romaji, label)
        else:
            self._emit({"type": "interim", "text": text, "romaji": romaji, "speaker": label, "confidence": "partial"})

    def _is_obvious_complete_question(self, text: str) -> bool:
        return len(text) >= _MIN_BYPASS_CHARS and bool(self._obvious_q_re.search(text))

    def _on_final(self, text: str, romaji: str, speaker_id: str):
        if not self._running:
            return
        label = self._map_speaker(speaker_id)
        if self._stabilizer:
            self._stabilizer.on_final(text, romaji, label)
        else:
            self._emit({"type": "final", "text": text, "romaji": romaji, "speaker": label, "confidence": "final"})

        self._persist_transcript(text, romaji, label, speaker_id)

        if label == "me" and self._llm:
            self._llm.add_user_speech(text, "")

        if label != "me" and self._suggestions_enabled and self._is_obvious_complete_question(text):
            self._active_line_id = ""
            self._current_is_auto = True
            self._emit({"type": "suggestion_start", "line_id": ""})
            self._enqueue_llm(text, romaji, label)
            if self._suggestion_ctrl:
                self._suggestion_ctrl.mark_busy()
            return

        if self._suggestion_ctrl and self._suggestions_enabled:
            self._suggestion_ctrl.on_final(text, romaji, label)
        elif self._suggestions_enabled:
            if label != "me" and time.time() - self._near_final_ts < 2.0:
                self._near_final_ts = 0.0
            else:
                self._enqueue_llm(text, romaji, label)

    def _on_near_final(self, text: str, romaji: str, speaker_id: str):
        pass

    def _persist_transcript(self, text: str, romaji: str, speaker_label: str, speaker_id: str):
        """Save final transcript entry to database."""
        try:
            db = _db_module.SessionLocal()
            entry = _db_module.TranscriptEntry(
                meeting_id=self.meeting_id,
                speaker=speaker_label,
                speaker_id=speaker_id,
                language=self.language,
                source="realtime",
                text=text,
                romaji=romaji,
            )
            db.add(entry)
            db.commit()
            db.close()
        except Exception as e:
            print(f"  [DB ERR] persist transcript: {e}", file=sys.stderr)

    def _persist_translation(self, vi: str, speaker_label: str):
        """Update the latest transcript entry for this speaker with translation."""
        try:
            db = _db_module.SessionLocal()
            entry = (
                db.query(_db_module.TranscriptEntry)
                .filter(
                    _db_module.TranscriptEntry.meeting_id == self.meeting_id,
                    _db_module.TranscriptEntry.speaker == speaker_label,
                )
                .order_by(_db_module.TranscriptEntry.id.desc())
                .first()
            )
            if entry and not entry.translation_vi:
                entry.translation_vi = vi
                db.commit()
            db.close()
        except Exception as e:
            print(f"  [DB ERR] persist translation: {e}", file=sys.stderr)

    def _on_translation(self, vi: str, speaker_id: str):
        if not self._running:
            return
        label = self._map_speaker(speaker_id)
        if self._stabilizer:
            self._stabilizer.on_translation(vi, label)
        else:
            self._emit({"type": "translation", "vi": vi, "speaker": label, "confidence": "final"})
        self._persist_translation(vi, label)

    # -- Suggestion pipeline callback --

    def _on_suggest_turn(self, turn: Turn):
        """Called by SuggestionController when a question is detected (auto mode)."""
        if not self._suggestions_enabled:
            return
        if self._suggestion_ctrl:
            self._suggestion_ctrl.mark_busy()
        self._active_line_id = ""
        self._current_is_auto = True

        if self._pregen and self._pregen.ready:
            cached = self._pregen.match_question(turn.full_text)
            if cached:
                self._suggestion_counter += 1
                sg_id = f"sg_{self._suggestion_counter}"
                self._emit({"type": "suggestion_start", "line_id": ""})
                if cached.get("answer_romaji"):
                    self._emit({"type": "suggestion_chunk", "line_id": "", "field": "answer_romaji", "chunk": cached["answer_romaji"]})
                if cached.get("answer_vi"):
                    self._emit({"type": "suggestion_chunk", "line_id": "", "field": "answer_vi", "chunk": cached["answer_vi"]})
                self._emit({"type": "suggestion_done", "line_id": "", "id": sg_id, "answer_romaji": cached.get("answer_romaji", ""), "answer_vi": cached.get("answer_vi", "")})
                if self._suggestion_ctrl:
                    self._suggestion_ctrl.mark_idle()
                return

        self._emit({"type": "suggestion_start", "line_id": ""})
        self._enqueue_llm(turn.full_text, turn.full_romaji, turn.speaker)

    # -- LLM callbacks --

    def _enqueue_llm(self, text: str, romaji: str, label: str):
        if not self._llm or not self._suggestions_enabled:
            return
        if label != "me":
            self._llm.enqueue(text, romaji, "")
        else:
            self._llm.add_user_speech(text, "")

    def _on_tier2_result(self, result: dict):
        is_manual = bool(self._active_line_id)
        if not self._suggestions_enabled and not is_manual:
            self._active_line_id = ""
            self._current_is_auto = False
            if self._suggestion_ctrl:
                self._suggestion_ctrl.mark_idle()
            return

        self._suggestion_counter += 1
        sg_id = f"sg_{self._suggestion_counter}"
        self._emit({
            "type": "suggestion_done",
            "line_id": self._active_line_id,
            "id": sg_id,
            "answer_romaji": result.get("answer_romaji", ""),
            "answer_vi": result.get("answer_vi", ""),
        })
        self._active_line_id = ""
        self._current_is_auto = False
        if self._suggestion_ctrl:
            self._suggestion_ctrl.mark_idle()

    def _on_answer_streaming(self, field: str, chunk: str):
        is_manual = bool(self._active_line_id)
        if not self._suggestions_enabled and not is_manual:
            return
        self._emit({
            "type": "suggestion_chunk",
            "line_id": self._active_line_id,
            "field": field,
            "chunk": chunk,
        })

    def _on_manual_result(self, result: dict):
        self._emit({
            "type": "suggestion_done",
            "line_id": "",
            "id": f"manual_{int(time.time())}",
            "answer_romaji": result.get("answer_romaji", ""),
            "answer_vi": result.get("answer_vi", ""),
        })

    def _on_llm_usage(self, usage: dict):
        """Persist LLM token usage to DB."""
        try:
            model = usage.get("model", "unknown")
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = usage.get("total_tokens", 0)
            latency_ms = usage.get("latency_ms", 0)
            request_type = usage.get("request_type", "suggestion")

            input_cost, output_cost = _COST_PER_1M.get(model, _DEFAULT_COST)
            estimated_cost = (prompt_tokens * input_cost + completion_tokens * output_cost) / 1_000_000

            db = _db_module.SessionLocal()
            from app.models.database import LLMUsageLog
            log = LLMUsageLog(
                meeting_id=self.meeting_id,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                estimated_cost=estimated_cost,
                request_type=request_type,
                latency_ms=latency_ms,
            )
            db.add(log)
            db.commit()
            db.close()
        except Exception as e:
            print(f"  [DB ERR] persist usage: {e}", file=sys.stderr)
