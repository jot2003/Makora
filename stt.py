"""Streaming STT with speaker diarization + instant translation + language switching.

Architecture:
  - ConversationTranscriber on loopback: STT + automatic speaker_id (Guest-1, Guest-2...)
  - SpeechRecognizer on mic: STT for user's own speech (always tagged "me")
  - TranslationRecognizer on loopback (shadow): instant source->VI using Speech SDK
  - Optional: Azure Translator REST API (if separate key provided)
  - switch_language(): stop recognizers, create new ones with different language, start again
  - Timer-based near-final: fires ~0.7s after last interim for early LLM trigger
"""

import sys
import threading
import time
import requests
import azure.cognitiveservices.speech as speechsdk
import pykakasi
from PyQt6.QtCore import QObject, pyqtSignal

_NEAR_FINAL_DEBOUNCE = 0.3
_NEAR_FINAL_MIN_LEN = 6
_SENTENCE_ENDERS = frozenset("。？！?!.")


class StreamingSTT(QObject):
    """Dual-recognizer STT with speaker diarization, translation, and runtime language switching."""

    interim_result = pyqtSignal(str, str, str)       # (text, romaji, speaker_id)
    final_result = pyqtSignal(str, str, str)          # (text, romaji, speaker_id)
    near_final_result = pyqtSignal(str, str, str)    # (text, romaji, speaker_id) - early trigger
    translation_ready = pyqtSignal(str, str)          # (vi, speaker_id)
    status_update = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    AUDIO_FORMAT = speechsdk.audio.AudioStreamFormat(
        samples_per_second=16000,
        bits_per_sample=16,
        channels=1,
    )

    def __init__(
        self,
        speech_key: str,
        speech_region: str,
        source_language: str = "ja-JP",
        translator_key: str = "",
        translator_region: str = "",
    ):
        super().__init__()
        self._kakasi = pykakasi.kakasi()
        self._kakasi_lock = threading.Lock()
        self._speech_key = speech_key
        self._speech_region = speech_region
        self._source_language = source_language

        self._translator_key = translator_key
        self._translator_region = translator_region or speech_region
        self._rest_translator_ok = bool(translator_key)

        self._last_translate_time = 0.0
        self._translate_debounce = 0.15
        self._latest_speaker_for_translation: dict[str, str] = {}

        self._nf_text = ""
        self._nf_speaker = ""
        self._nf_time = 0.0
        self._nf_fired = False
        self._nf_lock = threading.Lock()
        self._nf_timer: threading.Timer | None = None

        self._create_recognizers(source_language)

    @property
    def source_language(self) -> str:
        return self._source_language

    def _create_recognizers(self, language: str):
        """Create all recognizers for the given language. Sets push_stream_* attributes."""
        self._source_language = language

        # --- Loopback: ConversationTranscriber (speaker diarization) ---
        self.push_stream_lb = speechsdk.audio.PushAudioInputStream(stream_format=self.AUDIO_FORMAT)
        audio_config_lb = speechsdk.audio.AudioConfig(stream=self.push_stream_lb)

        speech_config_lb = speechsdk.SpeechConfig(
            subscription=self._speech_key,
            region=self._speech_region,
        )
        speech_config_lb.speech_recognition_language = language
        speech_config_lb.set_profanity(speechsdk.ProfanityOption.Raw)
        try:
            speech_config_lb.set_property(
                speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, "800"
            )
        except Exception:
            pass

        self._transcriber = speechsdk.transcription.ConversationTranscriber(
            speech_config=speech_config_lb,
            audio_config=audio_config_lb,
        )
        self._transcriber.transcribing.connect(self._on_lb_transcribing)
        self._transcriber.transcribed.connect(self._on_lb_transcribed)
        self._transcriber.canceled.connect(self._on_canceled)
        self._transcriber.session_started.connect(self._on_session_started)

        # --- Shadow TranslationRecognizer on loopback for instant translation ---
        self.push_stream_lb_shadow = speechsdk.audio.PushAudioInputStream(stream_format=self.AUDIO_FORMAT)
        audio_config_shadow = speechsdk.audio.AudioConfig(stream=self.push_stream_lb_shadow)

        trans_config = speechsdk.translation.SpeechTranslationConfig(
            subscription=self._speech_key,
            region=self._speech_region,
        )
        trans_config.speech_recognition_language = language
        trans_config.add_target_language("vi")
        trans_config.set_profanity(speechsdk.ProfanityOption.Raw)
        try:
            trans_config.set_property(
                speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, "800"
            )
        except Exception:
            pass

        self._shadow_translator = speechsdk.translation.TranslationRecognizer(
            translation_config=trans_config,
            audio_config=audio_config_shadow,
        )
        self._shadow_translator.recognizing.connect(self._on_shadow_translating)
        self._shadow_translator.recognized.connect(self._on_shadow_translated)
        self._shadow_translator.canceled.connect(self._on_canceled)

        # --- Mic: SpeechRecognizer (user's speech, always "me") ---
        self.push_stream_mic = speechsdk.audio.PushAudioInputStream(stream_format=self.AUDIO_FORMAT)
        audio_config_mic = speechsdk.audio.AudioConfig(stream=self.push_stream_mic)

        speech_config_mic = speechsdk.SpeechConfig(
            subscription=self._speech_key,
            region=self._speech_region,
        )
        speech_config_mic.speech_recognition_language = language
        speech_config_mic.set_profanity(speechsdk.ProfanityOption.Raw)

        self._mic_recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config_mic,
            audio_config=audio_config_mic,
        )
        self._mic_recognizer.recognizing.connect(self._on_mic_recognizing)
        self._mic_recognizer.recognized.connect(self._on_mic_recognized)
        self._mic_recognizer.canceled.connect(self._on_canceled)

    def switch_language(self, new_language: str):
        if new_language == self._source_language:
            return
        print(f"  [STT] Switching language: {self._source_language} -> {new_language}")
        self.stop()
        self._create_recognizers(new_language)
        self.start()
        self.status_update.emit(f"Đang nghe ({new_language})...")
        print(f"  [STT] Language switched to {new_language}")
        sys.stdout.flush()

    def set_phrase_list(self, phrases: list[str]):
        if not phrases:
            return
        try:
            pl_lb = speechsdk.PhraseListGrammar.from_recognizer(self._transcriber)
            for p in phrases:
                pl_lb.addPhrase(p)
        except Exception:
            pass
        try:
            pl_mic = speechsdk.PhraseListGrammar.from_recognizer(self._mic_recognizer)
            for p in phrases:
                pl_mic.addPhrase(p)
        except Exception:
            pass

    def start(self):
        self._transcriber.start_transcribing_async()
        self._shadow_translator.start_continuous_recognition_async()
        self._mic_recognizer.start_continuous_recognition_async()

    def stop(self):
        self._cancel_nf_timer()
        for obj in (self._transcriber, self._shadow_translator, self._mic_recognizer):
            try:
                if hasattr(obj, "stop_transcribing_async"):
                    obj.stop_transcribing_async()
                else:
                    obj.stop_continuous_recognition_async()
            except Exception:
                pass

    # -- Timer-based near-final --

    def _schedule_nf_check(self):
        self._cancel_nf_timer()
        self._nf_timer = threading.Timer(_NEAR_FINAL_DEBOUNCE, self._nf_timeout)
        self._nf_timer.daemon = True
        self._nf_timer.start()

    def _cancel_nf_timer(self):
        if self._nf_timer:
            self._nf_timer.cancel()
            self._nf_timer = None

    def _nf_timeout(self):
        with self._nf_lock:
            if self._nf_fired or not self._nf_text:
                return
            if len(self._nf_text) < _NEAR_FINAL_MIN_LEN:
                return
            self._nf_fired = True
            text = self._nf_text
            speaker = self._nf_speaker

        romaji = self._to_romaji(text)
        try:
            self.near_final_result.emit(text, romaji, speaker)
            print(f"  [NEAR-FINAL] [{speaker}] {text}")
            sys.stdout.flush()
        except Exception:
            pass

    # -- Loopback callbacks (ConversationTranscriber) --

    def _on_lb_transcribing(self, evt):
        try:
            text = evt.result.text
            if not text.strip():
                return
            speaker_id = getattr(evt.result, "speaker_id", "Unknown")
            romaji = self._to_romaji(text)
            self.interim_result.emit(text, romaji, speaker_id)
            self._latest_speaker_for_translation["lb"] = speaker_id
            print(f"  [LB LIVE] [{speaker_id}] {text}")
            sys.stdout.flush()

            ends_with_punctuation = text.rstrip()[-1:] in _SENTENCE_ENDERS if text.strip() else False

            with self._nf_lock:
                self._nf_text = text
                self._nf_speaker = speaker_id
                self._nf_time = time.time()
                self._nf_fired = False

            if ends_with_punctuation and len(text) >= _NEAR_FINAL_MIN_LEN:
                self._nf_timeout()
            else:
                self._schedule_nf_check()
        except Exception as e:
            print(f"  [LB LIVE ERR] {e}", file=sys.stderr)

    def _on_lb_transcribed(self, evt):
        try:
            reason = evt.result.reason
            if reason == speechsdk.ResultReason.RecognizedSpeech:
                text = evt.result.text
                if not text.strip():
                    return
                speaker_id = getattr(evt.result, "speaker_id", "Unknown")
                romaji = self._to_romaji(text)
                self._cancel_nf_timer()
                with self._nf_lock:
                    self._nf_text = ""
                    self._nf_fired = False
                self.final_result.emit(text, romaji, speaker_id)
                self._latest_speaker_for_translation["lb"] = speaker_id
                if self._rest_translator_ok:
                    self._rest_translate_async(text, speaker_id, is_interim=False)
                print(f"  [LB FINAL] [{speaker_id}] {text}")
                sys.stdout.flush()
        except Exception as e:
            print(f"  [LB FINAL ERR] {e}", file=sys.stderr)

    # -- Shadow TranslationRecognizer callbacks (instant translation) --

    def _on_shadow_translating(self, evt):
        try:
            translations = evt.result.translations
            vi = translations.get("vi", "")
            if vi:
                speaker_id = self._latest_speaker_for_translation.get("lb", "Unknown")
                self.translation_ready.emit(vi, speaker_id)
        except Exception as e:
            print(f"  [SHADOW LIVE ERR] {e}", file=sys.stderr)

    def _on_shadow_translated(self, evt):
        try:
            if evt.result.reason == speechsdk.ResultReason.TranslatedSpeech:
                translations = evt.result.translations
                vi = translations.get("vi", "")
                if vi:
                    speaker_id = self._latest_speaker_for_translation.get("lb", "Unknown")
                    self.translation_ready.emit(vi, speaker_id)
        except Exception as e:
            print(f"  [SHADOW FINAL ERR] {e}", file=sys.stderr)

    # -- Mic callbacks (SpeechRecognizer) --

    def _on_mic_recognizing(self, evt):
        try:
            text = evt.result.text
            if not text.strip():
                return
            romaji = self._to_romaji(text)
            self.interim_result.emit(text, romaji, "me")
            if self._rest_translator_ok:
                self._rest_translate_async(text, "me", is_interim=True)
            print(f"  [MIC LIVE] {text}")
            sys.stdout.flush()
        except Exception as e:
            print(f"  [MIC LIVE ERR] {e}", file=sys.stderr)

    def _on_mic_recognized(self, evt):
        try:
            if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
                text = evt.result.text
                if not text.strip():
                    return
                romaji = self._to_romaji(text)
                self.final_result.emit(text, romaji, "me")
                if self._rest_translator_ok:
                    self._rest_translate_async(text, "me", is_interim=False)
                print(f"  [MIC FINAL] {text}")
                sys.stdout.flush()
        except Exception as e:
            print(f"  [MIC FINAL ERR] {e}", file=sys.stderr)

    # -- Shared callbacks --

    def _on_canceled(self, evt):
        if evt.reason == speechsdk.CancellationReason.Error:
            details = getattr(evt, "error_details", str(evt.reason))
            self.error_occurred.emit(f"STT: {str(details)[:80]}")
            print(f"  [STT ERROR] {details}", file=sys.stderr)
            sys.stderr.flush()

    def _on_session_started(self, evt):
        lang = self._source_language
        self.status_update.emit(f"Đang nghe ({lang})...")
        print(f"  [STT] Transcriber session started ({lang})")
        sys.stdout.flush()

    # -- REST Translator (optional) --

    def _rest_translate_async(self, text: str, speaker_id: str, is_interim: bool):
        if not self._rest_translator_ok:
            return
        now = time.time()
        if is_interim and (now - self._last_translate_time) < self._translate_debounce:
            return
        self._last_translate_time = now
        t = threading.Thread(
            target=self._do_rest_translate,
            args=(text, speaker_id),
            daemon=True,
        )
        t.start()

    def _do_rest_translate(self, text: str, speaker_id: str):
        try:
            lang_short = self._source_language.split("-")[0]
            url = "https://api.cognitive.microsofttranslator.com/translate"
            params = {"api-version": "3.0", "from": lang_short, "to": "vi"}
            headers = {
                "Ocp-Apim-Subscription-Key": self._translator_key,
                "Ocp-Apim-Subscription-Region": self._translator_region,
                "Content-Type": "application/json",
            }
            body = [{"text": text}]
            resp = requests.post(url, params=params, headers=headers, json=body, timeout=3)

            if resp.status_code in (401, 403):
                if self._rest_translator_ok:
                    self._rest_translator_ok = False
                    print("  [REST TRANSLATOR] Key invalid, disabled.", file=sys.stderr)
                return

            resp.raise_for_status()
            data = resp.json()
            vi = data[0]["translations"][0]["text"]
            self.translation_ready.emit(vi, speaker_id)
        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            print(f"  [REST TRANSLATE ERR] {e}", file=sys.stderr)

    # -- Romaji (Japanese only) --

    def _to_romaji(self, text: str) -> str:
        if not self._source_language.startswith("ja"):
            return ""
        try:
            with self._kakasi_lock:
                result = self._kakasi.convert(text)
            return " ".join(item["hepburn"] for item in result if item["hepburn"])
        except Exception:
            return ""
