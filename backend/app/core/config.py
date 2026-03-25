"""Application configuration loaded from environment variables."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "meeting_copilot.db"
AUDIO_DIR = DATA_DIR / "audio"
AUDIO_DIR.mkdir(exist_ok=True)
DOCS_DIR = DATA_DIR / "documents"
DOCS_DIR.mkdir(exist_ok=True)
FAISS_DIR = DATA_DIR / "faiss_index"
FAISS_DIR.mkdir(exist_ok=True)


import re as _re
_REASONING_MODEL_RE = _re.compile(r'(?:^o[134]|gpt-5|o\d+-mini)', _re.IGNORECASE)


class _ModelConfig:
    """Configuration for a single Azure OpenAI model deployment."""
    def __init__(self, key: str, endpoint: str, deployment: str, label: str):
        self.key = key
        self.endpoint = endpoint
        self.deployment = deployment
        self.label = label
        self.is_reasoning = bool(_REASONING_MODEL_RE.search(deployment))

    def is_valid(self) -> bool:
        return bool(self.key and self.endpoint and self.deployment)

    def to_dict(self) -> dict:
        return {"id": self.deployment, "label": self.label, "is_reasoning": self.is_reasoning}


def _build_model_registry() -> list[_ModelConfig]:
    models: list[_ModelConfig] = []
    k1 = os.getenv("AZURE_OPENAI_KEY", "")
    e1 = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    d1 = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
    if k1 and e1 and d1:
        models.append(_ModelConfig(k1, e1, d1, d1))

    idx = 2
    while True:
        k = os.getenv(f"AZURE_OPENAI_KEY_{idx}", "")
        e = os.getenv(f"AZURE_OPENAI_ENDPOINT_{idx}", "")
        d = os.getenv(f"AZURE_OPENAI_DEPLOYMENT_{idx}", "")
        if not (k and e and d):
            break
        label = os.getenv(f"AZURE_OPENAI_LABEL_{idx}", d)
        models.append(_ModelConfig(k, e, d, label))
        idx += 1
    return models


class Settings:
    AZURE_SPEECH_KEY: str = os.getenv("AZURE_SPEECH_KEY", "")
    AZURE_SPEECH_REGION: str = os.getenv("AZURE_SPEECH_REGION", "")
    AZURE_OPENAI_KEY: str = os.getenv("AZURE_OPENAI_KEY", "")
    AZURE_OPENAI_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    AZURE_OPENAI_DEPLOYMENT: str = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
    AZURE_OPENAI_FAST_DEPLOYMENT: str = os.getenv("AZURE_OPENAI_FAST_DEPLOYMENT", "")
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
    AZURE_TRANSLATOR_KEY: str = os.getenv("AZURE_TRANSLATOR_KEY", "")
    AZURE_TRANSLATOR_REGION: str = os.getenv("AZURE_TRANSLATOR_REGION", "")

    MODEL_REGISTRY: list[_ModelConfig] = _build_model_registry()

    JWT_SECRET: str = os.getenv("JWT_SECRET", "meeting-copilot-dev-secret-change-in-prod")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = int(os.getenv("JWT_EXPIRE_HOURS", "72"))

    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GITHUB_CLIENT_ID: str = os.getenv("GITHUB_CLIENT_ID", "")
    GITHUB_CLIENT_SECRET: str = os.getenv("GITHUB_CLIENT_SECRET", "")
    OAUTH_REDIRECT_BASE: str = os.getenv("OAUTH_REDIRECT_BASE", "http://localhost:8000")

    DATABASE_URL: str = f"sqlite:///{DB_PATH}"
    CORS_ORIGINS: list[str] = [
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
        if o.strip()
    ]

    DEFAULT_LANGUAGE: str = "ja-JP"
    ENERGY_THRESHOLD: int = 200

    HF_TOKEN: str = os.getenv("HF_TOKEN", "")

    OVERLAY_FONT_SIZE: int = 16
    OVERLAY_OPACITY: int = 90
    OVERLAY_MAX_HISTORY: int = 8


settings = Settings()
