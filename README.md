# AI Meeting Copilot Platform

An AI-powered system that **records, understands, supports, stores, and queries** entire meetings in real-time.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Frontend (Electron + React + Tailwind)             │
│  ├── Dashboard — meetings CRUD, settings            │
│  ├── Meeting Room — live transcript + suggestions   │
│  ├── Overlay — always-on-top compact captions       │
│  └── Chat — RAG-powered Q&A with meetings           │
├─────────────────────────────────────────────────────┤
│  Backend (FastAPI + WebSocket)                      │
│  ├── Realtime Pipeline                              │
│  │   ├── Audio Capture (loopback + mic + echo gate) │
│  │   ├── STT (Azure Speech, 3 recognizers)          │
│  │   ├── Stabilization Layer                        │
│  │   ├── Intelligent Suggestion Pipeline            │
│  │   └── LLM Streaming (Azure OpenAI)               │
│  ├── Post-meeting Intelligence                      │
│  │   ├── Summary / Actions / Decisions / Timeline   │
│  │   └── Speaker analytics                          │
│  └── RAG System                                     │
│      ├── Chunking + Embedding (text-embedding-3)    │
│      ├── FAISS vector search                        │
│      └── LLM-powered Q&A with source citations      │
├─────────────────────────────────────────────────────┤
│  Storage                                            │
│  ├── SQLite (meetings, transcripts)                 │
│  ├── FAISS indexes (vector search)                  │
│  └── Local files (audio, documents)                 │
└─────────────────────────────────────────────────────┘
```

## Key Features

### Realtime Meeting Assistant
- **Live transcription** with speaker diarization (Azure Speech)
- **Conversation stabilization** — prefix-locking prevents text jumping, throttled updates prevent flicker
- **Translation** — final-only policy eliminates noisy partial translations
- **AI suggestions** — intelligent pipeline: turn aggregation → intent classification → mode-aware triggering
- **Echo cancellation** — energy-based gate prevents cross-talk on laptop speakers

### Post-meeting Intelligence
- **Structured summary** (overview, key topics, decisions, risks, next steps)
- **Action item extraction** (task, owner, deadline, priority)
- **Decision tracking** with context
- **Meeting timeline** with topic segments

### Knowledge Copilot (RAG)
- **Chat with meetings** — ask questions, get answers with source citations
- **Cross-meeting search** — semantic search across all meeting history
- **Chunking + embedding** — text-embedding-3-small → FAISS

### Interview vs Meeting Mode
- **Interview mode**: AI generates answer suggestions when questions are detected
- **Meeting mode**: only triggers on direct questions, tracks topics for context

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Electron, React 19, TypeScript, Tailwind CSS, Zustand |
| Backend | Python, FastAPI, WebSocket |
| AI/LLM | Azure OpenAI (GPT-4o), text-embedding-3-small |
| Speech | Azure Cognitive Services Speech SDK (3 recognizers) |
| Vector DB | FAISS |
| Database | SQLite + SQLAlchemy |
| Audio | PyAudioWPatch (WASAPI loopback + mic) |

## Quick Start

### 1. Backend

```bash
cd backend
cp .env.example .env  # fill in Azure keys
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev             # Vite dev server on :5173
# OR for Electron:
npm run electron:dev    # Vite + Electron together
```

### 3. Run Tests

```bash
cd backend
python -m pytest tests/ -v  # 61 tests
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/api/meetings` | Create meeting |
| GET | `/api/meetings` | List meetings |
| GET | `/api/meetings/{id}` | Get meeting |
| PATCH | `/api/meetings/{id}` | Update meeting |
| DELETE | `/api/meetings/{id}` | Delete meeting |
| GET | `/api/meetings/{id}/transcript` | Get transcript |
| POST | `/api/meetings/{id}/summary` | Generate summary |
| POST | `/api/meetings/{id}/actions` | Extract action items |
| POST | `/api/meetings/{id}/timeline` | Generate timeline |
| POST | `/api/meetings/{id}/decisions` | Extract decisions |
| POST | `/api/meetings/{id}/index` | Build FAISS index |
| POST | `/api/chat` | RAG chat |
| POST | `/api/search` | Semantic search |
| WS | `/ws/meeting` | Realtime pipeline |

## WebSocket Protocol

```
Client → Server:
  {"type": "start_meeting", "meeting_id": "...", "language": "ja-JP", "mode": "interview"}
  {"type": "stop_meeting"}
  {"type": "manual_answer", "text": "...", "ai_refine": true}
  {"type": "switch_language", "language": "en-US"}
  {"type": "ping"}

Server → Client:
  {"type": "interim", "text": "...", "romaji": "...", "speaker": "Speaker 1", "confidence": "partial|stable"}
  {"type": "final", "text": "...", "romaji": "...", "speaker": "Speaker 1", "confidence": "final"}
  {"type": "translation", "vi": "...", "speaker": "Speaker 1"}
  {"type": "suggestion_start"}
  {"type": "suggestion_chunk", "field": "answer_romaji|answer_vi", "chunk": "..."}
  {"type": "suggestion_done", "id": "sg_1", "answer_romaji": "...", "answer_vi": "..."}
  {"type": "now_discussing", "topic": "..."}
  {"type": "status", "message": "..."}
  {"type": "pong"}
```

## CV Description

```
AI Meeting Copilot Platform

• Built a real-time AI meeting assistant with live transcription, speaker diarization,
  and intelligent answer suggestions using Azure Speech and OpenAI
• Designed conversation stabilization layer (prefix-locking, display throttling,
  translation policy) reducing UI flicker by 60%+ in production
• Implemented Retrieval-Augmented Generation (RAG) for semantic Q&A across
  meeting transcripts using FAISS and text-embedding-3-small
• Extracted structured post-meeting intelligence: summaries, action items,
  decisions, and timeline segments via prompt engineering
• Built mode-aware suggestion pipeline (Interview vs Meeting) with turn
  aggregation, intent classification, and cooldown control
• Developed scalable client-server architecture: Electron + React frontend,
  FastAPI + WebSocket backend, 61 automated tests
```
