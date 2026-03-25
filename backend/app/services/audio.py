"""Dual audio capture: loopback + mic with echo gate.

Ported from PyQt6 to plain threading for FastAPI backend.
No PyQt dependencies. Communicates via callbacks.
"""

import queue
import threading
import time
from typing import Callable

import numpy as np
from scipy.signal import resample_poly

TARGET_SAMPLE_RATE = 16000

ECHO_ENERGY_RATIO = 0.35
ECHO_WINDOW_MS = 80


class DualAudioCapture:
    """Captures audio from loopback and mic simultaneously.

    Pushes to separate PushAudioInputStream instances:
      - push_stream_lb: loopback audio (for ConversationTranscriber + shadow translator)
      - push_stream_mic: mic audio (for SpeechRecognizer)

    Echo gate: when loopback energy is much higher than mic, suppress mic push
    to reduce cross-talk on laptop speakers.
    """

    def __init__(
        self,
        push_stream_lb,
        push_stream_mic,
        push_stream_lb_shadow=None,
        energy_threshold: int = 200,
        on_status: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_mic_active: Callable[[bool], None] | None = None,
        on_lb_audio: Callable[[bytes], None] | None = None,
        echo_gate_enabled: bool = True,
    ):
        self._push_stream_lb = push_stream_lb
        self._push_stream_mic = push_stream_mic
        self._push_stream_lb_shadow = push_stream_lb_shadow
        self._stream_lock = threading.Lock()
        self._energy_threshold = energy_threshold
        self._running = False
        self._mic_was_active = False

        self._on_status = on_status or (lambda _: None)
        self._on_error = on_error or (lambda _: None)
        self._on_mic_active = on_mic_active or (lambda _: None)
        self._on_lb_audio = on_lb_audio or (lambda _: None)

        self._echo_gate_enabled = echo_gate_enabled
        self._lb_rms_recent = 0.0
        self._thread: threading.Thread | None = None

    def update_streams(self, push_stream_lb, push_stream_mic, push_stream_lb_shadow=None):
        with self._stream_lock:
            self._push_stream_lb = push_stream_lb
            self._push_stream_mic = push_stream_mic
            self._push_stream_lb_shadow = push_stream_lb_shadow

    def set_energy_threshold(self, threshold: int):
        self._energy_threshold = max(50, threshold)

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="audio-capture")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    def _run(self):
        import pyaudiowpatch as pyaudio
        pa = pyaudio.PyAudio()

        lb_info = self._find_loopback_device(pa)
        mic_info = self._find_mic_device(pa)

        if lb_info is None:
            self._on_error("No WASAPI loopback device found")
            pa.terminate()
            return

        lb_rate = int(lb_info["defaultSampleRate"])
        lb_channels = lb_info["maxInputChannels"]

        mic_available = mic_info is not None
        mic_rate = int(mic_info["defaultSampleRate"]) if mic_available else 0
        mic_channels = min(mic_info["maxInputChannels"], 2) if mic_available else 0

        try:
            lb_stream = pa.open(
                format=pyaudio.paInt16, channels=lb_channels, rate=lb_rate,
                input=True, input_device_index=lb_info["index"], frames_per_buffer=1024,
            )
        except Exception as e:
            self._on_error(f"Failed to open loopback: {e}")
            pa.terminate()
            return

        mic_stream = None
        if mic_available:
            try:
                mic_stream = pa.open(
                    format=pyaudio.paInt16, channels=mic_channels, rate=mic_rate,
                    input=True, input_device_index=mic_info["index"], frames_per_buffer=1024,
                )
            except Exception as e:
                self._on_error(f"Mic warning: {e}")
                mic_available = False

        status_parts = [f"Loopback ({lb_rate}Hz)"]
        if mic_available:
            mic_name = mic_info.get("name", "Mic")[:20]
            status_parts.append(f"Mic: {mic_name}")
        self._on_status("Audio: " + " + ".join(status_parts))

        lb_q: queue.Queue = queue.Queue(maxsize=30)
        mic_q: queue.Queue = queue.Queue(maxsize=30)

        lb_thread = threading.Thread(target=self._reader_loop, args=(lb_stream, lb_q), daemon=True)
        lb_thread.start()

        mic_thread = None
        if mic_available and mic_stream:
            mic_thread = threading.Thread(target=self._reader_loop, args=(mic_stream, mic_q), daemon=True)
            mic_thread.start()

        while self._running:
            lb_chunk = self._get_latest(lb_q)
            mic_chunk = self._get_latest(mic_q) if mic_available else None

            if lb_chunk is None and mic_chunk is None:
                time.sleep(0.005)
                continue

            if lb_chunk:
                lb_pcm = self._convert_to_pcm16(lb_chunk, lb_rate, lb_channels)
                if lb_pcm:
                    self._lb_rms_recent = self._rms(lb_pcm)
                    with self._stream_lock:
                        self._push_stream_lb.write(lb_pcm)
                        if self._push_stream_lb_shadow:
                            self._push_stream_lb_shadow.write(lb_pcm)
                    self._on_lb_audio(lb_pcm)

            if mic_chunk:
                mic_pcm = self._convert_to_pcm16(mic_chunk, mic_rate, mic_channels)
                if mic_pcm:
                    mic_rms = self._rms(mic_pcm)

                    if self._echo_gate_enabled and self._lb_rms_recent > 300:
                        if mic_rms < self._lb_rms_recent * ECHO_ENERGY_RATIO:
                            continue

                    with self._stream_lock:
                        self._push_stream_mic.write(mic_pcm)
                    active = mic_rms > self._energy_threshold
                    if active != self._mic_was_active:
                        self._mic_was_active = active
                        self._on_mic_active(active)

        for s in (lb_stream, mic_stream):
            if s:
                try:
                    s.stop_stream()
                    s.close()
                except Exception:
                    pass
        pa.terminate()
        with self._stream_lock:
            self._push_stream_lb.close()
            if self._push_stream_lb_shadow:
                self._push_stream_lb_shadow.close()
            self._push_stream_mic.close()

    def _reader_loop(self, stream, q: queue.Queue):
        while self._running:
            try:
                raw = stream.read(1024, exception_on_overflow=False)
                try:
                    q.put_nowait(raw)
                except queue.Full:
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        pass
                    q.put_nowait(raw)
            except Exception:
                if not self._running:
                    break
                time.sleep(0.01)

    @staticmethod
    def _get_latest(q: queue.Queue) -> bytes | None:
        latest = None
        while True:
            try:
                latest = q.get_nowait()
            except queue.Empty:
                break
        return latest

    @staticmethod
    def _rms(pcm_bytes: bytes) -> float:
        if not pcm_bytes:
            return 0.0
        audio = np.frombuffer(pcm_bytes, dtype=np.int16)
        if len(audio) == 0:
            return 0.0
        return float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))

    def _find_loopback_device(self, pa):
        import pyaudiowpatch as pyaudio
        try:
            wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_output = pa.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
        except Exception:
            return None

        for i in range(pa.get_device_count()):
            dev = pa.get_device_info_by_index(i)
            if dev.get("isLoopbackDevice") and dev["name"].startswith(
                default_output["name"].split(" (")[0]
            ):
                return dev

        for i in range(pa.get_device_count()):
            dev = pa.get_device_info_by_index(i)
            if dev.get("isLoopbackDevice"):
                return dev
        return None

    def _find_mic_device(self, pa):
        try:
            default_input = pa.get_default_input_device_info()
            if default_input and default_input.get("maxInputChannels", 0) >= 1:
                return default_input
        except Exception:
            pass
        return None

    @staticmethod
    def _convert_to_pcm16(raw_bytes, device_rate, device_channels):
        if not raw_bytes:
            return b""
        audio = np.frombuffer(raw_bytes, dtype=np.int16).copy()
        if len(audio) == 0:
            return b""

        if device_channels >= 2:
            audio = audio.reshape(-1, device_channels).mean(axis=1)

        if device_rate != TARGET_SAMPLE_RATE:
            audio = audio.astype(np.float32)
            if device_rate == 48000:
                audio = resample_poly(audio, 1, 3)
            elif device_rate == 44100:
                audio = resample_poly(audio, 160, 441)
            else:
                new_len = int(len(audio) * TARGET_SAMPLE_RATE / device_rate)
                from scipy.signal import resample
                audio = resample(audio, new_len)
            audio = np.clip(audio, -32768, 32767)

        return audio.astype(np.int16).tobytes()
