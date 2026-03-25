"""Integration tests: verify the full data pipeline works end-to-end.

Tests the critical path: transcript persistence → intelligence API → RAG pipeline.
Uses seeded data to test without Azure keys.
"""

import json
import uuid
from unittest.mock import patch, MagicMock

import pytest
import numpy as np


# ── Helpers ──────────────────────────────────────────────────────

def _create_meeting(client, name="Test Meeting", mode="interview", language="ja-JP"):
    r = client.post("/api/meetings", json={"name": name, "mode": mode, "language": language})
    assert r.status_code == 201
    return r.json()


def _seed_transcript(client, meeting_id: str, entries: list[dict]):
    """Seed transcript entries directly via DB (simulating MeetingSession persist)."""
    from app.models.database import SessionLocal, TranscriptEntry
    db = SessionLocal()
    for e in entries:
        entry = TranscriptEntry(
            meeting_id=meeting_id,
            speaker=e.get("speaker", "Speaker 1"),
            speaker_id=e.get("speaker_id", "s1"),
            language=e.get("language", "ja-JP"),
            source=e.get("source", "realtime"),
            text=e.get("text", ""),
            romaji=e.get("romaji", ""),
            translation_vi=e.get("translation_vi", ""),
        )
        db.add(entry)
    db.commit()
    db.close()


SAMPLE_TRANSCRIPT = [
    {"speaker": "Speaker 1", "text": "今日はプロジェクトの進捗について話し合いましょう。"},
    {"speaker": "Speaker 2", "text": "はい、まずバックエンドの開発状況を報告します。APIは80%完成しています。"},
    {"speaker": "Speaker 1", "text": "テストはどうですか？"},
    {"speaker": "Speaker 2", "text": "ユニットテストは60%のカバレッジです。来週までに80%にする予定です。"},
    {"speaker": "Speaker 1", "text": "わかりました。フロントエンドはどうですか？"},
    {"speaker": "Speaker 2", "text": "React のコンポーネントは完成しました。ただ、モバイル対応がまだです。"},
    {"speaker": "Speaker 1", "text": "モバイル対応は来月に延期しましょう。リソースが足りません。"},
    {"speaker": "Speaker 2", "text": "了解です。次のスプリントでデプロイメントパイプラインを設定します。"},
]


# ── Test: Transcript Persistence ────────────────────────────────

class TestTranscriptPersistence:

    def test_seed_and_read_transcript(self, client):
        """Verify transcript entries can be stored and retrieved."""
        m = _create_meeting(client, "Persist Test")
        _seed_transcript(client, m["id"], SAMPLE_TRANSCRIPT)

        r = client.get(f"/api/meetings/{m['id']}/transcript")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == len(SAMPLE_TRANSCRIPT)
        assert data[0]["text"] == SAMPLE_TRANSCRIPT[0]["text"]
        assert data[0]["speaker"] == "Speaker 1"

    def test_transcript_count_on_meeting(self, client):
        """Meeting response should include transcript_count."""
        m = _create_meeting(client, "Count Test")
        _seed_transcript(client, m["id"], SAMPLE_TRANSCRIPT[:3])

        r = client.get(f"/api/meetings/{m['id']}")
        assert r.status_code == 200
        data = r.json()
        assert data["transcript_count"] == 3

    def test_meeting_delete_cascades_transcript(self, client):
        """Deleting a meeting should cascade-delete transcript entries."""
        m = _create_meeting(client, "Cascade Test")
        _seed_transcript(client, m["id"], SAMPLE_TRANSCRIPT[:2])

        r = client.delete(f"/api/meetings/{m['id']}")
        assert r.status_code == 204

        r = client.get(f"/api/meetings/{m['id']}")
        assert r.status_code == 404


# ── Test: Intelligence API ──────────────────────────────────────

class TestIntelligenceAPI:

    def test_summary_no_transcript_returns_400(self, client):
        m = _create_meeting(client, "Empty Meeting")
        r = client.post(f"/api/meetings/{m['id']}/summary")
        assert r.status_code == 400

    def test_actions_no_transcript_returns_400(self, client):
        m = _create_meeting(client, "Empty Meeting")
        r = client.post(f"/api/meetings/{m['id']}/actions")
        assert r.status_code == 400

    def test_timeline_no_transcript_returns_400(self, client):
        m = _create_meeting(client, "Empty Meeting")
        r = client.post(f"/api/meetings/{m['id']}/timeline")
        assert r.status_code == 400

    def test_decisions_no_transcript_returns_400(self, client):
        m = _create_meeting(client, "Empty Meeting")
        r = client.post(f"/api/meetings/{m['id']}/decisions")
        assert r.status_code == 400

    def test_summary_not_found(self, client):
        r = client.post("/api/meetings/nonexistent/summary")
        assert r.status_code == 404

    @patch("app.services.intelligence._call_llm")
    def test_summary_with_mock_llm(self, mock_llm, client):
        mock_llm.return_value = json.dumps({
            "overview": "Team discussed project progress. Backend 80% done.",
            "key_topics": ["Backend progress", "Testing coverage", "Mobile postponed"],
            "decisions": [{"decision": "Postpone mobile", "reason": "Lack of resources"}],
            "risks": ["Low test coverage"],
            "next_steps": ["Increase test coverage to 80%"],
        })

        m = _create_meeting(client, "Summary Test")
        _seed_transcript(client, m["id"], SAMPLE_TRANSCRIPT)

        r = client.post(f"/api/meetings/{m['id']}/summary")
        assert r.status_code == 200
        data = r.json()
        assert "overview" in data
        assert len(data["key_topics"]) > 0
        assert len(data["decisions"]) > 0
        assert data["decisions"][0]["decision"] == "Postpone mobile"

    @patch("app.services.intelligence._call_llm")
    def test_actions_with_mock_llm(self, mock_llm, client):
        mock_llm.return_value = json.dumps([
            {"task": "Increase test coverage to 80%", "owner": "Speaker 2", "deadline": "Next week", "priority": "high"},
            {"task": "Set up deployment pipeline", "owner": "Speaker 2", "deadline": "Next sprint", "priority": "medium"},
        ])

        m = _create_meeting(client, "Actions Test")
        _seed_transcript(client, m["id"], SAMPLE_TRANSCRIPT)

        r = client.post(f"/api/meetings/{m['id']}/actions")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2
        assert data[0]["task"] == "Increase test coverage to 80%"
        assert data[0]["priority"] == "high"

    @patch("app.services.intelligence._call_llm")
    def test_timeline_with_mock_llm(self, mock_llm, client):
        mock_llm.return_value = json.dumps([
            {"time": "00:00", "topic": "Project progress review", "summary": "Started discussing overall progress"},
            {"time": "02:30", "topic": "Testing status", "summary": "Reviewed test coverage numbers"},
        ])

        m = _create_meeting(client, "Timeline Test")
        _seed_transcript(client, m["id"], SAMPLE_TRANSCRIPT)

        r = client.post(f"/api/meetings/{m['id']}/timeline")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2

    @patch("app.services.intelligence._call_llm")
    def test_decisions_with_mock_llm(self, mock_llm, client):
        mock_llm.return_value = json.dumps([
            {"decision": "Postpone mobile support", "reason": "Lack of resources", "context": "Discussed during sprint planning"},
        ])

        m = _create_meeting(client, "Decisions Test")
        _seed_transcript(client, m["id"], SAMPLE_TRANSCRIPT)

        r = client.post(f"/api/meetings/{m['id']}/decisions")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert "mobile" in data[0]["decision"].lower()


# ── Test: Embedding / Chunking (unit-level) ─────────────────────

class TestChunking:

    def test_chunk_transcript_basic(self):
        from app.services.embedding import chunk_transcript

        entries = [
            {"meeting_id": "m1", "speaker": "A", "text": "Hello world " * 20},
            {"meeting_id": "m1", "speaker": "B", "text": "Goodbye world " * 20},
        ]
        chunks = chunk_transcript(entries, chunk_size=200, overlap=50)
        assert len(chunks) > 0
        for c in chunks:
            assert len(c["text"]) <= 200
            assert c["meeting_id"] == "m1"

    def test_chunk_transcript_empty(self):
        from app.services.embedding import chunk_transcript
        assert chunk_transcript([]) == []

    def test_chunk_transcript_overlap(self):
        from app.services.embedding import chunk_transcript

        entries = [
            {"meeting_id": "m1", "speaker": "A", "text": "x" * 600},
        ]
        chunks = chunk_transcript(entries, chunk_size=300, overlap=100)
        assert len(chunks) >= 2
        text0 = chunks[0]["text"]
        text1 = chunks[1]["text"]
        overlap_text = text0[-100:]
        assert overlap_text in text1


# ── Test: RAG API ───────────────────────────────────────────────

class TestRagAPI:

    def test_chat_no_index(self, client):
        """Chat without any indexed meetings should return a default message."""
        with patch("app.services.rag.search_index", return_value=[]):
            r = client.post("/api/chat", json={"query": "What happened?"})
            assert r.status_code == 200
            data = r.json()
            assert "answer" in data

    def test_index_no_transcript_returns_400(self, client):
        m = _create_meeting(client, "Empty for Index")
        r = client.post(f"/api/meetings/{m['id']}/index")
        assert r.status_code == 400

    @patch("app.services.embedding.get_embeddings")
    def test_index_and_search(self, mock_embed, client):
        """Index a meeting, then search it."""
        dim = 1536
        mock_embed.side_effect = lambda texts: np.random.randn(len(texts), dim).astype(np.float32)

        m = _create_meeting(client, "Index Test")
        _seed_transcript(client, m["id"], SAMPLE_TRANSCRIPT)

        r = client.post(f"/api/meetings/{m['id']}/index")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "indexed"
        assert data["chunks"] > 0

    def test_search_no_index(self, client):
        with patch("app.services.embedding.get_embeddings") as mock_embed:
            mock_embed.return_value = np.zeros((1, 1536), dtype=np.float32)
            r = client.post("/api/search", json={"query": "test"})
            assert r.status_code == 200

    def test_chat_with_mock_rag(self, client):
        with patch("app.services.rag.search_index") as mock_search, \
             patch("app.services.rag._get_client") as mock_client:

            mock_search.return_value = [
                {"meeting_id": "m1", "text": "We decided to postpone mobile.", "speakers": ["Speaker 1"], "score": 0.9},
            ]

            mock_completion = MagicMock()
            mock_completion.choices = [MagicMock()]
            mock_completion.choices[0].message.content = "The team decided to postpone mobile support."
            mock_client.return_value.chat.completions.create.return_value = mock_completion

            r = client.post("/api/chat", json={"query": "What about mobile?"})
            assert r.status_code == 200
            data = r.json()
            assert "mobile" in data["answer"].lower()
            assert len(data["sources"]) > 0


# ── Test: Upload API ────────────────────────────────────────────

class TestUploadAPI:

    def test_upload_no_file(self, client):
        r = client.post("/api/upload")
        assert r.status_code == 422

    def test_upload_unsupported_format(self, client):
        from io import BytesIO
        r = client.post(
            "/api/upload",
            files={"file": ("test.xyz", BytesIO(b"data"), "application/octet-stream")},
            data={"language": "ja", "mode": "meeting"},
        )
        assert r.status_code == 400

    @patch("app.api.upload.transcribe_file")
    def test_upload_success_with_mock_transcriber(self, mock_transcribe, client):
        """Upload a fake WAV file and verify the pipeline returns correct structure."""
        mock_transcribe.return_value = {
            "status": "ok",
            "segments": 5,
            "duration": 120.0,
            "method": "azure",
            "speakers": ["Guest-1", "Guest-2"],
        }

        from io import BytesIO
        wav_data = BytesIO(b"RIFF" + b"\x00" * 100)
        r = client.post(
            "/api/upload",
            files={"file": ("test.wav", wav_data, "audio/wav")},
            data={"language": "ja", "mode": "interview", "meeting_name": "Upload Test"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "transcribed"
        assert data["method"] == "azure"
        assert "Guest-1" in data["speakers"]
        assert data["segments"] == 5

    @patch("app.api.upload.transcribe_file")
    def test_upload_creates_meeting(self, mock_transcribe, client):
        """Uploaded file should auto-create a meeting record."""
        mock_transcribe.return_value = {
            "status": "ok", "segments": 1, "duration": 10.0,
            "method": "whisper", "speakers": ["Speaker"],
        }

        from io import BytesIO
        r = client.post(
            "/api/upload",
            files={"file": ("interview.mp3", BytesIO(b"\x00" * 50), "audio/mpeg")},
            data={"language": "ja", "mode": "interview"},
        )
        assert r.status_code == 200
        meeting_id = r.json()["meeting_id"]

        r2 = client.get(f"/api/meetings/{meeting_id}")
        assert r2.status_code == 200
        assert r2.json()["status"] == "completed"


# ── Test: Transcript Export ──────────────────────────────────────

class TestTranscriptExport:

    def test_export_not_found(self, client):
        r = client.get("/api/meetings/nonexistent/transcript/export")
        assert r.status_code == 404

    def test_export_no_entries(self, client):
        m = _create_meeting(client, "Empty Export")
        r = client.get(f"/api/meetings/{m['id']}/transcript/export")
        assert r.status_code == 200
        assert r.json()["text"] == ""

    def test_export_with_transcript(self, client):
        m = _create_meeting(client, "Export Test")
        _seed_transcript(client, m["id"], SAMPLE_TRANSCRIPT)

        r = client.get(f"/api/meetings/{m['id']}/transcript/export")
        assert r.status_code == 200
        data = r.json()
        assert "text" in data
        assert "Speaker 1" in data["text"]

    def test_export_html_format(self, client):
        m = _create_meeting(client, "HTML Export")
        _seed_transcript(client, m["id"], SAMPLE_TRANSCRIPT)

        r = client.get(f"/api/meetings/{m['id']}/transcript/export?format=html")
        assert r.status_code == 200
        data = r.json()
        assert "html" in data
        assert "HTML Export" in data["html"]


# ── Test: MeetingSession transcript persistence ─────────────────

class TestMeetingSessionPersist:

    def test_persist_transcript_writes_to_db(self, client):
        """Verify MeetingSession._persist_transcript writes to DB."""
        from app.services.meeting_session import MeetingSession
        import asyncio

        m = _create_meeting(client, "Session Persist Test")
        meeting_id = m["id"]

        async def noop(data):
            pass

        session = MeetingSession(noop, meeting_id, "ja-JP", "interview")
        session._persist_transcript("テスト発言", "tesuto hatsugen", "Speaker 1", "s1")

        r = client.get(f"/api/meetings/{meeting_id}/transcript")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["text"] == "テスト発言"
        assert data[0]["speaker"] == "Speaker 1"

    def test_persist_translation_updates_entry(self, client):
        """Verify MeetingSession._persist_translation updates the latest entry."""
        from app.services.meeting_session import MeetingSession

        m = _create_meeting(client, "Translation Persist Test")
        meeting_id = m["id"]

        async def noop(data):
            pass

        session = MeetingSession(noop, meeting_id, "ja-JP", "interview")
        session._persist_transcript("テスト", "", "Speaker 1", "s1")
        session._persist_translation("Bài kiểm tra", "Speaker 1")

        r = client.get(f"/api/meetings/{meeting_id}/transcript")
        data = r.json()
        assert len(data) == 1
        assert data[0]["translation_vi"] == "Bài kiểm tra"


# ── Test: Stabilizer → Pipeline integration ─────────────────────

class TestStabilizerIntegration:

    def test_full_stabilizer_pipeline_emits_correct_events(self):
        """Run interim→interim→final through the pipeline and verify output."""
        from app.services.stabilizer import StabilizedPipeline
        import time

        events = []
        def capture_emit(data):
            events.append(data)

        pipeline = StabilizedPipeline(
            emit_fn=capture_emit,
            throttle_ms=50,
            min_change_chars=1,
            translation_final_only=True,
            merge_window_ms=500,
            prefix_lock_ratio=0.5,
        )

        pipeline.on_interim("こんにちは", "konnichiwa", "Speaker 1")
        time.sleep(0.1)
        pipeline.on_interim("こんにちは世界", "konnichiwa sekai", "Speaker 1")
        time.sleep(0.1)
        pipeline.on_final("こんにちは世界", "konnichiwa sekai", "Speaker 1")

        finals = [e for e in events if e.get("type") == "final"]
        assert len(finals) >= 1
        assert finals[-1]["text"] == "こんにちは世界"

    def test_translation_blocked_then_allowed(self):
        """Translation should be blocked before final, allowed after."""
        from app.services.stabilizer import StabilizedPipeline

        events = []
        def capture_emit(data):
            events.append(data)

        pipeline = StabilizedPipeline(
            emit_fn=capture_emit,
            throttle_ms=0,
            min_change_chars=1,
            translation_final_only=True,
            merge_window_ms=500,
            prefix_lock_ratio=0.5,
        )

        pipeline.on_translation("Before final", "Speaker 1")
        blocked_translations = [e for e in events if e.get("type") == "translation"]
        assert len(blocked_translations) == 0

        pipeline.on_interim("テスト", "", "Speaker 1")
        pipeline.on_final("テスト", "", "Speaker 1")
        pipeline.on_translation("After final", "Speaker 1")

        translations = [e for e in events if e.get("type") == "translation"]
        assert len(translations) == 1
        assert translations[0]["vi"] == "After final"


# ── Test: Suggestion Pipeline integration ───────────────────────

class TestSuggestionIntegration:

    def test_question_triggers_suggestion(self):
        """Full flow: speech → aggregator → classifier → controller → suggestion."""
        from app.services.suggestion import SuggestionController, Turn

        suggestions = []
        topics = []

        ctrl = SuggestionController(
            mode="interview",
            on_suggest=lambda turn: suggestions.append(turn),
            on_topic=lambda topic: topics.append(topic),
            language="ja-JP",
            cooldown_ms=0,
        )

        ctrl.on_final("ReactのuseEffectについて説明してください", "", "Speaker 1")
        import time
        time.sleep(2.5)
        ctrl.on_final("dummy", "", "Speaker 2")

        assert len(suggestions) >= 1
        assert "useEffect" in suggestions[0].full_text

    def test_meeting_mode_filters_statements(self):
        """In meeting mode, statements should NOT trigger suggestions."""
        from app.services.suggestion import SuggestionController

        suggestions = []

        ctrl = SuggestionController(
            mode="meeting",
            on_suggest=lambda turn: suggestions.append(turn),
            on_topic=lambda topic: None,
            language="ja-JP",
            cooldown_ms=0,
        )

        ctrl.on_final("今日の天気は良いですね", "", "Speaker 1")
        import time
        time.sleep(2.5)
        ctrl.on_final("dummy", "", "Speaker 2")

        assert len(suggestions) == 0
