"""Pre-Generation Engine: pre-generate answers for common interview questions.

Generates answers at session start and matches incoming questions via cosine
similarity against a local FAISS index for sub-100ms cache hits.
"""

import re
import sys
import threading
import time
from typing import Optional

import numpy as np

from app.core.config import settings
import app.models.database as _db

_COMMON_QUESTIONS_JA = [
    "自己紹介をお願いします",
    "志望動機を教えてください",
    "転職理由を教えてください",
    "あなたの強みは何ですか",
    "あなたの弱みは何ですか",
    "これまでの経験を教えてください",
    "なぜこの会社を選びましたか",
    "5年後のビジョンを教えてください",
    "チームで働いた経験を教えてください",
    "困難を乗り越えた経験を教えてください",
    "前職での役割を教えてください",
    "技術スキルを教えてください",
    "プロジェクト管理の経験はありますか",
    "リーダーシップの経験を教えてください",
    "何か質問はありますか",
]

_EMBEDDING_DIM = 1536
_SIMILARITY_THRESHOLD = 0.82
_VI_DELIM_RE = re.compile(r'-{2,}\s*VI\s*-{0,}')


class PreGenEngine:
    """Manages pre-generated answers with embedding-based matching."""

    def __init__(self, meeting_id: str):
        self._meeting_id = meeting_id
        self._index = None
        self._answers: list[dict] = []
        self._lock = threading.Lock()
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def load_from_db(self):
        """Load existing pre-generated answers from DB into memory index."""
        try:
            db = _db.SessionLocal()
            rows = db.query(_db.PreGeneratedAnswer).filter(
                _db.PreGeneratedAnswer.meeting_id == self._meeting_id,
            ).all()
            db.close()

            if not rows:
                return

            embeddings = []
            answers = []
            for row in rows:
                if row.embedding:
                    emb = np.frombuffer(row.embedding, dtype=np.float32).copy()
                    if len(emb) == _EMBEDDING_DIM:
                        embeddings.append(emb)
                        answers.append({
                            "question": row.question_ja,
                            "answer_romaji": row.answer_romaji or "",
                            "answer_vi": row.answer_vi or "",
                        })

            if embeddings:
                import faiss
                emb_array = np.vstack(embeddings)
                faiss.normalize_L2(emb_array)
                idx = faiss.IndexFlatIP(_EMBEDDING_DIM)
                idx.add(emb_array)
                with self._lock:
                    self._index = idx
                    self._answers = answers
                    self._ready = True
                print(f"  [PREGEN] Loaded {len(answers)} cached answers for {self._meeting_id}", file=sys.stderr)

        except Exception as e:
            print(f"  [PREGEN] load_from_db error: {e}", file=sys.stderr)

    def generate_common(self, system_prompt: str, personal_info: str = "", company_info: str = ""):
        """Background: generate answers for common questions using own client.

        Uses a separate non-streaming API client so it never emits to the
        frontend or competes with the main LLM thread.
        """
        if not settings.AZURE_OPENAI_KEY or not settings.AZURE_OPENAI_ENDPOINT:
            return
        embedding_model = settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT
        if not embedding_model:
            print("  [PREGEN] No embedding deployment configured, skipping", file=sys.stderr)
            return

        try:
            from openai import AzureOpenAI

            client = AzureOpenAI(
                api_key=settings.AZURE_OPENAI_KEY,
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_version="2025-01-01-preview",
                timeout=30.0,
            )
            deployment = settings.AZURE_OPENAI_FAST_DEPLOYMENT or settings.AZURE_OPENAI_DEPLOYMENT

            db = _db.SessionLocal()
            existing = db.query(_db.PreGeneratedAnswer.question_ja).filter(
                _db.PreGeneratedAnswer.meeting_id == self._meeting_id,
            ).all()
            existing_set = {q[0] for q in existing}
            db.close()

            questions_to_gen = [q for q in _COMMON_QUESTIONS_JA if q not in existing_set]
            if not questions_to_gen:
                self.load_from_db()
                return

            from app.services.embedding import get_embeddings

            for q in questions_to_gen:
                try:
                    create_kwargs = {
                        "model": deployment,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"Interviewer: {q}"},
                        ],
                        "max_completion_tokens": 900,
                        "temperature": 0.7,
                        "stream": False,
                    }
                    try:
                        resp = client.chat.completions.create(**create_kwargs)
                    except Exception as api_err:
                        if "temperature" in str(api_err).lower() or "unsupported" in str(api_err).lower():
                            create_kwargs.pop("temperature", None)
                            resp = client.chat.completions.create(**create_kwargs)
                        else:
                            raise
                    raw = resp.choices[0].message.content or ""

                    romaji = ""
                    vi = ""
                    m = _VI_DELIM_RE.search(raw)
                    if m:
                        romaji = raw[:m.start()].strip()
                        vi = raw[m.end():].strip()
                    else:
                        romaji = raw.strip()

                    emb = get_embeddings([q])
                    emb_bytes = emb[0].tobytes() if len(emb) > 0 else None

                    db = _db.SessionLocal()
                    entry = _db.PreGeneratedAnswer(
                        meeting_id=self._meeting_id,
                        question_ja=q,
                        answer_romaji=romaji,
                        answer_vi=vi,
                        embedding=emb_bytes,
                    )
                    db.add(entry)
                    db.commit()
                    db.close()
                except Exception as e:
                    print(f"  [PREGEN] gen error for '{q[:30]}': {e}", file=sys.stderr)

            self.load_from_db()
            print(f"  [PREGEN] Generated {len(questions_to_gen)} new answers", file=sys.stderr)

        except Exception as e:
            print(f"  [PREGEN] generate_common error: {e}", file=sys.stderr)

    def match_question(self, question: str) -> Optional[dict]:
        """Match an incoming question against pre-generated answers.

        Returns dict with answer_romaji and answer_vi if match found, else None.
        """
        if not self._ready or self._index is None:
            return None

        try:
            from app.services.embedding import get_embeddings
            import faiss

            q_emb = get_embeddings([question])
            faiss.normalize_L2(q_emb)

            with self._lock:
                if self._index is None or self._index.ntotal == 0:
                    return None
                scores, indices = self._index.search(q_emb, 1)

            if scores[0][0] >= _SIMILARITY_THRESHOLD and indices[0][0] >= 0:
                idx = indices[0][0]
                if idx < len(self._answers):
                    match = self._answers[idx]
                    print(f"  [PREGEN] Cache hit (score={scores[0][0]:.3f}): '{question[:40]}' -> '{match['question'][:40]}'", file=sys.stderr)
                    return match

        except Exception as e:
            print(f"  [PREGEN] match error: {e}", file=sys.stderr)

        return None
