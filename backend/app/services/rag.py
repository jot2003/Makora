"""RAG: Retrieval-Augmented Generation for meeting Q&A.

Retrieves relevant chunks from FAISS, builds context, queries LLM.
"""

import sys
from typing import Any

from openai import AzureOpenAI

from app.core.config import settings
from app.services.embedding import search_index


def _get_client() -> AzureOpenAI:
    return AzureOpenAI(
        api_key=settings.AZURE_OPENAI_KEY,
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_version="2024-12-01-preview",
    )


def chat_with_meeting(
    query: str,
    meeting_ids: list[str] | None = None,
    top_k: int = 5,
) -> dict:
    """Answer a question using RAG over meeting transcripts."""
    results = search_index(query, meeting_ids=meeting_ids, top_k=top_k)

    if not results:
        return {
            "answer": "No relevant information found in the meeting transcripts.",
            "sources": [],
        }

    context_parts = []
    sources = []
    for r in results:
        context_parts.append(r["text"])
        sources.append({
            "meeting_id": r.get("meeting_id", ""),
            "meeting_name": "",
            "speaker": ", ".join(r.get("speakers", [])),
            "time": "",
            "text": r["text"][:200],
            "score": r["score"],
        })

    context = "\n---\n".join(context_parts)

    system = """You are a meeting knowledge assistant. Answer the user's question
based ONLY on the provided meeting transcript excerpts.

Rules:
- Be concise and specific
- If the information is not in the context, say so
- Reference specific speakers when relevant
- Use direct quotes when helpful"""

    user_msg = f"Context from meeting transcripts:\n{context}\n\nQuestion: {query}"

    try:
        client = _get_client()
        kwargs: dict = {
            "model": settings.AZURE_OPENAI_DEPLOYMENT,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            "max_completion_tokens": 1000,
            "temperature": 0.3,
        }
        try:
            resp = client.chat.completions.create(**kwargs)
        except Exception:
            kwargs.pop("temperature", None)
            resp = client.chat.completions.create(**kwargs)
        answer = resp.choices[0].message.content or ""
    except Exception as e:
        print(f"  [RAG ERR] {e}", file=sys.stderr)
        answer = f"Error generating answer: {str(e)[:100]}"

    return {"answer": answer, "sources": sources}
