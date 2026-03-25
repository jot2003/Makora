"""Meeting Copilot FastAPI backend entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.models.database import init_db
from app.api.auth import router as auth_router
from app.api.meetings import router as meetings_router
from app.api.context import router as context_router
from app.api.realtime import router as realtime_router
from app.api.intelligence import router as intelligence_router
from app.api.settings import router as settings_router
from app.api.chat import router as chat_router
from app.api.upload import router as upload_router
from app.api.usage import router as usage_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Meeting Copilot API",
    version="0.2.0",
    description="AI Meeting Copilot — realtime transcription, intelligence, RAG",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(meetings_router)
app.include_router(context_router)
app.include_router(settings_router)
app.include_router(realtime_router)
app.include_router(intelligence_router)
app.include_router(chat_router)
app.include_router(upload_router)
app.include_router(usage_router)


@app.get("/health")
def health():
    return {"status": "ok"}
