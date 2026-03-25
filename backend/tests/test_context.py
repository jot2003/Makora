"""Tests for Context/Notes/Glossary/Documents APIs."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.database import Base, engine, SessionLocal, User, Meeting

client = TestClient(app)


def _auth_headers():
    r = client.post("/api/auth/register", json={
        "email": "ctx@example.com", "username": "ctxuser", "password": "password",
    })
    if r.status_code == 409:
        r = client.post("/api/auth/login", json={
            "email": "ctx@example.com", "password": "password",
        })
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def meeting_id():
    headers = _auth_headers()
    r = client.post("/api/meetings", json={"name": "Context Test", "mode": "interview"},
                    headers={**headers, "Content-Type": "application/json"})
    return r.json()["id"]


class TestNotes:
    def test_get_empty_note(self, meeting_id):
        r = client.get(f"/api/meetings/{meeting_id}/notes/personal")
        assert r.status_code == 200
        assert r.json()["content"] == ""

    def test_put_and_get_note(self, meeting_id):
        r = client.put(f"/api/meetings/{meeting_id}/notes/personal",
                       json={"content": "My personal notes"})
        assert r.status_code == 200
        assert r.json()["content"] == "My personal notes"

        r = client.get(f"/api/meetings/{meeting_id}/notes/personal")
        assert r.json()["content"] == "My personal notes"

    def test_list_notes(self, meeting_id):
        client.put(f"/api/meetings/{meeting_id}/notes/personal", json={"content": "P"})
        client.put(f"/api/meetings/{meeting_id}/notes/company", json={"content": "C"})
        r = client.get(f"/api/meetings/{meeting_id}/notes")
        assert r.status_code == 200
        assert len(r.json()) >= 2


class TestGlossary:
    def test_add_and_list(self, meeting_id):
        r = client.post(f"/api/meetings/{meeting_id}/glossary",
                        json={"jp": "面接", "reading": "めんせつ", "vi": "Phỏng vấn"})
        assert r.status_code == 201
        entry_id = r.json()["id"]

        r = client.get(f"/api/meetings/{meeting_id}/glossary")
        assert len(r.json()) >= 1
        assert any(g["jp"] == "面接" for g in r.json())

        r = client.delete(f"/api/meetings/{meeting_id}/glossary/{entry_id}")
        assert r.status_code == 204

    def test_delete_nonexistent(self, meeting_id):
        r = client.delete(f"/api/meetings/{meeting_id}/glossary/99999")
        assert r.status_code == 404


class TestDocuments:
    def test_upload_and_list(self, meeting_id):
        r = client.post(f"/api/meetings/{meeting_id}/documents",
                        files={"file": ("test.txt", b"Hello world content", "text/plain")},
                        data={"category": "personal"})
        assert r.status_code == 201
        assert r.json()["filename"] == "test.txt"

        r = client.get(f"/api/meetings/{meeting_id}/documents")
        assert len(r.json()) >= 1

    def test_delete_document(self, meeting_id):
        r = client.post(f"/api/meetings/{meeting_id}/documents",
                        files={"file": ("del.txt", b"Delete me", "text/plain")},
                        data={"category": "company"})
        doc_id = r.json()["id"]
        r = client.delete(f"/api/meetings/{meeting_id}/documents/{doc_id}")
        assert r.status_code == 204
