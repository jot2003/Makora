"""Cửa sổ chính: quản lý phiên, từ điển, lịch sử hội thoại, tray hệ thống."""

import sys
from datetime import datetime
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QStackedWidget,
    QTextEdit, QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QTabWidget, QMessageBox, QSplitter,
    QApplication, QSystemTrayIcon, QMenu, QFrame, QInputDialog,
    QFileDialog, QSlider, QCheckBox, QGroupBox,
    QFormLayout,
)
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QSize
from PyQt6.QtGui import QFont, QIcon, QAction, QColor

from session import SessionManager, Session
from documents import extract_text, extract_keywords, copy_to_session, get_all_text_from_session
from settings import load_settings, save_settings, LANGUAGES


class MainWindow(QMainWindow):
    """Cửa sổ chính quản lý phiên phỏng vấn."""

    start_interview = pyqtSignal(Session)
    stop_interview = pyqtSignal()
    manual_answer_request = pyqtSignal(str, bool, bool)  # (text, ai_refine, context_only)

    settings_changed = pyqtSignal(dict)
    show_overlay_requested = pyqtSignal()

    def __init__(self, session_mgr: SessionManager):
        super().__init__()
        self._session_mgr = session_mgr
        self._current_session: Session | None = None
        self._interview_active = False
        self._settings = load_settings()

        self._current_language = self._settings.get("interview_language", "ja-JP")
        self.setWindowTitle("JInterview - Trợ lý phỏng vấn")
        self.setMinimumSize(900, 600)
        self.resize(1050, 700)

        self._setup_tray()
        self._setup_ui()
        self._load_sessions()

    # ── Giao diện ─────────────────────────────────────────────

    def _setup_tray(self):
        self._tray = QSystemTrayIcon(self)
        self._tray.setToolTip("JInterview")

        tray_menu = QMenu()
        self._tray_open_action = QAction("Mở cửa sổ chính", self)
        self._tray_open_action.triggered.connect(self._restore_from_tray)
        tray_menu.addAction(self._tray_open_action)

        self._tray_stop_action = QAction("Dừng phỏng vấn", self)
        self._tray_stop_action.triggered.connect(self._on_stop_interview)
        self._tray_stop_action.setEnabled(False)
        tray_menu.addAction(self._tray_stop_action)

        tray_menu.addSeparator()
        quit_action = QAction("Thoát", self)
        quit_action.triggered.connect(QApplication.quit)
        tray_menu.addAction(quit_action)

        self._tray.setContextMenu(tray_menu)
        self._tray.activated.connect(self._on_tray_activated)

    def _setup_ui(self):
        self.setStyleSheet("""
            QMainWindow { background: #1e1e2e; }
            QLabel { color: #cdd6f4; }
            QPushButton {
                background: #313244; color: #cdd6f4; border: 1px solid #45475a;
                border-radius: 6px; padding: 8px 16px; font-size: 13px;
            }
            QPushButton:hover { background: #45475a; }
            QPushButton:disabled { background: #181825; color: #585b70; }
            QPushButton#startBtn { background: #a6e3a1; color: #1e1e2e; font-weight: bold; }
            QPushButton#startBtn:hover { background: #94e2d5; }
            QPushButton#stopBtn { background: #f38ba8; color: #1e1e2e; font-weight: bold; }
            QPushButton#stopBtn:hover { background: #eba0ac; }
            QListWidget {
                background: #181825; color: #cdd6f4; border: none;
                font-size: 13px; outline: none;
            }
            QListWidget::item { padding: 10px 12px; border-bottom: 1px solid #313244; min-height: 36px; }
            QListWidget::item:selected { background: #313244; color: #cdd6f4; }
            QListWidget::item:hover { background: #28283d; }
            QTextEdit {
                background: #181825; color: #cdd6f4; border: 1px solid #313244;
                border-radius: 6px; font-size: 13px; padding: 8px;
            }
            QLineEdit {
                background: #181825; color: #cdd6f4; border: 1px solid #45475a;
                border-radius: 6px; padding: 6px 10px; font-size: 13px;
            }
            QTableWidget {
                background: #181825; color: #cdd6f4; border: 1px solid #313244;
                border-radius: 6px; gridline-color: #313244;
            }
            QTableWidget::item { padding: 4px 8px; }
            QHeaderView::section {
                background: #313244; color: #cdd6f4; border: none;
                padding: 6px; font-weight: bold;
            }
            QTabWidget::pane { border: 1px solid #313244; border-radius: 6px; }
            QTabBar::tab {
                background: #181825; color: #a6adc8; padding: 8px 18px;
                border: 1px solid #313244; border-bottom: none;
                border-top-left-radius: 6px; border-top-right-radius: 6px;
            }
            QTabBar::tab:selected { background: #313244; color: #cdd6f4; }
        """)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # -- Sidebar trái --
        sidebar = QWidget()
        sidebar.setMinimumWidth(200)
        sidebar.setMaximumWidth(400)
        sidebar.setStyleSheet("background: #181825;")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 12, 12, 12)
        sidebar_layout.setSpacing(8)

        sidebar_title = QLabel("Phiên phỏng vấn")
        sidebar_title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        sidebar_layout.addWidget(sidebar_title)

        self._session_list = QListWidget()
        self._session_list.currentRowChanged.connect(self._on_session_selected)
        sidebar_layout.addWidget(self._session_list, 1)

        btn_row = QHBoxLayout()
        self._new_btn = QPushButton("+ Tạo mới")
        self._new_btn.clicked.connect(self._on_create_session)
        btn_row.addWidget(self._new_btn)

        self._delete_btn = QPushButton("Xóa")
        self._delete_btn.setStyleSheet(
            "QPushButton { background: #45475a; } QPushButton:hover { background: #f38ba8; color: #1e1e2e; }"
        )
        self._delete_btn.clicked.connect(self._on_delete_session)
        btn_row.addWidget(self._delete_btn)
        sidebar_layout.addLayout(btn_row)

        splitter.addWidget(sidebar)

        # -- Nội dung bên phải --
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 12, 16, 12)
        content_layout.setSpacing(10)

        self._content_stack = QStackedWidget()

        welcome = self._build_welcome_page()
        self._content_stack.addWidget(welcome)

        session_detail = self._build_session_detail_page()
        self._content_stack.addWidget(session_detail)

        content_layout.addWidget(self._content_stack, 1)

        # Thanh hành động
        action_bar = QHBoxLayout()
        action_bar.addStretch()

        self._start_btn = QPushButton("Bắt đầu phỏng vấn")
        self._start_btn.setObjectName("startBtn")
        self._start_btn.setFixedHeight(42)
        self._start_btn.setMinimumWidth(180)
        self._start_btn.clicked.connect(self._on_start_interview)
        self._start_btn.setEnabled(False)
        action_bar.addWidget(self._start_btn)

        self._stop_btn = QPushButton("Dừng phỏng vấn")
        self._stop_btn.setObjectName("stopBtn")
        self._stop_btn.setFixedHeight(42)
        self._stop_btn.setMinimumWidth(160)
        self._stop_btn.clicked.connect(self._on_stop_interview)
        self._stop_btn.hide()
        action_bar.addWidget(self._stop_btn)

        self._show_overlay_btn = QPushButton("Hiện overlay")
        self._show_overlay_btn.setFixedHeight(42)
        self._show_overlay_btn.setMinimumWidth(140)
        self._show_overlay_btn.clicked.connect(self._on_show_overlay)
        self._show_overlay_btn.hide()
        action_bar.addWidget(self._show_overlay_btn)

        content_layout.addLayout(action_bar)
        splitter.addWidget(content)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 790])

    def _build_welcome_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch()

        title = QLabel("JInterview")
        title.setFont(QFont("Segoe UI", 28, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #a6e3a1;")
        layout.addWidget(title)

        subtitle = QLabel("Trợ lý phỏng vấn đa ngôn ngữ thời gian thực")
        subtitle.setFont(QFont("Segoe UI", 14))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #a6adc8;")
        layout.addWidget(subtitle)

        layout.addSpacing(20)

        first_btn = QPushButton("Tạo phiên phỏng vấn đầu tiên")
        first_btn.setObjectName("startBtn")
        first_btn.setFixedSize(280, 44)
        first_btn.clicked.connect(self._on_create_session)
        layout.addWidget(first_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addStretch()
        return page

    def _build_session_detail_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        self._session_name_label = QLabel("")
        self._session_name_label.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        header.addWidget(self._session_name_label)

        self._rename_btn = QPushButton("Đổi tên")
        self._rename_btn.setFixedHeight(28)
        self._rename_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #89b4fa; border: 1px solid #45475a;"
            " border-radius: 4px; padding: 2px 10px; font-size: 11px; }"
            " QPushButton:hover { background: #313244; }"
        )
        self._rename_btn.clicked.connect(self._on_rename_session)
        header.addWidget(self._rename_btn)
        header.addStretch()

        self._session_status_label = QLabel("")
        self._session_status_label.setFont(QFont("Segoe UI", 11))
        header.addWidget(self._session_status_label)
        layout.addLayout(header)

        self._session_date_label = QLabel("")
        self._session_date_label.setStyleSheet("color: #585b70; font-size: 12px;")
        layout.addWidget(self._session_date_label)

        self._tabs = QTabWidget()

        # Tab 1: Lịch sử hội thoại
        transcript_container = QWidget()
        transcript_layout = QVBoxLayout(transcript_container)
        transcript_layout.setContentsMargins(0, 4, 0, 0)
        transcript_layout.setSpacing(4)

        search_row = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Tìm kiếm trong lịch sử...")
        self._search_input.setStyleSheet(
            "background: #181825; color: #cdd6f4; border: 1px solid #45475a;"
            " border-radius: 6px; padding: 6px 10px; font-size: 12px;"
        )
        self._search_input.textChanged.connect(self._on_search_transcript)
        search_row.addWidget(self._search_input, 1)

        self._search_count_label = QLabel("")
        self._search_count_label.setStyleSheet("color: #585b70; font-size: 11px; min-width: 80px;")
        search_row.addWidget(self._search_count_label)

        clear_search_btn = QPushButton("Xóa")
        clear_search_btn.setFixedSize(50, 28)
        clear_search_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #a6adc8; border: 1px solid #45475a;"
            " border-radius: 4px; font-size: 11px; }"
            " QPushButton:hover { background: #313244; }"
        )
        clear_search_btn.clicked.connect(lambda: self._search_input.clear())
        search_row.addWidget(clear_search_btn)

        export_btn = QPushButton("Xuất")
        export_btn.setFixedSize(50, 28)
        export_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #89b4fa; border: 1px solid #89b4fa;"
            " border-radius: 4px; font-size: 11px; }"
            " QPushButton:hover { background: #1e2a3a; }"
        )
        export_btn.clicked.connect(self._on_export_transcript)
        search_row.addWidget(export_btn)

        transcript_layout.addLayout(search_row)

        self._transcript_view = QTextEdit()
        self._transcript_view.setReadOnly(True)
        self._transcript_view.setFont(QFont("Segoe UI", 12))
        self._transcript_view.setStyleSheet(
            "QTextEdit { background: #11111b; border: none; padding: 8px; }"
        )
        transcript_layout.addWidget(self._transcript_view, 1)

        self._tabs.addTab(transcript_container, "Lịch sử hội thoại")

        # Tab 2: Từ điển
        glossary_widget = self._build_glossary_tab()
        self._tabs.addTab(glossary_widget, "Từ điển")

        # Tab 3: Tài liệu
        docs_widget = self._build_documents_tab()
        self._tabs.addTab(docs_widget, "Tài liệu")

        # Tab 4: Cài đặt
        settings_widget = self._build_settings_tab()
        self._tabs.addTab(settings_widget, "Cài đặt")

        layout.addWidget(self._tabs, 1)

        # Panel nhập text thủ công (chỉ hiện khi đang phỏng vấn)
        self._manual_panel = QFrame()
        self._manual_panel.setStyleSheet("""
            QFrame {
                background: #1e2a3a; border: 1px solid #89b4fa;
                border-radius: 8px; padding: 2px;
            }
        """)
        panel_layout = QVBoxLayout(self._manual_panel)
        panel_layout.setContentsMargins(10, 8, 10, 8)
        panel_layout.setSpacing(6)

        panel_header = QLabel("Nhập ý tưởng trả lời")
        panel_header.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        panel_header.setStyleSheet("color: #89b4fa; border: none; background: transparent;")
        panel_layout.addWidget(panel_header)

        self._manual_text_edit = QTextEdit()
        self._manual_text_edit.setPlaceholderText(
            "Nhập ý tưởng bằng tiếng Việt... AI sẽ tạo câu trả lời tiếng Nhật + romaji"
        )
        self._manual_text_edit.setMaximumHeight(80)
        self._manual_text_edit.setFont(QFont("Segoe UI", 12))
        self._manual_text_edit.setStyleSheet(
            "background: #181825; border: 1px solid #45475a; border-radius: 6px;"
        )
        panel_layout.addWidget(self._manual_text_edit)

        manual_btn_row = QHBoxLayout()
        self._manual_ai_check = QCheckBox("AI chỉnh sửa")
        self._manual_ai_check.setChecked(True)
        self._manual_ai_check.setStyleSheet(
            "color: #cba6f7; font-size: 12px; spacing: 4px; border: none; background: transparent;"
        )
        manual_btn_row.addWidget(self._manual_ai_check)

        self._manual_context_check = QCheckBox("Chỉ bổ sung ngữ cảnh")
        self._manual_context_check.setStyleSheet(
            "color: #f9e2af; font-size: 12px; spacing: 4px; border: none; background: transparent;"
        )
        manual_btn_row.addWidget(self._manual_context_check)
        manual_btn_row.addStretch()

        self._manual_send_btn_mw = QPushButton("Gửi cho AI xử lý")
        self._manual_send_btn_mw.setStyleSheet("""
            QPushButton {
                background: #89b4fa; color: #1e1e2e; font-weight: bold;
                border: none; border-radius: 6px; padding: 8px 20px; font-size: 13px;
            }
            QPushButton:hover { background: #b4d0fb; }
            QPushButton:disabled { background: #45475a; color: #585b70; }
        """)
        self._manual_send_btn_mw.clicked.connect(self._on_manual_submit_mw)
        manual_btn_row.addWidget(self._manual_send_btn_mw)
        panel_layout.addLayout(manual_btn_row)

        # Vùng hiện kết quả thủ công
        self._manual_result_frame = QFrame()
        self._manual_result_frame.setStyleSheet(
            "background: #28283d; border: 1px solid #45475a; border-radius: 6px; padding: 4px;"
        )
        result_layout = QVBoxLayout(self._manual_result_frame)
        result_layout.setContentsMargins(8, 6, 8, 6)
        result_layout.setSpacing(2)

        self._manual_result_vi = QLabel("")
        self._manual_result_vi.setWordWrap(True)
        self._manual_result_vi.setFont(QFont("Segoe UI", 12))
        self._manual_result_vi.setStyleSheet("color: #89b4fa; border: none; background: transparent;")
        result_layout.addWidget(self._manual_result_vi)

        self._manual_result_ja = QLabel("")
        self._manual_result_ja.setWordWrap(True)
        self._manual_result_ja.setFont(QFont("Yu Gothic UI", 13))
        self._manual_result_ja.setStyleSheet("color: #cba6f7; border: none; background: transparent;")
        result_layout.addWidget(self._manual_result_ja)

        self._manual_result_romaji = QLabel("")
        self._manual_result_romaji.setWordWrap(True)
        self._manual_result_romaji.setFont(QFont("Segoe UI", 11))
        self._manual_result_romaji.setStyleSheet("color: #7f849c; border: none; background: transparent;")
        result_layout.addWidget(self._manual_result_romaji)

        self._manual_result_frame.hide()
        panel_layout.addWidget(self._manual_result_frame)

        self._manual_panel.hide()
        layout.addWidget(self._manual_panel)

        return page

    def _build_glossary_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 4, 0, 0)

        add_row = QHBoxLayout()
        self._glossary_jp_input = QLineEdit()
        self._glossary_jp_input.setPlaceholderText("Tiếng Nhật (JP)")
        add_row.addWidget(self._glossary_jp_input)

        self._glossary_reading_input = QLineEdit()
        self._glossary_reading_input.setPlaceholderText("Cách đọc (Romaji)")
        add_row.addWidget(self._glossary_reading_input)

        self._glossary_vi_input = QLineEdit()
        self._glossary_vi_input.setPlaceholderText("Tiếng Việt (VI)")
        add_row.addWidget(self._glossary_vi_input)

        add_btn = QPushButton("Thêm")
        add_btn.clicked.connect(self._on_add_glossary)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

        self._glossary_table = QTableWidget(0, 4)
        self._glossary_table.setHorizontalHeaderLabels(["Tiếng Nhật", "Cách đọc", "Tiếng Việt", ""])
        self._glossary_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._glossary_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._glossary_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self._glossary_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self._glossary_table.verticalHeader().setVisible(False)
        self._glossary_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        layout.addWidget(self._glossary_table, 1)

        return widget

    def _build_documents_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 4, 0, 0)

        # -- Ghi chú thủ công --
        notes_label = QLabel("Ghi chú thủ công (được đưa vào ngữ cảnh cho AI)")
        notes_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        notes_label.setStyleSheet("color: #cdd6f4;")
        layout.addWidget(notes_label)

        notes_row = QHBoxLayout()
        notes_row.setSpacing(8)

        personal_notes_box = QVBoxLayout()
        pn_label = QLabel("Thông tin cá nhân")
        pn_label.setStyleSheet("color: #a6e3a1; font-size: 12px; font-weight: bold;")
        personal_notes_box.addWidget(pn_label)

        self._notes_personal = QTextEdit()
        self._notes_personal.setPlaceholderText(
            "Nhập thông tin cá nhân: tên, kỹ năng, kinh nghiệm, dự án, học vấn..."
        )
        self._notes_personal.setMinimumHeight(80)
        self._notes_personal.setMaximumHeight(160)
        self._notes_personal.setFont(QFont("Segoe UI", 11))
        self._notes_personal.setStyleSheet(
            "background: #1e3a2e; border: 1px solid #a6e3a1; border-radius: 6px; padding: 6px;"
        )
        personal_notes_box.addWidget(self._notes_personal)

        save_personal_btn = QPushButton("Lưu ghi chú")
        save_personal_btn.setFixedHeight(28)
        save_personal_btn.setStyleSheet(
            "QPushButton { background: #a6e3a1; color: #1e1e2e; border: none;"
            " border-radius: 4px; font-weight: bold; font-size: 11px; padding: 0 12px; }"
            " QPushButton:hover { background: #b8f0c0; }"
        )
        save_personal_btn.clicked.connect(lambda: self._on_save_notes("personal"))
        personal_notes_box.addWidget(save_personal_btn)
        notes_row.addLayout(personal_notes_box, 1)

        company_notes_box = QVBoxLayout()
        cn_label = QLabel("Công ty / Vị trí ứng tuyển")
        cn_label.setStyleSheet("color: #89b4fa; font-size: 12px; font-weight: bold;")
        company_notes_box.addWidget(cn_label)

        self._notes_company = QTextEdit()
        self._notes_company.setPlaceholderText(
            "Nhập thông tin công ty, vị trí, yêu cầu JD, lý do ứng tuyển..."
        )
        self._notes_company.setMinimumHeight(80)
        self._notes_company.setMaximumHeight(160)
        self._notes_company.setFont(QFont("Segoe UI", 11))
        self._notes_company.setStyleSheet(
            "background: #1e2a3a; border: 1px solid #89b4fa; border-radius: 6px; padding: 6px;"
        )
        company_notes_box.addWidget(self._notes_company)

        save_company_btn = QPushButton("Lưu ghi chú")
        save_company_btn.setFixedHeight(28)
        save_company_btn.setStyleSheet(
            "QPushButton { background: #89b4fa; color: #1e1e2e; border: none;"
            " border-radius: 4px; font-weight: bold; font-size: 11px; padding: 0 12px; }"
            " QPushButton:hover { background: #a0c8ff; }"
        )
        save_company_btn.clicked.connect(lambda: self._on_save_notes("company"))
        company_notes_box.addWidget(save_company_btn)
        notes_row.addLayout(company_notes_box, 1)

        self._notes_saved_label = QLabel("")
        self._notes_saved_label.setStyleSheet("color: #a6e3a1; font-size: 11px;")
        self._notes_saved_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        layout.addLayout(notes_row)
        layout.addWidget(self._notes_saved_label)

        # -- Ngữ cảnh chung --
        general_label = QLabel("Ngữ cảnh chung")
        general_label.setStyleSheet("color: #f9e2af; font-size: 12px; font-weight: bold; margin-top: 4px;")
        layout.addWidget(general_label)

        self._notes_general = QTextEdit()
        self._notes_general.setPlaceholderText(
            "Nhập ngữ cảnh chung: lĩnh vực, công nghệ, phong cách phỏng vấn, ghi chú bổ sung..."
        )
        self._notes_general.setMinimumHeight(60)
        self._notes_general.setMaximumHeight(120)
        self._notes_general.setFont(QFont("Segoe UI", 11))
        self._notes_general.setStyleSheet(
            "background: #2a2a1e; border: 1px solid #f9e2af; border-radius: 6px; padding: 6px;"
        )
        layout.addWidget(self._notes_general)

        save_general_btn = QPushButton("Lưu ngữ cảnh chung")
        save_general_btn.setFixedHeight(28)
        save_general_btn.setStyleSheet(
            "QPushButton { background: #f9e2af; color: #1e1e2e; border: none;"
            " border-radius: 4px; font-weight: bold; font-size: 11px; padding: 0 12px; }"
            " QPushButton:hover { background: #fbefc0; }"
        )
        save_general_btn.clicked.connect(lambda: self._on_save_notes("general"))
        layout.addWidget(save_general_btn)

        # -- Upload tài liệu --
        upload_label = QLabel("Upload tài liệu")
        upload_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        upload_label.setStyleSheet("color: #cdd6f4; margin-top: 6px;")
        layout.addWidget(upload_label)

        btn_row = QHBoxLayout()
        personal_btn = QPushButton("+ Thông tin cá nhân (CV, kỹ năng...)")
        personal_btn.setStyleSheet(
            "QPushButton { background: #1e3a2e; border: 1px solid #a6e3a1; } "
            "QPushButton:hover { background: #2a4a3a; }"
        )
        personal_btn.clicked.connect(lambda: self._on_upload_document("personal"))
        btn_row.addWidget(personal_btn)

        company_btn = QPushButton("+ Công ty / Vị trí ứng tuyển (JD...)")
        company_btn.setStyleSheet(
            "QPushButton { background: #1e2a3a; border: 1px solid #89b4fa; } "
            "QPushButton:hover { background: #2a3a4a; }"
        )
        company_btn.clicked.connect(lambda: self._on_upload_document("company"))
        btn_row.addWidget(company_btn)
        layout.addLayout(btn_row)

        self._docs_list = QListWidget()
        self._docs_list.setMinimumHeight(100)
        self._docs_list.setStyleSheet(
            "QListWidget { background: #181825; border: 1px solid #313244; border-radius: 6px; }"
            " QListWidget::item { padding: 4px 0px; border-bottom: 1px solid #313244; }"
            " QListWidget::item:selected { background: #313244; }"
        )
        layout.addWidget(self._docs_list)

        preview_label = QLabel("Xem trước nội dung:")
        preview_label.setStyleSheet("color: #585b70; font-size: 12px; margin-top: 4px;")
        layout.addWidget(preview_label)

        self._doc_preview = QTextEdit()
        self._doc_preview.setReadOnly(True)
        self._doc_preview.setMaximumHeight(120)
        self._doc_preview.setFont(QFont("Segoe UI", 11))
        layout.addWidget(self._doc_preview)

        self._docs_keywords_label = QLabel("")
        self._docs_keywords_label.setWordWrap(True)
        self._docs_keywords_label.setStyleSheet("color: #89b4fa; font-size: 11px;")
        layout.addWidget(self._docs_keywords_label)

        return widget

    def _build_settings_tab(self) -> QWidget:
        from PyQt6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        GROUPBOX_STYLE = """
            QGroupBox { color: #cdd6f4; border: 1px solid #45475a; border-radius: 8px; padding: 16px; margin-top: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
        """
        INPUT_STYLE = (
            "QLineEdit { background: #181825; color: #cdd6f4; border: 1px solid #45475a;"
            " border-radius: 4px; padding: 6px 8px; min-height: 24px; font-size: 12px; }"
        )
        SLIDER_LABEL_STYLE = "color: #89b4fa; font-size: 13px; font-weight: bold; min-width: 50px;"

        # -- Overlay --
        overlay_group = QGroupBox("Overlay")
        overlay_group.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        overlay_group.setStyleSheet(GROUPBOX_STYLE)
        overlay_form = QFormLayout()
        overlay_form.setSpacing(10)

        self._setting_font_size = QSlider(Qt.Orientation.Horizontal)
        self._setting_font_size.setRange(10, 30)
        self._setting_font_size.setValue(self._settings.get("overlay_font_size", 16))
        self._setting_font_size.setTickInterval(2)
        self._font_size_label = QLabel(f"{self._setting_font_size.value()} px")
        self._font_size_label.setStyleSheet(SLIDER_LABEL_STYLE)
        self._setting_font_size.valueChanged.connect(
            lambda v: self._font_size_label.setText(f"{v} px")
        )
        font_row = QHBoxLayout()
        font_row.addWidget(self._setting_font_size, 1)
        font_row.addWidget(self._font_size_label)
        font_widget = QWidget()
        font_widget.setLayout(font_row)
        overlay_form.addRow("Cỡ chữ tiếng Nhật:", font_widget)

        self._setting_opacity = QSlider(Qt.Orientation.Horizontal)
        self._setting_opacity.setRange(40, 100)
        self._setting_opacity.setValue(self._settings.get("overlay_opacity", 90))
        self._setting_opacity.setTickInterval(10)
        self._opacity_value_label = QLabel(f"{self._setting_opacity.value()}%")
        self._opacity_value_label.setStyleSheet(SLIDER_LABEL_STYLE)
        self._setting_opacity.valueChanged.connect(
            lambda v: self._opacity_value_label.setText(f"{v}%")
        )
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self._setting_opacity, 1)
        opacity_row.addWidget(self._opacity_value_label)
        opacity_widget = QWidget()
        opacity_widget.setLayout(opacity_row)
        overlay_form.addRow("Độ trong suốt:", opacity_widget)

        self._setting_max_history = QSlider(Qt.Orientation.Horizontal)
        self._setting_max_history.setRange(1, 15)
        self._setting_max_history.setValue(self._settings.get("overlay_max_history", 8))
        self._setting_max_history.setTickInterval(1)
        self._max_history_label = QLabel(f"{self._setting_max_history.value()} câu")
        self._max_history_label.setStyleSheet(SLIDER_LABEL_STYLE)
        self._setting_max_history.valueChanged.connect(
            lambda v: self._max_history_label.setText(f"{v} câu")
        )
        hist_row = QHBoxLayout()
        hist_row.addWidget(self._setting_max_history, 1)
        hist_row.addWidget(self._max_history_label)
        hist_widget = QWidget()
        hist_widget.setLayout(hist_row)
        overlay_form.addRow("Số câu hiển thị:", hist_widget)

        overlay_group.setLayout(overlay_form)
        layout.addWidget(overlay_group)

        # -- Ngôn ngữ --
        from PyQt6.QtWidgets import QComboBox
        lang_group = QGroupBox("Ngôn ngữ phỏng vấn")
        lang_group.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        lang_group.setStyleSheet(GROUPBOX_STYLE)
        lang_form = QFormLayout()
        lang_form.setSpacing(10)

        lang_hint = QLabel(
            "Ngôn ngữ mặc định khi bắt đầu phiên.\n"
            "Có thể chuyển đổi JP ↔ EN trong lúc phỏng vấn bằng nút trên Overlay hoặc phím F2."
        )
        lang_hint.setStyleSheet("color: #585b70; font-size: 11px;")
        lang_form.addRow(lang_hint)

        self._setting_language = QComboBox()
        self._setting_language.setStyleSheet(
            "QComboBox { background: #181825; color: #cdd6f4; border: 1px solid #45475a;"
            " border-radius: 4px; padding: 6px 8px; min-height: 24px; font-size: 12px; }"
            " QComboBox::drop-down { border: none; }"
            " QComboBox QAbstractItemView { background: #181825; color: #cdd6f4; }"
        )
        for code, info in LANGUAGES.items():
            self._setting_language.addItem(f"{info['short'].upper()} - {info['name']}", code)
        current_lang = self._settings.get("interview_language", "ja-JP")
        idx = self._setting_language.findData(current_lang)
        if idx >= 0:
            self._setting_language.setCurrentIndex(idx)
        lang_form.addRow("Ngôn ngữ mặc định:", self._setting_language)

        lang_group.setLayout(lang_form)
        layout.addWidget(lang_group)

        # -- Nhận diện giọng nói --
        speaker_group = QGroupBox("Nhận diện người nói")
        speaker_group.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        speaker_group.setStyleSheet(GROUPBOX_STYLE)
        speaker_form = QFormLayout()
        speaker_form.setSpacing(10)

        speaker_hint = QLabel(
            "Loopback → ConversationTranscriber (tự phân biệt nhiều người nói)\n"
            "Mic → SpeechRecognizer (luôn gán là 'Bạn')"
        )
        speaker_hint.setStyleSheet("color: #585b70; font-size: 11px;")
        speaker_form.addRow(speaker_hint)

        self._setting_energy_threshold = QSlider(Qt.Orientation.Horizontal)
        self._setting_energy_threshold.setRange(50, 1000)
        self._setting_energy_threshold.setValue(self._settings.get("energy_threshold", 200))
        self._setting_energy_threshold.setTickInterval(50)
        self._energy_threshold_label = QLabel(f"{self._setting_energy_threshold.value()}")
        self._energy_threshold_label.setStyleSheet(SLIDER_LABEL_STYLE)
        self._setting_energy_threshold.valueChanged.connect(
            lambda v: self._energy_threshold_label.setText(str(v))
        )
        threshold_row = QHBoxLayout()
        threshold_row.addWidget(self._setting_energy_threshold, 1)
        threshold_row.addWidget(self._energy_threshold_label)
        threshold_widget = QWidget()
        threshold_widget.setLayout(threshold_row)
        speaker_form.addRow("Ngưỡng mic (energy):", threshold_widget)

        speaker_group.setLayout(speaker_form)
        layout.addWidget(speaker_group)

        # -- API Keys --
        api_group = QGroupBox("API Keys")
        api_group.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        api_group.setStyleSheet(GROUPBOX_STYLE)
        api_form = QFormLayout()
        api_form.setSpacing(10)
        api_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        api_note = QLabel("Thay đổi API key cần khởi động lại ứng dụng.")
        api_note.setStyleSheet("color: #fab387; font-size: 11px;")
        api_form.addRow(api_note)

        self._setting_speech_key = QLineEdit(self._settings.get("azure_speech_key", ""))
        self._setting_speech_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._setting_speech_key.setPlaceholderText("Azure Speech Key")
        self._setting_speech_key.setStyleSheet(INPUT_STYLE)
        api_form.addRow("Speech Key:", self._setting_speech_key)

        self._setting_speech_region = QLineEdit(self._settings.get("azure_speech_region", ""))
        self._setting_speech_region.setPlaceholderText("eastus, japaneast...")
        self._setting_speech_region.setStyleSheet(INPUT_STYLE)
        api_form.addRow("Speech Region:", self._setting_speech_region)

        self._setting_openai_key = QLineEdit(self._settings.get("azure_openai_key", ""))
        self._setting_openai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._setting_openai_key.setPlaceholderText("Azure OpenAI Key")
        self._setting_openai_key.setStyleSheet(INPUT_STYLE)
        api_form.addRow("OpenAI Key:", self._setting_openai_key)

        self._setting_openai_endpoint = QLineEdit(self._settings.get("azure_openai_endpoint", ""))
        self._setting_openai_endpoint.setPlaceholderText("https://xxx.openai.azure.com/")
        self._setting_openai_endpoint.setStyleSheet(INPUT_STYLE)
        api_form.addRow("OpenAI Endpoint:", self._setting_openai_endpoint)

        self._setting_openai_deployment = QLineEdit(self._settings.get("azure_openai_deployment", ""))
        self._setting_openai_deployment.setPlaceholderText("gpt-5.3-chat, gpt-4o...")
        self._setting_openai_deployment.setStyleSheet(INPUT_STYLE)
        api_form.addRow("Deployment:", self._setting_openai_deployment)

        self._setting_openai_fast_deployment = QLineEdit(self._settings.get("azure_openai_fast_deployment", ""))
        self._setting_openai_fast_deployment.setPlaceholderText("gpt-4o-mini, gpt-4.1-mini (nhanh, cho gợi ý tự động)")
        self._setting_openai_fast_deployment.setStyleSheet(INPUT_STYLE)
        fast_note = QLabel("Fast Model (cho gợi ý tự động, để trống = dùng Deployment chính):")
        fast_note.setStyleSheet("color: #89b4fa; font-size: 11px; margin-top: 4px;")
        api_form.addRow(fast_note)
        api_form.addRow("Fast Deployment:", self._setting_openai_fast_deployment)

        translator_note = QLabel("Translator (tùy chọn, để trống = dịch qua Speech SDK):")
        translator_note.setStyleSheet("color: #89b4fa; font-size: 11px; margin-top: 4px;")
        api_form.addRow(translator_note)

        self._setting_translator_key = QLineEdit(self._settings.get("azure_translator_key", ""))
        self._setting_translator_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._setting_translator_key.setPlaceholderText("Để trống = dịch qua Speech SDK")
        self._setting_translator_key.setStyleSheet(INPUT_STYLE)
        api_form.addRow("Translator Key:", self._setting_translator_key)

        self._setting_translator_region = QLineEdit(self._settings.get("azure_translator_region", ""))
        self._setting_translator_region.setPlaceholderText("Để trống = dùng Speech Region")
        self._setting_translator_region.setStyleSheet(INPUT_STYLE)
        api_form.addRow("Translator Region:", self._setting_translator_region)

        api_group.setLayout(api_form)
        layout.addWidget(api_group)

        # Nút lưu
        save_btn = QPushButton("Lưu cài đặt")
        save_btn.setObjectName("startBtn")
        save_btn.setFixedHeight(38)
        save_btn.setMinimumWidth(160)
        save_btn.clicked.connect(self._on_save_settings)
        layout.addWidget(save_btn, alignment=Qt.AlignmentFlag.AlignRight)

        layout.addStretch()

        scroll.setWidget(widget)
        return scroll

    def _on_save_settings(self):
        self._settings["overlay_font_size"] = self._setting_font_size.value()
        self._settings["overlay_opacity"] = self._setting_opacity.value()
        self._settings["overlay_max_history"] = self._setting_max_history.value()
        self._settings["energy_threshold"] = self._setting_energy_threshold.value()
        self._settings["interview_language"] = self._setting_language.currentData() or "ja-JP"
        self._settings["azure_speech_key"] = self._setting_speech_key.text().strip()
        self._settings["azure_speech_region"] = self._setting_speech_region.text().strip()
        self._settings["azure_openai_key"] = self._setting_openai_key.text().strip()
        self._settings["azure_openai_endpoint"] = self._setting_openai_endpoint.text().strip()
        self._settings["azure_openai_deployment"] = self._setting_openai_deployment.text().strip()
        self._settings["azure_openai_fast_deployment"] = self._setting_openai_fast_deployment.text().strip()
        self._settings["azure_translator_key"] = self._setting_translator_key.text().strip()
        self._settings["azure_translator_region"] = self._setting_translator_region.text().strip()
        save_settings(self._settings)
        self.settings_changed.emit(self._settings)
        QMessageBox.information(self, "Đã lưu", "Cài đặt đã được lưu.\nMột số thay đổi cần khởi động lại ứng dụng.")

    def get_settings(self) -> dict:
        return self._settings

    def _on_save_notes(self, category: str):
        if not self._current_session:
            return
        if category == "personal":
            text = self._notes_personal.toPlainText()
        elif category == "general":
            text = self._notes_general.toPlainText()
        else:
            text = self._notes_company.toPlainText()
        self._session_mgr.save_notes(self._current_session, category, text)
        cat_labels = {"personal": "Thông tin cá nhân", "company": "Thông tin công ty", "general": "Ngữ cảnh chung"}
        label_text = cat_labels.get(category, category)
        self._notes_saved_label.setText(f"Đã lưu {label_text}")
        self._notes_saved_label.setStyleSheet("color: #a6e3a1; font-size: 11px;")
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(2500, lambda: self._notes_saved_label.setText(""))

    def _load_notes(self, session: Session):
        self._notes_personal.blockSignals(True)
        self._notes_company.blockSignals(True)
        self._notes_general.blockSignals(True)
        self._notes_personal.setPlainText(self._session_mgr.load_notes(session, "personal"))
        self._notes_company.setPlainText(self._session_mgr.load_notes(session, "company"))
        self._notes_general.setPlainText(self._session_mgr.load_notes(session, "general"))
        self._notes_personal.blockSignals(False)
        self._notes_company.blockSignals(False)
        self._notes_general.blockSignals(False)

    def _on_upload_document(self, category: str = "company"):
        if not self._current_session:
            return
        cat_labels = {"personal": "thông tin cá nhân", "company": "thông tin công ty / vị trí"}
        files, _ = QFileDialog.getOpenFileNames(
            self, f"Chọn tài liệu ({cat_labels.get(category, category)})",
            "", "Tài liệu (*.pdf *.docx *.doc *.txt);;Tất cả (*)",
        )
        if not files:
            return
        for f in files:
            try:
                dest = copy_to_session(f, self._current_session.documents_dir)
                self._current_session.documents.append(dest.name)
                self._session_mgr._save_metadata(self._current_session)
                self._session_mgr.set_doc_category(self._current_session, dest.name, category)
            except Exception as e:
                QMessageBox.warning(self, "Lỗi tải lên", f"Không thể tải lên {f}:\n{e}")
        self._load_documents(self._current_session)

    def _load_documents(self, session: Session):
        self._docs_list.clear()
        self._doc_preview.clear()
        self._docs_keywords_label.clear()

        try:
            self._docs_list.currentRowChanged.disconnect(self._on_doc_selected)
        except (TypeError, RuntimeError):
            pass

        docs_dir = session.documents_dir
        if not docs_dir.exists():
            return

        doc_meta = self._session_mgr.load_doc_meta(session)
        cat_icons = {"personal": "[Cá nhân]", "company": "[Công ty]"}

        files = sorted(docs_dir.iterdir())
        for f in files:
            if f.is_file():
                cat = doc_meta.get(f.name, "company")
                label = f"{cat_icons.get(cat, '[?]')}  {f.name}"

                row_widget = QWidget()
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(8, 6, 8, 6)
                row_layout.setSpacing(8)

                file_label = QLabel(label)
                file_label.setFont(QFont("Segoe UI", 12))
                file_label.setWordWrap(True)
                color = "#a6e3a1" if cat == "personal" else "#89b4fa"
                file_label.setStyleSheet(f"color: {color};")
                row_layout.addWidget(file_label, 1)

                del_btn = QPushButton("Xóa")
                del_btn.setFixedSize(50, 28)
                del_btn.setStyleSheet(
                    "QPushButton { background: transparent; color: #f38ba8; border: 1px solid #f38ba8;"
                    " border-radius: 4px; font-size: 11px; }"
                    " QPushButton:hover { background: #f38ba8; color: #1e1e2e; }"
                )
                file_path = str(f)
                del_btn.clicked.connect(lambda checked, fp=file_path, fn=f.name: self._on_delete_document(fp, fn))
                row_layout.addWidget(del_btn)

                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, file_path)
                item.setSizeHint(QSize(0, 42))
                self._docs_list.addItem(item)
                self._docs_list.setItemWidget(item, row_widget)

        self._docs_list.currentRowChanged.connect(self._on_doc_selected)

        all_text = get_all_text_from_session(docs_dir)
        if all_text:
            keywords = extract_keywords(all_text, max_keywords=50)
            if keywords:
                self._docs_keywords_label.setText(
                    f"Từ khóa ({len(keywords)}): {', '.join(keywords[:30])}..."
                )

    def _on_delete_document(self, file_path: str, filename: str):
        if not self._current_session:
            return
        reply = QMessageBox.question(
            self, "Xác nhận xóa",
            f"Xóa tài liệu \"{filename}\"?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from pathlib import Path
        try:
            Path(file_path).unlink(missing_ok=True)
        except Exception:
            pass

        if filename in self._current_session.documents:
            self._current_session.documents.remove(filename)
            self._session_mgr._save_metadata(self._current_session)

        doc_meta = self._session_mgr.load_doc_meta(self._current_session)
        doc_meta.pop(filename, None)
        self._session_mgr.save_doc_meta(self._current_session, doc_meta)

        self._load_documents(self._current_session)

    def _on_doc_selected(self, row: int):
        if row < 0:
            return
        item = self._docs_list.item(row)
        if not item:
            return
        file_path = item.data(Qt.ItemDataRole.UserRole)
        try:
            text = extract_text(file_path)
            preview = text[:3000] + ("..." if len(text) > 3000 else "")
            self._doc_preview.setPlainText(preview)
        except Exception as e:
            self._doc_preview.setPlainText(f"Lỗi đọc file: {e}")

    # ── Quản lý danh sách phiên ──────────────────────────────

    def _load_sessions(self):
        self._session_list.clear()
        sessions = self._session_mgr.list_sessions()
        if not sessions:
            self._content_stack.setCurrentIndex(0)
            return

        for s in sessions:
            status_icons = {"created": "○", "active": "●", "completed": "✓"}
            icon = status_icons.get(s.status, "○")

            date_str = ""
            try:
                dt = datetime.fromisoformat(s.created_at)
                date_str = dt.strftime("%d/%m/%Y")
            except ValueError:
                pass

            count = 0
            if s.transcript_path.exists():
                try:
                    count = sum(1 for _ in open(s.transcript_path, encoding="utf-8"))
                except OSError:
                    pass

            display = f"{icon}  {s.name}\n     {date_str}  ·  {count} câu"
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, s.id)
            self._session_list.addItem(item)

        self._session_list.setCurrentRow(0)

    def _on_session_selected(self, row: int):
        if row < 0:
            self._current_session = None
            self._start_btn.setEnabled(False)
            return

        item = self._session_list.item(row)
        session_id = item.data(Qt.ItemDataRole.UserRole)
        session = self._session_mgr.load_session(session_id)
        if not session:
            return

        self._current_session = session
        self._content_stack.setCurrentIndex(1)
        self._session_name_label.setText(session.name)

        status_map = {"created": "Chưa bắt đầu", "active": "Đang phỏng vấn", "completed": "Đã hoàn thành"}
        status_color = {"created": "#a6adc8", "active": "#a6e3a1", "completed": "#89b4fa"}
        self._session_status_label.setText(status_map.get(session.status, session.status))
        self._session_status_label.setStyleSheet(
            f"color: {status_color.get(session.status, '#cdd6f4')}; font-size: 12px;"
        )

        try:
            dt = datetime.fromisoformat(session.created_at)
            self._session_date_label.setText(dt.strftime("Tạo lúc: %d/%m/%Y %H:%M"))
        except ValueError:
            self._session_date_label.setText(f"Tạo lúc: {session.created_at}")

        self._start_btn.setEnabled(not self._interview_active)
        self._load_transcript(session)
        self._load_glossary(session)
        self._load_documents(session)
        self._load_notes(session)

    def _on_create_session(self):
        name, ok = QInputDialog.getText(
            self, "Tạo phiên mới", "Tên phiên phỏng vấn:",
            text=f"Phỏng vấn {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        if ok and name.strip():
            session = self._session_mgr.create_session(name.strip())
            self._load_sessions()
            for i in range(self._session_list.count()):
                item = self._session_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == session.id:
                    self._session_list.setCurrentRow(i)
                    break

    def _on_rename_session(self):
        if not self._current_session:
            return
        new_name, ok = QInputDialog.getText(
            self, "Đổi tên phiên", "Tên mới:",
            text=self._current_session.name,
        )
        if ok and new_name.strip():
            self._current_session.name = new_name.strip()
            self._session_mgr._save_metadata(self._current_session)
            self._session_name_label.setText(self._current_session.name)
            self._load_sessions()
            for i in range(self._session_list.count()):
                item = self._session_list.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole) == self._current_session.id:
                    self._session_list.setCurrentRow(i)
                    break

    def _on_delete_session(self):
        if not self._current_session:
            return
        if self._interview_active and self._current_session.status == "active":
            QMessageBox.warning(self, "Lỗi", "Không thể xóa phiên đang phỏng vấn!")
            return
        reply = QMessageBox.question(
            self, "Xác nhận xóa",
            f"Xóa phiên \"{self._current_session.name}\"?\nToàn bộ lịch sử và tài liệu sẽ bị xóa.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._session_mgr.delete_session(self._current_session.id)
            self._current_session = None
            self._load_sessions()

    # ── Lịch sử hội thoại ────────────────────────────────────

    def _load_transcript(self, session: Session):
        entries = self._session_mgr.load_transcript(session)
        self._transcript_view.clear()
        if not entries:
            self._transcript_view.setHtml(
                '<p style="color: #585b70;">Chưa có lịch sử. Bắt đầu phỏng vấn để ghi lại.</p>'
            )
            return
        self._render_transcript(entries)

    @staticmethod
    def _hl(text: str, query: str) -> str:
        if not query or not text:
            return text
        import re
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        return pattern.sub(
            lambda m: f'<span style="background: #fab387; color: #1e1e2e; border-radius: 2px; padding: 0 2px;">{m.group()}</span>',
            text,
        )

    def _render_transcript(self, entries: list[dict], highlight: str = ""):
        hl = lambda t: self._hl(t, highlight) if highlight else t
        html_parts = []
        for e in entries:
            time_str = ""
            if "time" in e:
                try:
                    dt = datetime.fromisoformat(e["time"])
                    time_str = dt.strftime("%H:%M:%S")
                except ValueError:
                    time_str = e["time"]

            speaker = e.get("speaker", "") or ""
            ja = e.get("ja", "") or ""
            romaji = e.get("romaji", "") or ""
            vi_azure = e.get("vi_azure", "") or ""
            vi_llm = e.get("vi_llm", "") or ""
            vi = vi_llm or vi_azure
            entry_lang = e.get("language", "ja-JP")
            show_romaji = LANGUAGES.get(entry_lang, LANGUAGES["ja-JP"])["has_romaji"]

            MAIN_SPEAKER_COLORS = {
                "me": "#a6e3a1",
                "me_draft": "#fab387",
                "Speaker 1": "#89b4fa",
                "Speaker 2": "#fab387",
                "Speaker 3": "#a6e3a1",
                "Speaker 4": "#94e2d5",
                "Speaker 5": "#f9e2af",
            }
            if speaker == "me_draft":
                bg = "#2a2a1e"
                speaker_label = "Bạn (thủ công)"
                speaker_color = "#fab387"
                ja_color = "#fab387"
            elif speaker == "me":
                bg = "#1e3a2e"
                speaker_label = "Bạn"
                speaker_color = "#a6e3a1"
                ja_color = "#a6e3a1"
            else:
                bg = "#28283d"
                speaker_label = speaker or "Speaker"
                speaker_color = MAIN_SPEAKER_COLORS.get(speaker, "#cba6f7")
                ja_color = "#ffffff"

            lang_info = LANGUAGES.get(entry_lang, LANGUAGES["ja-JP"])
            src_font = lang_info["font"]

            romaji_html = ""
            if show_romaji and romaji:
                romaji_html = f'<span style="color: #7f849c; font-size: 12px;">{hl(romaji)}</span><br>'

            answer_html = ""
            answer_vi = e.get("answer_vi", "") or ""
            answer_primary = e.get("answer_romaji", "") or ""
            if answer_vi or answer_primary:
                primary_span = ""
                if answer_primary:
                    primary_span = f'<span style="color: #cba6f7; font-size: 12px;">{hl(answer_primary)}</span><br>'
                answer_html = f"""
                    <div style="margin-top: 6px; padding: 6px; background: #1e2a3a; border-radius: 4px;">
                        <span style="color: #89b4fa; font-size: 11px; font-weight: bold;">Gợi ý:</span><br>
                        {primary_span}
                        <span style="color: #89b4fa; font-size: 13px;">{hl(answer_vi)}</span>
                    </div>
                """

            lang_badge = ""
            if entry_lang.startswith("en"):
                lang_badge = '<span style="color: #f9e2af; font-size: 9px; margin-left: 4px;">[EN]</span>'

            html_parts.append(f"""
                <div style="margin-bottom: 10px; padding: 8px; background: {bg}; border-radius: 6px;">
                    <span style="color: {speaker_color}; font-size: 11px; font-weight: bold;">{speaker_label}</span>
                    {lang_badge}
                    <span style="color: #585b70; font-size: 11px; margin-left: 8px;">{time_str}</span><br>
                    <span style="font-family: {src_font}; color: {ja_color}; font-size: 15px;">{hl(ja)}</span><br>
                    {romaji_html}
                    <span style="color: #a6e3a1; font-size: 14px;">{hl(vi)}</span>
                    {answer_html}
                </div>
            """)
        self._transcript_view.setHtml("".join(html_parts))
        scrollbar = self._transcript_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_export_transcript(self):
        if not self._current_session:
            return
        entries = self._session_mgr.load_transcript(self._current_session)
        if not entries:
            QMessageBox.information(self, "Xuất lịch sử", "Chưa có lịch sử để xuất.")
            return

        default_name = f"JInterview_{self._current_session.name.replace(' ', '_')}"
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self, "Xuất lịch sử hội thoại", default_name,
            "Text (*.txt);;HTML (*.html)",
        )
        if not file_path:
            return

        try:
            if file_path.endswith(".html"):
                self._export_html(file_path, entries)
            else:
                self._export_txt(file_path, entries)
            QMessageBox.information(self, "Xuất thành công", f"Đã xuất ra:\n{file_path}")
        except Exception as e:
            QMessageBox.warning(self, "Lỗi xuất", str(e))

    def _export_txt(self, path: str, entries: list[dict]):
        lines = []
        for e in entries:
            time_str = e.get("time", "")[:19]
            speaker = e.get("speaker", "interviewer")
            labels = {"interviewer": "Nhà tuyển dụng", "me": "Bạn", "me_draft": "Bạn (thủ công)"}
            label = labels.get(speaker, speaker)

            lines.append(f"[{time_str}] {label}")
            lines.append(f"  JP: {e.get('ja', '')}")
            lines.append(f"  Romaji: {e.get('romaji', '')}")
            vi = e.get("vi_llm") or e.get("vi_azure", "")
            lines.append(f"  VI: {vi}")
            if e.get("answer_vi") or e.get("answer_romaji"):
                lines.append(f"  --- Gợi ý ---")
                primary = e.get("answer_romaji", "")
                if primary:
                    lines.append(f"  Primary: {primary}")
                lines.append(f"  VI: {e.get('answer_vi','')}")
            lines.append("")

        from pathlib import Path
        Path(path).write_text("\n".join(lines), encoding="utf-8")

    def _export_html(self, path: str, entries: list[dict]):
        html_entries = []
        for e in entries:
            time_str = e.get("time", "")[:19]
            speaker = e.get("speaker", "interviewer")
            labels = {"interviewer": "Nhà tuyển dụng", "me": "Bạn", "me_draft": "Bạn (thủ công)"}
            label = labels.get(speaker, speaker)
            colors = {"interviewer": "#89b4fa", "me": "#a6e3a1", "me_draft": "#fab387"}
            color = colors.get(speaker, "#cdd6f4")
            vi = e.get("vi_llm") or e.get("vi_azure", "")

            answer_html = ""
            primary = e.get("answer_romaji", "")
            if e.get("answer_vi") or primary:
                primary_span = f'<span style="color:#cba6f7;">{primary}</span><br>' if primary else ""
                answer_html = (
                    f'<div style="margin-top:4px;padding:6px;background:#1e2a3a;border-radius:4px;">'
                    f'<b style="color:#89b4fa;">Gợi ý:</b><br>'
                    f'{primary_span}'
                    f'<span style="color:#89b4fa;">{e.get("answer_vi","")}</span>'
                    f'</div>'
                )

            html_entries.append(
                f'<div style="margin:8px 0;padding:10px;background:#28283d;border-radius:8px;">'
                f'<b style="color:{color};">{label}</b> '
                f'<span style="color:#585b70;font-size:12px;">{time_str}</span><br>'
                f'<span style="color:#fff;font-size:16px;">{e.get("ja","")}</span><br>'
                f'<span style="color:#999;font-size:12px;">{e.get("romaji","")}</span><br>'
                f'<span style="color:#a6e3a1;font-size:14px;">{vi}</span>'
                f'{answer_html}</div>'
            )

        html = (
            '<!DOCTYPE html><html><head><meta charset="utf-8">'
            '<title>JInterview Transcript</title>'
            '<style>body{background:#1e1e2e;color:#cdd6f4;font-family:Segoe UI,sans-serif;'
            'max-width:800px;margin:0 auto;padding:20px;}</style></head><body>'
            f'<h1 style="color:#a6e3a1;">JInterview - {self._current_session.name if self._current_session else ""}</h1>'
            + "".join(html_entries) +
            '</body></html>'
        )
        from pathlib import Path
        Path(path).write_text(html, encoding="utf-8")

    def _on_search_transcript(self, query: str):
        if not self._current_session:
            return
        entries = self._session_mgr.load_transcript(self._current_session)
        if not query.strip():
            self._search_count_label.clear()
            self._render_transcript(entries)
            return
        q = query.strip().lower()
        filtered = [
            e for e in entries
            if q in e.get("ja", "").lower()
            or q in e.get("romaji", "").lower()
            or q in e.get("vi_azure", "").lower()
            or q in (e.get("vi_llm", "") or "").lower()
            or q in (e.get("answer_vi", "") or "").lower()
            or q in (e.get("answer_ja", "") or "").lower()
        ]
        self._search_count_label.setText(f"{len(filtered)} kết quả")
        self._render_transcript(filtered, highlight=q)

    @pyqtSlot(str, str, str)
    def on_live_final(self, ja: str, romaji: str, vi: str):
        """Cập nhật live khi có kết quả mới trong phiên đang phỏng vấn."""
        self._refresh_transcript()

    @pyqtSlot(str, str)
    def on_live_translation(self, vi: str, label: str):
        """Cập nhật khi nhận bản dịch mới."""
        self._refresh_transcript()

    @pyqtSlot(dict)
    def on_live_tier2(self, result: dict):
        """Cập nhật khi LLM trả về kết quả Tier 2 (gợi ý, sửa lỗi)."""
        self._refresh_transcript()

    def _refresh_transcript(self):
        if not self._current_session:
            return
        entries = self._session_mgr.load_transcript(self._current_session)
        self._render_transcript(entries)

    def set_language(self, lang_code: str):
        """Update current language display."""
        self._current_language = lang_code
        lang_info = LANGUAGES.get(lang_code, LANGUAGES["ja-JP"])
        short = lang_info["short"].upper()
        self._session_status_label.setText(
            f"Đang phỏng vấn [{short}]"
        )
        self._session_status_label.setStyleSheet("color: #a6e3a1; font-size: 12px;")

    # ── Từ điển ───────────────────────────────────────────────

    def _load_glossary(self, session: Session):
        entries = self._session_mgr.load_glossary(session)
        self._glossary_table.setRowCount(0)
        for entry in entries:
            self._add_glossary_row(entry.get("jp", ""), entry.get("reading", ""), entry.get("vi", ""))

    def _add_glossary_row(self, jp: str, reading: str, vi: str):
        row = self._glossary_table.rowCount()
        self._glossary_table.insertRow(row)
        self._glossary_table.setItem(row, 0, QTableWidgetItem(jp))
        self._glossary_table.setItem(row, 1, QTableWidgetItem(reading))
        self._glossary_table.setItem(row, 2, QTableWidgetItem(vi))

        del_btn = QPushButton("Xóa")
        del_btn.setStyleSheet("background: transparent; color: #f38ba8; border: none; font-size: 12px;")
        del_btn.clicked.connect(lambda checked, r=row: self._on_delete_glossary(r))
        self._glossary_table.setCellWidget(row, 3, del_btn)

    def _on_add_glossary(self):
        if not self._current_session:
            return
        jp = self._glossary_jp_input.text().strip()
        vi = self._glossary_vi_input.text().strip()
        reading = self._glossary_reading_input.text().strip()
        if not jp or not vi:
            return

        entries = self._session_mgr.load_glossary(self._current_session)
        entries.append({"jp": jp, "reading": reading, "vi": vi})
        self._session_mgr.save_glossary(self._current_session, entries)

        self._add_glossary_row(jp, reading, vi)
        self._glossary_jp_input.clear()
        self._glossary_reading_input.clear()
        self._glossary_vi_input.clear()

    def _on_delete_glossary(self, row: int):
        if not self._current_session:
            return
        if row >= self._glossary_table.rowCount():
            return
        self._glossary_table.removeRow(row)
        self._save_current_glossary()
        self._load_glossary(self._current_session)

    def _save_current_glossary(self):
        if not self._current_session:
            return
        entries = []
        for r in range(self._glossary_table.rowCount()):
            jp_item = self._glossary_table.item(r, 0)
            reading_item = self._glossary_table.item(r, 1)
            vi_item = self._glossary_table.item(r, 2)
            entries.append({
                "jp": jp_item.text() if jp_item else "",
                "reading": reading_item.text() if reading_item else "",
                "vi": vi_item.text() if vi_item else "",
            })
        self._session_mgr.save_glossary(self._current_session, entries)

    # ── Nhập text thủ công ─────────────────────────────────

    def _on_manual_submit_mw(self):
        text = self._manual_text_edit.toPlainText().strip()
        if not text:
            return
        ai_refine = self._manual_ai_check.isChecked()
        context_only = self._manual_context_check.isChecked()
        self._manual_text_edit.clear()
        self._manual_send_btn_mw.setEnabled(False)
        self._manual_send_btn_mw.setText("Đang xử lý...")
        self.manual_answer_request.emit(text, ai_refine, context_only)

    @pyqtSlot(dict)
    def on_manual_answer(self, result: dict):
        """Hiển thị kết quả từ LLM sau khi xử lý text thủ công."""
        self._manual_send_btn_mw.setEnabled(True)
        self._manual_send_btn_mw.setText("Gửi cho AI xử lý")

        answer_vi = result.get("answer_vi", "")
        answer_romaji = result.get("answer_romaji", "")

        self._manual_result_vi.setText(answer_vi)
        self._manual_result_ja.clear()
        self._manual_result_ja.hide()
        self._manual_result_romaji.setText(answer_romaji)
        self._manual_result_frame.show()

        if self._current_session:
            self._load_transcript(self._current_session)

    # ── Bắt đầu / Dừng phỏng vấn ────────────────────────────

    def _on_start_interview(self):
        if not self._current_session:
            QMessageBox.warning(self, "Lỗi", "Hãy chọn hoặc tạo một phiên trước!")
            return

        if self._current_session.status == "completed":
            reply = QMessageBox.question(
                self, "Tiếp tục phiên",
                f"Phiên \"{self._current_session.name}\" đã hoàn thành.\n"
                "Bạn muốn tiếp tục ghi thêm vào phiên này?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._interview_active = True
        self._session_mgr.update_status(self._current_session, "active")

        self._start_btn.hide()
        self._stop_btn.show()
        self._new_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)
        self._tray_stop_action.setEnabled(True)
        self._tray.show()

        self._tabs.setCurrentIndex(0)
        self._manual_panel.show()
        self._show_overlay_btn.show()

        self.start_interview.emit(self._current_session)

    def _on_stop_interview(self):
        self._interview_active = False
        if self._current_session:
            self._session_mgr.update_status(self._current_session, "completed")

        self._stop_btn.hide()
        self._start_btn.show()
        self._start_btn.setEnabled(True)
        self._new_btn.setEnabled(True)
        self._delete_btn.setEnabled(True)
        self._tray_stop_action.setEnabled(False)
        self._tray.hide()

        self._manual_panel.hide()
        self._manual_result_frame.hide()
        self._show_overlay_btn.hide()

        self.stop_interview.emit()

        if not self.isVisible():
            self._restore_from_tray()

        if self._current_session:
            self._load_transcript(self._current_session)
            self._load_sessions()

    # ── Tray hệ thống ────────────────────────────────────────

    def _restore_from_tray(self):
        self.show()
        self.activateWindow()
        self.raise_()

    def _on_show_overlay(self):
        self.show_overlay_requested.emit()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._restore_from_tray()

    def closeEvent(self, event):
        if self._interview_active:
            self.hide()
            self._tray.show()
            self._tray.showMessage(
                "JInterview",
                "Đang phỏng vấn. Click tray icon để mở lại.",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )
            event.ignore()
        else:
            self._tray.hide()
            event.accept()
