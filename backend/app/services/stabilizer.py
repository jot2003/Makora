"""Conversation Stabilization Layer.

Fixes the core UX problems:
  1. UtteranceBuffer — prefix-locking to prevent text from jumping
  2. DisplayThrottler — cadence-based updates to prevent flicker
  3. TranslationPolicy — only emit final translations (no partial noise)
  4. SpeakerConsolidation — merge rapid same-speaker utterances

These components sit BETWEEN raw STT output and WebSocket emission.
"""

import threading
import time
from dataclasses import dataclass, field


# ─── UtteranceBuffer ─────────────────────────────────────────────────────
# Prevents text "jumping" by locking confirmed prefixes.
# When interim text arrives, we only update from the locked prefix onward.
# Once a final is received, the full text is locked.


@dataclass
class UtteranceState:
    locked_text: str = ""
    current_text: str = ""
    romaji: str = ""
    speaker: str = ""
    last_update: float = 0.0
    is_final: bool = False


class UtteranceBuffer:
    """Manages per-speaker utterance state with prefix locking."""

    def __init__(self, prefix_lock_ratio: float = 0.6):
        self._states: dict[str, UtteranceState] = {}
        self._lock = threading.Lock()
        self._prefix_lock_ratio = prefix_lock_ratio

    def on_interim(self, text: str, romaji: str, speaker: str) -> UtteranceState:
        with self._lock:
            state = self._states.get(speaker)

            if state is None or state.is_final:
                state = UtteranceState(
                    locked_text="", current_text=text, romaji=romaji,
                    speaker=speaker, last_update=time.time(), is_final=False,
                )
                self._states[speaker] = state
                return state

            if text.startswith(state.locked_text):
                state.current_text = text
            elif len(text) > len(state.current_text) * 0.5:
                common = _longest_common_prefix(state.current_text, text)
                if len(common) >= len(state.locked_text):
                    state.current_text = text
                    state.locked_text = common
                else:
                    state.current_text = text
                    state.locked_text = ""
            else:
                state.current_text = text

            lock_point = int(len(state.current_text) * self._prefix_lock_ratio)
            if lock_point > len(state.locked_text):
                state.locked_text = state.current_text[:lock_point]

            state.romaji = romaji
            state.last_update = time.time()
            return state

    def on_final(self, text: str, romaji: str, speaker: str) -> UtteranceState:
        with self._lock:
            state = UtteranceState(
                locked_text=text, current_text=text, romaji=romaji,
                speaker=speaker, last_update=time.time(), is_final=True,
            )
            self._states[speaker] = state
            return state

    def get_state(self, speaker: str) -> UtteranceState | None:
        with self._lock:
            return self._states.get(speaker)

    def clear(self, speaker: str | None = None):
        with self._lock:
            if speaker:
                self._states.pop(speaker, None)
            else:
                self._states.clear()


def _longest_common_prefix(a: str, b: str) -> str:
    i = 0
    while i < len(a) and i < len(b) and a[i] == b[i]:
        i += 1
    return a[:i]


# ─── DisplayThrottler ────────────────────────────────────────────────────
# Prevents rapid UI updates by enforcing minimum intervals.


class DisplayThrottler:
    """Rate-limits interim updates per speaker to prevent flickering."""

    def __init__(self, min_interval_ms: int = 300, min_change_chars: int = 3):
        self._min_interval = min_interval_ms / 1000.0
        self._min_change_chars = min_change_chars
        self._last_emit: dict[str, float] = {}
        self._last_text: dict[str, str] = {}
        self._lock = threading.Lock()

    def should_emit(self, speaker: str, text: str) -> bool:
        """Returns True if enough time/change has passed to warrant a UI update."""
        with self._lock:
            now = time.time()
            last_time = self._last_emit.get(speaker, 0)
            last_text = self._last_text.get(speaker, "")

            time_ok = (now - last_time) >= self._min_interval
            change_ok = abs(len(text) - len(last_text)) >= self._min_change_chars

            if time_ok or change_ok:
                self._last_emit[speaker] = now
                self._last_text[speaker] = text
                return True
            return False

    def force_emit(self, speaker: str, text: str):
        """Mark as emitted without checking (for finals)."""
        with self._lock:
            self._last_emit[speaker] = time.time()
            self._last_text[speaker] = text

    def clear(self, speaker: str | None = None):
        with self._lock:
            if speaker:
                self._last_emit.pop(speaker, None)
                self._last_text.pop(speaker, None)
            else:
                self._last_emit.clear()
                self._last_text.clear()


# ─── TranslationPolicy ───────────────────────────────────────────────────
# Controls when translations are emitted.
# Interim translations cause noise and inaccuracy — we only emit finals.


class TranslationPolicy:
    """Only emit translation when it's "final" enough — after STT final or
    after a stability timeout for tentative translations."""

    _FINAL_WINDOW_S = 3.0

    def __init__(self, final_only: bool = True, tentative_delay_ms: int = 1500):
        self._final_only = final_only
        self._tentative_delay = tentative_delay_ms / 1000.0
        self._pending: dict[str, tuple[str, float]] = {}
        self._finals: dict[str, float] = {}
        self._lock = threading.Lock()

    def on_stt_final(self, speaker: str):
        """Mark that a final STT result arrived for this speaker —
        translations for this speaker within the next few seconds should be emitted."""
        with self._lock:
            self._finals[speaker] = time.time()

    def should_emit_translation(self, vi: str, speaker: str) -> tuple[bool, str]:
        """Returns (should_emit, corrected_speaker)."""
        with self._lock:
            now = time.time()
            ts = self._finals.get(speaker)
            if ts and (now - ts) < self._FINAL_WINDOW_S:
                del self._finals[speaker]
                self._pending.pop(speaker, None)
                return True, speaker

            for other_spk, other_ts in list(self._finals.items()):
                if (now - other_ts) < self._FINAL_WINDOW_S:
                    del self._finals[other_spk]
                    self._pending.pop(other_spk, None)
                    return True, other_spk

            if self._final_only:
                return False, speaker

            prev = self._pending.get(speaker)
            if prev and (now - prev[1]) < self._tentative_delay:
                self._pending[speaker] = (vi, now)
                return False, speaker

            self._pending[speaker] = (vi, now)
            return True, speaker

    def clear(self):
        with self._lock:
            self._pending.clear()
            self._finals.clear()


# ─── SpeakerConsolidation ────────────────────────────────────────────────
# Merges rapid consecutive utterances from the same speaker into one line.


@dataclass
class ConsolidatedUtterance:
    speaker: str
    lines: list[str] = field(default_factory=list)
    romaji_lines: list[str] = field(default_factory=list)
    last_time: float = 0.0

    @property
    def text(self) -> str:
        return " ".join(self.lines)

    @property
    def romaji(self) -> str:
        return " ".join(self.romaji_lines)


class SpeakerConsolidation:
    """Merges consecutive same-speaker finals within a time window."""

    def __init__(self, merge_window_ms: int = 3000, max_lines: int = 5):
        self._merge_window = merge_window_ms / 1000.0
        self._max_lines = max_lines
        self._current: ConsolidatedUtterance | None = None
        self._lock = threading.Lock()

    def add_final(self, text: str, romaji: str, speaker: str) -> tuple[ConsolidatedUtterance | None, bool]:
        """Returns (utterance, is_new_group).

        If speaker changes or timeout, returns the PREVIOUS consolidated
        utterance as completed + starts a new one. If same speaker within
        window, appends and returns the updated current utterance.
        """
        with self._lock:
            now = time.time()

            if self._current is None:
                self._current = ConsolidatedUtterance(
                    speaker=speaker, lines=[text], romaji_lines=[romaji], last_time=now,
                )
                return self._current, True

            same_speaker = self._current.speaker == speaker
            within_window = (now - self._current.last_time) < self._merge_window
            not_full = len(self._current.lines) < self._max_lines

            if same_speaker and within_window and not_full:
                self._current.lines.append(text)
                self._current.romaji_lines.append(romaji)
                self._current.last_time = now
                return self._current, False

            completed = self._current
            self._current = ConsolidatedUtterance(
                speaker=speaker, lines=[text], romaji_lines=[romaji], last_time=now,
            )
            return completed, True

    def flush(self) -> ConsolidatedUtterance | None:
        with self._lock:
            result = self._current
            self._current = None
            return result

    def clear(self):
        with self._lock:
            self._current = None


# ─── StabilizedPipeline ──────────────────────────────────────────────────
# Combines all four components into one easy-to-use facade.


class StabilizedPipeline:
    """Drop-in middleware between raw STT and WebSocket output.

    Usage:
        pipeline = StabilizedPipeline(emit_fn=send_to_websocket)
        # In STT callbacks:
        pipeline.on_interim(text, romaji, speaker)
        pipeline.on_final(text, romaji, speaker)
        pipeline.on_translation(vi, speaker)
    """

    def __init__(
        self,
        emit_fn,
        throttle_ms: int = 300,
        min_change_chars: int = 3,
        translation_final_only: bool = True,
        merge_window_ms: int = 3000,
        prefix_lock_ratio: float = 0.6,
    ):
        self._emit = emit_fn
        self._buffer = UtteranceBuffer(prefix_lock_ratio=prefix_lock_ratio)
        self._throttler = DisplayThrottler(min_interval_ms=throttle_ms, min_change_chars=min_change_chars)
        self._translation = TranslationPolicy(final_only=translation_final_only)
        self._consolidation = SpeakerConsolidation(merge_window_ms=merge_window_ms)

    def on_interim(self, text: str, romaji: str, speaker: str):
        state = self._buffer.on_interim(text, romaji, speaker)
        if self._throttler.should_emit(speaker, state.current_text):
            self._emit({
                "type": "interim",
                "text": state.current_text,
                "romaji": state.romaji,
                "speaker": speaker,
                "confidence": "partial" if len(state.locked_text) < len(text) * 0.4 else "stable",
            })

    def on_final(self, text: str, romaji: str, speaker: str):
        self._buffer.on_final(text, romaji, speaker)
        self._throttler.force_emit(speaker, text)
        self._translation.on_stt_final(speaker)

        utterance, is_new = self._consolidation.add_final(text, romaji, speaker)
        self._emit({
            "type": "final",
            "text": utterance.text if utterance else text,
            "romaji": utterance.romaji if utterance else romaji,
            "speaker": speaker,
            "confidence": "final",
        })

    def on_translation(self, vi: str, speaker: str):
        should_emit, corrected_speaker = self._translation.should_emit_translation(vi, speaker)
        if should_emit:
            self._emit({
                "type": "translation",
                "vi": vi,
                "speaker": corrected_speaker,
                "confidence": "final",
            })

    def clear(self):
        self._buffer.clear()
        self._throttler.clear()
        self._translation.clear()
        self._consolidation.clear()
