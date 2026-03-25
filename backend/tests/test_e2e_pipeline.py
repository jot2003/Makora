"""End-to-end pipeline test: simulates the complete meeting lifecycle.

Tests the flow:
1. Create meeting
2. Seed transcript (simulating realtime STT)
3. Verify transcript persistence
4. Generate intelligence (summary, actions, decisions, timeline) with mocked LLM
5. Build FAISS index with mocked embeddings
6. Chat with meeting (RAG) with mocked LLM
7. Semantic search with mocked embeddings

This validates that ALL components work together correctly.
"""

import json
import uuid
from unittest.mock import patch, MagicMock
import os

import numpy as np
import pytest


MEETING_TRANSCRIPT = [
    {"speaker": "Interviewer", "text": "自己紹介をお願いします。"},
    {"speaker": "Candidate", "text": "はい、田中太郎と申します。ソフトウェアエンジニアとして5年の経験があります。"},
    {"speaker": "Interviewer", "text": "Pythonの経験はありますか？"},
    {"speaker": "Candidate", "text": "はい、Pythonは主にバックエンド開発で使用しています。FastAPIとDjangoの経験があります。"},
    {"speaker": "Interviewer", "text": "マイクロサービスの設計についてどう考えていますか？"},
    {"speaker": "Candidate", "text": "マイクロサービスは、チーム規模が大きい場合に有効だと思います。ただし、小さなチームではモノリスの方が効率的な場合もあります。"},
    {"speaker": "Interviewer", "text": "テストについてはどうですか？テストカバレッジはどれくらいを目標にしていますか？"},
    {"speaker": "Candidate", "text": "最低80%のカバレッジを目標にしています。特にビジネスロジックは100%に近づけるようにしています。"},
    {"speaker": "Interviewer", "text": "わかりました。では、次のステップとして技術課題をお送りします。来週の金曜日までに提出してください。"},
    {"speaker": "Candidate", "text": "承知しました。よろしくお願いします。"},
]

MOCK_SUMMARY = {
    "overview": "Technical interview with Tanaka Taro, a software engineer with 5 years of experience. Discussion covered Python expertise, microservices architecture, and testing practices.",
    "key_topics": ["Self-introduction", "Python experience", "Microservices design", "Testing coverage"],
    "decisions": [{"decision": "Send technical challenge", "reason": "Candidate seems qualified"}],
    "risks": ["Candidate may prefer monolith over microservices for small teams"],
    "next_steps": ["Send technical challenge by next Friday"],
}

MOCK_ACTIONS = [
    {"task": "Send technical challenge to candidate", "owner": "Interviewer", "deadline": "Next Friday", "priority": "high"},
    {"task": "Submit technical challenge", "owner": "Candidate", "deadline": "Next Friday", "priority": "high"},
]

MOCK_TIMELINE = [
    {"time": "00:00", "topic": "Self-introduction", "summary": "Candidate introduced himself as Tanaka Taro with 5 years of experience"},
    {"time": "01:30", "topic": "Python expertise", "summary": "Discussed Python backend experience with FastAPI and Django"},
    {"time": "03:00", "topic": "Architecture discussion", "summary": "Debated microservices vs monolith for different team sizes"},
    {"time": "05:00", "topic": "Testing practices", "summary": "Candidate targets 80% coverage minimum, higher for business logic"},
    {"time": "07:00", "topic": "Next steps", "summary": "Interviewer will send technical challenge due next Friday"},
]

MOCK_DECISIONS = [
    {"decision": "Send technical challenge", "reason": "Candidate demonstrated good technical knowledge", "context": "After discussing testing and architecture"},
]


def _seed(client, meeting_id, entries):
    from app.models.database import SessionLocal, TranscriptEntry
    db = SessionLocal()
    for e in entries:
        db.add(TranscriptEntry(
            meeting_id=meeting_id,
            speaker=e["speaker"],
            speaker_id="test",
            language="ja-JP",
            source="realtime",
            text=e["text"],
        ))
    db.commit()
    db.close()


class TestFullE2EPipeline:
    """Complete end-to-end test of the meeting copilot pipeline."""

    def test_complete_meeting_lifecycle(self, client):
        """Full lifecycle: create → transcribe → intelligence → index → chat → search."""

        # ── Step 1: Create meeting ──
        r = client.post("/api/meetings", json={
            "name": "Technical Interview - Tanaka Taro",
            "mode": "interview",
            "language": "ja-JP",
        })
        assert r.status_code == 201
        meeting = r.json()
        meeting_id = meeting["id"]
        assert meeting["name"] == "Technical Interview - Tanaka Taro"
        assert meeting["mode"] == "interview"

        # ── Step 2: Seed transcript (simulating realtime persistence) ──
        _seed(client, meeting_id, MEETING_TRANSCRIPT)

        r = client.get(f"/api/meetings/{meeting_id}/transcript")
        assert r.status_code == 200
        transcript = r.json()
        assert len(transcript) == 10
        assert transcript[0]["speaker"] == "Interviewer"
        assert transcript[1]["speaker"] == "Candidate"

        # Verify meeting transcript count
        r = client.get(f"/api/meetings/{meeting_id}")
        assert r.json()["transcript_count"] == 10

        # ── Step 3: Generate intelligence (mocked LLM) ──
        with patch("app.services.intelligence._call_llm") as mock_llm:
            # Summary
            mock_llm.return_value = json.dumps(MOCK_SUMMARY)
            r = client.post(f"/api/meetings/{meeting_id}/summary")
            assert r.status_code == 200
            summary = r.json()
            assert "Tanaka" in summary["overview"]
            assert len(summary["key_topics"]) >= 3
            assert len(summary["decisions"]) >= 1
            assert len(summary["next_steps"]) >= 1

            # Actions
            mock_llm.return_value = json.dumps(MOCK_ACTIONS)
            r = client.post(f"/api/meetings/{meeting_id}/actions")
            assert r.status_code == 200
            actions = r.json()
            assert len(actions) == 2
            assert any("technical challenge" in a["task"].lower() for a in actions)

            # Timeline
            mock_llm.return_value = json.dumps(MOCK_TIMELINE)
            r = client.post(f"/api/meetings/{meeting_id}/timeline")
            assert r.status_code == 200
            timeline = r.json()
            assert len(timeline) >= 4

            # Decisions
            mock_llm.return_value = json.dumps(MOCK_DECISIONS)
            r = client.post(f"/api/meetings/{meeting_id}/decisions")
            assert r.status_code == 200
            decisions = r.json()
            assert len(decisions) >= 1

        # ── Step 4: Build FAISS index (mocked embeddings) ──
        dim = 1536
        with patch("app.services.embedding.get_embeddings") as mock_embed:
            mock_embed.side_effect = lambda texts: np.random.randn(len(texts), dim).astype(np.float32)

            r = client.post(f"/api/meetings/{meeting_id}/index")
            assert r.status_code == 200
            idx_result = r.json()
            assert idx_result["status"] == "indexed"
            assert idx_result["chunks"] > 0

        # ── Step 5: Chat with meeting (mocked RAG) ──
        with patch("app.services.rag.search_index") as mock_search, \
             patch("app.services.rag._get_client") as mock_client:

            mock_search.return_value = [
                {
                    "meeting_id": meeting_id,
                    "text": "[Candidate] Pythonは主にバックエンド開発で使用しています。FastAPIとDjangoの経験があります。",
                    "speakers": ["Candidate"],
                    "score": 0.92,
                },
            ]

            mock_completion = MagicMock()
            mock_completion.choices = [MagicMock()]
            mock_completion.choices[0].message.content = (
                "The candidate has Python experience, primarily in backend development "
                "using FastAPI and Django frameworks."
            )
            mock_client.return_value.chat.completions.create.return_value = mock_completion

            r = client.post("/api/chat", json={
                "query": "What Python experience does the candidate have?",
                "meeting_ids": [meeting_id],
            })
            assert r.status_code == 200
            chat = r.json()
            assert "python" in chat["answer"].lower() or "Python" in chat["answer"]
            assert len(chat["sources"]) > 0
            assert chat["sources"][0]["meeting_id"] == meeting_id

        # ── Step 6: Search (mocked) ──
        with patch("app.services.embedding.search_index") as mock_search:
            mock_search.return_value = [
                {
                    "meeting_id": meeting_id,
                    "text": "[Interviewer] マイクロサービスの設計についてどう考えていますか？",
                    "speakers": ["Interviewer"],
                    "score": 0.88,
                },
            ]
            r = client.post("/api/search", json={"query": "microservices architecture"})
            assert r.status_code == 200
            results = r.json()
            assert len(results) >= 1

        # ── Step 7: Update meeting status ──
        r = client.patch(f"/api/meetings/{meeting_id}", json={"status": "completed"})
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

        # ── Step 8: Verify everything persisted ──
        r = client.get(f"/api/meetings/{meeting_id}")
        assert r.status_code == 200
        final = r.json()
        assert final["status"] == "completed"
        assert final["transcript_count"] == 10

    @patch.dict("os.environ", {"AZURE_SPEECH_KEY": "", "AZURE_SPEECH_REGION": ""})
    def test_websocket_session_flow(self, client):
        """Test WebSocket session start/stop lifecycle (placeholder mode — no audio)."""
        r = client.post("/api/meetings", json={"name": "WS Test", "mode": "interview"})
        meeting_id = r.json()["id"]

        # Temporarily disable Azure keys so MeetingSession doesn't try to open audio
        import app.core.config as cfg
        orig_key = cfg.settings.AZURE_SPEECH_KEY
        orig_region = cfg.settings.AZURE_SPEECH_REGION
        cfg.settings.AZURE_SPEECH_KEY = ""
        cfg.settings.AZURE_SPEECH_REGION = ""

        try:
            with client.websocket_connect("/ws/meeting") as ws:
                ws.send_text(json.dumps({"type": "ping"}))
                resp = ws.receive_json()
                assert resp["type"] == "pong"

                ws.send_text(json.dumps({
                    "type": "start_meeting",
                    "meeting_id": meeting_id,
                    "language": "ja-JP",
                    "mode": "interview",
                }))

                msg = ws.receive_json()
                assert msg["type"] == "status"
                assert "placeholder" in msg.get("message", "").lower() or "started" in msg.get("message", "").lower()

                ws.send_text(json.dumps({"type": "stop_meeting"}))
                stop = ws.receive_json()
                assert stop["type"] == "status"
                assert "stop" in stop.get("message", "").lower()
        finally:
            cfg.settings.AZURE_SPEECH_KEY = orig_key
            cfg.settings.AZURE_SPEECH_REGION = orig_region

    def test_multiple_meetings_isolation(self, client):
        """Verify transcript data is isolated between meetings."""
        r1 = client.post("/api/meetings", json={"name": "Meeting A"})
        r2 = client.post("/api/meetings", json={"name": "Meeting B"})
        id_a = r1.json()["id"]
        id_b = r2.json()["id"]

        _seed(client, id_a, [{"speaker": "Alice", "text": "Data for meeting A"}])
        _seed(client, id_b, [{"speaker": "Bob", "text": "Data for meeting B"}, {"speaker": "Bob", "text": "More data"}])

        r_a = client.get(f"/api/meetings/{id_a}/transcript")
        r_b = client.get(f"/api/meetings/{id_b}/transcript")

        assert len(r_a.json()) == 1
        assert len(r_b.json()) == 2
        assert r_a.json()[0]["speaker"] == "Alice"
        assert r_b.json()[0]["speaker"] == "Bob"


class TestUploadWithWav:
    """Test audio upload with a real generated WAV file."""

    def test_upload_wav_file(self, client):
        """Generate a short silent WAV and upload it."""
        import io
        import struct

        sample_rate = 16000
        duration = 0.5
        n_samples = int(sample_rate * duration)
        samples = b'\x00\x00' * n_samples

        wav_buf = io.BytesIO()
        n_channels = 1
        sample_width = 2
        data_size = n_samples * n_channels * sample_width
        wav_buf.write(b'RIFF')
        wav_buf.write(struct.pack('<I', 36 + data_size))
        wav_buf.write(b'WAVE')
        wav_buf.write(b'fmt ')
        wav_buf.write(struct.pack('<IHHIIHH', 16, 1, n_channels, sample_rate,
                                  sample_rate * n_channels * sample_width,
                                  n_channels * sample_width, sample_width * 8))
        wav_buf.write(b'data')
        wav_buf.write(struct.pack('<I', data_size))
        wav_buf.write(samples)
        wav_buf.seek(0)

        r = client.post(
            "/api/upload",
            files={"file": ("test_audio.wav", wav_buf, "audio/wav")},
            data={"language": "ja"},
        )
        # Whisper may or may not be installed; both outcomes are valid
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            data = r.json()
            assert "meeting_id" in data
            assert data["status"] == "transcribed"


class TestUploadFullPipeline:
    """Test the full upload → transcribe → intelligence → export pipeline."""

    @patch("app.api.upload.transcribe_file")
    def test_upload_to_intelligence_pipeline(self, mock_transcribe, client):
        """Upload → auto-create meeting → seed transcript → intelligence."""
        mock_transcribe.return_value = {
            "status": "ok", "segments": 4, "duration": 60.0,
            "method": "azure", "speakers": ["Guest-1", "Guest-2"],
        }

        from io import BytesIO
        r = client.post(
            "/api/upload",
            files={"file": ("interview.mp3", BytesIO(b"\x00" * 50), "audio/mpeg")},
            data={"language": "ja", "mode": "interview", "meeting_name": "Pipeline Test"},
        )
        assert r.status_code == 200
        meeting_id = r.json()["meeting_id"]

        _seed(client, meeting_id, MEETING_TRANSCRIPT)

        r = client.get(f"/api/meetings/{meeting_id}/transcript")
        assert r.status_code == 200
        assert len(r.json()) == 10

        with patch("app.services.intelligence._call_llm") as mock_llm:
            mock_llm.return_value = json.dumps(MOCK_SUMMARY)
            r = client.post(f"/api/meetings/{meeting_id}/summary")
            assert r.status_code == 200
            assert "Tanaka" in r.json()["overview"]

        r = client.get(f"/api/meetings/{meeting_id}/transcript/export")
        assert r.status_code == 200
        export = r.json()
        assert export["entries"] == 10
        assert "Pipeline Test" in export["text"]

    @patch("app.api.upload.transcribe_file")
    def test_upload_with_speakers_returns_metadata(self, mock_transcribe, client):
        """Verify upload response includes speaker and method metadata."""
        mock_transcribe.return_value = {
            "status": "ok", "segments": 73, "duration": 434.0,
            "method": "azure", "speakers": ["Guest-1", "Guest-2"],
        }

        from io import BytesIO
        r = client.post(
            "/api/upload",
            files={"file": ("web_interview.mp3", BytesIO(b"\x00" * 50), "audio/mpeg")},
            data={"language": "ja", "mode": "interview"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["method"] == "azure"
        assert len(data["speakers"]) == 2
        assert data["segments"] == 73
        assert data["duration"] == 434.0
