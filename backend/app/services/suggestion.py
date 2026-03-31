"""Intelligent Suggestion Pipeline.

Solves the core problem: when should AI suggestions be triggered?

Components:
  1. TurnAggregator — collects speech until speaker "turn" is done
  2. IntentClassifier — determines if the turn is a question, statement, or filler
  3. SuggestionController — mode-aware decision engine (Interview vs Meeting mode)

Key behaviors:
  Interview mode:
    - question → generate suggestion
    - long statement → summarize as "Now discussing: ..."
    - filler/greeting → skip
  Meeting mode:
    - only explicit questions → generate suggestion
    - everything else → skip (meeting members answer themselves)
    - optionally track topics for "Now discussing"
"""

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Literal

_QUESTION_PATTERNS_JA = re.compile(
    r'(?:ですか|ますか|でしょうか|ください|ありますか|ですか？|'
    r'お願いします|願います|してみて|お聞かせ|お話し|'
    r'何|どう|どの|いつ|どこ|なぜ|誰|いくつ|いくら|'
    r'教えて|説明して|述べて|話して|聞かせて)',
    re.IGNORECASE,
)

_QUESTION_PATTERNS_EN = re.compile(
    r'(?:^(?:what|how|why|when|where|who|which|can you|could you|do you|did you|'
    r'have you|will you|would you|are you|is there|tell me|explain|describe)'
    r'|\?$)',
    re.IGNORECASE | re.MULTILINE,
)

_FILLER_PATTERNS_JA = re.compile(
    r'^(?:はい|うん|ええ|そうですね|なるほど|了解|OK|わかりました|'
    r'よろしくお願いします|ありがとうございます|お疲れ様)$',
    re.IGNORECASE,
)

_FILLER_PATTERNS_EN = re.compile(
    r'^(?:yes|yeah|no|ok|okay|sure|right|I see|got it|thank you|thanks|'
    r'alright|uh huh|mm|hmm|hello|hi)$',
    re.IGNORECASE,
)

_GREETING_JA = re.compile(
    r'(?:おはよう|こんにちは|こんばんは|初めまして|よろしく)',
    re.IGNORECASE,
)

_QUESTION_END_JA = re.compile(
    r'(?:ですか|ますか|でしょうか|ください|お願いします|ませんか|'
    r'教えてください|聞かせてください|お話しください)[。？]?$|[？?]$'
)

_QUESTION_END_EN = re.compile(r'\?$')

_QUESTION_PATTERNS_VI = re.compile(
    r'(?:^(?:bạn|hãy|xin|cho biết|tại sao|thế nào|như thế nào|'
    r'bao giờ|ở đâu|cái gì|ai|làm sao|có thể|vì sao|'
    r'kể về|mô tả|giải thích|chia sẻ|trình bày)'
    r'|[?]$|là gì|như thế nào|được không|chưa|không)',
    re.IGNORECASE,
)

_FILLER_PATTERNS_VI = re.compile(
    r'^(?:vâng|dạ|ok|được|rồi|cảm ơn|'
    r'vâng ạ|dạ vâng|tôi hiểu|tôi biết|à|ừ|uhm)$',
    re.IGNORECASE,
)

_GREETING_VI = re.compile(
    r'(?:xin chào|chào bạn|chào anh|chào chị|rất vui|chào em)',
    re.IGNORECASE,
)

_QUESTION_END_VI = re.compile(
    r'(?:là gì|như thế nào|ra sao|thế nào|được không|'
    r'chưa|không|chứ|nhỉ|hả|nhé|vậy|ạ)[.?]?$|[?]$'
)


def _get_question_end_re(language: str) -> re.Pattern:
    if language.startswith("ja"):
        return _QUESTION_END_JA
    if language.startswith("vi"):
        return _QUESTION_END_VI
    return _QUESTION_END_EN


IntentType = Literal["question", "statement", "filler", "greeting"]
ModeType = Literal["interview", "meeting"]


@dataclass
class Turn:
    """A complete speaker turn (one or more consecutive utterances)."""
    speaker: str
    texts: list[str] = field(default_factory=list)
    romaji_texts: list[str] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    intent: IntentType = "statement"

    @property
    def full_text(self) -> str:
        return " ".join(self.texts)

    @property
    def full_romaji(self) -> str:
        return " ".join(self.romaji_texts)

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


# ─── TurnAggregator ─────────────────────────────────────────────────────

class TurnAggregator:
    """Aggregates consecutive same-speaker finals into a single Turn.

    A turn "completes" when:
    1. A different speaker starts talking, OR
    2. A silence gap > gap_ms passes after the last final
    3. Fast-path: question markers detected -> use shorter grace period
    """

    def __init__(
        self,
        gap_ms: int = 2000,
        max_turn_ms: int = 30000,
        fast_patterns: "re.Pattern | None" = None,
        fast_gap_ms: int = 200,
    ):
        self._gap = gap_ms / 1000.0
        self._fast_gap = fast_gap_ms / 1000.0
        self._max_turn = max_turn_ms / 1000.0
        self._fast_patterns = fast_patterns
        self._current: Turn | None = None
        self._lock = threading.Lock()
        self._gap_timer: threading.Timer | None = None

    def add_final(
        self,
        text: str,
        romaji: str,
        speaker: str,
        on_turn_complete: Callable[[Turn], None] | None = None,
    ) -> Turn | None:
        """Add a final utterance. Returns a completed Turn if the turn ended."""
        with self._lock:
            self._cancel_timer()
            now = time.time()
            completed = None

            if self._current is None:
                self._current = Turn(speaker=speaker, texts=[text], romaji_texts=[romaji], start_time=now, end_time=now)
            elif self._current.speaker != speaker:
                completed = self._current
                self._current = Turn(speaker=speaker, texts=[text], romaji_texts=[romaji], start_time=now, end_time=now)
            elif (now - self._current.start_time) > self._max_turn:
                completed = self._current
                self._current = Turn(speaker=speaker, texts=[text], romaji_texts=[romaji], start_time=now, end_time=now)
            else:
                self._current.texts.append(text)
                self._current.romaji_texts.append(romaji)
                self._current.end_time = now

            use_fast = (
                self._fast_patterns is not None
                and self._current is not None
                and self._fast_patterns.search(self._current.full_text)
            )
            gap = self._fast_gap if use_fast else self._gap
            self._start_gap_timer(on_turn_complete, gap)

        if completed and on_turn_complete:
            on_turn_complete(completed)
        return completed

    def set_fast_patterns(self, patterns: "re.Pattern | None"):
        with self._lock:
            self._fast_patterns = patterns

    def flush(self) -> Turn | None:
        with self._lock:
            self._cancel_timer()
            result = self._current
            self._current = None
            return result

    def _start_gap_timer(self, callback: Callable[[Turn], None] | None, gap: float | None = None):
        actual_gap = gap if gap is not None else self._gap

        def on_gap():
            with self._lock:
                if self._current:
                    completed = self._current
                    self._current = None
                else:
                    return
            if callback:
                callback(completed)

        self._gap_timer = threading.Timer(actual_gap, on_gap)
        self._gap_timer.daemon = True
        self._gap_timer.start()

    def _cancel_timer(self):
        if self._gap_timer:
            self._gap_timer.cancel()
            self._gap_timer = None

    def clear(self):
        with self._lock:
            self._cancel_timer()
            self._current = None


# ─── IntentClassifier ────────────────────────────────────────────────────

class IntentClassifier:
    """Classifies a Turn's intent based on patterns (no LLM call needed)."""

    def classify(self, turn: Turn, language: str = "ja-JP") -> IntentType:
        text = turn.full_text.strip()
        if not text:
            return "filler"

        is_ja = language.startswith("ja")
        is_vi = language.startswith("vi")

        if is_ja:
            filler_re = _FILLER_PATTERNS_JA
            question_re = _QUESTION_PATTERNS_JA
        elif is_vi:
            filler_re = _FILLER_PATTERNS_VI
            question_re = _QUESTION_PATTERNS_VI
        else:
            filler_re = _FILLER_PATTERNS_EN
            question_re = _QUESTION_PATTERNS_EN

        if filler_re.match(text):
            return "filler"

        if is_ja and _GREETING_JA.search(text):
            return "greeting"
        if is_vi and _GREETING_VI.search(text):
            return "greeting"

        if question_re.search(text):
            return "question"

        if text.endswith("?") or text.endswith("？"):
            return "question"

        return "statement"


# ─── SuggestionController ───────────────────────────────────────────────

@dataclass
class SuggestionDecision:
    should_suggest: bool = False
    should_show_topic: bool = False
    topic: str = ""
    reason: str = ""


class SuggestionController:
    """Mode-aware decision engine for when to trigger AI suggestions."""

    def __init__(
        self,
        mode: ModeType = "interview",
        on_suggest: Callable[[Turn], None] | None = None,
        on_topic: Callable[[str], None] | None = None,
        language: str = "ja-JP",
        min_question_chars: int = 5,
        cooldown_ms: int = 3000,
    ):
        self._mode = mode
        self._on_suggest = on_suggest or (lambda _: None)
        self._on_topic = on_topic or (lambda _: None)
        self._language = language
        self._min_question_chars = min_question_chars
        self._cooldown = cooldown_ms / 1000.0
        self._last_suggest_time = 0.0
        self._is_idle = True
        self._classifier = IntentClassifier()

        self._aggregator = TurnAggregator(
            gap_ms=700, max_turn_ms=30000,
            fast_patterns=_get_question_end_re(language), fast_gap_ms=200,
        )

    def set_mode(self, mode: ModeType):
        self._mode = mode

    def set_language(self, language: str):
        self._language = language
        self._aggregator.set_fast_patterns(_get_question_end_re(language))

    def on_final(self, text: str, romaji: str, speaker: str):
        """Feed a final STT result. The controller will aggregate turns
        and decide when to trigger suggestions."""
        if speaker == "me":
            return

        self._aggregator.add_final(text, romaji, speaker, on_turn_complete=self._on_turn_complete)

    def mark_busy(self):
        self._is_idle = False

    def mark_idle(self):
        self._is_idle = True

    def _on_turn_complete(self, turn: Turn):
        turn.intent = self._classifier.classify(turn, self._language)
        decision = self._decide(turn)

        if decision.should_suggest:
            now = time.time()
            cooldown_ok = self._is_idle or (now - self._last_suggest_time) >= self._cooldown
            if cooldown_ok:
                self._last_suggest_time = now
                self._on_suggest(turn)

        if decision.should_show_topic and decision.topic:
            self._on_topic(decision.topic)

    def _decide(self, turn: Turn) -> SuggestionDecision:
        if turn.intent == "filler" or turn.intent == "greeting":
            return SuggestionDecision(reason=f"Skipped: {turn.intent}")

        if len(turn.full_text) < self._min_question_chars:
            return SuggestionDecision(reason="Too short")

        if self._mode == "interview":
            topic = turn.full_text[:80]
            return SuggestionDecision(
                should_suggest=True,
                should_show_topic=True,
                topic=topic,
                reason=f"Interview turn ({turn.intent}) → suggest",
            )

        elif self._mode == "meeting":
            if turn.intent == "question":
                return SuggestionDecision(
                    should_suggest=True,
                    reason="Meeting question detected",
                )
            else:
                topic = turn.full_text[:80]
                return SuggestionDecision(
                    should_show_topic=True,
                    topic=topic,
                    reason="Meeting statement → topic only",
                )

        return SuggestionDecision(reason="Unknown mode")

    def flush(self):
        turn = self._aggregator.flush()
        if turn:
            self._on_turn_complete(turn)

    def clear(self):
        self._aggregator.clear()
        self._last_suggest_time = 0.0
