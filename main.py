"""
main.py — Scene Doctor Studio
Standalone PySide6 app for AI-powered scene diagnostics.
Connects to Maya/Blender via TCP sockets.
Built by Ezz El-Din
"""
import sys, os, re, json

def resource_path(filename: str) -> str:
    """Return absolute path to a bundled resource.
    Works in development (uses script dir) and in PyInstaller EXE (uses _MEIPASS)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, filename)

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QFrame, QSplitter,
    QMessageBox, QSizePolicy, QMenu, QDialog, QLineEdit
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QThread, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont, QIcon, QAction, QImage, QPixmap, QPalette, QColor, QPainter
from PySide6.QtSvg import QSvgRenderer

import session_manager
import dcc_connector
import settings as app_settings
import ai_backend

from ui_widgets import (
    COLORS, MessageBubble, SessionItemWidget, TypingIndicator,
    CodeBlockWidget, ChatLineEdit, AGENT_LABELS, AGENT_COLORS,
    get_app_stylesheet, set_theme
)
from studio_settings_dialog import SettingsDialog


# ---------------------------------------------------------------------------
# Background worker: fetch scene info without blocking the UI
# ---------------------------------------------------------------------------
class GetSceneInfoWorker(QThread):
    """Runs dcc_connector.get_scene_info() on a background thread."""
    finished = Signal(str, dict)  # (dcc, info_dict)

    def __init__(self, dcc):
        super().__init__()
        self._dcc = dcc

    def run(self):
        success, info = dcc_connector.get_scene_info(self._dcc)
        self.finished.emit(self._dcc, info if (success and isinstance(info, dict)) else {})


# ---------------------------------------------------------------------------
# DCC Worker — runs blocking socket calls off the main thread
# ---------------------------------------------------------------------------
class DCCWorker(QThread):
    finished = Signal(bool, str)   # success, result

    def __init__(self, fn, *args):
        super().__init__()
        self._fn = fn
        self._args = args

    def run(self):
        try:
            success, result = self._fn(*self._args)
            self.finished.emit(success, result)
        except Exception as e:
            self.finished.emit(False, str(e))


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------
class StudioWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Scene Doctor Studio")
        self.resize(1100, 700)
        self.setMinimumSize(800, 500)
        self.setAcceptDrops(True)

        # Set window icon — prefer ICO (multi-size) over SVG
        _ico_path = resource_path("scene_doctor.ico")
        _svg_path = resource_path("scene_doctor_icon_transparent.svg")
        if os.path.exists(_ico_path):
            self.setWindowIcon(QIcon(_ico_path))
        elif os.path.exists(_svg_path):
            _renderer = QSvgRenderer(_svg_path)
            _icon_pix = QPixmap(256, 256)
            _icon_pix.fill(Qt.transparent)
            _p = QPainter(_icon_pix)
            _p.setRenderHint(QPainter.Antialiasing)
            _renderer.render(_p)
            _p.end()
            self.setWindowIcon(QIcon(_icon_pix))

        self._settings = app_settings.load_settings()
        self._sessions = session_manager.load_all_sessions()
        self._current_session = None
        self._worker = None
        self._current_bubble = None
        self._agent_phase = "idle"
        self._current_response = ""
        self._is_busy = False
        self._pending_screenshot = None
        self._session_widgets = {}
        self._original_msg = ""
        # Per-agent histories (multi-agent mode)
        self._analyzer_history = []
        self._codewriter_history = []
        self._vision_history = []
        # Agentic auto-check
        self._agentic_iter = 0
        # Search mode
        self._search_mode = False
        # Image paste
        self._pending_image_b64 = None
        # Context management
        self._msg_count_since_summary = 0
        # Apply saved accent color
        accent = self._settings.get("accent_color")
        if accent:
            COLORS["accent_blue"] = accent
            COLORS["accent_blue_hover"] = self._darken(accent, 0.85)
        # Apply saved theme
        theme = self._settings.get("theme", "dark")
        set_theme(theme)
        if accent:
            COLORS["accent_blue"] = accent
            COLORS["accent_blue_hover"] = self._darken(accent, 0.85)
        self._summary_worker = None

        self._build_ui()
        self._load_sessions_list()

        if self._sessions:
            self._select_session(self._sessions[0]["session_id"])

    # -----------------------------------------------------------------------
    # UI Construction
    # -----------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # === Collapsible sidebar (Claude-style) ===
        self._sidebar_expanded_width = 260
        self._sidebar_collapsed_width = 56
        self._sidebar_expanded = True
        self._sidebar_text_labels = []
        self._sidebar_section_headers = []
        self._sidebar_separators = []   # separators to hide when collapsed

        self.sidebar = QWidget()
        self.sidebar.setFixedWidth(self._sidebar_expanded_width)
        self.sidebar.setStyleSheet(f"""
            QWidget {{
                background: {COLORS['bg_sidebar']};
            }}
        """)
        self.sidebar.setObjectName("sidebar")
        sb_layout = QVBoxLayout(self.sidebar)
        sb_layout.setContentsMargins(4, 8, 4, 10)
        sb_layout.setSpacing(2)

        # --- Header: title (left) + toggle (right) ---
        header_row = QHBoxLayout()
        header_row.setContentsMargins(4, 0, 4, 4)
        header_row.setSpacing(8)

        # Logo: icon (transparent SVG) + "Scene Doctor" text side by side
        _svg_path = resource_path("scene_doctor_icon_transparent.svg")

        _brand_widget = QWidget()
        _brand_widget.setStyleSheet("background: transparent;")
        _brand_widget.setAttribute(Qt.WA_TransparentForMouseEvents)
        _brand_layout = QHBoxLayout(_brand_widget)
        _brand_layout.setContentsMargins(2, 0, 0, 0)
        _brand_layout.setSpacing(6)

        # Icon
        self._sidebar_icon_lbl = QLabel()
        self._sidebar_icon_lbl.setStyleSheet("background: transparent;")
        self._sidebar_icon_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        if os.path.exists(_svg_path):
            _renderer = QSvgRenderer(_svg_path)
            _icon_pix = QPixmap(32, 32)
            _icon_pix.fill(Qt.transparent)
            _p = QPainter(_icon_pix)
            _p.setRenderHint(QPainter.SmoothPixmapTransform)
            _p.setRenderHint(QPainter.Antialiasing)
            _renderer.render(_p)
            _p.end()
            self._sidebar_icon_lbl.setPixmap(_icon_pix)
        _brand_layout.addWidget(self._sidebar_icon_lbl)

        # Text
        self._sidebar_title = QLabel("Scene Doctor")
        self._sidebar_title.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 14px; font-weight: bold; background: transparent;"
        )
        self._sidebar_title.setAttribute(Qt.WA_TransparentForMouseEvents)
        _brand_layout.addWidget(self._sidebar_title)
        _brand_layout.addStretch()

        header_row.addWidget(_brand_widget, 1)
        # Both hide when sidebar collapses
        self._sidebar_text_labels.append(_brand_widget)



        self.sidebar_toggle_btn = QPushButton("\u2630")
        self.sidebar_toggle_btn.setFixedSize(40, 40)
        self.sidebar_toggle_btn.setToolTip("Toggle sidebar")
        self.sidebar_toggle_btn.setStyleSheet(self._sidebar_icon_style())
        self.sidebar_toggle_btn.clicked.connect(self._toggle_sidebar)
        header_row.addWidget(self.sidebar_toggle_btn)

        sb_layout.addLayout(header_row)
        sb_layout.addSpacing(2)

        # --- Top actions ---
        sb_layout.addWidget(self._make_sidebar_btn("+", "New Session", self._on_new_session))
        sb_layout.addSpacing(4)

        # --- Session search bar (hidden when collapsed) ---
        self._search_bar = QLineEdit()
        self._search_bar.setPlaceholderText("  Search sessions...")
        self._search_bar.setFixedHeight(30)
        self._search_bar.setStyleSheet(f"""
            QLineEdit {{
                background: {COLORS['bg_input']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                padding: 0 10px;
                font-size: 12px;
            }}
            QLineEdit:focus {{ border-color: {COLORS['accent_blue']}; }}
        """)
        self._search_bar.textChanged.connect(self._filter_sessions)
        self._search_bar_container = QWidget()
        self._search_bar_container.setStyleSheet("background: transparent;")
        sb_search_layout = QHBoxLayout(self._search_bar_container)
        sb_search_layout.setContentsMargins(4, 0, 4, 4)
        sb_search_layout.addWidget(self._search_bar)
        sb_layout.addWidget(self._search_bar_container)
        self._sidebar_text_labels.append(self._search_bar_container)

        # Search icon shown ONLY when sidebar is collapsed
        self._search_icon_btn = QPushButton("\U0001f50d")
        self._search_icon_btn.setFixedHeight(40)
        self._search_icon_btn.setToolTip("Search sessions")
        self._search_icon_btn.setCursor(Qt.PointingHandCursor)
        self._search_icon_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
                color: {COLORS['text_muted']}; font-size: 20px;
                border-radius: 8px; padding: 0;
            }}
            QPushButton:hover {{ background: {COLORS['bg_panel']}; }}
            QPushButton:pressed {{ background: {COLORS['bg_secondary']}; }}
        """)
        self._search_icon_btn.clicked.connect(self._expand_to_search)
        self._search_icon_btn.setVisible(False)  # hidden when expanded
        sb_layout.addWidget(self._search_icon_btn)

        # --- Separator ---
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setFixedHeight(1)
        sep1.setStyleSheet(f"background: {COLORS['divider']}; border: none;")
        sb_layout.addWidget(sep1)
        self._sidebar_separators.append(sep1)

        # --- Recents label ---
        self._recents_label = QLabel("Recents")
        self._recents_label.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 10px; font-weight: bold; letter-spacing: 1px;"
            f"padding: 6px 10px 2px 10px; background: transparent;"
        )
        sb_layout.addWidget(self._recents_label)
        self._sidebar_section_headers.append(self._recents_label)

        # --- Session list ---
        self.session_scroll = QScrollArea()
        self.session_scroll.setWidgetResizable(True)
        self.session_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.session_scroll.setStyleSheet("background: transparent; border: none;")
        self.session_list_widget = QWidget()
        self.session_list_widget.setStyleSheet("background: transparent;")
        self.session_list_layout = QVBoxLayout(self.session_list_widget)
        self.session_list_layout.setContentsMargins(2, 0, 2, 0)
        self.session_list_layout.setSpacing(2)
        self.session_list_layout.addStretch()
        self.session_scroll.setWidget(self.session_list_widget)
        sb_layout.addWidget(self.session_scroll, 1)

        # --- Separator ---
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background: {COLORS['divider']}; border: none;")
        sb_layout.addWidget(sep2)
        self._sidebar_separators.append(sep2)
        sb_layout.addSpacing(2)

        # --- Bottom actions ---
        sb_layout.addWidget(self._make_sidebar_btn("\u2699", "Settings", self._on_settings))
        sb_layout.addWidget(self._make_sidebar_btn("\u00d7", "Clear Chat", self._clear_current_chat))
        sb_layout.addWidget(self._make_sidebar_btn("\u26a1", "DCC Setup", self._show_dcc_setup))

        # Footer: attribution only (disclaimer is shown under the chat input bar)
        sb_layout.addSpacing(6)
        _footer = QLabel(
            'Built by <a href="https://www.linkedin.com/in/ezzel-din-tarek-mostafa/" '
            'style="color:#00BFA5;">Ezz El-Din</a>.'
        )
        _footer.setOpenExternalLinks(True)
        _footer.setStyleSheet("color: #6b7280; font-size: 11px; padding: 4px 12px 8px 12px; background: transparent;")
        _footer.setWordWrap(True)
        sb_layout.addWidget(_footer)
        self._sidebar_text_labels.append(_footer)


        root.addWidget(self.sidebar)

        # === Right chat panel ===
        chat_panel = QWidget()
        chat_panel.setStyleSheet(f"background: {COLORS['bg_dark']};")
        cp_layout = QVBoxLayout(chat_panel)
        cp_layout.setContentsMargins(0, 0, 0, 0)
        cp_layout.setSpacing(0)

        # Chat header
        self.chat_header = QLabel("Select or create a session")
        self.chat_header.setStyleSheet(f"""
            padding: 12px 16px;
            background: {COLORS['bg_panel']};
            color: {COLORS['text']};
            font-size: 14px; font-weight: bold;
            border-bottom: 1px solid {COLORS['border']};
        """)
        cp_layout.addWidget(self.chat_header)

        # Chat messages scroll area
        self.chat_scroll = QScrollArea()
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chat_content = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_content)
        self.chat_layout.setContentsMargins(16, 8, 16, 8)
        self.chat_layout.setSpacing(4)
        self.chat_layout.addStretch()
        self.chat_scroll.setWidget(self.chat_content)
        cp_layout.addWidget(self.chat_scroll, 1)

        # Input bar
        input_bar = QWidget()
        input_bar.setStyleSheet(f"background: {COLORS['bg_panel']}; border-top: 1px solid {COLORS['border']};")
        ib_layout = QHBoxLayout(input_bar)
        ib_layout.setContentsMargins(14, 10, 14, 10)
        ib_layout.setSpacing(8)

        # --- Icon button style (shared) ---
        _icon_btn_style = f"""
            QPushButton {{
                background: {COLORS['bg_input']}; border: 1px solid {COLORS['border']};
                border-radius: 8px; font-size: 17px; padding: 0;
                color: {COLORS['text_muted']};
            }}
            QPushButton:hover {{
                border-color: {COLORS['accent_blue']};
                background: {COLORS['bg_panel']};
                color: {COLORS['text']};
            }}
        """

        # Screenshot button
        self.screenshot_btn = QPushButton("📷")
        self.screenshot_btn.setFixedSize(38, 38)
        self.screenshot_btn.setToolTip("Capture viewport screenshot")
        self.screenshot_btn.setStyleSheet(_icon_btn_style)
        self.screenshot_btn.clicked.connect(self._on_screenshot)
        ib_layout.addWidget(self.screenshot_btn)

        # Scan button — teal accent pill
        scan_btn = QPushButton("⬡  Scan")
        scan_btn.setFixedHeight(38)
        scan_btn.setToolTip("Scan the current scene and send data to AI")
        scan_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {COLORS['accent_teal']};
                border: 1px solid {COLORS['accent_teal']};
                border-radius: 8px;
                padding: 0 14px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {COLORS['accent_teal']};
                color: {COLORS['bg_dark']};
            }}
        """)
        scan_btn.clicked.connect(self._on_scan)
        ib_layout.addWidget(scan_btn)

        # Search mode toggle — icon only
        self.search_btn = QPushButton("🌐")
        self.search_btn.setFixedSize(38, 38)
        self.search_btn.setCheckable(True)
        self.search_btn.setToolTip("Search mode — AI searches web for tools/resources")
        self.search_btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['bg_input']}; border: 1px solid {COLORS['border']};
                border-radius: 8px; font-size: 17px; padding: 0;
                color: {COLORS['text_muted']};
            }}
            QPushButton:hover {{ border-color: {COLORS['accent_blue']}; background: {COLORS['bg_panel']}; }}
            QPushButton:checked {{
                background: {COLORS['accent_teal']}; border-color: {COLORS['accent_teal']};
                color: {COLORS['bg_dark']};
            }}
        """)
        self.search_btn.clicked.connect(self._toggle_search)
        ib_layout.addWidget(self.search_btn)

        # Input field — rounded, tall
        self.input_field = ChatLineEdit()
        self.input_field.setPlaceholderText("Type a message...")
        self.input_field.setFixedHeight(40)
        self.input_field.setStyleSheet(f"""
            QLineEdit {{
                background: {COLORS['bg_input']};
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
                color: {COLORS['text']};
                padding: 0 14px;
                font-size: 13px;
                selection-background-color: {COLORS['accent_blue']};
            }}
            QLineEdit:focus {{
                border-color: {COLORS['accent_blue']};
            }}
        """)
        self.input_field.returnPressed.connect(self._on_send)
        self.input_field.pasted_image.connect(self._on_image_pasted)
        ib_layout.addWidget(self.input_field, 1)

        # Send button — accent filled pill
        self.send_btn = QPushButton("Send ›")
        self.send_btn.setFixedSize(80, 38)
        self.send_btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['accent_blue']};
                color: white;
                border: none;
                border-radius: 10px;
                font-size: 13px;
                font-weight: bold;
                padding: 0 10px;
            }}
            QPushButton:hover {{ background: {COLORS['accent_blue_hover']}; }}
            QPushButton:pressed {{ background: {COLORS['accent_blue_hover']}; }}
            QPushButton:disabled {{ background: {COLORS['border']}; color: {COLORS['text_muted']}; }}
        """)
        self.send_btn.clicked.connect(self._on_send)
        ib_layout.addWidget(self.send_btn)


        cp_layout.addWidget(input_bar)

        # Disclaimer under input bar (ChatGPT/Claude style)
        _disclaimer = QLabel("⚠ AI responses may contain errors — always review generated code before running.")
        _disclaimer.setAlignment(Qt.AlignCenter)
        _disclaimer.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 10px; "
            f"padding: 4px 16px 6px 16px; "
            f"background: {COLORS['bg_panel']}; "
            f"border-top: 1px solid {COLORS['divider']};"
        )
        _disclaimer.setWordWrap(True)
        cp_layout.addWidget(_disclaimer)

        root.addWidget(chat_panel, 1)

    # -----------------------------------------------------------------------
    # Sidebar helpers
    # -----------------------------------------------------------------------
    def _sidebar_icon_style(self):
        return f"""
            QPushButton {{
                background: transparent; border: none;
                color: {COLORS['text_muted']}; font-size: 20px;
                border-radius: 8px; padding: 0;
                min-width: 40px; min-height: 40px;
            }}
            QPushButton:hover {{
                background: {COLORS['bg_panel']};
                color: {COLORS['text']};
            }}
            QPushButton:pressed {{
                background: {COLORS['bg_secondary']};
            }}
        """

    def _make_sidebar_btn(self, icon, text, callback=None):
        """Sidebar row: full-width QPushButton with icon + text. Icon stays visible when collapsed."""
        row = QPushButton()
        row.setFlat(True)
        row.setFixedHeight(40)
        row.setCursor(Qt.PointingHandCursor)
        row.setToolTip(text)
        row.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 8px;
                text-align: left;
                padding: 0;
            }}
            QPushButton:hover {{
                background: {COLORS['bg_panel']};
            }}
            QPushButton:pressed {{
                background: {COLORS['bg_secondary']};
            }}
        """)
        if callback:
            row.clicked.connect(callback)

        layout = QHBoxLayout(row)
        # Equal L/R margins (8px) so the 40px icon is centered inside the 56px collapsed sidebar
        # ( sidebar 56 - outer margin 4*2 = 48 inner, button L+icon+R = 4+40+4 = 48 )
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(10)

        icon_lbl = QLabel(icon)
        icon_lbl.setFixedSize(40, 40)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 20px; font-weight: bold; background: transparent;"
        )
        layout.addWidget(icon_lbl)

        text_label = QLabel(text)
        text_label.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 13px; background: transparent;"
        )
        layout.addWidget(text_label, 1)
        self._sidebar_text_labels.append(text_label)

        # Pass mouse events through labels so the outer QPushButton receives them
        icon_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        text_label.setAttribute(Qt.WA_TransparentForMouseEvents)

        return row

    def _filter_sessions(self, query):
        """Show/hide session items based on a name search query."""
        q = query.strip().lower()
        for s in self._sessions:
            sid = s["session_id"]
            w = self._session_widgets.get(sid)
            if w is None:
                continue
            name = s.get("scene_name", "untitled").lower()
            dcc = s.get("dcc", "").lower()
            visible = (not q) or (q in name) or (q in dcc)
            w.setVisible(visible)

    def _expand_to_search(self):
        """Expand the sidebar and focus the search bar (called from collapsed search icon)."""
        if not self._sidebar_expanded:
            self._toggle_sidebar()
        QTimer.singleShot(230, self._search_bar.setFocus)

    # -----------------------------------------------------------------------
    # Session management
    # -----------------------------------------------------------------------
    def _load_sessions_list(self):
        # Clear existing
        while self.session_list_layout.count() > 1:
            item = self.session_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._session_widgets.clear()

        for s in self._sessions:
            w = SessionItemWidget(s)
            w.clicked.connect(self._select_session)
            w.setContextMenuPolicy(Qt.CustomContextMenu)
            w.customContextMenuRequested.connect(lambda pos, sid=s["session_id"]: self._session_context_menu(sid, pos))
            self._session_widgets[s["session_id"]] = w
            self.session_list_layout.insertWidget(self.session_list_layout.count() - 1, w)

    def _select_session(self, session_id):
        # Load session data
        data = session_manager.load_session(session_id)
        if not data:
            for s in self._sessions:
                if s["session_id"] == session_id:
                    data = s
                    break
        if not data:
            return

        self._current_session = data
        dcc = data.get("dcc", "").capitalize()
        name = data.get("scene_name", "untitled")
        dcc_color = COLORS.get(f"{data.get('dcc','')}_color", COLORS['text'])
        self.chat_header.setText(f"{name} • {dcc}")

        # Update selection highlight
        for sid, w in self._session_widgets.items():
            w.set_selected(sid == session_id)

        self._render_chat_history()

    def _render_chat_history(self):
        # Clear chat
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._current_session:
            return

        for msg in self._current_session.get("chat_history", []):
            role = msg.get("role", "user")
            text = msg.get("content", "")
            display_role = role
            if role == "assistant":
                display_role = "analyzer"
            bubble = MessageBubble(display_role)
            bubble.set_text(text)
            bubble.run_code.connect(self._run_code)
            self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)

        QTimer.singleShot(50, self._scroll_to_bottom)

    def _on_new_session(self):
        dccs = dcc_connector.detect_connected_dccs()
        if not dccs:
            QMessageBox.warning(self, "No DCC Found",
                "No Maya or Blender connection detected.\n\n"
                "Click '\u26a1 DCC Setup' in the sidebar\n"
                "to get the connection script for your DCC.")
            return

        # If multiple DCCs detected, let user choose (fast \u2014 no network call)
        if len(dccs) > 1:
            from PySide6.QtWidgets import QInputDialog
            labels = {"maya": "\U0001f537 Maya", "blender": "\U0001f7e0 Blender"}
            items = [labels.get(d, d) for d in dccs]
            choice, ok = QInputDialog.getItem(self, "Choose DCC",
                "Multiple DCCs detected. Connect to:", items, 0, False)
            if not ok:
                return
            dcc = dccs[items.index(choice)]
        else:
            dcc = dccs[0]

        # Show animated loading state in header
        self._loading_dots = 0
        self._loading_dcc = dcc
        self.chat_header.setStyleSheet(f"""
            padding: 12px 16px;
            background: {COLORS['bg_panel']};
            color: {COLORS['accent_blue']};
            font-size: 14px; font-weight: bold;
            border-bottom: 1px solid {COLORS['border']};
        """)
        self._loading_timer = QTimer(self)
        self._loading_timer.timeout.connect(self._pulse_loading)
        self._loading_timer.start(350)
        self._pulse_loading()

        # Run get_scene_info in background thread
        self._ns_worker = GetSceneInfoWorker(dcc)
        self._ns_worker.finished.connect(self._finish_new_session)
        self._ns_worker.start()

    def _pulse_loading(self):
        """Animate connecting dots in the chat header."""
        self._loading_dots = (self._loading_dots + 1) % 4
        dots = "\u25cf" * self._loading_dots + "\u25cb" * (3 - self._loading_dots)
        dcc = getattr(self, "_loading_dcc", "DCC")
        self.chat_header.setText(f"\U0001f50c  Connecting to {dcc.capitalize()}  {dots}")

    def _finish_new_session(self, dcc, info):
        """Called on main thread when scene info is ready."""
        if hasattr(self, "_loading_timer"):
            self._loading_timer.stop()
        # Restore normal header style
        self.chat_header.setStyleSheet(f"""
            padding: 12px 16px;
            background: {COLORS['bg_panel']};
            color: {COLORS['text']};
            font-size: 14px; font-weight: bold;
            border-bottom: 1px solid {COLORS['border']};
        """)

        raw_name = info.get("name", "").strip()
        is_untitled = not raw_name or raw_name.lower() == "untitled"
        path = info.get("path", "")

        if is_untitled:
            # Offer a file picker so the user can point to their scene file
            from PySide6.QtWidgets import QFileDialog
            filters = {
                "maya": "Maya Scenes (*.mb *.ma);;All Files (*)",
                "blender": "Blender Files (*.blend);;All Files (*)",
            }
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                f"Select your {dcc.capitalize()} scene file (optional)",
                "",
                filters.get(dcc, "All Files (*)"),
            )
            if file_path:
                import os
                path = file_path
                name = os.path.splitext(os.path.basename(file_path))[0]
                is_untitled = False
            else:
                name = f"{dcc.capitalize()} Scene"
        else:
            name = raw_name

        session = session_manager.create_session(dcc, name, path)
        session_manager.save_session(session)
        self._sessions = session_manager.load_all_sessions()
        self._load_sessions_list()
        self._select_session(session["session_id"])

        if is_untitled:
            self._add_system_msg(
                f"\U0001f517 Connected to {dcc.capitalize()} — scene is untitled.\n"
                f"\U0001f4a1 Right-click this session to rename it, or open a named scene and create a new session."
            )
        else:
            self._add_system_msg(f"\U0001f517 Connected to {dcc.capitalize()}: {name}")





    def _session_context_menu(self, session_id, pos):
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {COLORS['bg_panel']}; color: {COLORS['text']};
                border: 1px solid {COLORS['border']}; border-radius: 4px; padding: 4px;
            }}
            QMenu::item:selected {{ background: {COLORS['accent_blue']}; }}
        """)
        rename_action = menu.addAction("✏ Rename")
        delete_action = menu.addAction("🗑 Delete Session")
        action = menu.exec(self._session_widgets[session_id].mapToGlobal(pos))
        if action == rename_action:
            from PySide6.QtWidgets import QInputDialog
            # Find current name
            current_name = "untitled"
            for s in self._sessions:
                if s["session_id"] == session_id:
                    current_name = s.get("scene_name", "untitled")
                    break
            new_name, ok = QInputDialog.getText(self, "Rename Session",
                "New name:", text=current_name)
            if ok and new_name.strip():
                updated = session_manager.rename_session(session_id, new_name.strip())
                if updated:
                    self._sessions = session_manager.load_all_sessions()
                    self._load_sessions_list()
                    if self._current_session and self._current_session["session_id"] == session_id:
                        self._current_session["scene_name"] = new_name.strip()
                        self._select_session(session_id)
        elif action == delete_action:
            confirm = QMessageBox.warning(
                self, "Delete Session",
                "Are you sure you want to delete this session?\nThis action cannot be undone.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if confirm == QMessageBox.Yes:
                session_manager.delete_session(session_id)
                self._sessions = session_manager.load_all_sessions()
                self._load_sessions_list()
                if self._current_session and self._current_session["session_id"] == session_id:
                    self._current_session = None
                    self.chat_header.setText("Select or create a session")
                    self._render_chat_history()

    def _show_dcc_setup(self):
        """Show DCC connection setup dialog with copyable scripts."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit
        dlg = QDialog(self)
        dlg.setWindowTitle("Setup DCC Connection")
        dlg.setMinimumWidth(520)
        dlg.setStyleSheet(f"""
            QDialog {{ background: {COLORS['bg_dark']}; color: {COLORS['text']}; }}
            QLabel {{ color: {COLORS['text']}; }}
            QTextEdit {{ background: {COLORS['bg_code']}; color: {COLORS['text_code']};
                border: 1px solid {COLORS['border']}; border-radius: 6px;
                font-family: Consolas, monospace; font-size: 12px; padding: 8px; }}
        """)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)

        # Maya section
        maya_title = QLabel("🔷 Maya")
        maya_title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {COLORS['maya_color']};")
        layout.addWidget(maya_title)
        maya_desc = QLabel("Run this in Maya's Script Editor (Python tab):")
        maya_desc.setStyleSheet("font-size: 12px;")
        layout.addWidget(maya_desc)
        maya_code = QTextEdit()
        maya_code.setPlainText(dcc_connector.MAYA_SETUP_COMMAND)
        maya_code.setReadOnly(True)
        maya_code.setFixedHeight(50)
        layout.addWidget(maya_code)
        maya_copy = QPushButton("📋 Copy Maya Script")
        maya_copy.setStyleSheet(f"""
            QPushButton {{ background: {COLORS['maya_color']}; color: white;
                border-radius: 4px; padding: 6px 12px; font-size: 12px; }}
            QPushButton:hover {{ background: #3a7bc8; }}
        """)
        maya_copy.clicked.connect(lambda: (
            QApplication.clipboard().setText(dcc_connector.MAYA_SETUP_COMMAND),
            maya_copy.setText("✅ Copied!")
        ))
        layout.addWidget(maya_copy)

        # Blender section
        blender_title = QLabel("🟠 Blender")
        blender_title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {COLORS['blender_color']};")
        layout.addWidget(blender_title)
        blender_desc = QLabel("Run this in Blender's Python console or Script Editor:")
        blender_desc.setStyleSheet("font-size: 12px;")
        blender_desc.setWordWrap(True)
        layout.addWidget(blender_desc)
        blender_script = (
            "import bpy, socket, threading, sys, io, traceback\n\n"
            "def _scene_doctor_server():\n"
            "    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
            "    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
            "    srv.bind(('localhost', 7002))\n"
            "    srv.listen(1)\n"
            "    print('Scene Doctor: Blender listening on port 7002')\n"
            "    while True:\n"
            "        conn, _ = srv.accept()\n"
            "        data = b''\n"
            "        while True:\n"
            "            chunk = conn.recv(65536)\n"
            "            if not chunk: break\n"
            "            data += chunk\n"
            "        code = data.decode('utf-8')\n"
            "        buf = io.StringIO()\n"
            "        old = sys.stdout\n"
            "        sys.stdout = buf\n"
            "        try:\n"
            "            exec(code)\n"
            "        except: traceback.print_exc(file=buf)\n"
            "        finally: sys.stdout = old\n"
            "        conn.sendall(buf.getvalue().encode('utf-8'))\n"
            "        conn.close()\n\n"
            "threading.Thread(target=_scene_doctor_server, daemon=True).start()"
        )
        blender_code = QTextEdit()
        blender_code.setPlainText(blender_script)
        blender_code.setReadOnly(True)
        blender_code.setFixedHeight(100)
        layout.addWidget(blender_code)
        blender_copy = QPushButton("📋 Copy Blender Script")
        blender_copy.setStyleSheet(f"""
            QPushButton {{ background: {COLORS['blender_color']}; color: white;
                border-radius: 4px; padding: 6px 12px; font-size: 12px; }}
            QPushButton:hover {{ background: #cc6d0b; }}
        """)
        blender_copy.clicked.connect(lambda: (
            QApplication.clipboard().setText(blender_script),
            blender_copy.setText("✅ Copied!")
        ))
        layout.addWidget(blender_copy)

        # Ports info
        ports = QLabel(f"Ports: Maya = {dcc_connector.PORTS['maya']}  |  Blender = {dcc_connector.PORTS['blender']}")
        ports.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 11px; padding-top: 8px;")
        layout.addWidget(ports)

        # Close
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn)
        dlg.exec()

    def _on_settings(self):
        dlg = SettingsDialog(self._settings, self)
        if dlg.exec() == QDialog.Accepted:
            self._settings = dlg.get_settings()
            app_settings.save_settings(self._settings)
            mode = self._settings.get("mode", "single")
            # Apply theme + accent color
            theme = self._settings.get("theme", "dark")
            set_theme(theme)
            accent = self._settings.get("accent_color")
            if accent:
                COLORS["accent_blue"] = accent
                COLORS["accent_blue_hover"] = self._darken(accent, 0.85)
            # Update global stylesheet + Fusion palette
            app = QApplication.instance()
            app.setStyleSheet(get_app_stylesheet())
            palette = QPalette()
            palette.setColor(QPalette.Window, QColor(COLORS['bg_dark']))
            palette.setColor(QPalette.WindowText, QColor(COLORS['text']))
            palette.setColor(QPalette.Base, QColor(COLORS['bg_input']))
            palette.setColor(QPalette.Text, QColor(COLORS['text']))
            palette.setColor(QPalette.Button, QColor(COLORS['bg_panel']))
            palette.setColor(QPalette.ButtonText, QColor(COLORS['text']))
            palette.setColor(QPalette.Highlight, QColor(COLORS['accent_blue']))
            app.setPalette(palette)
            # Rebuild entire UI so all inline styles pick up new COLORS
            current_sid = self._current_session["session_id"] if self._current_session else None
            self._build_ui()
            self._load_sessions_list()
            if current_sid:
                self._select_session(current_sid)

    @staticmethod
    def _darken(hex_color, factor=0.85):
        """Darken a hex color by a factor (0-1)."""
        hex_color = hex_color.lstrip("#")
        r = max(0, int(int(hex_color[0:2], 16) * factor))
        g = max(0, int(int(hex_color[2:4], 16) * factor))
        b = max(0, int(int(hex_color[4:6], 16) * factor))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _toggle_sidebar(self):
        """Animate sidebar between collapsed (56px icon rail) and expanded (260px)."""
        self._sidebar_expanded = not self._sidebar_expanded
        target = self._sidebar_expanded_width if self._sidebar_expanded else self._sidebar_collapsed_width

        # Animate both min and max width for smooth resize
        anim1 = QPropertyAnimation(self.sidebar, b"minimumWidth")
        anim1.setDuration(220)
        anim1.setStartValue(self.sidebar.width())
        anim1.setEndValue(target)
        anim1.setEasingCurve(QEasingCurve.InOutCubic)

        anim2 = QPropertyAnimation(self.sidebar, b"maximumWidth")
        anim2.setDuration(220)
        anim2.setStartValue(self.sidebar.width())
        anim2.setEndValue(target)
        anim2.setEasingCurve(QEasingCurve.InOutCubic)

        anim1.start()
        anim2.start()
        self._sidebar_anim = (anim1, anim2)  # prevent GC

        # Show/hide text labels (text portions of buttons + search bar)
        for label in self._sidebar_text_labels:
            label.setVisible(self._sidebar_expanded)

        # Search icon appears only when collapsed; full bar appears when expanded
        self._search_icon_btn.setVisible(not self._sidebar_expanded)

        # Show/hide section headers (Recents label)
        for header in self._sidebar_section_headers:
            header.setVisible(self._sidebar_expanded)

        # Show/hide decorative separators
        for sep in self._sidebar_separators:
            sep.setVisible(self._sidebar_expanded)

        # Update session items — show only dot in collapsed mode
        for w in self._session_widgets.values():
            w.set_expanded(self._sidebar_expanded)

    def _toggle_search(self):
        self._search_mode = self.search_btn.isChecked()

    def _on_image_pasted(self, image):
        """Handle Ctrl+V image paste from ChatLineEdit."""
        import base64
        from PySide6.QtCore import QBuffer, QIODevice
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        image.save(buf, "JPG", 80)
        self._pending_image_b64 = base64.b64encode(buf.data().data()).decode('utf-8')
        self._add_system_msg("📷 Image pasted — will attach to next message")

    def dragEnterEvent(self, event):
        if event.mimeData().hasImage() or event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            path = event.mimeData().urls()[0].toLocalFile()
            if path.lower().endswith(('.png','.jpg','.jpeg','.bmp')):
                img = QImage(path)
                if not img.isNull():
                    self._on_image_pasted(img)
                    return
        if event.mimeData().hasImage():
            img = QImage(event.mimeData().imageData())
            if not img.isNull():
                self._on_image_pasted(img)

    def _clear_current_chat(self):
        if not self._current_session:
            return

        # --- Confirmation dialog ---
        msg = QMessageBox(self)
        msg.setWindowTitle("Clear Chat")
        msg.setText("Clear all messages in this session?")
        msg.setInformativeText("This action cannot be undone.")
        msg.setIcon(QMessageBox.Warning)
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        msg.setDefaultButton(QMessageBox.Cancel)
        msg.setStyleSheet(f"""
            QMessageBox {{
                background: {COLORS['bg_dark']};
                color: {COLORS['text']};
            }}
            QMessageBox QLabel {{
                color: {COLORS['text']};
                font-size: 13px;
            }}
            QPushButton {{
                background: {COLORS['btn_secondary']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 6px 18px;
                font-size: 13px;
                min-width: 70px;
            }}
            QPushButton:hover {{ background: {COLORS['btn_secondary_hover']}; }}
            QPushButton[text="Yes"] {{
                background: {COLORS['btn_danger']};
                border-color: {COLORS['accent_red']};
                color: {COLORS['accent_red']};
            }}
            QPushButton[text="Yes"]:hover {{ background: {COLORS['btn_danger_hover']}; }}
        """)

        if msg.exec() != QMessageBox.Yes:
            return

        self._current_session["chat_history"] = []
        session_manager.save_session(self._current_session)
        self._analyzer_history.clear()
        self._codewriter_history.clear()
        self._vision_history.clear()
        self._render_chat_history()
        self._add_system_msg("🗑 Chat cleared")


    def _classify_intent(self, content, has_image=False):
        if has_image:
            return "vision"
        lower = content.lower()
        if "Diagnostic Report" in content:
            return "analyze_and_fix"
        fix_kw = ["fix","clean","delete","remove","freeze","create","add",
                  "change","modify","light","camera","move","rotate","scale",
                  "rename","setup","bake","merge","reduce","optimize"]
        if any(k in lower for k in fix_kw):
            return "analyze_and_fix"
        return "general"

    def _sanitize_node_names(self, code):
        code = re.sub(r"'(\|+)([^'|]+)'", lambda m: f"'{m.group(2)}'", code)
        code = re.sub(r'"(\|+)([^"|]+)"', lambda m: f'"{{m.group(2)}}"', code)
        return code

    # -----------------------------------------------------------------------
    # Chat actions
    # -----------------------------------------------------------------------
    def _add_bubble(self, role, text=""):
        bubble = MessageBubble(role, text)
        bubble.run_code.connect(self._run_code)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)
        QTimer.singleShot(50, self._scroll_to_bottom)
        return bubble

    def _add_system_msg(self, text):
        self._add_bubble("system", text)
        if self._current_session:
            session_manager.add_message(self._current_session, "system", text)

    def _scroll_to_bottom(self):
        sb = self.chat_scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_send(self):
        if self._is_busy or not self._current_session:
            return
        text = self.input_field.text().strip()
        img_b64 = self._pending_image_b64 or self._pending_screenshot
        if not text and not img_b64:
            return
        self.input_field.clear()
        self._agentic_iter = 0

        if self._search_mode and text:
            text = f"[SEARCH_MODE] Please search for: {text}"
            self.search_btn.setChecked(False)
            self._search_mode = False

        self._add_bubble("user", text or "[Image attached]")

        session_manager.add_message(self._current_session, "user", text, img_b64)
        if img_b64:
            self._pending_image_b64 = None
            self._pending_screenshot = None
        self._start_ai(text, has_image=bool(img_b64))

    def _on_scan(self):
        if self._is_busy or not self._current_session:
            return
        dcc = self._current_session.get("dcc", "")
        self._add_bubble("user", "🔍 Scanning scene...")
        self._set_dcc_loading("Scanning...")
        self._dcc_worker = DCCWorker(dcc_connector.run_scan, dcc)
        self._dcc_worker.finished.connect(self._on_scan_done)
        self._dcc_worker.start()

    @Slot(bool, str)
    def _on_scan_done(self, success, result):
        self._clear_dcc_loading()
        if not success:
            self._add_system_msg(f"⚠ Scan failed: {result}")
            return
        msg_text = "Please analyse this scene:\n\n" + result
        session_manager.add_message(self._current_session, "user", msg_text)
        self._start_ai(msg_text)

    def _on_screenshot(self):
        if not self._current_session:
            return
        dcc = self._current_session.get("dcc", "")
        self._set_dcc_loading("Capturing...")
        self._dcc_worker = DCCWorker(dcc_connector.take_screenshot, dcc)
        self._dcc_worker.finished.connect(self._on_screenshot_done)
        self._dcc_worker.start()

    @Slot(bool, str)
    def _on_screenshot_done(self, success, result):
        self._clear_dcc_loading()
        if success:
            self._pending_screenshot = result
            self._add_system_msg("📷 Viewport captured — will attach to next message")
        else:
            self._add_system_msg(f"⚠ Screenshot failed: {result}")

    def _set_dcc_loading(self, label="Working..."):
        """Show loading state on Send button and disable scan actions."""
        self.send_btn.setEnabled(False)
        self.send_btn.setText(label)
        self.screenshot_btn.setEnabled(False)

    def _clear_dcc_loading(self):
        """Restore Send button and re-enable scan actions."""
        self.send_btn.setText("Send ›")
        if not self._is_busy:
            self.send_btn.setEnabled(True)
        self.screenshot_btn.setEnabled(True)

    # -----------------------------------------------------------------------
    # AI streaming
    # -----------------------------------------------------------------------
    def _start_ai(self, user_text, has_image=False):
        self._is_busy = True
        self._current_response = ""
        self._original_msg = user_text
        self.send_btn.setEnabled(False)
        mode = self._settings.get("mode", "single")
        dcc = self._current_session.get("dcc", "") if self._current_session else ""
        chat_hist = self._current_session.get("chat_history", []) if self._current_session else []
        search = user_text.startswith("[SEARCH_MODE]") if user_text else False

        if mode == "single":
            self._agent_phase = "single"
            settings = app_settings.get_agent_settings(self._settings, "single", dcc)
            self._current_bubble = self._add_bubble("assistant")
            self._start_worker(chat_hist, settings, search)
        else:
            intent = self._classify_intent(user_text, has_image)
            if intent == "vision":
                self._agent_phase = "vision"
                self._vision_history.append({"role":"user","content":user_text})
                settings = app_settings.get_agent_settings(self._settings, "vision", dcc)
                self._current_bubble = self._add_bubble("vision")
                self._start_worker(self._vision_history, settings)
            elif intent == "analyze_and_fix":
                self._agent_phase = "analyzer"
                self._analyzer_history.append({"role":"user","content":user_text})
                settings = app_settings.get_agent_settings(self._settings, "analyzer", dcc)
                self._current_bubble = self._add_bubble("analyzer")
                self._start_worker(self._analyzer_history, settings, search)
            else:
                self._agent_phase = "analyzer"
                self._analyzer_history.append({"role":"user","content":user_text})
                settings = app_settings.get_agent_settings(self._settings, "analyzer", dcc)
                self._current_bubble = self._add_bubble("analyzer")
                self._start_worker(self._analyzer_history, settings, search)

    def _start_worker(self, messages, agent_settings, search_mode=False):
        self._scan_suppressed = False   # reset per-call
        self._worker = ai_backend.StreamWorker(messages, agent_settings, search_mode=search_mode)
        self._worker.token.connect(self._on_token)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    @Slot(str)
    def _on_token(self, token):
        self._current_response += token
        # Suppress [SCAN_SCENE] from appearing in chat bubble
        if "[SCAN_SCENE]" in self._current_response:
            if not self._scan_suppressed:
                self._scan_suppressed = True
                if self._current_bubble:
                    self._current_bubble.hide()
            return  # don't render — _on_done handles the scan
        if self._current_bubble:
            self._current_bubble.append_text(token)
        QTimer.singleShot(10, self._scroll_to_bottom)

    @Slot()
    def _on_done(self):
        response = self._current_response
        if self._current_bubble:
            self._current_bubble.finalize()
        if self._current_session:
            session_manager.add_message(self._current_session, "assistant", response)
            session_manager.save_session(self._current_session)

        mode = self._settings.get("mode", "single")
        dcc = self._current_session.get("dcc", "") if self._current_session else ""

        # [SCAN_SCENE] intercept — analyzer requests a scan (non-blocking)
        if self._agent_phase in ("analyzer","single") and response.strip() == "[SCAN_SCENE]":
            self._add_system_msg("🔍 AI requested a scan...")
            self._set_dcc_loading("Scanning...")
            self._dcc_worker = DCCWorker(dcc_connector.run_scan, dcc)
            def _on_ai_scan_done(success, scan, _resp=response):
                self._clear_dcc_loading()
                if success:
                    scan_msg = "Latest scene data (DO NOT output [SCAN_SCENE] again):\n\n" + scan
                    session_manager.add_message(self._current_session, "user", scan_msg)
                    self._analyzer_history.append({"role":"user","content":scan_msg})
                    QTimer.singleShot(100, lambda: self._start_ai(scan_msg))
                else:
                    self._add_system_msg(f"⚠ Scan failed: {scan}")
                    self._reset_busy()
            self._dcc_worker.finished.connect(_on_ai_scan_done)
            self._dcc_worker.start()
            return

        # Save to per-agent history
        if self._agent_phase == "analyzer":
            self._analyzer_history.append({"role":"assistant","content":response})
        elif self._agent_phase == "codewriter":
            self._codewriter_history.append({"role":"assistant","content":response})
        elif self._agent_phase == "vision":
            self._vision_history.append({"role":"assistant","content":response})

        # Multi-agent: analyzer done → start codewriter
        if self._agent_phase == "analyzer" and mode == "multi":
            self._agent_phase = "codewriter"
            self._current_response = ""
            self._current_bubble = self._add_bubble("codewriter")
            cw_msg = (f"Scene analysis:\n{response}\n\n"
                      f"User request: {self._original_msg}\n\n"
                      "Write ONE complete self-contained code block.")
            self._codewriter_history.append({"role":"user","content":cw_msg})
            cw_settings = app_settings.get_agent_settings(self._settings, "codewriter", dcc)
            self._start_worker(self._codewriter_history, cw_settings)
            return

        # Context management
        self._msg_count_since_summary += 1

        self._reset_busy()

    def _reset_busy(self):
        self._agent_phase = "idle"
        self._is_busy = False
        self.send_btn.setEnabled(True)
        self._worker = None

    @Slot(str)
    def _on_error(self, msg):
        self._add_system_msg(f"⚠ Error: {msg}")
        self._agent_phase = "idle"
        self._is_busy = False
        self.send_btn.setEnabled(True)
        self._worker = None

    # -----------------------------------------------------------------------
    # Code execution
    # -----------------------------------------------------------------------
    def _run_code(self, code):
        if not self._current_session:
            return
        dcc = self._current_session.get("dcc", "")
        code = self._sanitize_node_names(code)
        self._set_dcc_loading("Running...")

        self._dcc_worker = DCCWorker(dcc_connector.send_code, dcc, code)

        def _on_run_done(success, result, _code=code):
            self._clear_dcc_loading()
            if success:
                self._add_system_msg(f"✅ Code executed\n{result[:200]}")
                QTimer.singleShot(500, self._agentic_check)
            else:
                self._add_system_msg(f"⚠ Execution error: {result}")
            # Update the code block widget result badge
            for i in range(self.chat_layout.count()):
                item = self.chat_layout.itemAt(i)
                if item and item.widget():
                    bubble = item.widget()
                    if isinstance(bubble, MessageBubble):
                        for j in range(bubble.code_container.count()):
                            cb_item = bubble.code_container.itemAt(j)
                            if cb_item and cb_item.widget():
                                cb = cb_item.widget()
                                if isinstance(cb, CodeBlockWidget) and cb.code == _code:
                                    cb.show_result(success, result[:100] if success else result[:200])
                                    break

        self._dcc_worker.finished.connect(_on_run_done)
        self._dcc_worker.start()

    def _agentic_check(self):
        """Auto-check: take viewport screenshot → Vision agent → verify fix."""
        if not self._current_session:
            return
        self._agentic_iter += 1
        if self._agentic_iter > 3:
            self._add_system_msg("🔁 Max auto-check iterations reached (3)")
            self._agentic_iter = 0
            return
        self._add_system_msg(f"🔄 Auto-checking result... ({self._agentic_iter}/3)")
        dcc = self._current_session.get("dcc", "")
        success, img_b64 = dcc_connector.take_screenshot(dcc)
        if not success:
            self._add_system_msg("⚠ Could not capture viewport for auto-check")
            return
        check_msg = ("Here is the viewport after running the fix. "
                     "Does it look correct? If yes, confirm. If not, suggest another fix.")
        session_manager.add_message(self._current_session, "user", check_msg, img_b64)
        self._vision_history.append({"role":"user","content":check_msg,"image_b64":img_b64})
        settings = app_settings.get_agent_settings(
            self._settings, "vision",
            self._current_session.get("dcc", ""))
        self._agent_phase = "vision"
        self._is_busy = True
        self.send_btn.setEnabled(False)
        self._current_response = ""
        self._current_bubble = self._add_bubble("vision")
        self._start_worker(self._vision_history, settings)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(get_app_stylesheet())

    # Apply palette
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(COLORS['bg_dark']))
    palette.setColor(QPalette.WindowText, QColor(COLORS['text']))
    palette.setColor(QPalette.Base, QColor(COLORS['bg_input']))
    palette.setColor(QPalette.Text, QColor(COLORS['text']))
    palette.setColor(QPalette.Button, QColor(COLORS['bg_panel']))
    palette.setColor(QPalette.ButtonText, QColor(COLORS['text']))
    palette.setColor(QPalette.Highlight, QColor(COLORS['accent_blue']))
    app.setPalette(palette)

    window = StudioWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
