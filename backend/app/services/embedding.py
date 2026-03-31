"""Chunking + embedding for RAG pipeline.

Splits transcript into overlapping chunks, generates embeddings via
Azure OpenAI text-embedding-3-small, and stores in FAISS index.
"""

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import settings, FAISS_DIR

CHUNK_SIZE = 500
CHUNK_OVERLAP = 100
EMBEDDING_MODEL = settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT
EMBEDDING_DIM = 1536

_embedding_client = None
_embedding_client_lock = threading.Lock()
_embedding_cache: dict[str, list[float]] = {}
_embedding_cache_lock = threading.Lock()
_EMBEDDING_CACHE_MAX = 1000


def _get_embedding_client():
    global _embedding_client
    if _embedding_client is not None:
        return _embedding_client
    with _embedding_client_lock:
        if _embedding_client is not None:
            return _embedding_client
        from openai import AzureOpenAI
        _embedding_client = AzureOpenAI(
            api_key=settings.AZURE_OPENAI_KEY,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_version="2024-12-01-preview",
            timeout=15.0,
        )
        return _embedding_client


def chunk_transcript(entries: list[dict], chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[dict]:
    """Split transcript entries into overlapping text chunks with metadata."""
    all_text_parts = []
    for e in entries:
        speaker = e.get("speaker", "")
        text = e.get("text", "") or e.get("ja", "")
        ts = e.get("timestamp", "") or e.get("time", "")
        meeting_id = e.get("meeting_id", "")
        if text.strip():
            all_text_parts.append({
                "text": f"[{speaker}] {text}",
                "speaker": speaker,
                "time": str(ts),
                "meeting_id": meeting_id,
            })

    if not all_text_parts:
        return []

    full_text = "\n".join(p["text"] for p in all_text_parts)
    chunks = []
    start = 0
    chunk_idx = 0

    while start < len(full_text):
        end = min(start + chunk_size, len(full_text))
        chunk_text = full_text[start:end]

        first_entry = all_text_parts[0] if all_text_parts else {}
        meeting_id = first_entry.get("meeting_id", "")

        speaker_set = set()
        for p in all_text_parts:
            if p["text"] in chunk_text:
                speaker_set.add(p["speaker"])

        chunks.append({
            "chunk_id": f"{meeting_id}_chunk_{chunk_idx}",
            "meeting_id": meeting_id,
            "text": chunk_text,
            "speakers": list(speaker_set),
            "index": chunk_idx,
        })

        chunk_idx += 1
        start += chunk_size - overlap
        if start >= len(full_text):
            break

    return chunks


def get_embeddings(texts: list[str]) -> np.ndarray:
    """Get embeddings from Azure OpenAI with LRU cache (thread-safe)."""
    client = _get_embedding_client()

    results: list[list[float]] = []
    uncached_texts: list[str] = []
    uncached_indices: list[int] = []

    with _embedding_cache_lock:
        for i, t in enumerate(texts):
            cached = _embedding_cache.get(t)
            if cached is not None:
                results.append(cached)
            else:
                results.append([])
                uncached_texts.append(t)
                uncached_indices.append(i)

    if uncached_texts:
        batch_size = 16
        fetched: list[list[float]] = []
        for i in range(0, len(uncached_texts), batch_size):
            batch = uncached_texts[i:i + batch_size]
            try:
                resp = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
                for item in resp.data:
                    fetched.append(item.embedding)
            except Exception as e:
                print(f"  [EMBEDDING ERR] {e}", file=sys.stderr)
                for _ in batch:
                    fetched.append([0.0] * EMBEDDING_DIM)

        with _embedding_cache_lock:
            for j, (result_idx, emb) in enumerate(zip(uncached_indices, fetched)):
                results[result_idx] = emb
                _embedding_cache[uncached_texts[j]] = emb
                if len(_embedding_cache) > _EMBEDDING_CACHE_MAX:
                    _embedding_cache.pop(next(iter(_embedding_cache)))

    return np.array(results, dtype=np.float32)


def build_faiss_index(chunks: list[dict]) -> tuple[Any, list[dict]]:
    """Build FAISS index from chunks. Returns (index, metadata_list)."""
    import faiss

    if not chunks:
        index = faiss.IndexFlatIP(EMBEDDING_DIM)
        return index, []

    texts = [c["text"] for c in chunks]
    embeddings = get_embeddings(texts)

    faiss.normalize_L2(embeddings)
    index = faiss.IndexFlatIP(EMBEDDING_DIM)
    index.add(embeddings)

    metadata = [
        {
            "chunk_id": c["chunk_id"],
            "meeting_id": c["meeting_id"],
            "text": c["text"],
            "speakers": c.get("speakers", []),
            "index": c["index"],
        }
        for c in chunks
    ]

    return index, metadata


def save_index(meeting_id: str, index, metadata: list[dict]):
    """Save FAISS index and metadata to disk."""
    import faiss

    idx_dir = FAISS_DIR / meeting_id
    idx_dir.mkdir(parents=True, exist_ok=True)

    faiss.write_index(index, str(idx_dir / "index.faiss"))
    with open(idx_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


def load_index(meeting_id: str) -> tuple[Any | None, list[dict]]:
    """Load FAISS index and metadata from disk."""
    import faiss

    idx_dir = FAISS_DIR / meeting_id
    idx_path = idx_dir / "index.faiss"
    meta_path = idx_dir / "metadata.json"

    if not idx_path.exists() or not meta_path.exists():
        return None, []

    index = faiss.read_index(str(idx_path))
    with open(meta_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    return index, metadata


def search_index(query: str, meeting_ids: list[str] | None = None, top_k: int = 5) -> list[dict]:
    """Search across one or more meeting indexes."""
    import faiss

    query_embedding = get_embeddings([query])
    faiss.normalize_L2(query_embedding)

    if meeting_ids is None:
        meeting_ids = [d.name for d in FAISS_DIR.iterdir() if d.is_dir()]

    results = []
    for mid in meeting_ids:
        index, metadata = load_index(mid)
        if index is None or index.ntotal == 0:
            continue

        k = min(top_k, index.ntotal)
        scores, indices = index.search(query_embedding, k)

        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(metadata):
                continue
            meta = metadata[idx]
            results.append({
                "meeting_id": meta.get("meeting_id", mid),
                "text": meta.get("text", ""),
                "speakers": meta.get("speakers", []),
                "score": float(score),
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]
