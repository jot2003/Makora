"""Offline transcription: process audio/video files with speaker diarization.

Strategy (in priority order):
1. Azure ConversationTranscriber — best diarization (speaker IDs), needs Azure keys
2. Whisper fallback — good transcription, no speaker diarization

Supports: MP4, MP3, WAV, M4A, WEBM, MKV, AVI, MOV, FLAC, OGG.
Converts to 16kHz mono WAV via ffmpeg before processing.
"""

import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Callable

from app.core.config import settings, AUDIO_DIR
import app.models.database as _db_module

FFMPEG_NAMES = ["ffmpeg", str(Path(__file__).parent.parent.parent / "ffmpeg.exe")]


def _find_ffmpeg() -> str | None:
    for name in FFMPEG_NAMES:
        try:
            r = subprocess.run([name, "-version"], capture_output=True, timeout=5)
            if r.returncode == 0:
                return name
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def _extract_to_wav(input_path: str, output_wav: str) -> bool:
    """Convert any audio/video file to 16kHz mono PCM WAV."""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        print("  [FFMPEG] not found", file=sys.stderr)
        return False
    try:
        cmd = [
            ffmpeg, "-y", "-i", input_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            output_wav,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        return result.returncode == 0
    except Exception as e:
        print(f"  [FFMPEG ERR] {e}", file=sys.stderr)
        return False


def _ensure_wav(file_path: str) -> tuple[str, bool]:
    """Return (wav_path, is_temp). Converts if needed."""
    p = Path(file_path)
    if p.suffix.lower() == ".wav":
        return str(p), False

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=str(AUDIO_DIR))
    tmp.close()
    if _extract_to_wav(file_path, tmp.name):
        return tmp.name, True
    Path(tmp.name).unlink(missing_ok=True)
    return "", False


# ── Azure ConversationTranscriber (offline batch mode) ──────────

def _transcribe_azure(wav_path: str, language: str = "ja-JP") -> list[dict]:
    """Transcribe WAV file using Azure ConversationTranscriber with speaker diarization.

    Returns list of {"speaker": str, "text": str, "start": float, "end": float}.
    """
    try:
        import azure.cognitiveservices.speech as speechsdk
    except ImportError:
        return []

    if not settings.AZURE_SPEECH_KEY or not settings.AZURE_SPEECH_REGION:
        return []

    audio_config = speechsdk.audio.AudioConfig(filename=wav_path)
    speech_config = speechsdk.SpeechConfig(
        subscription=settings.AZURE_SPEECH_KEY,
        region=settings.AZURE_SPEECH_REGION,
    )
    speech_config.speech_recognition_language = language
    speech_config.set_profanity(speechsdk.ProfanityOption.Raw)
    speech_config.request_word_level_timestamps()

    transcriber = speechsdk.transcription.ConversationTranscriber(
        speech_config=speech_config,
        audio_config=audio_config,
    )

    segments = []
    done_event = threading.Event()
    error_msg = []

    def on_transcribed(evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            speaker = evt.result.speaker_id or "Unknown"
            text = evt.result.text.strip()
            offset_ticks = evt.result.offset
            duration_ticks = evt.result.duration
            start_sec = offset_ticks / 10_000_000
            end_sec = start_sec + duration_ticks / 10_000_000
            if text:
                segments.append({
                    "speaker": speaker,
                    "text": text,
                    "start": start_sec,
                    "end": end_sec,
                })

    def on_canceled(evt):
        if evt.reason == speechsdk.CancellationReason.Error:
            error_msg.append(f"Azure STT error: {evt.error_details}")
        done_event.set()

    def on_stopped(evt):
        done_event.set()

    transcriber.transcribed.connect(on_transcribed)
    transcriber.canceled.connect(on_canceled)
    transcriber.session_stopped.connect(on_stopped)

    print("  [AZURE] Starting ConversationTranscriber...")
    transcriber.start_transcribing_async().get()

    done_event.wait(timeout=600)
    transcriber.stop_transcribing_async().get()

    if error_msg:
        print(f"  [AZURE ERR] {error_msg[0]}", file=sys.stderr)

    print(f"  [AZURE] Done: {len(segments)} segments with speaker IDs")
    return segments


# ── Whisper fallback ────────────────────────────────────────────

def _transcribe_whisper(wav_path: str, language: str = "ja") -> list[dict]:
    """Transcribe using OpenAI Whisper (no speaker diarization)."""
    try:
        import whisper
    except ImportError:
        return []

    print("  [WHISPER] Loading model (small)...")
    model = whisper.load_model("small")
    print("  [WHISPER] Transcribing...")
    result = model.transcribe(wav_path, language=language, verbose=False)

    segments = []
    for seg in result.get("segments", []):
        text = seg.get("text", "").strip()
        if text:
            segments.append({
                "speaker": "Speaker",
                "text": text,
                "start": seg.get("start", 0.0),
                "end": seg.get("end", 0.0),
            })

    print(f"  [WHISPER] Done: {len(segments)} segments (no speaker IDs)")
    return segments


# ── Main entry point ────────────────────────────────────────────

def transcribe_file(
    file_path: str,
    meeting_id: str,
    language: str = "ja",
    prefer_azure: bool = True,
) -> dict:
    """Transcribe an audio/video file with speaker diarization and save to DB.

    Pipeline:
    1. Convert to WAV (ffmpeg)
    2. Try Azure ConversationTranscriber (speaker diarization)
    3. Fall back to Whisper if Azure unavailable
    4. Merge consecutive same-speaker segments
    5. Save to DB as TranscriptEntry rows

    Returns: {"status": "ok"|"error", "segments": int, "duration": float, "method": str, "speakers": list}
    """
    input_path = Path(file_path)
    if not input_path.exists():
        return {"status": "error", "message": f"File not found: {file_path}"}

    suffix = input_path.suffix.lower()
    allowed = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".wma", ".mp4", ".webm", ".mkv", ".avi", ".mov"}
    if suffix not in allowed:
        return {"status": "error", "message": f"Unsupported format: {suffix}"}

    wav_path, is_temp = _ensure_wav(file_path)
    if not wav_path:
        return {"status": "error", "message": "Failed to convert to WAV (is ffmpeg installed?)"}

    azure_lang = language if "-" in language else {"ja": "ja-JP", "en": "en-US", "zh": "zh-CN", "ko": "ko-KR"}.get(language, f"{language}-{language.upper()}")
    whisper_lang = language.split("-")[0]

    segments = []
    method = "none"

    if prefer_azure and settings.AZURE_SPEECH_KEY:
        segments = _transcribe_azure(wav_path, azure_lang)
        if segments:
            method = "azure"

    if not segments:
        segments = _transcribe_whisper(wav_path, whisper_lang)
        if segments:
            method = "whisper"

    if is_temp:
        Path(wav_path).unlink(missing_ok=True)

    if not segments:
        return {"status": "error", "message": "Both Azure and Whisper failed to transcribe"}

    merged = _merge_segments(segments)
    speakers = list({s["speaker"] for s in merged})

    db = _db_module.SessionLocal()
    try:
        for seg in merged:
            entry = _db_module.TranscriptEntry(
                meeting_id=meeting_id,
                speaker=seg["speaker"],
                speaker_id=seg["speaker"],
                language=language,
                source="whisper" if method == "whisper" else "realtime",
                text=seg["text"],
                romaji="",
            )
            db.add(entry)
        db.commit()
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": f"DB error: {str(e)[:200]}"}
    finally:
        db.close()

    duration = merged[-1]["end"] if merged else 0.0

    return {
        "status": "ok",
        "segments": len(merged),
        "duration": duration,
        "method": method,
        "speakers": speakers,
    }


def _merge_segments(segments: list[dict], gap_threshold: float = 1.0) -> list[dict]:
    """Merge consecutive segments from the same speaker within gap_threshold seconds."""
    if not segments:
        return []

    merged = []
    current = dict(segments[0])

    for seg in segments[1:]:
        gap = seg["start"] - current["end"]
        if seg["speaker"] == current["speaker"] and gap < gap_threshold:
            current["text"] += " " + seg["text"]
            current["end"] = seg["end"]
        else:
            merged.append(current)
            current = dict(seg)

    merged.append(current)
    return merged
