"""Tests for the Auth system — register, login, JWT, protected endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.database import Base, engine, SessionLocal, User, Meeting

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    db.query(Meeting).delete()
    db.query(User).delete()
    db.commit()
    db.close()
    yield
    db = SessionLocal()
    db.query(Meeting).delete()
    db.query(User).delete()
    db.commit()
    db.close()


def test_register_success():
    r = client.post("/api/auth/register", json={
        "email": "test@example.com",
        "username": "testuser",
        "password": "secret123",
    })
    assert r.status_code == 200
    data = r.json()
    assert "token" in data
    assert data["user"]["email"] == "test@example.com"
    assert data["user"]["username"] == "testuser"
    assert data["user"]["is_verified"] is True


def test_register_duplicate_email():
    client.post("/api/auth/register", json={
        "email": "dup@example.com", "username": "user1", "password": "secret123",
    })
    r = client.post("/api/auth/register", json={
        "email": "dup@example.com", "username": "user2", "password": "secret456",
    })
    assert r.status_code == 409


def test_register_short_password():
    r = client.post("/api/auth/register", json={
        "email": "short@example.com", "username": "user", "password": "12345",
    })
    assert r.status_code == 400


def test_login_success():
    client.post("/api/auth/register", json={
        "email": "login@example.com", "username": "loginuser", "password": "mypassword",
    })
    r = client.post("/api/auth/login", json={
        "email": "login@example.com", "password": "mypassword",
    })
    assert r.status_code == 200
    assert "token" in r.json()


def test_login_wrong_password():
    client.post("/api/auth/register", json={
        "email": "wrong@example.com", "username": "user", "password": "correct",
    })
    r = client.post("/api/auth/login", json={
        "email": "wrong@example.com", "password": "incorrect",
    })
    assert r.status_code == 401


def test_login_nonexistent_email():
    r = client.post("/api/auth/login", json={
        "email": "nobody@example.com", "password": "anything",
    })
    assert r.status_code == 401


def test_me_authenticated():
    reg = client.post("/api/auth/register", json={
        "email": "me@example.com", "username": "meuser", "password": "password",
    })
    token = reg.json()["token"]
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == "me@example.com"


def test_me_no_token():
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_me_invalid_token():
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer invalidtoken"})
    assert r.status_code == 401


def test_providers_endpoint():
    r = client.get("/api/auth/providers")
    assert r.status_code == 200
    data = r.json()
    assert "google" in data
    assert "github" in data
    assert isinstance(data["google"], bool)
    assert isinstance(data["github"], bool)


def test_google_oauth_not_configured():
    r = client.get("/api/auth/google", follow_redirects=False)
    assert r.status_code == 307
    assert "error" in r.headers.get("location", "")


def test_github_oauth_not_configured():
    r = client.get("/api/auth/github", follow_redirects=False)
    assert r.status_code == 307
    assert "error" in r.headers.get("location", "")


def test_meetings_user_isolation():
    r1 = client.post("/api/auth/register", json={
        "email": "user1@example.com", "username": "user1", "password": "password1",
    })
    r2 = client.post("/api/auth/register", json={
        "email": "user2@example.com", "username": "user2", "password": "password2",
    })
    token1 = r1.json()["token"]
    token2 = r2.json()["token"]

    client.post("/api/meetings", json={"name": "User1 meeting", "mode": "interview"},
                headers={"Authorization": f"Bearer {token1}", "Content-Type": "application/json"})
    client.post("/api/meetings", json={"name": "User2 meeting", "mode": "interview"},
                headers={"Authorization": f"Bearer {token2}", "Content-Type": "application/json"})

    m1 = client.get("/api/meetings", headers={"Authorization": f"Bearer {token1}"})
    m2 = client.get("/api/meetings", headers={"Authorization": f"Bearer {token2}"})

    assert len(m1.json()) == 1
    assert m1.json()[0]["name"] == "User1 meeting"
    assert len(m2.json()) == 1
    assert m2.json()[0]["name"] == "User2 meeting"
