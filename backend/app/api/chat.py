"""RAG Chat & Search API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.models.database import Meeting, TranscriptEntry, get_db
from app.models.schemas import ChatRequest, ChatResponse, SearchRequest, SearchResult
from app.services.embedding import chunk_transcript, build_faiss_index, save_index, search_index
from app.services.rag import chat_with_meeting

router = APIRouter(prefix="/api", tags=["rag"])


@router.post("/meetings/{meeting_id}/index")
def index_meeting(meeting_id: str, db: Session = Depends(get_db)):
    """Build FAISS index for a meeting's transcript."""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    entries = (
        db.query(TranscriptEntry)
        .filter(TranscriptEntry.meeting_id == meeting_id)
        .order_by(TranscriptEntry.timestamp)
        .all()
    )

    if not entries:
        raise HTTPException(400, "No transcript entries to index")

    entry_dicts = [
        {
            "meeting_id": meeting_id,
            "speaker": e.speaker,
            "text": e.text,
            "time": str(e.timestamp),
        }
        for e in entries
    ]

    chunks = chunk_transcript(entry_dicts)
    if not chunks:
        raise HTTPException(400, "No chunks produced from transcript")

    index, metadata = build_faiss_index(chunks)
    save_index(meeting_id, index, metadata)

    return {"status": "indexed", "chunks": len(chunks), "meeting_id": meeting_id}


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest):
    """Chat with meeting transcripts using RAG."""
    result = chat_with_meeting(
        query=body.query,
        meeting_ids=body.meeting_ids,
        top_k=5,
    )
    return ChatResponse(
        answer=result["answer"],
        sources=[
            {
                "meeting_id": s.get("meeting_id", ""),
                "meeting_name": s.get("meeting_name", ""),
                "speaker": s.get("speaker", ""),
                "time": s.get("time", ""),
                "text": s.get("text", ""),
            }
            for s in result.get("sources", [])
        ],
    )


@router.post("/search", response_model=list[SearchResult])
def search(body: SearchRequest):
    """Semantic search across meeting transcripts."""
    results = search_index(body.query, top_k=10)
    return [
        SearchResult(
            meeting_id=r.get("meeting_id", ""),
            speaker=", ".join(r.get("speakers", [])),
            text=r.get("text", "")[:300],
            score=r.get("score", 0.0),
        )
        for r in results
    ]
