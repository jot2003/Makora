"""SQLite database setup with SQLAlchemy."""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey,
    Integer, LargeBinary, String, Text, create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


# ── Auth ──────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False, index=True)
    username = Column(String, nullable=False)
    hashed_password = Column(String, default="")
    is_verified = Column(Boolean, default=False)
    avatar_url = Column(String, default="")
    provider = Column(String, default="local")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    meetings = relationship("Meeting", back_populates="user", cascade="all, delete-orphan")
    ai_providers = relationship("AIProvider", back_populates="user", cascade="all, delete-orphan")
    user_settings = relationship("UserSettings", back_populates="user", uselist=False, cascade="all, delete-orphan")


# ── Meetings ──────────────────────────────────────────────────

class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    name = Column(String, nullable=False)
    mode = Column(Enum("interview", "meeting", name="meeting_mode"), default="interview")
    language = Column(String, default="ja-JP")
    status = Column(Enum("created", "active", "completed", name="meeting_status"), default="created")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="meetings")
    transcript_entries = relationship("TranscriptEntry", back_populates="meeting", cascade="all, delete-orphan")
    notes = relationship("SessionNote", back_populates="meeting", cascade="all, delete-orphan")
    glossary_entries = relationship("GlossaryEntry", back_populates="meeting", cascade="all, delete-orphan")
    documents = relationship("SessionDocument", back_populates="meeting", cascade="all, delete-orphan")


class TranscriptEntry(Base):
    __tablename__ = "transcript_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(String, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    speaker = Column(String, default="")
    speaker_id = Column(String, default="")
    language = Column(String, default="ja-JP")
    source = Column(Enum("realtime", "whisper", name="transcript_source"), default="realtime")

    text = Column(Text, default="")
    romaji = Column(Text, default="")
    translation_vi = Column(Text, default="")
    answer_vi = Column(Text, default="")
    answer_ja = Column(Text, default="")
    answer_romaji = Column(Text, default="")

    meeting = relationship("Meeting", back_populates="transcript_entries")


# ── Context / Notes / Glossary / Documents ────────────────────

class SessionNote(Base):
    __tablename__ = "session_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(String, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    category = Column(Enum("personal", "company", "general", name="note_category"), nullable=False)
    content = Column(Text, default="")
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    meeting = relationship("Meeting", back_populates="notes")


class GlossaryEntry(Base):
    __tablename__ = "glossary_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(String, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    jp = Column(String, nullable=False)
    reading = Column(String, default="")
    vi = Column(String, default="")

    meeting = relationship("Meeting", back_populates="glossary_entries")


class SessionDocument(Base):
    __tablename__ = "session_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(String, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String, nullable=False)
    category = Column(Enum("personal", "company", name="doc_category"), default="personal")
    extracted_text = Column(Text, default="")
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    meeting = relationship("Meeting", back_populates="documents")


# ── Settings / AI Providers ───────────────────────────────────

class UserSettings(Base):
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    settings_json = Column(Text, default="{}")

    user = relationship("User", back_populates="user_settings")


class AIProvider(Base):
    __tablename__ = "ai_providers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    provider_type = Column(String, default="azure")
    api_key = Column(String, default="")
    endpoint = Column(String, default="")
    deployment = Column(String, default="")
    is_active = Column(Boolean, default=False)

    user = relationship("User", back_populates="ai_providers")


# ── LLM Usage Tracking ────────────────────────────────────────

class LLMUsageLog(Base):
    __tablename__ = "llm_usage_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(String, nullable=True)
    model = Column(String, nullable=False)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    estimated_cost = Column(Float, default=0.0)
    request_type = Column(String, default="suggestion")
    latency_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ── Pre-Generated Answers ─────────────────────────────────────

class PreGeneratedAnswer(Base):
    __tablename__ = "pre_generated_answers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(String, nullable=False, index=True)
    question_ja = Column(String, nullable=False)
    answer_ja = Column(Text, default="")
    answer_romaji = Column(Text, default="")
    answer_vi = Column(Text, default="")
    embedding = Column(LargeBinary, nullable=True)
    jp_level = Column(String, default="natural")
    language = Column(String, default="ja-JP")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ── Engine ────────────────────────────────────────────────────

engine = create_engine(settings.DATABASE_URL, echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
