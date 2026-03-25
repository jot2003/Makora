"""WebSocket endpoint for realtime meeting pipeline.

Handles the full lifecycle: start → audio/STT/LLM → stream events → stop.
Falls back to placeholder mode if Azure credentials are missing.
"""

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings

router = APIRouter()


@router.websocket("/ws/meeting")
async def meeting_ws(ws: WebSocket):
    await ws.accept()
    session = None
    loop = asyncio.get_running_loop()

    async def send_json_safe(data: dict):
        try:
            await ws.send_json(data)
        except Exception:
            pass

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = msg.get("type", "")

            if msg_type == "ping":
                await ws.send_json({"type": "pong"})

            elif msg_type == "start_meeting":
                if session:
                    await asyncio.to_thread(session.stop)
                    session = None
                    await asyncio.sleep(0.8)

                meeting_id = msg.get("meeting_id", "")
                language = msg.get("language", "ja-JP")
                mode = msg.get("mode", "interview")
                model_id = msg.get("model_id", "")

                has_speech_keys = bool(settings.AZURE_SPEECH_KEY and settings.AZURE_SPEECH_REGION)
                if has_speech_keys:
                    from app.services.meeting_session import MeetingSession
                    session = MeetingSession(send_json_safe, meeting_id, language, mode)
                    await asyncio.to_thread(session.start, loop)
                    if model_id:
                        session.switch_model(model_id)
                else:
                    await ws.send_json({
                        "type": "status",
                        "message": f"Meeting {meeting_id} started (placeholder — no Azure keys)",
                    })

            elif msg_type == "stop_meeting":
                if session:
                    await asyncio.to_thread(session.stop)
                    session = None
                else:
                    await ws.send_json({"type": "status", "message": "Meeting stopped"})

            elif msg_type == "switch_language":
                lang = msg.get("language", "ja-JP")
                if session:
                    session.switch_language(lang)
                else:
                    await ws.send_json({"type": "status", "message": f"Language switched to {lang}"})

            elif msg_type == "manual_answer":
                text = msg.get("text", "")
                ai_refine = msg.get("ai_refine", True)
                context_only = msg.get("context_only", False)
                if context_only and session:
                    session.append_context_note(text)
                    await ws.send_json({"type": "status", "message": "Added to context notes"})
                elif session:
                    await asyncio.to_thread(session.handle_manual_answer, text, ai_refine)
                else:
                    await ws.send_json({
                        "type": "suggestion_done",
                        "id": "manual_placeholder",
                        "answer_romaji": "",
                        "answer_vi": f"[placeholder] Received: {text[:50]}",
                    })

            elif msg_type == "switch_model":
                model_id = msg.get("model_id", "")
                if session:
                    result = session.switch_model(model_id)
                    await ws.send_json({"type": "model_switched", "model_id": result})
                else:
                    await ws.send_json({"type": "status", "message": "No active session"})

            elif msg_type == "toggle_suggestions":
                enabled = msg.get("enabled", True)
                if session:
                    session.set_suggestions_enabled(enabled)
                await ws.send_json({"type": "status", "message": f"Suggestions {'enabled' if enabled else 'disabled'}"})

            elif msg_type == "request_suggestion":
                text = msg.get("text", "")
                romaji = msg.get("romaji", "")
                line_id = msg.get("line_id", "")
                length = msg.get("length", "")
                if session:
                    await asyncio.to_thread(session.handle_request_suggestion, text, romaji, line_id, length)
                else:
                    await ws.send_json({
                        "type": "suggestion_done",
                        "line_id": line_id,
                        "id": f"sg_{line_id}",
                        "answer_romaji": "",
                        "answer_vi": "[No active session]",
                    })

            elif msg_type == "set_answer_length":
                raw = msg.get("length", 3)
                length = int(raw) if isinstance(raw, (int, float)) else 3
                if session:
                    session.set_answer_length(length)
                await ws.send_json({"type": "answer_length_changed", "length": length})

            elif msg_type == "set_jp_level":
                level = msg.get("level", "natural")
                if session:
                    session.set_jp_level(level)
                await ws.send_json({"type": "jp_level_changed", "level": level})

            elif msg_type == "set_max_speakers":
                n = int(msg.get("max_speakers", 2))
                if session:
                    session.set_max_speakers(n)
                await ws.send_json({"type": "status", "message": f"Max speakers: {n}"})

            elif msg_type in ("pin_suggestion", "dismiss_suggestion"):
                pass

            else:
                await ws.send_json({"type": "error", "message": f"Unknown type: {msg_type}"})

    except WebSocketDisconnect:
        if session:
            try:
                session.stop()
            except Exception:
                pass
            session = None
    except Exception:
        if session:
            try:
                session.stop()
            except Exception:
                pass
            session = None
