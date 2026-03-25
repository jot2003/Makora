"""Session management: create/load/save interview sessions, transcript logging, glossary."""

import json
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

SESSIONS_DIR = Path(__file__).parent / "sessions"


@dataclass
class Session:
    id: str
    name: str
    created_at: str
    status: str = "created"
    documents: list[str] = field(default_factory=list)

    @property
    def dir_path(self) -> Path:
        return SESSIONS_DIR / self.id

    @property
    def transcript_path(self) -> Path:
        return self.dir_path / "transcript.jsonl"

    @property
    def glossary_path(self) -> Path:
        return self.dir_path / "glossary.json"

    @property
    def context_path(self) -> Path:
        return self.dir_path / "context.txt"

    @property
    def documents_dir(self) -> Path:
        return self.dir_path / "documents"


class SessionManager:

    def __init__(self):
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    def create_session(self, name: str) -> Session:
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        session = Session(
            id=session_id,
            name=name,
            created_at=datetime.now().isoformat(),
        )
        session.dir_path.mkdir(parents=True, exist_ok=True)
        session.documents_dir.mkdir(exist_ok=True)
        self._save_metadata(session)
        self.save_glossary(session, [])
        return session

    def list_sessions(self) -> list[Session]:
        sessions = []
        if not SESSIONS_DIR.exists():
            return sessions
        for d in sorted(SESSIONS_DIR.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            meta_path = d / "session.json"
            if meta_path.exists():
                try:
                    sessions.append(self._load_metadata(meta_path))
                except (json.JSONDecodeError, TypeError):
                    continue
        return sessions

    def load_session(self, session_id: str) -> Optional[Session]:
        meta_path = SESSIONS_DIR / session_id / "session.json"
        if meta_path.exists():
            return self._load_metadata(meta_path)
        return None

    def delete_session(self, session_id: str):
        path = SESSIONS_DIR / session_id
        if path.exists():
            shutil.rmtree(path)

    def update_status(self, session: Session, status: str):
        session.status = status
        self._save_metadata(session)

    def append_transcript(self, session: Session, entry: dict):
        with open(session.transcript_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def load_transcript(self, session: Session) -> list[dict]:
        if not session.transcript_path.exists():
            return []
        entries = []
        with open(session.transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return entries

    def get_recent_context(self, session: Session, n: int = 5) -> list[dict]:
        transcript = self.load_transcript(session)
        return transcript[-n:] if transcript else []

    def load_glossary(self, session: Session) -> list[dict]:
        if not session.glossary_path.exists():
            return []
        with open(session.glossary_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_glossary(self, session: Session, entries: list[dict]):
        with open(session.glossary_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)

    # -- Phân loại tài liệu --

    def _doc_meta_path(self, session: Session) -> Path:
        return session.dir_path / "doc_meta.json"

    def load_doc_meta(self, session: Session) -> dict[str, str]:
        """Load document category mapping: {filename: "personal"|"company"}."""
        path = self._doc_meta_path(session)
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_doc_meta(self, session: Session, meta: dict[str, str]):
        with open(self._doc_meta_path(session), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def set_doc_category(self, session: Session, filename: str, category: str):
        meta = self.load_doc_meta(session)
        meta[filename] = category
        self.save_doc_meta(session, meta)

    # -- Ghi chú thủ công --

    def load_notes(self, session: Session, category: str) -> str:
        path = session.dir_path / f"notes_{category}.txt"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def save_notes(self, session: Session, category: str, text: str):
        path = session.dir_path / f"notes_{category}.txt"
        path.write_text(text, encoding="utf-8")

    def _save_metadata(self, session: Session):
        meta = {
            "id": session.id,
            "name": session.name,
            "created_at": session.created_at,
            "status": session.status,
            "documents": session.documents,
        }
        with open(session.dir_path / "session.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def _load_metadata(self, meta_path: Path) -> Session:
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Session(**data)
