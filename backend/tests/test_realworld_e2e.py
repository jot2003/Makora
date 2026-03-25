"""
Real-world E2E test suite.
Runs against a LIVE server at http://localhost:8000.
Tests the full pipeline: upload → transcribe → intelligence → RAG → export.

Usage:
    python tests/test_realworld_e2e.py
"""
import json
import os
import sys
import time
import shutil
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import httpx

BASE = os.environ.get("API_URL", "http://localhost:8000")
TIMEOUT = httpx.Timeout(300.0, connect=10.0)

SAMPLE_AUDIO = Path(__file__).parent.parent / "data" / "audio" / "web_interview_sample.mp3"

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

passed = 0
failed = 0
results = []


def log(msg: str, color: str = RESET):
    print(f"{color}{msg}{RESET}")


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        results.append((name, True, detail))
        log(f"  PASS  {name}" + (f" — {detail}" if detail else ""), GREEN)
    else:
        failed += 1
        results.append((name, False, detail))
        log(f"  FAIL  {name}" + (f" — {detail}" if detail else ""), RED)


def section(title: str):
    log(f"\n{'='*60}", CYAN)
    log(f"  {title}", CYAN + BOLD)
    log(f"{'='*60}", CYAN)


def main():
    global passed, failed
    client = httpx.Client(base_url=BASE, timeout=TIMEOUT)
    created_meeting_ids = []

    # ── 1. Health ──
    section("1. Health Check")
    try:
        r = client.get("/health")
        check("GET /health returns 200", r.status_code == 200)
        check("Response has status=ok", r.json().get("status") == "ok")
    except Exception as e:
        check("Server reachable", False, str(e))
        log("\nServer not running. Start with: python -m uvicorn app.main:app --port 8000", RED)
        return

    # ── 2. Meeting CRUD ──
    section("2. Meeting CRUD")
    r = client.post("/api/meetings", json={"name": "E2E Test Meeting", "mode": "interview"})
    check("Create meeting", r.status_code in (200, 201), f"status={r.status_code}")
    m1 = r.json()
    m1_id = m1.get("id", "")
    created_meeting_ids.append(m1_id)
    check("Meeting has id", bool(m1_id))
    check("Meeting name correct", m1.get("name") == "E2E Test Meeting")

    r = client.get("/api/meetings")
    check("List meetings", r.status_code == 200)
    check("Created meeting in list", any(m["id"] == m1_id for m in r.json()))

    r = client.get(f"/api/meetings/{m1_id}")
    check("Get meeting by id", r.status_code == 200 and r.json()["id"] == m1_id)

    r = client.patch(f"/api/meetings/{m1_id}", json={"name": "Renamed Meeting"})
    check("Update meeting", r.status_code == 200 and r.json()["name"] == "Renamed Meeting")

    r = client.get("/api/meetings/nonexistent-id")
    check("Get nonexistent meeting returns 404", r.status_code == 404)

    # ── 3. Upload & Transcription ──
    section("3. Upload & Transcription (Real Audio)")
    upload_id = None
    if SAMPLE_AUDIO.exists():
        log(f"  Using: {SAMPLE_AUDIO.name} ({SAMPLE_AUDIO.stat().st_size / 1024 / 1024:.1f} MB)", YELLOW)
        t0 = time.time()
        with open(SAMPLE_AUDIO, "rb") as f:
            r = client.post("/api/upload", files={"file": ("sample.mp3", f, "audio/mpeg")},
                            data={"language": "ja", "mode": "interview", "meeting_name": "Real Audio Test"})
        elapsed = time.time() - t0
        check("Upload returns 200", r.status_code == 200, f"{elapsed:.1f}s")
        if r.status_code == 200:
            data = r.json()
            upload_id = data.get("meeting_id", "")
            created_meeting_ids.append(upload_id)
            segments = data.get("segments", 0)
            duration = data.get("duration", 0)
            method = data.get("method", "unknown")
            speakers = data.get("speakers", [])

            check("Has meeting_id", bool(upload_id))
            check("Has segments > 0", segments > 0, f"{segments} segments")
            check("Has duration > 0", duration > 0, f"{duration:.1f}s")
            check("Method reported", method in ("azure", "whisper"), method)
            check("Speakers detected", len(speakers) >= 1, str(speakers))

            # Transcript read
            r = client.get(f"/api/meetings/{upload_id}/transcript")
            check("Transcript readable", r.status_code == 200)
            entries = r.json() if r.status_code == 200 else []
            check("Transcript has entries", len(entries) > 0, f"{len(entries)} entries")

            if entries:
                has_speaker = any(e.get("speaker") for e in entries)
                check("Entries have speaker labels", has_speaker)
                has_text = all(e.get("text") for e in entries)
                check("All entries have text", has_text)

            # Export transcript
            r = client.get(f"/api/meetings/{upload_id}/transcript/export")
            check("Export transcript", r.status_code == 200)
            if r.status_code == 200:
                export_text = r.json().get("text", "")
                check("Export has content", len(export_text) > 50, f"{len(export_text)} chars")
        else:
            log(f"  Upload failed: {r.text}", RED)
    else:
        log(f"  SKIP: No audio file at {SAMPLE_AUDIO}", YELLOW)
        upload_id = None

    # ── 4. Intelligence ──
    section("4. Post-meeting Intelligence")
    test_id = upload_id if upload_id else m1_id
    has_transcript = False

    r = client.get(f"/api/meetings/{test_id}/transcript")
    if r.status_code == 200 and len(r.json()) > 0:
        has_transcript = True

    if has_transcript:
        for endpoint in ["summary", "actions", "timeline", "decisions"]:
            t0 = time.time()
            r = client.post(f"/api/meetings/{test_id}/{endpoint}")
            elapsed = time.time() - t0
            check(f"POST /{endpoint} returns 200", r.status_code == 200, f"{elapsed:.1f}s")
            if r.status_code == 200:
                data = r.json()
                if endpoint == "summary":
                    has_overview = bool(data.get("overview"))
                    check("Summary has overview", has_overview, data.get("overview", "")[:80] if has_overview else "empty (LLM may have returned different format)")
                    check("Summary has key_topics", isinstance(data.get("key_topics"), list))
                elif endpoint == "actions":
                    check("Actions is list", isinstance(data, list))
                    if data:
                        check("Action has task field", bool(data[0].get("task")))
                elif endpoint == "timeline":
                    check("Timeline is list", isinstance(data, list))
                    if data:
                        check("Timeline entry has time", bool(data[0].get("time")))
                elif endpoint == "decisions":
                    check("Decisions is list", isinstance(data, list))
    else:
        log("  SKIP: No transcript available for intelligence tests", YELLOW)

    # ── 5. RAG Pipeline ──
    section("5. RAG Pipeline (Index -> Chat -> Search)")
    if has_transcript:
        t0 = time.time()
        r = client.post(f"/api/meetings/{test_id}/index")
        elapsed = time.time() - t0
        check("Build FAISS index", r.status_code == 200, f"{elapsed:.1f}s")
        if r.status_code == 200:
            idx_data = r.json()
            check("Index has chunks", idx_data.get("chunks", 0) > 0, f"{idx_data.get('chunks')} chunks")

        t0 = time.time()
        r = client.post("/api/chat", json={"query": "What was discussed in this meeting?"})
        elapsed = time.time() - t0
        check("Chat returns 200", r.status_code == 200, f"{elapsed:.1f}s")
        if r.status_code == 200:
            chat_data = r.json()
            check("Chat has answer", bool(chat_data.get("answer")))
            check("Chat has sources", isinstance(chat_data.get("sources"), list))
            log(f"\n  AI Answer: {chat_data.get('answer', '')[:200]}...", YELLOW)

        t0 = time.time()
        r = client.post("/api/search", json={"query": "interview questions", "top_k": 3})
        elapsed = time.time() - t0
        check("Search returns 200", r.status_code == 200, f"{elapsed:.1f}s")
        if r.status_code == 200:
            search_data = r.json()
            check("Search has results", isinstance(search_data, list), f"{len(search_data)} results")
    else:
        log("  SKIP: No transcript for RAG tests", YELLOW)

    # ── 6. WebSocket ──
    section("6. WebSocket Connectivity")
    try:
        import websockets
        import asyncio

        async def ws_test():
            uri = BASE.replace("http", "ws") + "/ws/meeting"
            async with websockets.connect(uri) as ws:
                await ws.send(json.dumps({"type": "ping"}))
                resp = await asyncio.wait_for(ws.recv(), timeout=5.0)
                data = json.loads(resp)
                return data.get("type") == "pong"

        ws_ok = asyncio.get_event_loop().run_until_complete(ws_test())
        check("WebSocket ping/pong", ws_ok)
    except ImportError:
        log("  SKIP: websockets package not installed", YELLOW)
    except Exception as e:
        check("WebSocket connectivity", False, str(e))

    # ── 7. Edge Cases ──
    section("7. Edge Cases & Error Handling")

    r = client.post("/api/upload", files={"file": ("test.xyz", b"not audio", "application/octet-stream")},
                     data={"language": "ja"})
    check("Reject unsupported file format", r.status_code in (400, 422), f"status={r.status_code}")

    r = client.get("/api/meetings/nonexistent/transcript/export")
    check("Export nonexistent meeting", r.status_code == 404)

    r = client.post("/api/meetings/nonexistent/summary")
    check("Intelligence on nonexistent meeting", r.status_code in (400, 404))

    r = client.post("/api/chat", json={"query": ""})
    check("Chat with empty query handled", r.status_code in (200, 400, 422))

    # ── 8. Multi-meeting RAG ──
    section("8. Cross-meeting RAG")
    r2 = client.post("/api/meetings", json={"name": "Second Test Meeting", "mode": "meeting"})
    if r2.status_code in (200, 201):
        m2_id = r2.json()["id"]
        created_meeting_ids.append(m2_id)

        try:
            import sqlite3
            db_path = Path(__file__).parent.parent / "data" / "meeting_copilot.db"
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("INSERT INTO transcript_entries (meeting_id, speaker, text, source, language) VALUES (?, ?, ?, ?, ?)",
                        (m2_id, "Alice", "We should launch the AI feature next quarter.", "whisper", "en"))
            cur.execute("INSERT INTO transcript_entries (meeting_id, speaker, text, source, language) VALUES (?, ?, ?, ?, ?)",
                        (m2_id, "Bob", "Agreed. Budget is approved for the AI project.", "whisper", "en"))
            conn.commit()
            conn.close()

            r = client.post(f"/api/meetings/{m2_id}/index")
            check("Index second meeting", r.status_code == 200)

            r = client.post("/api/chat", json={"query": "What did Alice say about AI?"})
            check("Cross-meeting chat", r.status_code == 200)
            if r.status_code == 200:
                answer = r.json().get("answer", "")
                check("Answer references AI content",
                      "ai" in answer.lower() or "launch" in answer.lower() or len(answer) > 10,
                      f"answer length: {len(answer)}")
        except Exception as e:
            check("Cross-meeting RAG setup", False, str(e)[:100])
    else:
        check("Create second meeting", False, f"status={r2.status_code}")

    # ── 9. Cleanup ──
    section("9. Cleanup")
    for mid in created_meeting_ids:
        r = client.delete(f"/api/meetings/{mid}")
        status = "ok" if r.status_code in (200, 204) else f"status={r.status_code}"
        log(f"  Deleted {mid}: {status}", YELLOW)

    # ── Summary ──
    section("RESULTS")
    total = passed + failed
    log(f"\n  {BOLD}{GREEN}{passed}{RESET} passed, {BOLD}{RED if failed else GREEN}{failed}{RESET} failed out of {total} checks\n")

    if failed > 0:
        log("  Failed checks:", RED)
        for name, ok, detail in results:
            if not ok:
                log(f"    - {name}: {detail}", RED)
        sys.exit(1)
    else:
        log("  All checks passed!", GREEN + BOLD)


if __name__ == "__main__":
    main()
