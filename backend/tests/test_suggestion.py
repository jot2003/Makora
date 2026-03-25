"""Tests for the Intelligent Suggestion Pipeline."""

import time
import threading

import pytest

from app.services.suggestion import (
    TurnAggregator,
    IntentClassifier,
    SuggestionController,
    Turn,
)


# ── IntentClassifier ─────────────────────────────────────────

class TestIntentClassifier:
    def setup_method(self):
        self.clf = IntentClassifier()

    def _turn(self, text: str, speaker: str = "S1") -> Turn:
        return Turn(speaker=speaker, texts=[text], start_time=time.time(), end_time=time.time())

    def test_ja_question(self):
        t = self._turn("これについて説明してください")
        assert self.clf.classify(t, "ja-JP") == "question"

    def test_ja_question_mark(self):
        t = self._turn("お名前は？")
        assert self.clf.classify(t, "ja-JP") == "question"

    def test_ja_filler(self):
        t = self._turn("はい")
        assert self.clf.classify(t, "ja-JP") == "filler"

    def test_ja_greeting(self):
        t = self._turn("よろしくお願いします")
        assert self.clf.classify(t, "ja-JP") in ("filler", "greeting")

    def test_ja_statement(self):
        t = self._turn("次のプロジェクトについて話します")
        assert self.clf.classify(t, "ja-JP") == "statement"

    def test_en_question(self):
        t = self._turn("What is your experience with Python?")
        assert self.clf.classify(t, "en-US") == "question"

    def test_en_question_mark(self):
        t = self._turn("You worked at Google?")
        assert self.clf.classify(t, "en-US") == "question"

    def test_en_filler(self):
        t = self._turn("ok")
        assert self.clf.classify(t, "en-US") == "filler"

    def test_en_statement(self):
        t = self._turn("Let me tell you about the next phase of our project")
        assert self.clf.classify(t, "en-US") == "statement"

    def test_empty_text(self):
        t = self._turn("")
        assert self.clf.classify(t, "ja-JP") == "filler"

    def test_multi_sentence_question(self):
        t = Turn(
            speaker="S1",
            texts=["今日のプロジェクトについて", "何か質問ありますか"],
            start_time=time.time(),
            end_time=time.time(),
        )
        assert self.clf.classify(t, "ja-JP") == "question"


# ── TurnAggregator ───────────────────────────────────────────

class TestTurnAggregator:
    def test_same_speaker_aggregates(self):
        agg = TurnAggregator(gap_ms=5000)
        agg.add_final("hello", "", "S1")
        completed = agg.add_final("world", "", "S1")
        assert completed is None
        turn = agg.flush()
        assert turn is not None
        assert turn.full_text == "hello world"

    def test_different_speaker_completes(self):
        agg = TurnAggregator(gap_ms=5000)
        agg.add_final("hello", "", "S1")
        completed = agg.add_final("hi", "", "S2")
        assert completed is not None
        assert completed.speaker == "S1"
        assert completed.full_text == "hello"

    def test_flush_returns_current(self):
        agg = TurnAggregator()
        agg.add_final("text", "", "S1")
        turn = agg.flush()
        assert turn is not None
        assert turn.full_text == "text"

    def test_flush_empty(self):
        agg = TurnAggregator()
        assert agg.flush() is None

    def test_gap_timer_completes_turn(self):
        completed_turns = []
        agg = TurnAggregator(gap_ms=200)
        agg.add_final("hello", "", "S1", on_turn_complete=completed_turns.append)
        time.sleep(0.5)
        assert len(completed_turns) == 1
        assert completed_turns[0].full_text == "hello"

    def test_max_turn_duration(self):
        agg = TurnAggregator(gap_ms=5000, max_turn_ms=100)
        agg.add_final("a", "", "S1")
        time.sleep(0.15)
        completed = agg.add_final("b", "", "S1")
        assert completed is not None
        assert completed.full_text == "a"


# ── SuggestionController ────────────────────────────────────

class TestSuggestionController:
    def test_interview_question_triggers(self):
        suggestions = []
        ctrl = SuggestionController(
            mode="interview",
            on_suggest=suggestions.append,
            language="ja-JP",
            cooldown_ms=0,
        )
        ctrl.on_final("お名前は何ですか", "", "S1")
        time.sleep(2.5)
        assert len(suggestions) >= 1

    def test_interview_filler_skips(self):
        suggestions = []
        ctrl = SuggestionController(
            mode="interview",
            on_suggest=suggestions.append,
            language="ja-JP",
            cooldown_ms=0,
        )
        ctrl.on_final("はい", "", "S1")
        time.sleep(2.5)
        assert len(suggestions) == 0

    def test_interview_statement_shows_topic(self):
        topics = []
        ctrl = SuggestionController(
            mode="interview",
            on_topic=topics.append,
            language="ja-JP",
            cooldown_ms=0,
        )
        ctrl.on_final("次のプロジェクトについて話しましょう", "", "S1")
        time.sleep(2.5)
        assert len(topics) >= 1

    def test_meeting_only_question_triggers(self):
        suggestions = []
        ctrl = SuggestionController(
            mode="meeting",
            on_suggest=suggestions.append,
            language="ja-JP",
            cooldown_ms=0,
        )
        ctrl.on_final("このバグの原因は何ですか", "", "S1")
        time.sleep(2.5)
        assert len(suggestions) >= 1

    def test_my_speech_ignored(self):
        suggestions = []
        ctrl = SuggestionController(
            mode="interview",
            on_suggest=suggestions.append,
            language="ja-JP",
            cooldown_ms=0,
        )
        ctrl.on_final("私の名前はタンです", "", "me")
        time.sleep(2.5)
        assert len(suggestions) == 0

    def test_cooldown_prevents_rapid_fire(self):
        suggestions = []
        ctrl = SuggestionController(
            mode="interview",
            on_suggest=suggestions.append,
            language="ja-JP",
            cooldown_ms=5000,
        )
        ctrl.on_final("お名前は何ですか", "", "S1")
        time.sleep(2.5)
        ctrl.on_final("趣味は何ですか", "", "S1")
        time.sleep(2.5)
        assert len(suggestions) <= 1

    def test_en_question_triggers(self):
        suggestions = []
        ctrl = SuggestionController(
            mode="interview",
            on_suggest=suggestions.append,
            language="en-US",
            cooldown_ms=0,
        )
        ctrl.on_final("What is your experience with React?", "", "S1")
        time.sleep(2.5)
        assert len(suggestions) >= 1

    def test_mode_switch(self):
        suggestions = []
        ctrl = SuggestionController(
            mode="meeting",
            on_suggest=suggestions.append,
            language="ja-JP",
            cooldown_ms=0,
        )
        ctrl.set_mode("interview")
        assert ctrl._mode == "interview"
