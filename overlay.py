"""Overlay UI: hai tầng hiển thị (Tier 1 tức thì + Tier 2 LLM) + speaker diarization + nhập text thủ công."""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QPushButton, QApplication,
    QLineEdit, QCheckBox, QScrollArea,
)
from PyQt6.QtCore import Qt, QPoint, QRect, QTimer, pyqtSlot, pyqtSignal
from PyQt6.QtGui import QFont, QShortcut, QKeySequence

SPEAKER_COLORS = {
    "me": "#f38ba8",
    "Speaker 1": "#89b4fa",
    "Speaker 2": "#fab387",
    "Speaker 3": "#a6e3a1",
    "Speaker 4": "#94e2d5",
    "Speaker 5": "#f9e2af",
}
DEFAULT_SPEAKER_COLOR = "#cba6f7"
_EDGE = 8


class OverlayWindow(QMainWindow):
    """Cửa sổ overlay trong suốt, luôn hiện trên cùng, resize bằng cạnh."""

    closed = pyqtSignal()
    minimize_requested = pyqtSignal()
    manual_answer_request = pyqtSignal(str, bool, bool)
    language_switch_request = pyqtSignal(str)

    MAX_HISTORY = 8

    def __init__(self):
        super().__init__()
        self._drag_pos = QPoint()
        self._current_speaker = ""
        self._recent_sentences: list[dict] = []
        self._current_language = "ja-JP"
        self._has_romaji = True
        self._resize_edge = 0
        self._resize_start_pos = QPoint()
        self._resize_start_geo: QRect | None = None
        self._setup_window()
        self._setup_ui()
        self._position_bottom_right()

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(400, 250)
        self.setMouseTracking(True)

    def _setup_ui(self):
        central = QWidget()
        central.setObjectName("central")
        central.setMouseTracking(True)
        central.setStyleSheet("""
            #central {
                background: rgba(20, 20, 25, 230);
                border-radius: 12px;
                border: 1px solid rgba(255, 255, 255, 30);
            }
        """)
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(4)

        # === Title bar (fixed) ===
        title_bar = QHBoxLayout()
        title_label = QLabel("JInterview")
        title_label.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        title_label.setStyleSheet("color: rgba(255,255,255,120);")
        title_bar.addWidget(title_label)
        title_bar.addStretch()

        self._status_label = QLabel("Đang khởi động...")
        self._status_label.setFont(QFont("Segoe UI", 8))
        self._status_label.setStyleSheet("color: rgba(255,255,255,60);")
        title_bar.addWidget(self._status_label)

        self._lang_btn = QPushButton("JP")
        self._lang_btn.setFixedSize(36, 24)
        self._lang_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._lang_btn.setStyleSheet("""
            QPushButton {
                background: rgba(137, 180, 250, 160); color: #1e1e2e;
                border: none; border-radius: 4px;
            }
            QPushButton:hover { background: rgba(137, 180, 250, 255); }
        """)
        self._lang_btn.setToolTip("F2: Chuyển ngôn ngữ (JP / EN)")
        self._lang_btn.clicked.connect(self._toggle_language)
        title_bar.addWidget(self._lang_btn)

        minimize_btn = QPushButton("–")
        minimize_btn.setFixedSize(24, 24)
        minimize_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: rgba(255,255,255,100);
                border: none; font-size: 16px; font-weight: bold;
            }
            QPushButton:hover { color: #89b4fa; }
        """)
        minimize_btn.clicked.connect(self._on_minimize)
        title_bar.addWidget(minimize_btn)

        close_btn = QPushButton("X")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: rgba(255,255,255,100);
                border: none; font-size: 13px; font-weight: bold;
            }
            QPushButton:hover { color: #ff6b6b; }
        """)
        close_btn.clicked.connect(self.close)
        title_bar.addWidget(close_btn)
        layout.addLayout(title_bar)

        # === Scrollable content area ===
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll_area.setMouseTracking(True)
        self._scroll_area.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical {
                background: rgba(30, 30, 40, 150); width: 6px; border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 40); border-radius: 3px; min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        scroll_content.setMouseTracking(True)
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setContentsMargins(0, 0, 6, 0)
        content_layout.setSpacing(4)

        self._history_label = QLabel("")
        self._history_label.setWordWrap(True)
        self._history_label.setTextFormat(Qt.TextFormat.RichText)
        self._history_label.setStyleSheet("color: #cdd6f4; background: transparent;")
        self._history_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        content_layout.addWidget(self._history_label)

        speaker_row = QHBoxLayout()
        self._speaker_indicator = QLabel("●")
        self._speaker_indicator.setFont(QFont("Segoe UI", 12))
        self._speaker_indicator.setStyleSheet("color: #89b4fa;")
        self._speaker_indicator.setFixedWidth(20)
        speaker_row.addWidget(self._speaker_indicator)

        self._source_label = QLabel("Chờ nhận giọng nói...")
        self._source_label.setFont(QFont("Segoe UI", 9))
        self._source_label.setStyleSheet("color: rgba(255,255,255,50);")
        speaker_row.addWidget(self._source_label)
        speaker_row.addStretch()
        content_layout.addLayout(speaker_row)

        self.transcript_label = QLabel("")
        self.transcript_label.setFont(QFont("Yu Gothic UI", 16))
        self.transcript_label.setStyleSheet("color: rgba(255,255,255,60);")
        self.transcript_label.setWordWrap(True)
        content_layout.addWidget(self.transcript_label)

        self.romaji_label = QLabel("")
        self.romaji_label.setFont(QFont("Segoe UI", 11))
        self.romaji_label.setStyleSheet("color: rgba(153,153,153,80);")
        self.romaji_label.setWordWrap(True)
        content_layout.addWidget(self.romaji_label)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet("color: rgba(255,255,255,40);")
        content_layout.addWidget(sep1)

        self.translation_label = QLabel("")
        self.translation_label.setFont(QFont("Segoe UI", 13))
        self.translation_label.setStyleSheet("color: rgba(255,255,255,40);")
        self.translation_label.setWordWrap(True)
        content_layout.addWidget(self.translation_label)

        # Answer section (inside scrollable area)
        self._answer_sep = QFrame()
        self._answer_sep.setFrameShape(QFrame.Shape.HLine)
        self._answer_sep.setStyleSheet("color: rgba(137, 180, 250, 40);")
        self._answer_sep.hide()
        content_layout.addWidget(self._answer_sep)

        self._answer_header = QLabel("Gợi ý trả lời:")
        self._answer_header.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._answer_header.setStyleSheet("color: rgba(137, 180, 250, 120);")
        self._answer_header.hide()
        content_layout.addWidget(self._answer_header)

        self._answer_romaji_label = QLabel("")
        self._answer_romaji_label.setFont(QFont("Segoe UI", 11))
        self._answer_romaji_label.setStyleSheet("color: rgba(203, 166, 247, 180);")
        self._answer_romaji_label.setWordWrap(True)
        self._answer_romaji_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._answer_romaji_label.hide()
        content_layout.addWidget(self._answer_romaji_label)

        self._answer_vi_label = QLabel("")
        self._answer_vi_label.setFont(QFont("Segoe UI", 12))
        self._answer_vi_label.setStyleSheet("color: #89b4fa;")
        self._answer_vi_label.setWordWrap(True)
        self._answer_vi_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._answer_vi_label.hide()
        content_layout.addWidget(self._answer_vi_label)

        content_layout.addStretch()
        self._scroll_area.setWidget(scroll_content)
        layout.addWidget(self._scroll_area, 1)

        # === Input row (fixed) ===
        input_row = QHBoxLayout()
        input_row.setSpacing(6)

        self._manual_input = QLineEdit()
        self._manual_input.setPlaceholderText("Nhập ý tưởng trả lời...")
        self._manual_input.setFont(QFont("Segoe UI", 11))
        self._manual_input.setStyleSheet("""
            QLineEdit {
                background: rgba(49, 50, 68, 200); color: #cdd6f4;
                border: 1px solid rgba(137, 180, 250, 80); border-radius: 6px;
                padding: 5px 10px;
            }
            QLineEdit:focus { border: 1px solid rgba(137, 180, 250, 180); }
        """)
        self._manual_input.returnPressed.connect(self._on_manual_submit)
        input_row.addWidget(self._manual_input, 1)

        self._manual_send_btn = QPushButton("Gửi")
        self._manual_send_btn.setFixedSize(50, 30)
        self._manual_send_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._manual_send_btn.setStyleSheet("""
            QPushButton {
                background: rgba(137, 180, 250, 200); color: #1e1e2e;
                border: none; border-radius: 6px;
            }
            QPushButton:hover { background: rgba(137, 180, 250, 255); }
        """)
        self._manual_send_btn.clicked.connect(self._on_manual_submit)
        input_row.addWidget(self._manual_send_btn)

        self._ai_refine_check = QCheckBox("AI")
        self._ai_refine_check.setChecked(True)
        self._ai_refine_check.setFont(QFont("Segoe UI", 9))
        self._ai_refine_check.setStyleSheet("color: rgba(203, 166, 247, 180); spacing: 4px;")
        self._ai_refine_check.setToolTip("Bật: AI chỉnh sửa cho hay hơn\nTắt: Dịch nguyên văn")
        input_row.addWidget(self._ai_refine_check)

        self._context_only_check = QCheckBox("Ngữ cảnh")
        self._context_only_check.setFont(QFont("Segoe UI", 9))
        self._context_only_check.setStyleSheet("color: rgba(249, 226, 175, 200); spacing: 4px;")
        self._context_only_check.setToolTip("Bật: chỉ bổ sung thông tin vào ngữ cảnh, không tạo câu trả lời")
        input_row.addWidget(self._context_only_check)

        layout.addLayout(input_row)

        # === Bottom bar ===
        bottom_bar = QHBoxLayout()
        shortcut_label = QLabel("F2: ngôn ngữ | F3: dừng | F4: nhập | Kéo cạnh để resize")
        shortcut_label.setFont(QFont("Segoe UI", 8))
        shortcut_label.setStyleSheet("color: rgba(255,255,255,25);")
        bottom_bar.addWidget(shortcut_label)
        bottom_bar.addStretch()
        layout.addLayout(bottom_bar)

        QShortcut(QKeySequence("F2"), self).activated.connect(self._toggle_language)
        QShortcut(QKeySequence("F3"), self).activated.connect(self.close)
        QShortcut(QKeySequence("F4"), self).activated.connect(self._focus_manual_input)

    # -- Edge-based resize --

    def _get_edge(self, pos: QPoint) -> int:
        r = self.rect()
        edge = 0
        if pos.x() <= _EDGE:
            edge |= 1
        if pos.x() >= r.width() - _EDGE:
            edge |= 2
        if pos.y() <= _EDGE:
            edge |= 4
        if pos.y() >= r.height() - _EDGE:
            edge |= 8
        return edge

    def _edge_cursor(self, edge: int):
        return {
            1: Qt.CursorShape.SizeHorCursor,
            2: Qt.CursorShape.SizeHorCursor,
            4: Qt.CursorShape.SizeVerCursor,
            8: Qt.CursorShape.SizeVerCursor,
            5: Qt.CursorShape.SizeFDiagCursor,
            10: Qt.CursorShape.SizeFDiagCursor,
            6: Qt.CursorShape.SizeBDiagCursor,
            9: Qt.CursorShape.SizeBDiagCursor,
        }.get(edge, Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._resize_edge = self._get_edge(event.pos())
            if self._resize_edge:
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geo = QRect(self.geometry())
            else:
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            if self._resize_edge and self._resize_start_geo:
                delta = event.globalPosition().toPoint() - self._resize_start_pos
                geo = QRect(self._resize_start_geo)
                if self._resize_edge & 1:
                    geo.setLeft(geo.left() + delta.x())
                if self._resize_edge & 2:
                    geo.setRight(geo.right() + delta.x())
                if self._resize_edge & 4:
                    geo.setTop(geo.top() + delta.y())
                if self._resize_edge & 8:
                    geo.setBottom(geo.bottom() + delta.y())
                if geo.width() >= self.minimumWidth() and geo.height() >= self.minimumHeight():
                    self.setGeometry(geo)
            else:
                self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        else:
            edge = self._get_edge(event.pos())
            self.setCursor(self._edge_cursor(edge))
            event.accept()

    def mouseReleaseEvent(self, event):
        self._resize_edge = 0
        self.setCursor(Qt.CursorShape.ArrowCursor)
        event.accept()

    # -- Settings --

    def apply_settings(self, settings: dict):
        font_size = settings.get("overlay_font_size", 16)
        opacity_pct = settings.get("overlay_opacity", 90)
        max_history = settings.get("overlay_max_history", 3)

        self.MAX_HISTORY = max_history
        self.transcript_label.setFont(QFont("Yu Gothic UI", font_size))

        opacity = opacity_pct / 100.0
        alpha = int(opacity * 255)
        central = self.centralWidget()
        if central:
            central.setStyleSheet(f"""
                #central {{
                    background: rgba(20, 20, 25, {alpha});
                    border-radius: 12px;
                    border: 1px solid rgba(255, 255, 255, 30);
                }}
            """)

        if len(self._recent_sentences) > self.MAX_HISTORY:
            self._recent_sentences = self._recent_sentences[-self.MAX_HISTORY:]
            self._render_history()

    def _toggle_language(self):
        if self._current_language == "ja-JP":
            new_lang = "en-US"
        else:
            new_lang = "ja-JP"
        self.language_switch_request.emit(new_lang)

    def set_language(self, lang_code: str):
        from settings import LANGUAGES
        self._current_language = lang_code
        lang_info = LANGUAGES.get(lang_code, LANGUAGES["ja-JP"])
        self._has_romaji = lang_info["has_romaji"]
        font_name = lang_info["font"]
        short = lang_info["short"].upper()

        self._lang_btn.setText(short)
        self.transcript_label.setFont(QFont(font_name, self.transcript_label.font().pointSize()))

        if self._has_romaji:
            self.romaji_label.show()
        else:
            self.romaji_label.hide()
            self.romaji_label.clear()

        self._render_history()

    def _position_bottom_right(self):
        self.resize(650, 480)
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.width() - 670, geo.height() - 500)

    def restore_position(self, x: int, y: int):
        if x >= 0 and y >= 0:
            screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                if 0 <= x <= geo.width() - 100 and 0 <= y <= geo.height() - 50:
                    self.move(x, y)
                    return
        self._position_bottom_right()

    def save_position(self) -> tuple[int, int]:
        pos = self.pos()
        return pos.x(), pos.y()

    # -- Speaker indicator --

    def _update_speaker_display(self, speaker_label: str):
        if speaker_label == self._current_speaker:
            return
        self._current_speaker = speaker_label
        color = SPEAKER_COLORS.get(speaker_label, DEFAULT_SPEAKER_COLOR)
        self._speaker_indicator.setStyleSheet(f"color: {color};")
        display_name = "Bạn" if speaker_label == "me" else speaker_label
        self._source_label.setText(f"{display_name} đang nói")
        self._source_label.setStyleSheet(f"color: {color};")

    # -- Manual input --

    def _focus_manual_input(self):
        self._manual_input.setFocus()

    def _on_manual_submit(self):
        text = self._manual_input.text().strip()
        if not text:
            return
        ai_refine = self._ai_refine_check.isChecked()
        context_only = self._context_only_check.isChecked()
        self._manual_input.clear()
        self._manual_input.setPlaceholderText("Đang xử lý...")
        self._manual_send_btn.setEnabled(False)
        self.manual_answer_request.emit(text, ai_refine, context_only)

    def on_manual_answer_done(self):
        self._manual_input.setPlaceholderText("Nhập ý tưởng trả lời...")
        self._manual_send_btn.setEnabled(True)

    @pyqtSlot(dict)
    def on_manual_answer(self, result: dict):
        self.on_manual_answer_done()
        answer_vi = result.get("answer_vi", "")
        answer_romaji = result.get("answer_romaji", "")
        if answer_vi or answer_romaji:
            self._answer_header.setText("Gợi ý trả lời [Thủ công]:")
            self._answer_header.setStyleSheet("color: rgba(250, 179, 135, 160);")
            self._show_answer(answer_romaji, answer_vi)

    # -- Tier 1: STT results --

    def on_interim(self, ja: str, romaji: str, speaker_label: str):
        self._update_speaker_display(speaker_label)
        self.transcript_label.setText(ja)
        self.transcript_label.setStyleSheet("color: rgba(255,255,255,120);")
        self.romaji_label.setText(romaji)
        self.romaji_label.setStyleSheet("color: rgba(153,153,153,80);")
        if speaker_label != "me":
            self._hide_answer()

    def on_final(self, ja: str, romaji: str, speaker_label: str):
        self._update_speaker_display(speaker_label)
        if ja.strip():
            existing_vi = self.translation_label.text()
            color = SPEAKER_COLORS.get(speaker_label, DEFAULT_SPEAKER_COLOR)
            self._recent_sentences.append({
                "ja": ja, "romaji": romaji, "vi": existing_vi,
                "speaker": speaker_label, "color": color,
            })
            if len(self._recent_sentences) > self.MAX_HISTORY:
                self._recent_sentences = self._recent_sentences[-self.MAX_HISTORY:]
            self._render_history()

        self.transcript_label.clear()
        self.romaji_label.clear()

    def on_translation(self, vi: str, speaker_label: str):
        self.translation_label.setText(vi)
        self.translation_label.setStyleSheet("color: rgba(144, 238, 144, 200);")
        if self._recent_sentences:
            self._recent_sentences[-1]["vi"] = vi
            self._render_history()

    # -- Tier 2: LLM --

    @pyqtSlot(dict)
    def on_tier2(self, result: dict):
        try:
            ja_fixed = result.get("ja_fixed", "")
            romaji = result.get("romaji", "")
            vi_refined = result.get("vi_refined", "")
            answer_vi = result.get("answer_vi", "")
            answer_romaji = result.get("answer_romaji", "")

            if self._recent_sentences:
                latest = self._recent_sentences[-1]
                if ja_fixed:
                    latest["ja"] = ja_fixed
                if romaji:
                    latest["romaji"] = romaji
                if vi_refined:
                    latest["vi"] = vi_refined
                latest["refined"] = True
                self._render_history()

            if answer_vi or answer_romaji:
                self._answer_header.setText("Gợi ý trả lời:")
                self._answer_header.setStyleSheet("color: rgba(137, 180, 250, 120);")
                self._show_answer(answer_romaji, answer_vi)
        except RuntimeError:
            pass

    @pyqtSlot(str, str)
    def on_tier2_partial(self, field: str, text: str):
        try:
            if not text:
                return
            if field == "vi_refined" and self._recent_sentences:
                self._recent_sentences[-1]["vi"] = text
                self._render_history()
            elif field == "answer_vi":
                self._answer_header.setText("Gợi ý trả lời:")
                self._answer_header.setStyleSheet("color: rgba(137, 180, 250, 120);")
                self._answer_vi_label.setText(text)
                self._show_answer_section()
            elif field == "answer_romaji":
                self._answer_romaji_label.setText(text)
                self._answer_romaji_label.show()
        except RuntimeError:
            pass

    @pyqtSlot(str, str)
    def on_answer_chunk(self, field: str, chunk: str):
        try:
            if not chunk:
                return
            if field == "answer_vi":
                self._show_answer_section()
                self._answer_header.setText("Gợi ý trả lời:")
                self._answer_header.setStyleSheet("color: rgba(137, 180, 250, 120);")
                current = self._answer_vi_label.text()
                self._answer_vi_label.setText(current + chunk)
                self._scroll_to_bottom()
            elif field == "answer_romaji":
                self._show_answer_section()
                current = self._answer_romaji_label.text()
                self._answer_romaji_label.setText(current + chunk)
                self._answer_romaji_label.show()
                self._scroll_to_bottom()
        except RuntimeError:
            pass

    # -- History rendering --

    def _render_history(self):
        if not self._recent_sentences:
            self._history_label.clear()
            return

        html_parts = []
        total = len(self._recent_sentences)
        for i, s in enumerate(self._recent_sentences):
            is_latest = (i == total - 1)
            is_refined = s.get("refined", False)
            speaker = s.get("speaker", "")
            sp_color = s.get("color", "#89b4fa")

            if is_latest:
                ja_size, ja_opacity = 16, "1.0"
                vi_size, vi_opacity = 13, "1.0"
                romaji_opacity = "0.7"
                ja_color = "#ffffff"
                vi_color = "#a6e3a1" if is_refined else "#90EE90"
            else:
                ja_size, ja_opacity = 13, "0.45"
                vi_size, vi_opacity = 11, "0.45"
                romaji_opacity = "0.3"
                ja_color = "#cdd6f4"
                vi_color = "#a6e3a1"

            sp_name = "Bạn" if speaker == "me" else speaker
            speaker_html = (
                f'<span style="font-size: 9px; color: {sp_color}; '
                f'opacity: {ja_opacity}; font-weight: bold;">[{sp_name}]</span> '
            )

            ja_text = s.get("ja", "")
            romaji_text = s.get("romaji", "")
            vi_text = s.get("vi", "")

            from settings import LANGUAGES
            lang_info = LANGUAGES.get(self._current_language, LANGUAGES["ja-JP"])
            src_font = lang_info["font"]

            romaji_html = ""
            if self._has_romaji and romaji_text:
                romaji_html = (
                    f'<span style="font-family: Segoe UI; font-size: 10px; '
                    f'color: #999; opacity: {romaji_opacity};">{romaji_text}</span><br>'
                )

            html_parts.append(
                f'<div style="margin-bottom: 6px;">'
                f'{speaker_html}'
                f'<span style="font-family: {src_font}; font-size: {ja_size}px; '
                f'color: {ja_color}; opacity: {ja_opacity};">{ja_text}</span><br>'
                f'{romaji_html}'
                f'<span style="font-family: Segoe UI; font-size: {vi_size}px; '
                f'color: {vi_color}; opacity: {vi_opacity};">{vi_text}</span>'
                f'</div>'
            )

        self._history_label.setText("".join(html_parts))
        QTimer.singleShot(10, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        vbar = self._scroll_area.verticalScrollBar()
        vbar.setValue(vbar.maximum())

    # -- Answer display --

    def _show_answer(self, primary: str, secondary_vi: str):
        self._answer_sep.show()
        self._answer_header.show()
        if primary:
            self._answer_romaji_label.setText(primary)
            self._answer_romaji_label.show()
        else:
            self._answer_romaji_label.hide()
            self._answer_romaji_label.clear()
        if secondary_vi:
            self._answer_vi_label.setText(secondary_vi)
            self._answer_vi_label.show()
        self._scroll_to_bottom()

    def _show_answer_section(self):
        self._answer_sep.show()
        self._answer_header.show()
        self._answer_vi_label.show()

    def _hide_answer(self):
        self._answer_sep.hide()
        self._answer_header.hide()
        self._answer_vi_label.hide()
        self._answer_vi_label.clear()
        self._answer_romaji_label.hide()
        self._answer_romaji_label.clear()

    def _on_minimize(self):
        self.hide()
        self.minimize_requested.emit()

    # -- Status --

    @pyqtSlot(str)
    def on_status(self, text: str):
        self._status_label.setText(text)
        self._status_label.setStyleSheet("color: rgba(255,255,255,60);")

    @pyqtSlot(str)
    def on_error(self, text: str):
        self._status_label.setText(f"[!] {text}")
        self._status_label.setStyleSheet("color: #ff6b6b;")

    def closeEvent(self, event):
        self.closed.emit()
        event.accept()
