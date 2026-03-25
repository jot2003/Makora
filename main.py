"""JInterview v2 - Trợ lý phỏng vấn tiếng Nhật.

Luồng hoạt động:
  MainWindow (quản lý phiên) -> Bấm "Bắt đầu"
    -> Overlay + DualAudioCapture + StreamingSTT khởi chạy
    -> MainWindow vẫn hiện, hiển thị live transcript
  Bấm "Dừng" (overlay / tray / MainWindow)
    -> Dừng Audio/STT, đóng overlay
  Tự động phát hiện người nói:
    -> Loopback -> ConversationTranscriber (speaker diarization)
    -> Mic -> SpeechRecognizer (luôn là "me")
"""

import json
import os
import sys
import time

os.environ["QT_OPENGL"] = "software"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _global_exception_hook(exc_type, exc_value, exc_tb):
    import traceback
    print("=" * 60, file=sys.stderr)
    print("[UNHANDLED EXCEPTION]", file=sys.stderr)
    traceback.print_exception(exc_type, exc_value, exc_tb, file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    sys.stderr.flush()


sys.excepthook = _global_exception_hook

from dotenv import load_dotenv
from PyQt6.QtWidgets import QApplication

from session import SessionManager, Session
from main_window import MainWindow
from overlay import OverlayWindow
from audio import DualAudioCapture
from stt import StreamingSTT
from llm import LLMEngine
from documents import extract_keywords, get_all_text_from_session, get_text_by_category
from settings import load_settings, LANGUAGES

from datetime import datetime


class App:
    """Bộ điều khiển kết nối MainWindow, Overlay, Audio, STT."""

    def __init__(self):
        load_dotenv()
        self._app_settings = load_settings()

        self._speech_key = os.getenv("AZURE_SPEECH_KEY", "") or self._app_settings.get("azure_speech_key", "")
        self._speech_region = os.getenv("AZURE_SPEECH_REGION", "") or self._app_settings.get("azure_speech_region", "")

        self._session_mgr = SessionManager()
        self._qapp = QApplication(sys.argv)

        if not self._speech_key or not self._speech_region:
            self._prompt_speech_keys()

        self._main_window = MainWindow(self._session_mgr)
        self._main_window.start_interview.connect(self._on_start)
        self._main_window.stop_interview.connect(self._on_stop)
        self._main_window.settings_changed.connect(self._on_settings_changed)
        self._main_window.show()

        self._openai_key = os.getenv("AZURE_OPENAI_KEY", "") or self._app_settings.get("azure_openai_key", "")
        self._openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "") or self._app_settings.get("azure_openai_endpoint", "")
        self._openai_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "") or self._app_settings.get("azure_openai_deployment", "")
        self._openai_fast_deployment = self._app_settings.get("azure_openai_fast_deployment", "")

        self._overlay: OverlayWindow | None = None
        self._stt: StreamingSTT | None = None
        self._audio: DualAudioCapture | None = None
        self._llm: LLMEngine | None = None
        self._active_session: Session | None = None

        self._speaker_map: dict[str, str] = {}
        self._current_language = self._app_settings.get("interview_language", "ja-JP")
        self._near_final_ts = 0.0

    def _prompt_speech_keys(self):
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout
        dialog = QDialog()
        dialog.setWindowTitle("JInterview - Cấu hình Azure Speech")
        dialog.setMinimumWidth(450)
        dialog.setStyleSheet("background: #1e1e2e; color: #cdd6f4;")

        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Chưa có Azure Speech API key.\nVui lòng nhập để tiếp tục:"))

        key_input = QLineEdit(self._speech_key)
        key_input.setPlaceholderText("Azure Speech Key")
        key_input.setEchoMode(QLineEdit.EchoMode.Password)
        key_input.setStyleSheet("background: #181825; border: 1px solid #45475a; border-radius: 4px; padding: 6px;")
        layout.addWidget(QLabel("Speech Key:"))
        layout.addWidget(key_input)

        region_input = QLineEdit(self._speech_region)
        region_input.setPlaceholderText("eastus, japaneast...")
        region_input.setStyleSheet("background: #181825; border: 1px solid #45475a; border-radius: 4px; padding: 6px;")
        layout.addWidget(QLabel("Speech Region:"))
        layout.addWidget(region_input)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("Lưu và tiếp tục")
        ok_btn.setStyleSheet("background: #a6e3a1; color: #1e1e2e; font-weight: bold; border-radius: 6px; padding: 8px 16px;")
        ok_btn.clicked.connect(dialog.accept)
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            print("Người dùng hủy. Thoát ứng dụng.")
            sys.exit(0)

        self._speech_key = key_input.text().strip()
        self._speech_region = region_input.text().strip()

        if not self._speech_key or not self._speech_region:
            print("LỖI: Thiếu Azure Speech Key hoặc Region.")
            sys.exit(1)

        self._app_settings["azure_speech_key"] = self._speech_key
        self._app_settings["azure_speech_region"] = self._speech_region
        from settings import save_settings
        save_settings(self._app_settings)

    def run(self) -> int:
        return self._qapp.exec()

    def _map_speaker(self, speaker_id: str) -> str:
        """Map Azure speaker_id to a readable label."""
        if speaker_id == "me":
            return "me"
        if speaker_id in self._speaker_map:
            return self._speaker_map[speaker_id]
        idx = len(self._speaker_map) + 1
        label = f"Speaker {idx}"
        self._speaker_map[speaker_id] = label
        print(f"  [SPEAKER MAP] {speaker_id} -> {label}")
        return label

    def _on_start(self, session: Session):
        self._active_session = session
        self._speaker_map = {}
        self._current_language = self._app_settings.get("interview_language", "ja-JP")
        print(f"[BẮT ĐẦU] Phỏng vấn: {session.name} ({session.id}) [{self._current_language}]")

        translator_key = self._app_settings.get("azure_translator_key", "")
        translator_region = self._app_settings.get("azure_translator_region", "") or self._speech_region

        self._stt = StreamingSTT(
            self._speech_key,
            self._speech_region,
            source_language=self._current_language,
            translator_key=translator_key,
            translator_region=translator_region,
        )

        phrases = self._collect_phrases(session)
        if phrases:
            self._stt.set_phrase_list(phrases)
            print(f"  Danh sách từ khóa: {len(phrases)} từ")

        energy_threshold = self._app_settings.get("energy_threshold", 200)
        self._audio = DualAudioCapture(
            self._stt.push_stream_lb,
            self._stt.push_stream_mic,
            push_stream_lb_shadow=self._stt.push_stream_lb_shadow,
            energy_threshold=energy_threshold,
        )
        self._overlay = OverlayWindow()
        self._overlay.apply_settings(self._app_settings)
        w = self._app_settings.get("overlay_width", -1)
        h = self._app_settings.get("overlay_height", -1)
        if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
            self._overlay.resize(w, h)
        self._overlay.restore_position(
            self._app_settings.get("overlay_x", -1),
            self._app_settings.get("overlay_y", -1),
        )

        self._overlay.set_language(self._current_language)
        self._overlay.language_switch_request.connect(self._on_language_switch)

        lang_info = LANGUAGES.get(self._current_language, LANGUAGES["ja-JP"])

        # LLM Tier 2
        if self._openai_key and self._openai_endpoint and self._openai_deployment:
            self._llm = LLMEngine(
                self._openai_key, self._openai_endpoint, self._openai_deployment,
                fast_deployment=self._openai_fast_deployment,
            )
            doc_meta = self._session_mgr.load_doc_meta(session)
            notes = {
                "personal": self._session_mgr.load_notes(session, "personal"),
                "company": self._session_mgr.load_notes(session, "company"),
                "general": self._session_mgr.load_notes(session, "general"),
            }
            texts = get_text_by_category(session.documents_dir, doc_meta, notes=notes)
            glossary = self._session_mgr.load_glossary(session)
            self._llm.set_language(lang_info["name"], lang_info["has_romaji"])
            self._llm.set_context(texts["personal"], texts["company"], glossary,
                                  general_context=texts.get("general", ""))
            recent = self._session_mgr.get_recent_context(session)
            self._llm.set_recent_transcript(recent)
            self._llm.tier2_result.connect(self._overlay.on_tier2)
            self._llm.answer_streaming.connect(self._overlay.on_answer_chunk)
            self._llm.tier2_result.connect(self._update_transcript_tier2)
            self._llm.tier2_result.connect(self._main_window.on_live_tier2)
            self._llm.manual_answer_result.connect(self._overlay.on_manual_answer)
            self._llm.manual_answer_result.connect(self._main_window.on_manual_answer)
            self._llm.manual_answer_result.connect(self._save_manual_answer)
            self._llm.error_occurred.connect(self._overlay.on_error)
            fast = self._openai_fast_deployment
            if fast and fast != self._openai_deployment:
                print(f"  LLM Tier 2 đã bật (fast: {fast}, main: {self._openai_deployment})")
            else:
                print(f"  LLM Tier 2 đã bật (model: {self._openai_deployment})")
        else:
            self._llm = None
            print("  LLM Tier 2 tắt (thiếu Azure OpenAI keys)")

        # STT signals (new signatures with speaker_id)
        self._stt.interim_result.connect(self._on_interim)
        self._stt.final_result.connect(self._on_final)
        self._stt.near_final_result.connect(self._on_near_final)
        self._stt.translation_ready.connect(self._on_translation)
        self._stt.status_update.connect(self._overlay.on_status)
        self._stt.error_occurred.connect(self._overlay.on_error)

        # Audio signals
        self._audio.status_update.connect(self._overlay.on_status)
        self._audio.error_occurred.connect(self._overlay.on_error)

        # Overlay signals
        self._overlay.manual_answer_request.connect(self._on_manual_answer)
        self._overlay.minimize_requested.connect(self._on_overlay_minimized)
        self._overlay.closed.connect(self._on_overlay_closed)

        self._main_window.manual_answer_request.connect(self._on_manual_answer)
        self._main_window.show_overlay_requested.connect(self._on_show_overlay)

        self._overlay.show()
        self._overlay.on_status("Đang khởi động...")

        self._stt.start()
        self._audio.start()
        if self._llm:
            self._llm.start()
        print("[OK] Đã bắt đầu thu âm.")

    # -- STT event handlers --

    def _on_interim(self, ja: str, romaji: str, speaker_id: str):
        if not self._overlay:
            return
        try:
            label = self._map_speaker(speaker_id)
            self._overlay.on_interim(ja, romaji, label)
        except RuntimeError:
            pass

    def _on_final(self, ja: str, romaji: str, speaker_id: str):
        try:
            label = self._map_speaker(speaker_id)
            if self._overlay:
                self._overlay.on_final(ja, romaji, label)
            self._save_transcript(ja, romaji, label, speaker_id)
            if label != "me" and time.time() - self._near_final_ts < 2.0:
                self._near_final_ts = 0.0
            else:
                self._enqueue_llm(ja, romaji, label)
            self._main_window.on_live_final(ja, romaji, "")
        except RuntimeError:
            pass

    def _on_near_final(self, ja: str, romaji: str, speaker_id: str):
        """Early trigger for LLM using near-final interim from loopback."""
        try:
            label = self._map_speaker(speaker_id)
            if label != "me":
                self._near_final_ts = time.time()
                self._enqueue_llm(ja, romaji, label)
        except RuntimeError:
            pass

    def _on_translation(self, vi: str, speaker_id: str):
        try:
            label = self._map_speaker(speaker_id)
            if self._overlay:
                self._overlay.on_translation(vi, label)
            self._save_translation_to_transcript(vi)
            self._main_window.on_live_translation(vi, label)
        except RuntimeError:
            pass

    # -- Transcript & LLM --

    def _save_transcript(self, ja: str, romaji: str, label: str, raw_speaker_id: str):
        if not self._active_session:
            return
        entry = {
            "time": datetime.now().isoformat(),
            "speaker": label,
            "speaker_id": raw_speaker_id,
            "language": self._current_language,
            "ja": ja,
            "romaji": romaji,
            "vi_azure": "",
            "vi_llm": "",
            "answer_vi": "",
            "answer_ja": "",
            "answer_romaji": "",
        }
        self._session_mgr.append_transcript(self._active_session, entry)

    def _save_translation_to_transcript(self, vi: str):
        if not self._active_session or not vi:
            return
        entries = self._session_mgr.load_transcript(self._active_session)
        if not entries:
            return
        last = entries[-1]
        if not last.get("vi_azure"):
            last["vi_azure"] = vi
            lines = [json.dumps(e, ensure_ascii=False) for e in entries]
            self._active_session.transcript_path.write_text(
                "\n".join(lines) + "\n", encoding="utf-8"
            )
            self._main_window.on_live_final("", "", "")

    def _enqueue_llm(self, ja: str, romaji: str, label: str):
        if not self._llm:
            return
        if label != "me":
            self._llm.enqueue(ja, romaji, "")
            print(f"  [ENQUEUE LLM] tier2 for [{label}]")
        else:
            self._llm.add_user_speech(ja, "")

    def _update_transcript_tier2(self, result: dict):
        try:
            if not self._active_session:
                return
            entries = self._session_mgr.load_transcript(self._active_session)
            if not entries:
                return
            last = entries[-1]
            if last.get("speaker") == "me":
                return
            last["ja"] = result.get("ja_fixed", last.get("ja", ""))
            last["romaji"] = result.get("romaji", last.get("romaji", ""))
            last["vi_llm"] = result.get("vi_refined", "")
            last["answer_vi"] = result.get("answer_vi", "")
            last["answer_ja"] = result.get("answer_ja", "")
            last["answer_romaji"] = result.get("answer_romaji", "")

            lines = []
            for e in entries:
                lines.append(json.dumps(e, ensure_ascii=False))
            self._active_session.transcript_path.write_text(
                "\n".join(lines) + "\n", encoding="utf-8"
            )
            self._main_window.on_live_final("", "", "")
        except Exception as e:
            print(f"  [TIER2 SAVE ERR] {e}", file=sys.stderr)

    # -- Settings --

    def _on_settings_changed(self, settings: dict):
        self._app_settings = settings
        self._openai_key = settings.get("azure_openai_key", "") or self._openai_key
        self._openai_endpoint = settings.get("azure_openai_endpoint", "") or self._openai_endpoint
        self._openai_deployment = settings.get("azure_openai_deployment", "") or self._openai_deployment
        self._openai_fast_deployment = settings.get("azure_openai_fast_deployment", "")
        if self._overlay:
            self._overlay.apply_settings(settings)
        if self._audio:
            self._audio.set_energy_threshold(settings.get("energy_threshold", 200))

    # -- Manual answer --

    def _on_manual_answer(self, text: str, ai_refine: bool, context_only: bool):
        if context_only and self._active_session:
            # Bổ sung nhanh vào ngữ cảnh (ghi vào ghi chú cá nhân và reload context cho LLM)
            personal = self._session_mgr.load_notes(self._active_session, "personal")
            new_text = (personal + "\n" + text).strip() if personal else text
            self._session_mgr.save_notes(self._active_session, "personal", new_text)

            doc_meta = self._session_mgr.load_doc_meta(self._active_session)
            notes = {
                "personal": new_text,
                "company": self._session_mgr.load_notes(self._active_session, "company"),
                "general": self._session_mgr.load_notes(self._active_session, "general"),
            }
            texts = get_text_by_category(self._active_session.documents_dir, doc_meta, notes=notes)
            glossary = self._session_mgr.load_glossary(self._active_session)
            if self._llm:
                self._llm.set_context(texts["personal"], texts["company"], glossary,
                                      general_context=texts.get("general", ""))
            if self._overlay:
                self._overlay.on_status("Đã bổ sung vào ngữ cảnh.")
                self._overlay.on_manual_answer_done()
            self._main_window._manual_send_btn_mw.setEnabled(True)
            self._main_window._manual_send_btn_mw.setText("Gửi cho AI xử lý")
            return

        if not self._llm:
            if self._overlay:
                self._overlay.on_error("LLM chưa sẵn sàng (thiếu API key)")
                self._overlay.on_manual_answer_done()
            self._main_window._manual_send_btn_mw.setEnabled(True)
            self._main_window._manual_send_btn_mw.setText("Gửi cho AI xử lý")
            return
        self._llm.enqueue_manual(text, ai_refine)
        print(f"  [THỦ CÔNG] Đã gửi: '{text[:40]}...' (AI={'có' if ai_refine else 'không'})")

    def _save_manual_answer(self, result: dict):
        if not self._active_session:
            return
        entry = {
            "time": datetime.now().isoformat(),
            "speaker": "me_draft",
            "speaker_id": "me",
            "language": self._current_language,
            "ja": result.get("answer_ja", ""),
            "romaji": result.get("answer_romaji", ""),
            "vi_azure": result.get("original_text", ""),
            "vi_llm": result.get("answer_vi", ""),
            "answer_vi": result.get("answer_vi", ""),
            "answer_ja": result.get("answer_ja", ""),
            "answer_romaji": result.get("answer_romaji", ""),
        }
        self._session_mgr.append_transcript(self._active_session, entry)
        if self._llm:
            self._llm.add_user_speech(
                result.get("answer_ja", ""),
                result.get("answer_vi", ""),
            )

    # -- Language switching --

    def _on_language_switch(self, new_lang: str):
        """Handle language switch request from overlay."""
        if new_lang == self._current_language:
            return
        if not self._stt or not self._audio:
            return

        print(f"[CHUYỂN NGÔN NGỮ] {self._current_language} -> {new_lang}")
        self._current_language = new_lang
        lang_info = LANGUAGES.get(new_lang, LANGUAGES["ja-JP"])

        self._stt.switch_language(new_lang)

        self._audio.update_streams(
            self._stt.push_stream_lb,
            self._stt.push_stream_mic,
            self._stt.push_stream_lb_shadow,
        )

        if self._active_session:
            phrases = self._collect_phrases(self._active_session, new_lang)
            if phrases:
                self._stt.set_phrase_list(phrases)

        if self._llm:
            self._llm.set_language(lang_info["name"], lang_info["has_romaji"])

        self._overlay.set_language(new_lang)
        self._main_window.set_language(new_lang)

        print(f"[OK] Đã chuyển sang {lang_info['name']}")
        sys.stdout.flush()

    # -- Stop / Cleanup --

    def _on_overlay_minimized(self):
        # Overlay đã hide, phỏng vấn vẫn tiếp tục.
        if self._overlay:
            print("[OVERLAY] Minimized (hidden).")

    def _on_show_overlay(self):
        if self._overlay:
            self._overlay.show()
            self._overlay.raise_()

    def _on_stop(self):
        print("[DỪNG] Kết thúc phỏng vấn...")
        self._cleanup_interview()

    def _on_overlay_closed(self):
        self._main_window._on_stop_interview()

    def _collect_phrases(self, session: Session, language: str = "") -> list[str]:
        lang = language or self._current_language
        phrases = set()

        glossary = self._session_mgr.load_glossary(session)
        for entry in glossary:
            jp = entry.get("jp", "").strip()
            if jp:
                phrases.add(jp)

        doc_text = get_all_text_from_session(session.documents_dir)
        if doc_text:
            keywords = extract_keywords(doc_text, max_keywords=150, language=lang)
            phrases.update(keywords)

        return list(phrases)[:200]

    def _cleanup_interview(self):
        if self._audio:
            self._audio.stop()
            self._audio.wait(3000)
            self._audio = None

        if self._stt:
            self._stt.stop()
            self._stt = None

        if self._llm:
            self._llm.stop()
            self._llm.wait(3000)
            self._llm = None

        try:
            self._main_window.manual_answer_request.disconnect(self._on_manual_answer)
        except (TypeError, RuntimeError):
            pass

        if self._overlay:
            x, y = self._overlay.save_position()
            self._app_settings["overlay_x"] = x
            self._app_settings["overlay_y"] = y
            # lưu luôn kích thước overlay hiện tại
            size = self._overlay.size()
            self._app_settings["overlay_width"] = size.width()
            self._app_settings["overlay_height"] = size.height()
            from settings import save_settings
            save_settings(self._app_settings)

            try:
                self._overlay.closed.disconnect(self._on_overlay_closed)
            except (TypeError, RuntimeError):
                pass
            self._overlay.close()
            self._overlay = None

        if self._active_session:
            transcript = self._session_mgr.load_transcript(self._active_session)
            print(f"[OK] Phiên kết thúc. {len(transcript)} câu đã ghi.")
            self._active_session = None

        self._speaker_map = {}


def main():
    app = App()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
