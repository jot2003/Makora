"""Phase 0 smoke tests — health, CRUD, WebSocket ping/pong."""

import json

import pytest


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_create_and_list_meeting(client):
    r = client.post("/api/meetings", json={"name": "Test meeting"})
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Test meeting"
    assert data["mode"] == "interview"
    assert data["status"] == "created"

    r2 = client.get("/api/meetings")
    assert r2.status_code == 200
    assert len(r2.json()) == 1


def test_get_meeting(client):
    r = client.post("/api/meetings", json={"name": "M1"})
    mid = r.json()["id"]

    r2 = client.get(f"/api/meetings/{mid}")
    assert r2.status_code == 200
    assert r2.json()["id"] == mid


def test_update_meeting(client):
    r = client.post("/api/meetings", json={"name": "M1"})
    mid = r.json()["id"]

    r2 = client.patch(f"/api/meetings/{mid}", json={"name": "Updated", "mode": "meeting"})
    assert r2.status_code == 200
    assert r2.json()["name"] == "Updated"
    assert r2.json()["mode"] == "meeting"


def test_delete_meeting(client):
    r = client.post("/api/meetings", json={"name": "M1"})
    mid = r.json()["id"]

    r2 = client.delete(f"/api/meetings/{mid}")
    assert r2.status_code == 204

    r3 = client.get(f"/api/meetings/{mid}")
    assert r3.status_code == 404


def test_meeting_not_found(client):
    r = client.get("/api/meetings/nonexistent")
    assert r.status_code == 404


def test_ws_ping_pong(client):
    with client.websocket_connect("/ws/meeting") as ws:
        ws.send_text(json.dumps({"type": "ping"}))
        resp = ws.receive_json()
        assert resp["type"] == "pong"


def test_ws_start_stop(client):
    with client.websocket_connect("/ws/meeting") as ws:
        ws.send_text(json.dumps({
            "type": "start_meeting",
            "meeting_id": "test_123",
            "language": "ja-JP",
            "mode": "interview",
        }))
        found_start = False
        for _ in range(10):
            resp = ws.receive_json()
            if resp.get("type") == "status" and "test_123" in resp.get("message", ""):
                found_start = True
                break
        assert found_start, "Never received start confirmation"

        ws.send_text(json.dumps({"type": "stop_meeting"}))
        found_stop = False
        for _ in range(10):
            resp = ws.receive_json()
            if resp.get("type") == "status" and "stopped" in resp.get("message", "").lower():
                found_stop = True
                break
        assert found_stop, "Never received stop confirmation"


def test_ws_invalid_json(client):
    with client.websocket_connect("/ws/meeting") as ws:
        ws.send_text("not json")
        resp = ws.receive_json()
        assert resp["type"] == "error"
