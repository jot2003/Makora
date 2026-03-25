"""Authentication API: register, login, OAuth, JWT."""

from datetime import datetime, timezone, timedelta
from typing import Annotated

import bcrypt
import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.database import User, get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Schemas ───────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str
    username: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    token: str
    user: "UserResponse"


class UserResponse(BaseModel):
    id: int
    email: str
    username: str
    avatar_url: str
    provider: str
    is_verified: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ── Helpers ───────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def _create_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRE_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def _decode_token(token: str) -> int | None:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return int(payload["sub"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError):
        return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    token = auth_header[7:]
    user_id = _decode_token(token)
    if user_id is None:
        raise HTTPException(401, "Invalid or expired token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(401, "User not found")
    return user


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Return user if token present, None otherwise (backward compat)."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    user_id = _decode_token(token)
    if user_id is None:
        return None
    return db.query(User).filter(User.id == user_id).first()


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        avatar_url=user.avatar_url or "",
        provider=user.provider or "local",
        is_verified=user.is_verified,
        created_at=user.created_at,
    )


# ── OAuth availability check ──────────────────────────────────

@router.get("/providers")
def available_providers():
    """Return which OAuth providers are configured."""
    return {
        "google": bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET),
        "github": bool(settings.GITHUB_CLIENT_ID and settings.GITHUB_CLIENT_SECRET),
    }


# ── Register / Login ─────────────────────────────────────────

@router.post("/register", response_model=AuthResponse)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(409, "Email already registered")
    user = User(
        email=body.email,
        username=body.username,
        hashed_password=_hash_password(body.password),
        is_verified=True,
        provider="local",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return AuthResponse(token=_create_token(user.id), user=_user_response(user))


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not user.hashed_password:
        raise HTTPException(401, "Invalid email or password")
    if not _verify_password(body.password, user.hashed_password):
        raise HTTPException(401, "Invalid email or password")
    return AuthResponse(token=_create_token(user.id), user=_user_response(user))


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    return _user_response(user)


# ── OAuth helper ──────────────────────────────────────────────

FRONTEND_URL = "http://localhost:5173"


def _frontend_callback_url(token: str | None = None, error: str | None = None) -> str:
    if error:
        return f"{FRONTEND_URL}/#/auth/callback?error={error}"
    return f"{FRONTEND_URL}/#/auth/callback?token={token}"


def _upsert_oauth_user(db: Session, email: str, username: str, avatar_url: str, provider: str) -> User:
    """Find or create user. If user exists with different provider, link by updating avatar."""
    user = db.query(User).filter(User.email == email).first()
    if user:
        if not user.avatar_url and avatar_url:
            user.avatar_url = avatar_url
        if not user.is_verified:
            user.is_verified = True
        db.commit()
        db.refresh(user)
    else:
        user = User(
            email=email,
            username=username,
            avatar_url=avatar_url,
            is_verified=True,
            provider=provider,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


# ── OAuth: Google ─────────────────────────────────────────────

@router.get("/google")
def google_login():
    if not settings.GOOGLE_CLIENT_ID:
        return RedirectResponse(_frontend_callback_url(error="Google OAuth not configured. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to .env"))
    redirect_uri = f"{settings.OAUTH_REDIRECT_BASE}/api/auth/google/callback"
    url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={settings.GOOGLE_CLIENT_ID}&"
        f"redirect_uri={redirect_uri}&"
        "response_type=code&"
        "scope=openid%20email%20profile&"
        "access_type=offline"
    )
    return RedirectResponse(url)


@router.get("/google/callback")
async def google_callback(code: str = "", error: str = "", db: Session = Depends(get_db)):
    if error or not code:
        return RedirectResponse(_frontend_callback_url(error=error or "Google login cancelled"))

    redirect_uri = f"{settings.OAUTH_REDIRECT_BASE}/api/auth/google/callback"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token_resp = await client.post("https://oauth2.googleapis.com/token", data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            })
            if token_resp.status_code != 200:
                return RedirectResponse(_frontend_callback_url(error="Google token exchange failed"))
            tokens = token_resp.json()

            info_resp = await client.get("https://www.googleapis.com/oauth2/v2/userinfo",
                                         headers={"Authorization": f"Bearer {tokens['access_token']}"})
            if info_resp.status_code != 200:
                return RedirectResponse(_frontend_callback_url(error="Failed to get Google profile"))
            info = info_resp.json()
    except Exception as e:
        return RedirectResponse(_frontend_callback_url(error=f"Google OAuth error: {str(e)[:80]}"))

    email = info.get("email", "")
    if not email:
        return RedirectResponse(_frontend_callback_url(error="No email from Google account"))

    user = _upsert_oauth_user(
        db, email=email,
        username=info.get("name", email.split("@")[0]),
        avatar_url=info.get("picture", ""),
        provider="google",
    )
    return RedirectResponse(_frontend_callback_url(token=_create_token(user.id)))


# ── OAuth: GitHub ─────────────────────────────────────────────

@router.get("/github")
def github_login():
    if not settings.GITHUB_CLIENT_ID:
        return RedirectResponse(_frontend_callback_url(error="GitHub OAuth not configured. Add GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET to .env"))
    redirect_uri = f"{settings.OAUTH_REDIRECT_BASE}/api/auth/github/callback"
    url = (
        "https://github.com/login/oauth/authorize?"
        f"client_id={settings.GITHUB_CLIENT_ID}&"
        f"redirect_uri={redirect_uri}&"
        "scope=user:email"
    )
    return RedirectResponse(url)


@router.get("/github/callback")
async def github_callback(code: str = "", error: str = "", db: Session = Depends(get_db)):
    if error or not code:
        return RedirectResponse(_frontend_callback_url(error=error or "GitHub login cancelled"))

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token_resp = await client.post("https://github.com/login/oauth/access_token", json={
                "client_id": settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
                "code": code,
            }, headers={"Accept": "application/json"})
            if token_resp.status_code != 200:
                return RedirectResponse(_frontend_callback_url(error="GitHub token exchange failed"))
            access_token = token_resp.json().get("access_token")
            if not access_token:
                return RedirectResponse(_frontend_callback_url(error="No access token from GitHub"))

            user_resp = await client.get("https://api.github.com/user",
                                         headers={"Authorization": f"Bearer {access_token}"})
            info = user_resp.json()

            email_resp = await client.get("https://api.github.com/user/emails",
                                          headers={"Authorization": f"Bearer {access_token}"})
            emails = email_resp.json() if isinstance(email_resp.json(), list) else []
            email = next((e["email"] for e in emails if e.get("primary")), info.get("email", ""))
    except Exception as e:
        return RedirectResponse(_frontend_callback_url(error=f"GitHub OAuth error: {str(e)[:80]}"))

    if not email:
        return RedirectResponse(_frontend_callback_url(error="Could not get email from GitHub. Make sure your email is public or grant email permission."))

    user = _upsert_oauth_user(
        db, email=email,
        username=info.get("login", email.split("@")[0]),
        avatar_url=info.get("avatar_url", ""),
        provider="github",
    )
    return RedirectResponse(_frontend_callback_url(token=_create_token(user.id)))
