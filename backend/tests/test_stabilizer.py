"""Tests for the Conversation Stabilization Layer."""

import time

import pytest

from app.services.stabilizer import (
    UtteranceBuffer,
    DisplayThrottler,
    TranslationPolicy,
    SpeakerConsolidation,
    StabilizedPipeline,
    _longest_common_prefix,
)


# ── UtteranceBuffer ──────────────────────────────────────────

class TestUtteranceBuffer:
    def test_first_interim_creates_state(self):
        buf = UtteranceBuffer()
        state = buf.on_interim("hello", "hello", "Speaker 1")
        assert state.current_text == "hello"
        assert state.speaker == "Speaker 1"
        assert not state.is_final

    def test_progressive_interim_grows_locked(self):
        buf = UtteranceBuffer(prefix_lock_ratio=0.6)
        buf.on_interim("今日", "", "S1")
        state = buf.on_interim("今日はいい天気です", "", "S1")
        assert state.current_text == "今日はいい天気です"
        assert len(state.locked_text) > 0

    def test_final_locks_full_text(self):
        buf = UtteranceBuffer()
        buf.on_interim("hello", "", "S1")
        state = buf.on_final("hello world", "", "S1")
        assert state.locked_text == "hello world"
        assert state.is_final

    def test_new_interim_after_final_starts_fresh(self):
        buf = UtteranceBuffer()
        buf.on_final("done", "", "S1")
        state = buf.on_interim("new text", "", "S1")
        assert state.current_text == "new text"
        assert not state.is_final

    def test_clear_speaker(self):
        buf = UtteranceBuffer()
        buf.on_interim("text", "", "S1")
        buf.clear("S1")
        assert buf.get_state("S1") is None

    def test_clear_all(self):
        buf = UtteranceBuffer()
        buf.on_interim("a", "", "S1")
        buf.on_interim("b", "", "S2")
        buf.clear()
        assert buf.get_state("S1") is None
        assert buf.get_state("S2") is None

    def test_handles_text_revision(self):
        """When STT revises text (common with Azure), buffer adapts gracefully."""
        buf = UtteranceBuffer(prefix_lock_ratio=0.5)
        buf.on_interim("I think we should", "", "S1")
        state = buf.on_interim("I think we need to", "", "S1")
        assert "I think" in state.current_text


# ── DisplayThrottler ─────────────────────────────────────────

class TestDisplayThrottler:
    def test_first_emit_always_passes(self):
        throttler = DisplayThrottler(min_interval_ms=300)
        assert throttler.should_emit("S1", "hello") is True

    def test_rapid_updates_throttled(self):
        throttler = DisplayThrottler(min_interval_ms=300, min_change_chars=10)
        throttler.should_emit("S1", "hello")
        assert throttler.should_emit("S1", "hello!") is False

    def test_big_change_bypasses_throttle(self):
        throttler = DisplayThrottler(min_interval_ms=5000, min_change_chars=5)
        throttler.should_emit("S1", "abc")
        assert throttler.should_emit("S1", "abcdefgh") is True

    def test_different_speakers_independent(self):
        throttler = DisplayThrottler(min_interval_ms=5000, min_change_chars=100)
        throttler.should_emit("S1", "hello")
        assert throttler.should_emit("S2", "world") is True

    def test_force_emit_resets(self):
        throttler = DisplayThrottler(min_interval_ms=5000)
        throttler.force_emit("S1", "text")
        assert throttler.should_emit("S1", "text") is False


# ── TranslationPolicy ───────────────────────────────────────

class TestTranslationPolicy:
    def test_final_only_blocks_interim(self):
        pol = TranslationPolicy(final_only=True)
        assert pol.should_emit_translation("xin chào", "S1") is False

    def test_after_stt_final_allows_translation(self):
        pol = TranslationPolicy(final_only=True)
        pol.on_stt_final("S1")
        assert pol.should_emit_translation("xin chào", "S1") is True

    def test_stt_final_only_once(self):
        pol = TranslationPolicy(final_only=True)
        pol.on_stt_final("S1")
        pol.should_emit_translation("xin chào", "S1")
        assert pol.should_emit_translation("xin chào 2", "S1") is False

    def test_different_speakers_independent(self):
        pol = TranslationPolicy(final_only=True)
        pol.on_stt_final("S1")
        assert pol.should_emit_translation("text", "S2") is False


# ── SpeakerConsolidation ─────────────────────────────────────

class TestSpeakerConsolidation:
    def test_first_final_creates_group(self):
        cons = SpeakerConsolidation()
        utt, is_new = cons.add_final("hello", "hello", "S1")
        assert is_new is True
        assert utt.text == "hello"
        assert utt.speaker == "S1"

    def test_same_speaker_merges(self):
        cons = SpeakerConsolidation(merge_window_ms=5000)
        cons.add_final("hello", "", "S1")
        utt, is_new = cons.add_final("world", "", "S1")
        assert is_new is False
        assert utt.text == "hello world"

    def test_different_speaker_breaks_group(self):
        cons = SpeakerConsolidation(merge_window_ms=5000)
        cons.add_final("hello", "", "S1")
        utt, is_new = cons.add_final("hi", "", "S2")
        assert is_new is True
        assert utt.speaker == "S1"

    def test_max_lines_breaks_group(self):
        cons = SpeakerConsolidation(merge_window_ms=10000, max_lines=2)
        cons.add_final("a", "", "S1")
        cons.add_final("b", "", "S1")
        utt, is_new = cons.add_final("c", "", "S1")
        assert is_new is True

    def test_flush_returns_current(self):
        cons = SpeakerConsolidation()
        cons.add_final("hello", "", "S1")
        utt = cons.flush()
        assert utt is not None
        assert utt.text == "hello"
        assert cons.flush() is None


# ── StabilizedPipeline ───────────────────────────────────────

class TestStabilizedPipeline:
    def test_interim_emits_throttled(self):
        emitted = []
        pipeline = StabilizedPipeline(
            emit_fn=emitted.append,
            throttle_ms=0,
            min_change_chars=0,
        )
        pipeline.on_interim("abc", "", "S1")
        assert len(emitted) == 1
        assert emitted[0]["type"] == "interim"

    def test_final_always_emits(self):
        emitted = []
        pipeline = StabilizedPipeline(emit_fn=emitted.append, throttle_ms=0)
        pipeline.on_final("hello world", "", "S1")
        assert any(e["type"] == "final" for e in emitted)

    def test_translation_blocked_without_final(self):
        emitted = []
        pipeline = StabilizedPipeline(emit_fn=emitted.append, translation_final_only=True)
        pipeline.on_translation("xin chào", "S1")
        assert not any(e["type"] == "translation" for e in emitted)

    def test_translation_after_final_emits(self):
        emitted = []
        pipeline = StabilizedPipeline(emit_fn=emitted.append, translation_final_only=True, throttle_ms=0)
        pipeline.on_final("こんにちは", "", "S1")
        pipeline.on_translation("xin chào", "S1")
        assert any(e["type"] == "translation" for e in emitted)

    def test_rapid_interims_throttled(self):
        emitted = []
        pipeline = StabilizedPipeline(
            emit_fn=emitted.append,
            throttle_ms=500,
            min_change_chars=20,
        )
        pipeline.on_interim("a", "", "S1")
        pipeline.on_interim("ab", "", "S1")
        pipeline.on_interim("abc", "", "S1")
        assert len([e for e in emitted if e["type"] == "interim"]) == 1


# ── Helpers ──────────────────────────────────────────────────

class TestHelpers:
    def test_longest_common_prefix(self):
        assert _longest_common_prefix("hello world", "hello there") == "hello "
        assert _longest_common_prefix("abc", "xyz") == ""
        assert _longest_common_prefix("", "abc") == ""
        assert _longest_common_prefix("same", "same") == "same"
