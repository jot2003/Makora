"""Settings and AI Provider management API."""

import json
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.database import User, UserSettings, AIProvider, get_db
from app.api.auth import get_current_user

from app.core.config import settings as app_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/models")
def list_models():
    """Return available LLM models, non-reasoning first for better defaults."""
    valid = [m for m in app_settings.MODEL_REGISTRY if m.is_valid()]
    valid.sort(key=lambda m: m.is_reasoning)
    return [m.to_dict() for m in valid]


# ── User Settings ─────────────────────────────────────────────

class SettingsPayload(BaseModel):
    overlay_font_size: int = 16
    overlay_opacity: int = 90
    overlay_max_history: int = 8
    energy_threshold: int = 200
    default_language: str = "ja-JP"


class SettingsResponse(BaseModel):
    overlay_font_size: int
    overlay_opacity: int
    overlay_max_history: int
    energy_threshold: int
    default_language: str


@router.get("", response_model=SettingsResponse)
def get_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    us = db.query(UserSettings).filter(UserSettings.user_id == user.id).first()
    defaults = SettingsPayload()
    if not us:
        return defaults
    try:
        data = json.loads(us.settings_json)
        return SettingsResponse(**{**defaults.model_dump(), **data})
    except Exception:
        return defaults


@router.put("", response_model=SettingsResponse)
def update_settings(body: SettingsPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    us = db.query(UserSettings).filter(UserSettings.user_id == user.id).first()
    if not us:
        us = UserSettings(user_id=user.id, settings_json=json.dumps(body.model_dump()))
        db.add(us)
    else:
        us.settings_json = json.dumps(body.model_dump())
    db.commit()
    db.refresh(us)
    return body


# ── AI Providers ──────────────────────────────────────────────

class ProviderCreate(BaseModel):
    name: str
    provider_type: str = "azure"
    api_key: str = ""
    endpoint: str = ""
    deployment: str = ""


class ProviderUpdate(BaseModel):
    name: Optional[str] = None
    api_key: Optional[str] = None
    endpoint: Optional[str] = None
    deployment: Optional[str] = None
    is_active: Optional[bool] = None


class ProviderResponse(BaseModel):
    id: int
    name: str
    provider_type: str
    endpoint: str
    deployment: str
    is_active: bool
    has_key: bool

    class Config:
        from_attributes = True


def _provider_resp(p: AIProvider) -> ProviderResponse:
    return ProviderResponse(
        id=p.id, name=p.name, provider_type=p.provider_type,
        endpoint=p.endpoint, deployment=p.deployment,
        is_active=p.is_active, has_key=bool(p.api_key),
    )


@router.get("/providers", response_model=list[ProviderResponse])
def list_providers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    providers = db.query(AIProvider).filter(AIProvider.user_id == user.id).all()
    return [_provider_resp(p) for p in providers]


@router.post("/providers", response_model=ProviderResponse, status_code=201)
def create_provider(body: ProviderCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = AIProvider(
        user_id=user.id,
        name=body.name,
        provider_type=body.provider_type,
        api_key=body.api_key,
        endpoint=body.endpoint,
        deployment=body.deployment,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _provider_resp(p)


@router.put("/providers/{provider_id}", response_model=ProviderResponse)
def update_provider(provider_id: int, body: ProviderUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = db.query(AIProvider).filter(AIProvider.id == provider_id, AIProvider.user_id == user.id).first()
    if not p:
        raise HTTPException(404, "Provider not found")
    if body.name is not None:
        p.name = body.name
    if body.api_key is not None:
        p.api_key = body.api_key
    if body.endpoint is not None:
        p.endpoint = body.endpoint
    if body.deployment is not None:
        p.deployment = body.deployment
    if body.is_active is not None:
        if body.is_active:
            for other in db.query(AIProvider).filter(AIProvider.user_id == user.id, AIProvider.id != provider_id).all():
                other.is_active = False
        p.is_active = body.is_active
    db.commit()
    db.refresh(p)
    return _provider_resp(p)


@router.delete("/providers/{provider_id}", status_code=204)
def delete_provider(provider_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = db.query(AIProvider).filter(AIProvider.id == provider_id, AIProvider.user_id == user.id).first()
    if not p:
        raise HTTPException(404, "Provider not found")
    db.delete(p)
    db.commit()


@router.post("/providers/{provider_id}/test")
def test_provider(provider_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = db.query(AIProvider).filter(AIProvider.id == provider_id, AIProvider.user_id == user.id).first()
    if not p:
        raise HTTPException(404, "Provider not found")
    if not p.api_key or not p.endpoint:
        return {"ok": False, "error": "Missing API key or endpoint"}
    try:
        from openai import AzureOpenAI
        client = AzureOpenAI(api_key=p.api_key, azure_endpoint=p.endpoint, api_version="2024-12-01-preview")
        resp = client.chat.completions.create(
            model=p.deployment or "gpt-4o",
            messages=[{"role": "user", "content": "Say OK"}],
            max_completion_tokens=5,
        )
        return {"ok": True, "model": p.deployment, "response": resp.choices[0].message.content}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/providers/{provider_id}/models")
def detect_models(provider_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = db.query(AIProvider).filter(AIProvider.id == provider_id, AIProvider.user_id == user.id).first()
    if not p:
        raise HTTPException(404, "Provider not found")
    if not p.api_key or not p.endpoint:
        return {"models": []}
    try:
        endpoint = p.endpoint.rstrip("/")
        url = f"{endpoint}/openai/deployments?api-version=2024-12-01-preview"
        r = httpx.get(url, headers={"api-key": p.api_key}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            models = [d.get("id", d.get("model", "")) for d in data.get("data", data.get("value", []))]
            return {"models": [m for m in models if m]}
    except Exception:
        pass
    return {"models": [p.deployment] if p.deployment else []}
