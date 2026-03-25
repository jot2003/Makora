"""Post-meeting intelligence: summary, actions, decisions, timeline.

Uses Azure OpenAI to analyze the full transcript and extract structured insights.
"""

import json
import sys
from typing import Any

from openai import AzureOpenAI

from app.core.config import settings


def _get_client() -> AzureOpenAI:
    return AzureOpenAI(
        api_key=settings.AZURE_OPENAI_KEY,
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_version="2024-12-01-preview",
    )


def _call_llm(system: str, user: str, max_tokens: int = 2000) -> str:
    client = _get_client()
    deployment = settings.AZURE_OPENAI_DEPLOYMENT
    try:
        kwargs: dict = {
            "model": deployment,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_completion_tokens": max_tokens,
            "temperature": 0.3,
        }
        try:
            resp = client.chat.completions.create(**kwargs)
        except Exception:
            kwargs.pop("temperature", None)
            resp = client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""
    except Exception as e:
        print(f"  [INTELLIGENCE ERR] {e}", file=sys.stderr)
        return ""


def _parse_json(raw: str) -> dict | list:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[:-3]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _format_transcript(entries: list[dict], max_chars: int = 12000) -> str:
    lines = []
    total = 0
    for e in entries:
        speaker = e.get("speaker", "Unknown")
        text = e.get("text", "") or e.get("ja", "")
        ts = e.get("timestamp", "") or e.get("time", "")
        line = f"[{ts}] {speaker}: {text}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)


def generate_summary(transcript_entries: list[dict], mode: str = "interview") -> dict:
    """Generate structured meeting summary."""
    transcript_text = _format_transcript(transcript_entries)
    if not transcript_text:
        return {"overview": "", "key_topics": [], "decisions": [], "risks": [], "next_steps": []}

    system = """Analyze this meeting/interview transcript and produce a structured summary.
Output ONLY valid JSON with these keys:
- "overview": string (2-3 sentence overview)
- "key_topics": list of strings (main topics discussed)
- "decisions": list of {"decision": string, "reason": string}
- "risks": list of strings (any risks or concerns mentioned)
- "next_steps": list of strings (action items or follow-ups)

Be concise and specific. Use the actual content, not generic statements."""

    raw = _call_llm(system, f"Transcript ({mode} mode):\n{transcript_text}")
    result = _parse_json(raw)
    if isinstance(result, dict):
        return {
            "overview": result.get("overview", ""),
            "key_topics": result.get("key_topics", []),
            "decisions": result.get("decisions", []),
            "risks": result.get("risks", []),
            "next_steps": result.get("next_steps", []),
        }
    return {"overview": "", "key_topics": [], "decisions": [], "risks": [], "next_steps": []}


def extract_action_items(transcript_entries: list[dict]) -> list[dict]:
    """Extract action items with task, owner, deadline, priority."""
    transcript_text = _format_transcript(transcript_entries)
    if not transcript_text:
        return []

    system = """Extract action items from this transcript.
Output ONLY a JSON array of objects with:
- "task": string (what needs to be done)
- "owner": string (who is responsible, or "" if unclear)
- "deadline": string (when, or "" if not specified)
- "priority": "high" | "medium" | "low"

Only include real, actionable tasks. Not general discussion points."""

    raw = _call_llm(system, f"Transcript:\n{transcript_text}")
    result = _parse_json(raw)
    if isinstance(result, list):
        return result
    return []


def generate_timeline(transcript_entries: list[dict]) -> list[dict]:
    """Generate meeting timeline with topic segments."""
    transcript_text = _format_transcript(transcript_entries)
    if not transcript_text:
        return []

    system = """Create a timeline of topic segments from this transcript.
Output ONLY a JSON array of objects with:
- "time": string (timestamp or relative time)
- "topic": string (what was being discussed)
- "summary": string (1 sentence summary of that segment)

Group by natural topic changes, typically 3-10 segments."""

    raw = _call_llm(system, f"Transcript:\n{transcript_text}")
    result = _parse_json(raw)
    if isinstance(result, list):
        return result
    return []


def extract_decisions(transcript_entries: list[dict]) -> list[dict]:
    """Extract specific decisions made during the meeting."""
    transcript_text = _format_transcript(transcript_entries)
    if not transcript_text:
        return []

    system = """Extract decisions made in this transcript.
Output ONLY a JSON array of objects with:
- "decision": string (what was decided)
- "reason": string (why, if mentioned)
- "context": string (surrounding discussion context, 1 sentence)

Only include actual decisions, not proposals or suggestions."""

    raw = _call_llm(system, f"Transcript:\n{transcript_text}")
    result = _parse_json(raw)
    if isinstance(result, list):
        return result
    return []
