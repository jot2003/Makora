"""Tests for Settings and AI Provider APIs."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.database import Base, engine, SessionLocal

client = TestClient(app)


def _auth_headers():
    r = client.post("/api/auth/register", json={
        "email": "settings@example.com", "username": "settingsuser", "password": "password",
    })
    if r.status_code == 409:
        r = client.post("/api/auth/login", json={
            "email": "settings@example.com", "password": "password",
        })
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    from app.models.database import UserSettings, AIProvider, User
    db.query(AIProvider).delete()
    db.query(UserSettings).delete()
    db.query(User).filter(User.email == "settings@example.com").delete()
    db.commit()
    db.close()
    yield


class TestUserSettings:
    def test_get_defaults(self):
        h = _auth_headers()
        r = client.get("/api/settings", headers=h)
        assert r.status_code == 200
        d = r.json()
        assert d["overlay_font_size"] == 16
        assert d["default_language"] == "ja-JP"

    def test_update_settings(self):
        h = _auth_headers()
        r = client.put("/api/settings", headers=h,
                       json={"overlay_font_size": 20, "overlay_opacity": 85,
                             "overlay_max_history": 10, "energy_threshold": 300,
                             "default_language": "en-US"})
        assert r.status_code == 200
        assert r.json()["overlay_font_size"] == 20

        r = client.get("/api/settings", headers=h)
        assert r.json()["overlay_font_size"] == 20

    def test_requires_auth(self):
        r = client.get("/api/settings")
        assert r.status_code == 401


class TestAIProviders:
    def test_create_and_list(self):
        h = _auth_headers()
        r = client.post("/api/settings/providers", headers=h,
                        json={"name": "Azure Dev", "provider_type": "azure",
                              "api_key": "test-key", "endpoint": "https://test.openai.azure.com",
                              "deployment": "gpt-4o"})
        assert r.status_code == 201
        pid = r.json()["id"]
        assert r.json()["has_key"] is True
        assert r.json()["is_active"] is False

        r = client.get("/api/settings/providers", headers=h)
        assert len(r.json()) >= 1

        r = client.put(f"/api/settings/providers/{pid}", headers=h,
                       json={"is_active": True})
        assert r.json()["is_active"] is True

        r = client.delete(f"/api/settings/providers/{pid}", headers=h)
        assert r.status_code == 204

    def test_requires_auth(self):
        r = client.get("/api/settings/providers")
        assert r.status_code == 401
