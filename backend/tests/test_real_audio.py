"""Real audio transcription test — Azure ConversationTranscriber with speaker diarization.

Uses Azure Speech ConversationTranscriber to transcribe a Japanese interview MP3
with proper speaker diarization (Guest-1, Guest-2, etc.).

Falls back to Whisper + pitch heuristic if Azure keys are not available.
"""

import os
import sys
import threading
import subprocess
from pathlib import Path
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

AUDIO_PATH = Path(__file__).parent.parent / "data" / "audio" / "web_interview_sample.mp3"
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "transcription_output.txt"
FFMPEG_PATH = Path(__file__).parent.parent / "ffmpeg.exe"


def format_time(seconds: float) -> str:
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def convert_to_wav(input_path: str, output_path: str) -> bool:
    ffmpeg = str(FFMPEG_PATH) if FFMPEG_PATH.exists() else "ffmpeg"
    try:
        cmd = [ffmpeg, "-y", "-i", input_path,
               "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
               output_path]
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        return r.returncode == 0
    except Exception as e:
        print(f"ffmpeg error: {e}")
        return False


def transcribe_with_azure(wav_path: str) -> list[dict]:
    """Azure ConversationTranscriber — proper speaker diarization."""
    try:
        import azure.cognitiveservices.speech as speechsdk
    except ImportError:
        print("  azure-cognitiveservices-speech not installed")
        return []

    key = os.getenv("AZURE_SPEECH_KEY", "")
    region = os.getenv("AZURE_SPEECH_REGION", "")
    if not key or not region:
        print("  AZURE_SPEECH_KEY or AZURE_SPEECH_REGION not set")
        return []

    print(f"  Azure region: {region}")
    print(f"  Key prefix: {key[:8]}...")

    audio_config = speechsdk.audio.AudioConfig(filename=wav_path)
    speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
    speech_config.speech_recognition_language = "ja-JP"
    speech_config.set_profanity(speechsdk.ProfanityOption.Raw)
    speech_config.request_word_level_timestamps()

    transcriber = speechsdk.transcription.ConversationTranscriber(
        speech_config=speech_config,
        audio_config=audio_config,
    )

    segments = []
    done = threading.Event()
    errors = []

    def on_transcribed(evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            text = evt.result.text.strip()
            speaker = evt.result.speaker_id or "Unknown"
            start = evt.result.offset / 10_000_000
            end = start + evt.result.duration / 10_000_000
            if text:
                segments.append({
                    "speaker": speaker,
                    "text": text,
                    "start": start,
                    "end": end,
                })
                print(f"    [{format_time(start)}] {speaker}: {text[:50]}...")

    def on_canceled(evt):
        if evt.reason == speechsdk.CancellationReason.Error:
            errors.append(evt.error_details)
        done.set()

    def on_stopped(evt):
        done.set()

    transcriber.transcribed.connect(on_transcribed)
    transcriber.canceled.connect(on_canceled)
    transcriber.session_stopped.connect(on_stopped)

    print("  Starting Azure ConversationTranscriber...")
    transcriber.start_transcribing_async().get()
    done.wait(timeout=600)

    try:
        transcriber.stop_transcribing_async().get()
    except Exception:
        pass

    if errors:
        print(f"  Azure errors: {errors}")
    print(f"  Azure done: {len(segments)} segments")
    return segments


def transcribe_with_whisper(audio_path: str) -> list[dict]:
    """Whisper fallback — good transcription, no real speaker diarization."""
    try:
        import whisper
    except ImportError:
        print("  openai-whisper not installed")
        return []

    print("  Loading Whisper model (small)...")
    model = whisper.load_model("small")
    print("  Transcribing with Whisper...")
    result = model.transcribe(str(audio_path), language="ja", verbose=False)

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
    print(f"  Whisper done: {len(segments)} segments (no speaker IDs)")
    return segments


def merge_segments(segments: list[dict], gap_threshold: float = 1.5) -> list[dict]:
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


def build_output(merged: list[dict], method: str) -> str:
    lines = []
    lines.append("=" * 80)
    lines.append("TRANSCRIPTION: WEB Interview Practice")
    lines.append(f"Source: web_interview_sample.mp3")
    lines.append(f"Method: {method}")
    lines.append(f"Total turns: {len(merged)}")
    if merged:
        duration = merged[-1].get("end", 0)
        lines.append(f"Duration: {format_time(duration)}")
    lines.append("")

    if method == "azure":
        speakers = sorted(set(s["speaker"] for s in merged))
        for sp in speakers:
            lines.append(f"  {sp}")
        lines.append("")
        lines.append("(Azure auto-detects speakers as Guest-1, Guest-2, etc.)")
    else:
        lines.append("Speaker A = Interviewer (Male)")
        lines.append("Speaker B = Candidate (Female)")
        lines.append("(Whisper fallback — no speaker diarization)")

    lines.append("=" * 80)
    lines.append("")

    for turn in merged:
        start = format_time(turn["start"])
        end = format_time(turn["end"])
        speaker = turn["speaker"]
        lines.append(f"[{start} - {end}] {speaker}")
        lines.append(f"  {turn['text']}")
        lines.append("")

    lines.append("=" * 80)

    speaker_stats = {}
    for t in merged:
        sp = t["speaker"]
        speaker_stats.setdefault(sp, {"turns": 0, "chars": 0})
        speaker_stats[sp]["turns"] += 1
        speaker_stats[sp]["chars"] += len(t["text"])

    lines.append("STATS:")
    for sp, s in sorted(speaker_stats.items()):
        lines.append(f"  {sp}: {s['turns']} turns, {s['chars']} chars")
    lines.append(f"  Total turns: {len(merged)}")
    lines.append("=" * 80)

    return "\n".join(lines)


def run():
    sys.stdout.reconfigure(encoding="utf-8")

    if not AUDIO_PATH.exists():
        print(f"Audio file not found: {AUDIO_PATH}")
        return False

    print(f"Audio file: {AUDIO_PATH}")
    print(f"File size: {AUDIO_PATH.stat().st_size / 1024 / 1024:.1f} MB")
    print()

    wav_path = str(AUDIO_PATH).replace(".mp3", ".wav")
    if not Path(wav_path).exists():
        print("Converting MP3 to WAV...")
        if not convert_to_wav(str(AUDIO_PATH), wav_path):
            print("ERROR: ffmpeg conversion failed")
            return False
        print("Conversion done.")
    else:
        print("WAV already exists, skipping conversion.")
    print()

    segments = []
    method = "none"

    print("=== Trying Azure ConversationTranscriber ===")
    segments = transcribe_with_azure(wav_path)
    if segments:
        method = "azure"
    else:
        print("\n=== Azure unavailable, falling back to Whisper ===")
        segments = transcribe_with_whisper(str(AUDIO_PATH))
        if segments:
            method = "whisper"

    if not segments:
        print("ERROR: Both methods failed")
        return False

    print(f"\nUsed method: {method}")
    merged = merge_segments(segments)
    print(f"After merging: {len(merged)} turns\n")

    output = build_output(merged, method)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output)

    print(output)
    print(f"\nSaved to: {OUTPUT_PATH}")
    return True


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
