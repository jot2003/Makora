"""Real-time speaker diarization using pyannote speaker embeddings.

Architecture:
  - Receives 16kHz mono PCM audio chunks from DualAudioCapture
  - Buffers audio in a rolling window
  - On demand, computes speaker embedding for the most recent speech
  - Matches against known speaker profiles via cosine similarity
  - Returns stable speaker labels ("Interviewer 1", "Speaker 2", etc.)
"""

import sys
import threading
import time
from typing import Optional

import numpy as np

_PYANNOTE_AVAILABLE = False
_load_lock = threading.Lock()
_cached_inference = None

SAMPLE_RATE = 16000


def _get_inference(device: str = "cuda"):
    """Lazy-load the pyannote embedding model (heavy, ~5-10s first call)."""
    global _PYANNOTE_AVAILABLE, _cached_inference
    with _load_lock:
        if _cached_inference is not None:
            return _cached_inference
        try:
            import os
            import torch
            from pyannote.audio import Inference

            hf_token = os.getenv("HF_TOKEN", "")
            if hf_token:
                os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token
                try:
                    from huggingface_hub import login
                    login(token=hf_token, add_to_git_credential=False)
                except Exception:
                    pass

            from pyannote.audio import Model

            actual_device = device if torch.cuda.is_available() else "cpu"
            model = Model.from_pretrained("pyannote/embedding")
            _cached_inference = Inference(
                model,
                window="whole",
                device=torch.device(actual_device),
            )
            _PYANNOTE_AVAILABLE = True
            print(f"  [DIARIZER] Model loaded on {actual_device}", file=sys.stderr)
            return _cached_inference
        except Exception as e:
            print(f"  [DIARIZER] Failed to load model: {e}", file=sys.stderr)
            _PYANNOTE_AVAILABLE = False
            return None


class SpeakerDiarizer:
    """Online speaker identification via pyannote speaker embeddings."""

    def __init__(
        self,
        mode: str = "interview",
        max_speakers: int = 0,
        similarity_threshold: float = 0.65,
        device: str = "cuda",
    ):
        self._mode = mode
        self._max_speakers = max_speakers or (2 if mode == "interview" else 5)
        self._threshold = similarity_threshold
        self._device = device

        self._profiles: dict[str, np.ndarray] = {}
        self._profile_counts: dict[str, int] = {}
        self._label_counter = 0

        self._buffer: list[np.ndarray] = []
        self._buffer_lock = threading.Lock()
        self._max_buffer_samples = SAMPLE_RATE * 30

        self._inference = None
        self._ready = False

        self._init_thread = threading.Thread(
            target=self._load_model, daemon=True, name="diarizer-init",
        )
        self._init_thread.start()

    def _load_model(self):
        inf = _get_inference(self._device)
        if inf is not None:
            self._inference = inf
            self._ready = True

    @property
    def ready(self) -> bool:
        return self._ready

    def set_max_speakers(self, n: int):
        if n >= 1:
            self._max_speakers = n

    def push_audio(self, pcm_bytes: bytes):
        """Push 16kHz mono int16 PCM audio to the rolling buffer."""
        if not pcm_bytes:
            return
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        with self._buffer_lock:
            self._buffer.append(audio)
            total = sum(len(a) for a in self._buffer)
            while total > self._max_buffer_samples and len(self._buffer) > 1:
                total -= len(self._buffer.pop(0))

    def identify_speaker(self, duration_s: float = 3.0) -> Optional[str]:
        """Identify the speaker from the most recent buffered audio.

        Returns a stable label like "Interviewer 1" or None if not ready.
        """
        if not self._ready or self._inference is None:
            return None

        with self._buffer_lock:
            if not self._buffer:
                return None
            audio = np.concatenate(self._buffer)

        min_samples = SAMPLE_RATE  # need >= 1 second
        if len(audio) < min_samples:
            return None

        n_samples = int(duration_s * SAMPLE_RATE)
        segment = audio[-n_samples:] if len(audio) > n_samples else audio

        rms = float(np.sqrt(np.mean(segment ** 2)))
        if rms < 0.005:
            return None

        try:
            import torch
            waveform = torch.from_numpy(segment).unsqueeze(0)
            embedding = self._inference(
                {"waveform": waveform, "sample_rate": SAMPLE_RATE}
            )
            if isinstance(embedding, np.ndarray):
                embedding = embedding.flatten()
            else:
                embedding = np.array(embedding).flatten()
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm
        except Exception as e:
            print(f"  [DIARIZER] Embedding error: {e}", file=sys.stderr)
            return None

        best_label = None
        best_sim = -1.0
        for label, profile in self._profiles.items():
            sim = float(np.dot(embedding, profile))
            if sim > best_sim:
                best_sim = sim
                best_label = label

        if best_label and best_sim >= self._threshold:
            count = self._profile_counts[best_label]
            self._profiles[best_label] = (
                self._profiles[best_label] * count + embedding
            ) / (count + 1)
            self._profiles[best_label] /= np.linalg.norm(self._profiles[best_label])
            self._profile_counts[best_label] = count + 1
            return best_label

        if len(self._profiles) < self._max_speakers:
            self._label_counter += 1
            prefix = "Interviewer" if self._mode == "interview" else "Speaker"
            label = f"{prefix} {self._label_counter}"
            self._profiles[label] = embedding
            self._profile_counts[label] = 1
            return label

        return best_label or None

    def reset(self):
        """Clear speaker profiles and audio buffer."""
        self._profiles.clear()
        self._profile_counts.clear()
        self._label_counter = 0
        with self._buffer_lock:
            self._buffer.clear()

    def stop(self):
        """Release resources."""
        self.reset()
