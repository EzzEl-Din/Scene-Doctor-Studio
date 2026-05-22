"""
main.py — Scene Doctor Studio
Standalone PySide6 app for AI-powered scene diagnostics.
Connects to Maya/Blender via TCP sockets.
Built by Ezz El-Din
"""
import sys, os, re, json
from datetime import datetime

# Fix Windows rendering glitches — must be set before Qt imports
os.environ["QT_OPENGL"] = "software"
os.environ["QSG_RHI_BACKEND"] = "opengl"

def resource_path(filename: str) -> str:
    """Return absolute path to a bundled resource.
    Works in development (uses script dir) and in PyInstaller EXE (uses _MEIPASS)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, filename)

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QFrame, QSplitter,
    QMessageBox, QSizePolicy, QMenu, QDialog, QLineEdit,
    QGraphicsOpacityEffect, QTextEdit
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QThread, QPropertyAnimation, QEasingCurve, QPoint, Property, QSize, QEvent, QRectF, QUrl
from PySide6.QtGui import QFont, QIcon, QAction, QImage, QPixmap, QPalette, QColor, QPainter, QPen, QDesktopServices
from PySide6.QtSvg import QSvgRenderer

import session_manager
import dcc_connector
import settings as app_settings
import ai_backend

from ui_widgets import (
    COLORS, THEMES, MessageBubble, SessionItemWidget, TypingIndicator,
    CodeBlockWidget, ChatLineEdit, AGENT_LABELS, AGENT_COLORS,
    get_app_stylesheet, set_theme
)
from studio_settings_dialog import SettingsDialog


# ---------------------------------------------------------------------------
# Intent Classification — structural, not keyword-based
# ---------------------------------------------------------------------------

def needs_code_writer(user_message):
    """Returns True if the user wants ACTION (code) — not just analysis.
    
    Smart detection:
    - Imperative sentences (commands) → wants code
    - Questions → wants analysis
    - Confirmations after AI asked "want me to fix?" → wants code
    - Short affirmatives → wants code (follow-up to a suggestion)
    """
    msg = user_message.lower().strip()
    # Strip system-injected context prefixes
    msg = re.sub(r'\[session context.*?\[end context\]\s*', '', msg, flags=re.DOTALL)
    msg = re.sub(r'\[user profile.*?\[end profile\]\s*', '', msg, flags=re.DOTALL)
    msg = re.sub(r'\[.*?\]\s*', '', msg).strip()
    words = msg.split()
    
    # Short confirmations = user said yes to a previous offer
    if len(words) <= 3 and any(w in words for w in ('yes', 'yeah', 'yep', 'sure', 'ok', 'do', 'go')):
        return True
    
    # Questions are analysis, not code requests
    if msg.endswith('?'):
        return False
    if msg.startswith(('what ', 'why ', 'how ', 'is ', 'are ', 'can ', 'does ', 'do ')):
        return False
    
    # Imperative mood: first word is a verb (action command)
    # If the sentence starts with a base verb → it's a command
    first_word = words[0] if words else ''
    action_verbs = {'fix', 'create', 'add', 'make', 'build', 'generate', 'write',
                    'rename', 'delete', 'remove', 'change', 'modify', 'update',
                    'apply', 'set', 'move', 'rotate', 'scale', 'assign', 'run',
                    'execute', 'clean', 'merge', 'split', 'duplicate', 'replace',
                    'connect', 'disconnect', 'export', 'import', 'convert', 'optimize'}
    if first_word in action_verbs:
        return True
    
    # "do it", "go ahead", "let's go" patterns
    if any(p in msg for p in ('do it', 'go ahead', "let's go", 'fix it', 'run it')):
        return True
    
    # User explicitly asks for code (even mid-sentence)
    if any(p in msg for p in ('write the code', 'write code', 'give me the code',
                               'write a script', 'write the script', 'code it',
                               'in artifact', 'as artifact', 'save as artifact')):
        return True
    
    return False


def is_scan_request(user_message):
    """Returns True if this is a scan/diagnostic-only request.
    
    Detects intent to INSPECT without modifying.
    """
    msg = user_message.lower().strip()
    # Strip system-injected context prefixes
    msg = re.sub(r'\[session context.*?\[end context\]\s*', '', msg, flags=re.DOTALL)
    msg = re.sub(r'\[user profile.*?\[end profile\]\s*', '', msg, flags=re.DOTALL)
    msg = re.sub(r'\[.*?\]\s*', '', msg).strip()
    
    # Direct scan commands
    if msg.startswith(('scan', 'check', 'analyze', 'diagnose', 'inspect', 'audit')):
        return True
    
    # "What's wrong" / "any issues" / "is it clean" patterns
    if any(p in msg for p in ("what's wrong", "any issues", "any problems",
                               "health check", "is it clean", "is it ok",
                               "how's the", "status of")):
        return True
    
    return False


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
# Custom Plus Menu (iOS-style toggles)
# ---------------------------------------------------------------------------
class ToggleSwitch(QWidget):
    """iOS-style toggle switch — blue when active."""
    toggled = Signal(bool)
    
    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self._anim_pos = 1.0 if checked else 0.0  # 0.0 = off, 1.0 = on
        self.setFixedSize(44, 24)
        self.setCursor(Qt.PointingHandCursor)
        
        # Animation
        self._anim = QPropertyAnimation(self, b"anim_pos")
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
    
    def get_anim_pos(self):
        return self._anim_pos
    
    def set_anim_pos(self, value):
        self._anim_pos = value
        self.update()
    
    anim_pos = Property(float, get_anim_pos, set_anim_pos)
    
    def isChecked(self):
        return self._checked
    
    def setChecked(self, value):
        self._checked = value
        self._anim_pos = 1.0 if value else 0.0
        self.update()
    
    def mousePressEvent(self, event):
        self._checked = not self._checked
        
        self._anim.setStartValue(self._anim_pos)
        self._anim.setEndValue(1.0 if self._checked else 0.0)
        self._anim.start()
        
        self.toggled.emit(self._checked)
    
    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QColor, QPainterPath, QLinearGradient
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        t = self._anim_pos
        
        # Track color — interpolate gray → blue
        r = int(55  + (37  - 55)  * t)   # #374151 → #2563eb
        g = int(65  + (99  - 65)  * t)
        b = int(81  + (235 - 81)  * t)
        
        if not self._checked and t == 0.0:
            track_color = QColor(COLORS['border_hover'])
        else:
            track_color = QColor(r, g, b)
        
        # Draw track
        path = QPainterPath()
        path.addRoundedRect(0, 0, 44, 24, 12, 12)
        painter.fillPath(path, track_color)
        
        # Draw thumb — slides from left to right
        thumb_x = 2 + (22 * t)
        
        # Thumb shadow
        painter.setBrush(QColor(0, 0, 0, 30))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(int(thumb_x) + 1, 3, 20, 20)
        
        # Thumb
        painter.setBrush(QColor(COLORS.get('btn_primary_text', '#FFFFFF')))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(int(thumb_x), 2, 20, 20)
        
        painter.end()


class PlusMenuPopup(QWidget):
    """Floating popup with toggle switches — alien-style, rounded, clean."""
    
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)  # enables true rounded corners
        self.setObjectName("plusMenuOuter")
        self._toggles = {}
        self._all_labels = []
        self._warning_label = None
        self._rows = []
        self._ROW_HOVER = COLORS['btn_secondary']
        self._ROW_NORMAL = COLORS['bg_input']
        self._setup_ui()
    
    def _setup_ui(self):
        # Outer layout — transparent padding holds the inner card
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)  # room for drop shadow
        outer.setSpacing(0)
        
        # Inner card — the actual rounded content
        self._card = QFrame()
        self._card.setObjectName("plusMenuCard")
        self._card.setStyleSheet(f"""
            QFrame#plusMenuCard {{
                background: {COLORS['bg_input']};
                border: 1px solid {COLORS['accent_teal']};
                border-radius: 14px;
            }}
            QFrame#plusMenuCard QLabel {{
                background: transparent;
                border: none;
                padding: 0;
                margin: 0;
            }}
            QFrame#plusMenuCard QWidget {{
                border: none;
            }}
        """)
        outer.addWidget(self._card)
        
        # Drop shadow on the card for alien glow effect
        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        shadow = QGraphicsDropShadowEffect(self._card)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(45, 212, 191, 70))  # teal glow
        self._card.setGraphicsEffect(shadow)
        
        # Card content
        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(2)
        
        items = [
            ("viewport",   "Viewport Image",  False, True),
            ("search",     "Search Mode",     False, False),
            ("steps",      "Step-by-step",    False, False),
            ("autorun",    "Auto-run Code",   True,  False),
            ("plan",       "Plan Mode",       False, False),
        ]
        
        for key, label, has_warning, is_action in items:
            row = self._make_row(key, label, has_warning, is_action)
            layout.addWidget(row)
        
        self.setFixedWidth(276)  # outer width (card is 260 + 16 padding)
    
    def _make_row(self, key, label, has_warning, is_action):
        row = QWidget()
        row.setObjectName(f"plusRow_{key}")
        row.setFixedHeight(40)
        row.setStyleSheet(f"""
            QWidget#plusRow_{key} {{
                background: {self._ROW_NORMAL};
                border: none;
                border-radius: 8px;
            }}
        """)
        self._rows.append(row)
        
        # Hover effect
        row.enterEvent = lambda e, r=row, k=key: r.setStyleSheet(
            f"QWidget#plusRow_{k} {{ background: {self._ROW_HOVER}; border: none; border-radius: 8px; }}"
        )
        row.leaveEvent = lambda e, r=row, k=key: r.setStyleSheet(
            f"QWidget#plusRow_{k} {{ background: {self._ROW_NORMAL}; border: none; border-radius: 8px; }}"
        )
        
        layout = QHBoxLayout(row)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(10)
        
        # Label styling
        warning_suffix = "  \u26a0" if has_warning else ""
        color = COLORS['status_warning'] if has_warning else COLORS['text']
        weight = 'bold' if has_warning else '500'
        lbl = QLabel(label + warning_suffix)
        lbl.setFixedHeight(24)
        lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        lbl.setStyleSheet(f"""
            color: {color};
            font-size: 13px;
            font-weight: {weight};
            background: transparent;
            border: none;
            padding: 0;
        """)
        
        if has_warning:
            self._warning_label = lbl
        else:
            self._all_labels.append(lbl)
            
        layout.addWidget(lbl)
        layout.addStretch()
        
        if not is_action:
            toggle = ToggleSwitch(checked=False)
            toggle.toggled.connect(lambda checked, k=key: self._on_toggle(k, checked))
            layout.addWidget(toggle, 0, Qt.AlignVCenter)
            self._toggles[key] = toggle
        else:
            # Arrow indicator for action items
            arrow = QLabel("\u203a")
            arrow.setFixedSize(20, 24)
            arrow.setAlignment(Qt.AlignCenter)
            arrow.setStyleSheet(
                f"color: {COLORS['accent_teal']}; font-size: 18px; font-weight: bold; "
                f"background: transparent; border: none;"
            )
            layout.addWidget(arrow, 0, Qt.AlignVCenter)
            # Connect click on the row to the action handler
            row.setCursor(Qt.PointingHandCursor)
            row.mousePressEvent = lambda e, k=key: self._on_action(k)
        
        return row
    
    def _on_action(self, key):
        self.close()
        if key == "viewport":
            self.parent()._on_screenshot()
    
    def _on_toggle(self, key, checked):
        main = self.parent()
        if key == "search":
            main._toggle_search_mode(checked)
        elif key == "steps":
            main._toggle_step_mode(checked)
        elif key == "autorun":
            main._toggle_auto_run(checked)
        elif key == "plan":
            main._toggle_plan_mode(checked)
    
    def _apply_popup_theme(self):
        main_win = self.parent()
        if not main_win or not hasattr(main_win, "_theme"):
            return
        t = main_win._theme
        
        self._card.setStyleSheet(f"""
            QFrame#plusMenuCard {{
                background: {t['bg_input']};
                border: 1px solid {t['accent_teal']};
                border-radius: 14px;
            }}
            QFrame#plusMenuCard QLabel {{
                background: transparent;
                border: none;
                padding: 0;
                margin: 0;
            }}
            QFrame#plusMenuCard QWidget {{
                border: none;
            }}
        """)
        
        # Row hover/normal colors
        self._ROW_HOVER = t['btn_secondary']
        self._ROW_NORMAL = t['bg_input']
        
        # Update existing row backgrounds (scoped by object name)
        for row in self._rows:
            obj_name = row.objectName()
            row.setStyleSheet(f"""
                QWidget#{obj_name} {{
                    background: {self._ROW_NORMAL};
                    border: none;
                    border-radius: 8px;
                }}
            """)
        
        # Update all row labels
        for label in self._all_labels:
            label.setStyleSheet(f"""
                color: {t['text']};
                font-size: 13px;
                font-weight: 500;
                background: transparent;
                border: none;
                padding: 0;
            """)
        
        # Warning label stays orange
        if self._warning_label:
            self._warning_label.setStyleSheet(f"""
                color: {t['status_warning']};
                font-size: 13px;
                font-weight: bold;
                background: transparent;
                border: none;
                padding: 0;
            """)
    
    def set_toggle(self, key, value):
        if key in self._toggles:
            self._toggles[key].setChecked(value)
    
    def show_at(self, pos):
        self.adjustSize()
        # Ensure popup stays within screen bounds
        screen = QApplication.primaryScreen().availableGeometry()
        popup_h = self.height()
        popup_w = self.width()
        
        # Try above the button
        y = pos.y() - popup_h - 4
        if y < screen.top():
            # Show below instead
            y = pos.y() + 36 + 4
        
        x = pos.x()
        if x + popup_w > screen.right():
            x = screen.right() - popup_w - 8
        if x < screen.left():
            x = screen.left() + 8
        
        self.move(x, y)
        self.show()


class DCCTabStrip(QWidget):
    """Horizontal DCC filter strip — sits inside the sidebar below the header."""
    dcc_selected = Signal(str)  # emits "maya", "blender", "all"

    DCC_COLORS = {
        "maya": "#2563eb",
        "blender": "#f97316",
        "houdini": "#f59e0b",
        "nuke": "#10b981",
    }
    DCC_LABELS = {"maya": "M", "blender": "B", "houdini": "H", "nuke": "N"}
    DCC_ICON_FILES = {
        "maya": "autodesk-maya-seeklogo.png",
        "blender": "blender-seeklogo.png",
        "houdini": "houdini_.png",
        "nuke": "nuke_.png",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self._buttons = {}
        self._active_dcc = "all"
        self._icon_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dcc icon")
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 2, 8, 2)   # 2px top/bottom keeps buttons unclipped
        main_layout.setSpacing(6)

        self._container = QFrame()
        self._container.setObjectName("dccTabContainer")
        self._container.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._container.setStyleSheet(f"""
            QFrame#dccTabContainer {{
                background: {COLORS['bg_secondary']};
                border-radius: 10px;
            }}
        """)
        layout = QHBoxLayout(self._container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        main_layout.addWidget(self._container)
        main_layout.addStretch()

        # "All" button
        self._all_btn = self._make_tab_btn("all", "All")
        self._all_btn.setChecked(True)
        layout.addWidget(self._all_btn)

        # Installed DCC buttons
        from settings import load_settings
        _s = load_settings()
        installed = _s.get("installed_plugins") or _s.get(
            "installed_dccs", ["maya", "blender"]
        )
        for dcc in installed:
            btn = self._make_dcc_icon_btn(dcc)
            layout.addWidget(btn)
            self._buttons[dcc] = btn

        # + button — outside the pill, right-aligned in main_layout
        self._add_btn = QPushButton("+")
        self._add_btn.setObjectName("dccAddBtn")
        self._add_btn.setFixedSize(28, 28)
        self._add_btn.setToolTip("Add DCC support")
        self._add_btn.setStyleSheet(f"""
            QPushButton#dccAddBtn {{
                background: {COLORS['bg_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                color: {COLORS['text_muted']};
                font-size: 18px;
                padding: 0px;
            }}
            QPushButton#dccAddBtn:hover {{
                border-color: {COLORS['accent_teal']};
                color: {COLORS['accent_teal']};
            }}
        """)
        main_layout.addWidget(self._add_btn)

    def _make_tab_btn(self, key, label):
        btn = QPushButton(label)
        btn.setObjectName(f"dccTab_{key}")
        btn.setFixedSize(32, 32)
        btn.setCheckable(True)
        btn.setStyleSheet(f"""
            QPushButton#dccTab_{key} {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 8px;
                color: {COLORS['text_muted']};
                font-size: 12px;
                font-weight: 600;
                padding: 0px;
            }}
            QPushButton#dccTab_{key}:hover {{
                background: {COLORS['bg_panel']};
            }}
            QPushButton#dccTab_{key}:checked {{
                background: {COLORS['bg_panel']};
                border-color: {COLORS['accent_teal']};
                color: {COLORS['text']};
            }}
        """)
        btn.clicked.connect(lambda checked, k=key: self._on_tab_clicked(k))
        return btn

    def _make_dcc_icon_btn(self, dcc):
        """Create DCC button using PNG icon from dcc icon folder."""
        btn = QPushButton()
        btn.setObjectName(f"dccIcon_{dcc}")
        btn.setFixedSize(32, 32)
        btn.setCheckable(True)
        btn.setToolTip(dcc.capitalize())

        icon_path = os.path.join(self._icon_dir, self.DCC_ICON_FILES.get(dcc, ""))
        if os.path.exists(icon_path):
            btn.setIcon(QIcon(icon_path))
            btn.setIconSize(QSize(20, 20))
        else:
            btn.setText(self.DCC_LABELS.get(dcc, dcc[0].upper()))

        btn.setStyleSheet(f"""
            QPushButton#dccIcon_{dcc} {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 8px;
                color: {COLORS['text_muted']};
                font-size: 12px;
                font-weight: bold;
                padding: 0px;
            }}
            QPushButton#dccIcon_{dcc}:hover {{
                background: {COLORS['bg_panel']};
            }}
            QPushButton#dccIcon_{dcc}:checked {{
                background: {COLORS['bg_panel']};
                border-color: {COLORS['accent_teal']};
            }}
        """)
        btn.clicked.connect(lambda checked, d=dcc: self._on_tab_clicked(d))
        return btn

    def _apply_dcc_theme(self, t):
        self._container.setStyleSheet(f"""
            QFrame#dccTabContainer {{
                background: {t.get('bg_secondary')};
                border-radius: 10px;
            }}
        """)
        
        self._all_btn.setStyleSheet(f"""
            QPushButton#dccTab_all {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 8px;
                color: {t.get('text_muted')};
                font-size: 12px;
                font-weight: 600;
                padding: 0px;
            }}
            QPushButton#dccTab_all:hover {{
                background: {t.get('bg_panel')};
            }}
            QPushButton#dccTab_all:checked {{
                background: {t.get('bg_panel')};
                border-color: {t.get('accent_teal')};
                color: {t.get('text')};
            }}
        """)

        for dcc, btn in self._buttons.items():
            btn.setStyleSheet(f"""
                QPushButton#dccIcon_{dcc} {{
                    background: transparent;
                    border: 1px solid transparent;
                    border-radius: 8px;
                    color: {t.get('text_muted')};
                    font-size: 12px;
                    font-weight: bold;
                    padding: 0px;
                }}
                QPushButton#dccIcon_{dcc}:hover {{
                    background: {t.get('bg_panel')};
                }}
                QPushButton#dccIcon_{dcc}:checked {{
                    background: {t.get('bg_panel')};
                    border-color: {t.get('accent_teal')};
                }}
            """)

        self._add_btn.setStyleSheet(f"""
            QPushButton#dccAddBtn {{
                background: {t.get('bg_secondary')};
                border: 1px solid {t.get('border')};
                border-radius: 8px;
                color: {t.get('text_muted')};
                font-size: 18px;
                padding: 0px;
            }}
            QPushButton#dccAddBtn:hover {{
                border-color: {t.get('accent_teal')};
                color: {t.get('accent_teal')};
            }}
        """)

    def _on_tab_clicked(self, dcc):
        self._all_btn.setChecked(dcc == "all")
        for key, btn in self._buttons.items():
            btn.setChecked(key == dcc)
        self._active_dcc = dcc
        self.dcc_selected.emit(dcc)

    def add_dcc(self, dcc):
        if dcc not in self._buttons:
            btn = self._make_dcc_icon_btn(dcc)
            layout = self._container.layout()
            layout.addWidget(btn)
            self._buttons[dcc] = btn

    def remove_dcc(self, dcc):
        """Remove a DCC tab from the strip after the plugin is uninstalled."""
        btn = self._buttons.pop(dcc, None)
        if btn is not None:
            layout = self._container.layout()
            layout.removeWidget(btn)
            btn.deleteLater()
            # If the removed tab was active, fall back to "All"
            if self._active_dcc == dcc:
                self._all_btn.setChecked(True)
                self._active_dcc = "all"
                self.dcc_selected.emit("all")

class PluginStoreWindow(QDialog):
    """Plugin store — install / uninstall / update DCC plugins from GitHub.

    Drives off the GitHub registry and the local PluginManager. Users only
    download what they need; uninstall removes plugin files but keeps
    sessions and chat history.
    """

    dcc_installed = Signal(str)     # emitted after a plugin is installed
    dcc_uninstalled = Signal(str)   # emitted after a plugin is uninstalled

    DISPLAY_DEFAULTS = {
        "maya":     {"color": "#5a8fc4"},
        "blender":  {"color": "#f97316"},
        "houdini":  {"color": "#f59e0b"},
        "nuke":     {"color": "#10b981"},
        "comfyui":  {"color": "#7c3aed"},
        "unreal":   {"color": "#8b5cf6"},
    }

    ICON_FILES = {
        "maya":    "autodesk-maya-seeklogo.png",
        "blender": "blender-seeklogo.png",
        "houdini": "houdini_.png",
        "nuke":    "nuke_.png",
    }

    @staticmethod
    def _hex_to_rgba(hex_color, alpha=34):
        """Convert '#RRGGBB' to a Qt-friendly 'rgba(r, g, b, a/255)' string.
        Qt parses '#RRGGBBAA' as ARGB (not RGBA), so we use rgba() to avoid
        accidental color shifts when adding transparency.
        """
        try:
            h = hex_color.lstrip('#')
            if len(h) == 3:
                h = ''.join(c * 2 for c in h)
            r = int(h[0:2], 16)
            g = int(h[2:4], 16)
            b = int(h[4:6], 16)
            a = max(0, min(255, int(alpha))) / 255.0
            return f"rgba({r}, {g}, {b}, {a:.3f})"
        except Exception:
            return hex_color

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plugin Store")
        self.setFixedSize(560, 580)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        from plugin_manager import PluginManager
        self._plugin_manager = PluginManager()
        self._card_widgets = {}
        self._cards_layout = None
        self._status_label = None

        self._build_chrome()
        self._refresh_cards()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_chrome(self):
        if self.layout():
            QWidget().setLayout(self.layout())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QFrame()
        container.setObjectName("pluginStoreContainer")
        container.setStyleSheet(f"""
            QFrame#pluginStoreContainer {{
                background: {COLORS['bg_panel']};
                border: 1px solid {COLORS['border']};
                border-radius: 16px;
            }}
            QFrame#pluginStoreContainer QLabel {{
                background: transparent;
                border: none;
            }}
            QFrame#pluginStoreContainer QWidget {{
                background: transparent;
            }}
        """)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        header_layout = QHBoxLayout()
        title = QLabel("Plugin Store")
        title.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 18px; font-weight: 700;"
        )

        close_btn = QPushButton("X")
        close_btn.setObjectName("pluginStoreClose")
        close_btn.setFixedSize(32, 32)
        close_btn.clicked.connect(self.close)
        close_btn.setStyleSheet(f"""
            QPushButton#pluginStoreClose {{
                background: {COLORS['btn_secondary']};
                border: none;
                border-radius: 16px;
                color: {COLORS['text']};
                font-size: 16px;
                font-weight: bold;
                padding: 0px;
            }}
            QPushButton#pluginStoreClose:hover {{
                color: {COLORS.get('btn_primary_text', COLORS['text'])};
                background: {COLORS['accent_red']};
            }}
        """)
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(close_btn)
        layout.addLayout(header_layout)

        subtitle = QLabel("Install only the DCCs you need. Plugins live on GitHub.")
        subtitle.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 13px;")
        layout.addWidget(subtitle)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px;"
        )
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        cards_widget = QWidget()
        cards_widget.setStyleSheet("background: transparent;")
        self._cards_layout = QVBoxLayout(cards_widget)
        self._cards_layout.setSpacing(8)
        self._cards_layout.addStretch()

        scroll.setWidget(cards_widget)
        layout.addWidget(scroll)

        outer.addWidget(container)

    # ------------------------------------------------------------------
    # Registry resolution + refresh
    # ------------------------------------------------------------------
    def _resolve_plugins(self):
        """Build the list of plugin_ids to display, plus a manifest for each.
        Tries the GitHub registry first; falls back to whatever is locally
        installed plus built-in defaults so the dialog still works offline.
        """
        ids = self._plugin_manager.fetch_registry()
        if not ids:
            installed = self._plugin_manager.get_installed()
            ids = list(dict.fromkeys(["maya", "blender"] + installed))

        manifests = {}
        for pid in ids:
            local = self._plugin_manager.get_local_manifest(pid)
            if local:
                manifests[pid] = local
                continue
            remote = self._plugin_manager.fetch_plugin_manifest(pid)
            if remote:
                manifests[pid] = remote
            else:
                fallback = self._plugin_manager.fallback_manifest(pid)
                if fallback:
                    manifests[pid] = fallback
                else:
                    manifests[pid] = {
                        "id": pid,
                        "name": pid.capitalize(),
                        "description": "",
                        "version": "?",
                        "files": [],
                        "coming_soon": True,
                    }
        return ids, manifests

    def _refresh_cards(self):
        if self._cards_layout is None:
            return
        while self._cards_layout.count() > 1:
            item = self._cards_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._card_widgets.clear()

        ids, manifests = self._resolve_plugins()
        installed_ids = set(self._plugin_manager.get_installed())

        for pid in ids:
            manifest = manifests.get(pid, {})
            local = self._plugin_manager.get_local_manifest(pid)
            local_version = (local or {}).get("version") if pid in installed_ids else None
            card = self._make_plugin_card(
                pid, manifest, pid in installed_ids, local_version
            )
            self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)

    # ------------------------------------------------------------------
    # Card construction
    # ------------------------------------------------------------------
    def _make_plugin_card(self, plugin_id, manifest, is_installed, local_version=None):
        card = QFrame()
        card.setObjectName(f"card_{plugin_id}")
        card.setStyleSheet(f"""
            QFrame#card_{plugin_id} {{
                background: {COLORS['bg_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
            }}
            QFrame#card_{plugin_id}:hover {{
                border-color: {COLORS['border_hover']};
            }}
        """)

        layout = QHBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        color = (manifest.get("color")
                 or self.DISPLAY_DEFAULTS.get(plugin_id, {}).get("color", "#666"))
        icon_label = QLabel()
        icon_label.setFixedSize(36, 36)
        icon_label.setAlignment(Qt.AlignCenter)

        icon_filename = self.ICON_FILES.get(plugin_id, "")
        icon_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "dcc icon",
            icon_filename,
        ) if icon_filename else ""
        if icon_filename and os.path.isfile(icon_path):
            pixmap = QPixmap(icon_path).scaled(
                28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            icon_label.setPixmap(pixmap)
            icon_label.setStyleSheet(
                f"background: {COLORS['bg_dark']}; border: none; border-radius: 8px;"
            )
        else:
            icon_label.setText((manifest.get("name") or plugin_id)[0].upper())
            icon_label.setStyleSheet(f"""
                background: {self._hex_to_rgba(color, 34)};
                color: {color};
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
            """)
        layout.addWidget(icon_label)

        info_widget = QWidget()
        info_widget.setStyleSheet("background: transparent; border: none;")
        info_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(2)

        name = QLabel(manifest.get("name") or plugin_id.capitalize())
        name.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 14px; font-weight: 600; "
            f"background: transparent; border: none;"
        )
        desc = QLabel(manifest.get("description", ""))
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; "
            f"background: transparent; border: none;"
        )
        info_layout.addWidget(name)
        info_layout.addWidget(desc)
        layout.addWidget(info_widget, 1)

        btn_holder = QWidget()
        btn_holder.setFixedWidth(170)
        btn_holder.setStyleSheet("background: transparent; border: none;")
        btn_holder_layout = QHBoxLayout(btn_holder)
        btn_holder_layout.setContentsMargins(0, 0, 0, 0)
        btn_holder_layout.setSpacing(6)
        btn_holder_layout.addStretch()

        remote_version = manifest.get("version")
        needs_update = (
            is_installed and remote_version and local_version
            and remote_version != local_version
        )

        if is_installed and needs_update:
            update_btn = QPushButton(f"↑ Update to {remote_version}")
            update_btn.setFixedHeight(32)
            update_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {self._hex_to_rgba(COLORS['accent_orange'], 34)};
                    border: 1px solid {COLORS['accent_orange']};
                    border-radius: 8px;
                    color: {COLORS['accent_orange']};
                    font-size: 12px;
                    padding: 4px 12px;
                }}
                QPushButton:hover {{
                    background: {COLORS['accent_orange']};
                    color: {COLORS.get('btn_primary_text', COLORS['text'])};
                }}
            """)
            update_btn.clicked.connect(
                lambda checked, pid=plugin_id: self._update_plugin(pid)
            )
            btn_holder_layout.addWidget(update_btn)

        elif is_installed:
            installed_label = QPushButton("✓ Installed")
            installed_label.setEnabled(False)
            installed_label.setFixedHeight(32)
            installed_label.setFixedWidth(92)
            installed_label.setStyleSheet(f"""
                QPushButton {{
                    background: {self._hex_to_rgba(COLORS['status_success'], 34)};
                    border: 1px solid {COLORS['status_success']};
                    border-radius: 8px;
                    color: {COLORS['status_success']};
                    font-size: 12px;
                    padding: 4px 10px;
                }}
                QPushButton:disabled {{
                    background: {self._hex_to_rgba(COLORS['status_success'], 34)};
                    border: 1px solid {COLORS['status_success']};
                    color: {COLORS['status_success']};
                }}
            """)

            uninstall_btn = QPushButton("Remove")
            uninstall_btn.setFixedWidth(64)
            uninstall_btn.setFixedHeight(32)
            uninstall_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: 1px solid {COLORS['border']};
                    border-radius: 8px;
                    color: {COLORS['text_muted']};
                    font-size: 11px;
                    padding: 4px 8px;
                }}
                QPushButton:hover {{
                    border-color: {COLORS['accent_red']};
                    color: {COLORS['accent_red']};
                }}
            """)
            uninstall_btn.clicked.connect(
                lambda checked, pid=plugin_id: self._uninstall_plugin(pid)
            )
            btn_holder_layout.addWidget(installed_label)
            btn_holder_layout.addWidget(uninstall_btn)

        elif manifest.get("coming_soon"):
            soon_btn = QPushButton("Coming Soon")
            soon_btn.setEnabled(False)
            soon_btn.setFixedHeight(32)
            soon_btn.setFixedWidth(110)
            soon_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: 1px solid {COLORS['border']};
                    border-radius: 8px;
                    color: {COLORS['text_muted']};
                    font-size: 12px;
                    padding: 4px 12px;
                }}
                QPushButton:disabled {{
                    background: transparent;
                    border: 1px solid {COLORS['border']};
                    color: {COLORS['text_muted']};
                }}
            """)
            btn_holder_layout.addWidget(soon_btn)

        else:
            install_btn = QPushButton("⬇ Install")
            install_btn.setFixedHeight(32)
            install_btn.setFixedWidth(96)
            install_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {self._hex_to_rgba(COLORS['accent_blue'], 34)};
                    border: 1px solid {COLORS['accent_blue']};
                    border-radius: 8px;
                    color: {COLORS['accent_blue']};
                    font-size: 12px;
                    padding: 4px 12px;
                }}
                QPushButton:hover {{
                    background: {COLORS['accent_blue']};
                    color: {COLORS.get('btn_primary_text', COLORS['text'])};
                }}
            """)
            install_btn.clicked.connect(
                lambda checked, pid=plugin_id: self._install_plugin(pid)
            )
            btn_holder_layout.addWidget(install_btn)

        layout.addWidget(btn_holder)
        self._card_widgets[plugin_id] = {
            "card": card,
            "btn_holder": btn_holder,
        }
        return card

    # ------------------------------------------------------------------
    # Status / loading helpers
    # ------------------------------------------------------------------
    def _set_card_loading(self, plugin_id, loading):
        widgets = self._card_widgets.get(plugin_id)
        if not widgets:
            return
        holder = widgets.get("btn_holder")
        if holder is None:
            return
        for child in holder.findChildren(QPushButton):
            child.setEnabled(not loading)

    def _update_card_status(self, plugin_id, message):
        if self._status_label is None:
            return
        self._status_label.setText(f"{plugin_id}: {message}")
        self._status_label.setVisible(bool(message))
        QApplication.processEvents()

    def _clear_status(self):
        if self._status_label is None:
            return
        self._status_label.setText("")
        self._status_label.setVisible(False)

    def _show_success(self, message):
        QMessageBox.information(self, "Plugin Store", message)

    def _show_error(self, message):
        QMessageBox.warning(self, "Plugin Store", message)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    def _persist_installed(self):
        """Mirror PluginManager's installed list into settings.json."""
        try:
            from settings import load_settings, save_settings
            installed = self._plugin_manager.get_installed()
            settings = load_settings()
            settings["installed_plugins"] = installed
            settings["installed_dccs"] = installed
            save_settings(settings)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Install / uninstall / update actions
    # ------------------------------------------------------------------
    def _install_plugin(self, plugin_id):
        self._set_card_loading(plugin_id, True)
        self._update_card_status(plugin_id, "Starting...")

        success, message = self._plugin_manager.install(
            plugin_id, lambda m: self._update_card_status(plugin_id, m)
        )

        self._clear_status()
        self._set_card_loading(plugin_id, False)

        if success:
            self._persist_installed()
            self.dcc_installed.emit(plugin_id)
            self._refresh_cards()
            self._show_success(message)
        else:
            self._show_error(message)

    def _uninstall_plugin(self, plugin_id):
        confirm = QMessageBox.question(
            self,
            "Remove Plugin",
            f"Remove {plugin_id.capitalize()} support?\n"
            f"Your sessions and chat history will be kept.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        success, message = self._plugin_manager.uninstall(plugin_id)
        if success:
            self._persist_installed()
            self.dcc_uninstalled.emit(plugin_id)
            self._refresh_cards()
        else:
            self._show_error(message)

    def _update_plugin(self, plugin_id):
        self._set_card_loading(plugin_id, True)
        self._update_card_status(plugin_id, "Updating...")

        success, message = self._plugin_manager.update(
            plugin_id, lambda m: self._update_card_status(plugin_id, m)
        )

        self._clear_status()
        self._set_card_loading(plugin_id, False)

        if success:
            self._persist_installed()
            self.dcc_installed.emit(plugin_id)
            self._refresh_cards()
            self._show_success(message)
        else:
            self._show_error(message)


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
        _svg_path = resource_path("svgs/scene_doctor_icon_transparent.svg")
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
        self._force_artifact_next = False
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
        self._active_dcc_filter = "all"
        # Apply saved theme first
        theme = self._settings.get("theme", "dark")
        set_theme(theme)
        # Then apply accent color override (after theme sets defaults)
        accent = self._settings.get("accent_color")
        if accent:
            COLORS["accent_blue"] = accent
            COLORS["accent_teal"] = accent
            COLORS["accent_blue_hover"] = self._darken(accent, 0.85)
            COLORS["status_info"] = accent
        self._apply_global_palette()
        self._summary_worker = None
        self._chat_message_widgets = []

        self._build_ui()
        self._apply_theme(theme)
        self._load_sessions_list()
        self._restore_sidebar_state()

        if self._sessions:
            self._select_session(self._sessions[0]["session_id"])

    # -----------------------------------------------------------------------
    # UI Construction
    # -----------------------------------------------------------------------
    def _build_collapsed_sidebar(self):
        """Build a separate 56px icon rail for collapsed sidebar state.
        
        Returns a QWidget with vertically centered icons, proper spacing,
        and a flexible spacer to separate top and bottom sections.
        """
        collapsed = QWidget()
        collapsed.setFixedWidth(56)
        collapsed.setStyleSheet(f"""
            QWidget {{
                background: {COLORS['bg_sidebar']};
            }}
        """)
        collapsed.setObjectName("collapsedSidebar")
        
        layout = QVBoxLayout(collapsed)
        layout.setContentsMargins(0, 8, 0, 10)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignHCenter)
        
        # TOP SECTION: Logo with hover toggle icon overlay
        # Create a container widget for logo + overlay
        logo_container = QWidget()
        logo_container.setFixedSize(40, 40)
        logo_container.setStyleSheet("background: transparent;")
        
        # Logo button (32x32 icon, centered)
        logo_btn = QPushButton(logo_container)
        if self._logo_pixmap:
            logo_btn.setIcon(QIcon(self._logo_pixmap))
            logo_btn.setIconSize(QSize(32, 32))
        logo_btn.setFixedSize(40, 40)
        logo_btn.setToolTip("Expand sidebar")
        logo_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                padding: 0;
            }
        """)
        logo_btn.clicked.connect(self._toggle_sidebar)
        logo_btn.move(0, 0)
        
        # Toggle icon overlay (hidden by default, shown on hover)
        # Styled like the other icon buttons with visible background
        toggle_overlay = QPushButton(logo_container)
        toggle_overlay.setObjectName("collapsedLogoOverlay")
        toggle_overlay.setIcon(self._create_sidebar_panel_icon())
        toggle_overlay.setIconSize(QSize(16, 16))
        toggle_overlay.setFixedSize(40, 40)
        toggle_overlay.setCursor(Qt.PointingHandCursor)
        toggle_overlay.setStyleSheet(f"""
            QPushButton#collapsedLogoOverlay {{
                background: {COLORS['bg_panel']};
                border: none;
                border-radius: 8px;
                padding: 0px;
            }}
            QPushButton#collapsedLogoOverlay:hover {{
                background: {COLORS['bg_secondary']};
            }}
            QPushButton#collapsedLogoOverlay:pressed {{
                background: {COLORS['border']};
            }}
        """)
        toggle_overlay.clicked.connect(self._toggle_sidebar)
        toggle_overlay.move(0, 0)
        toggle_overlay.hide()
        
        # Create opacity effect for smooth fade in/out
        overlay_opacity = QGraphicsOpacityEffect(toggle_overlay)
        toggle_overlay.setGraphicsEffect(overlay_opacity)
        overlay_opacity.setOpacity(0.0)
        
        # Create simple fade animation (reuse for both in and out)
        fade_anim = QPropertyAnimation(overlay_opacity, b"opacity")
        fade_anim.setDuration(120)  # Fast and snappy
        fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        
        # Store references
        self._collapsed_logo_btn = logo_btn
        self._collapsed_toggle_overlay = toggle_overlay
        self._overlay_fade_anim = fade_anim
        self._overlay_opacity = overlay_opacity
        
        # Simple hover handlers
        def on_enter(e):
            toggle_overlay.show()
            fade_anim.stop()
            fade_anim.setStartValue(overlay_opacity.opacity())
            fade_anim.setEndValue(1.0)
            fade_anim.start()
        
        def on_leave(e):
            fade_anim.stop()
            fade_anim.setStartValue(overlay_opacity.opacity())
            fade_anim.setEndValue(0.0)
            fade_anim.finished.connect(lambda: toggle_overlay.hide() if overlay_opacity.opacity() == 0.0 else None)
            fade_anim.start()
        
        # Install event handlers
        logo_container.enterEvent = on_enter
        logo_container.leaveEvent = on_leave
        
        layout.addWidget(logo_container, 0, Qt.AlignHCenter)
        
        # + button (New Session)
        new_btn = self._make_icon_button("+", "New Session", self._on_new_session)
        layout.addWidget(new_btn, 0, Qt.AlignHCenter)
        
        # Search button
        search_btn = self._make_icon_button("\U0001f50d", "Search sessions", self._expand_to_search)
        layout.addWidget(search_btn, 0, Qt.AlignHCenter)
        
        # Flexible spacer (pushes bottom section down)
        layout.addStretch(1)
        
        # BOTTOM SECTION: Settings, DCC Setup
        settings_btn = self._make_icon_button("\u2699", "Settings", self._on_settings)
        layout.addWidget(settings_btn, 0, Qt.AlignHCenter)
        
        dcc_setup_btn = self._make_icon_button("\u26a1", "DCC Setup", self._show_dcc_setup)
        layout.addWidget(dcc_setup_btn, 0, Qt.AlignHCenter)
        
        # Store references to all icon buttons for theme updates
        self._collapsed_icon_buttons = [new_btn, search_btn, settings_btn, dcc_setup_btn]
        
        return collapsed
    
    def keyPressEvent(self, event):
        """Handle global keyboard shortcuts."""
        modifiers = event.modifiers()
        key = event.key()
        
        # Ctrl+K → New Session
        if modifiers == Qt.ControlModifier and key == Qt.Key_K:
            self._on_new_session()
            event.accept()
            return
        
        # Ctrl+B → Toggle Sidebar
        if modifiers == Qt.ControlModifier and key == Qt.Key_B:
            self._toggle_sidebar()
            event.accept()
            return
        
        super().keyPressEvent(event)

    def _build_ui(self):
        central = QWidget()
        self._central = central
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # === Collapsible sidebar (Claude-style) ===
        self._sidebar_expanded_width = 260
        self._sidebar_collapsed_width = 56  # slim icon rail
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

        # --- Header: logo + title + hamburger ---
        _header_widget = QWidget()
        _header_widget.setFixedHeight(48)
        _header_widget.setStyleSheet("background: transparent;")
        header_row = QHBoxLayout(_header_widget)
        header_row.setContentsMargins(10, 0, 6, 0)
        header_row.setSpacing(8)

        # Logo icon (SVG)
        _svg_path = resource_path("svgs/scene_doctor_icon_transparent.svg")
        self._sidebar_icon_lbl = QLabel()
        self._sidebar_icon_lbl.setFixedSize(32, 32)
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
            self._logo_pixmap = _icon_pix
        else:
            self._logo_pixmap = None
        header_row.addWidget(self._sidebar_icon_lbl)

        # Title
        self._sidebar_title = QLabel("Scene Doctor")
        self._sidebar_title.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 15px; font-weight: 700;"
            f" letter-spacing: 0.3px; background: transparent;"
        )
        self._sidebar_title.setAttribute(Qt.WA_TransparentForMouseEvents)
        header_row.addWidget(self._sidebar_title)
        self._sidebar_text_labels.append(self._sidebar_title)

        header_row.addStretch()

        # Sidebar toggle with panel icon
        self.sidebar_toggle_btn = QPushButton()
        panel_icon = self._create_sidebar_panel_icon()
        self.sidebar_toggle_btn.setIcon(panel_icon)
        self.sidebar_toggle_btn.setIconSize(QSize(16, 16))
        self.sidebar_toggle_btn.setFixedSize(32, 32)
        self.sidebar_toggle_btn.setToolTip("Toggle sidebar (Ctrl+B)")
        self.sidebar_toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {COLORS['text_muted']};
                font-size: 16px;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background: {COLORS['btn_secondary']};
                color: {COLORS['text']};
            }}
        """)
        self.sidebar_toggle_btn.clicked.connect(self._toggle_sidebar)
        header_row.addWidget(self.sidebar_toggle_btn)

        sb_layout.addWidget(_header_widget)
        self._sidebar_header = _header_widget

        # --- DCC Tab Strip (horizontal, inside sidebar) ---
        self._dcc_strip = DCCTabStrip()
        self._dcc_strip.dcc_selected.connect(self._on_dcc_filter_changed)
        self._dcc_strip._add_btn.clicked.connect(self._show_plugin_store)
        sb_layout.addWidget(self._dcc_strip)
        self._sidebar_text_labels.append(self._dcc_strip)

        # Divider after DCC strip
        _dcc_sep = QFrame()
        _dcc_sep.setFrameShape(QFrame.HLine)
        _dcc_sep.setFixedHeight(1)
        _dcc_sep.setStyleSheet(f"background: {COLORS['divider']}; border: none;")
        sb_layout.addWidget(_dcc_sep)
        self._sidebar_separators.append(_dcc_sep)
        sb_layout.addSpacing(8)

        # --- Top actions ---
        self._new_session_btn = self._make_sidebar_btn("+", "New Session", self._on_new_session)
        sb_layout.addWidget(self._new_session_btn)
        sb_layout.addSpacing(8)

        # --- Icon buttons for collapsed state (Phase 4.1) ---
        # Create new session icon button
        self._new_session_icon_btn = self._make_icon_button("+", "New Session", self._on_new_session)
        self._new_session_icon_btn.setVisible(False)  # initially hidden (shown when collapsed)
        sb_layout.addWidget(self._new_session_icon_btn)

        # --- Session search bar (hidden when collapsed) ---
        self._search_bar = QLineEdit()
        self._search_bar.setPlaceholderText("Search sessions...")
        self._search_bar.setFixedHeight(30)
        self._search_bar.setStyleSheet(f"""
            QLineEdit {{
                background: {COLORS['bg_input']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
                padding: 4px 10px;
                font-size: 12px;
            }}
            QLineEdit:focus {{ border-color: {COLORS['accent_teal']}; }}
        """)

        # Set placeholder text color
        _pal = self._search_bar.palette()
        _pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(COLORS['text_muted']))
        self._search_bar.setPalette(_pal)

        self._search_bar.textChanged.connect(self._filter_sessions)
        self._search_bar_container = QWidget()
        self._search_bar_container.setStyleSheet("background: transparent;")
        sb_search_layout = QHBoxLayout(self._search_bar_container)
        sb_search_layout.setContentsMargins(4, 0, 4, 2)
        sb_search_layout.addWidget(self._search_bar)
        sb_layout.addWidget(self._search_bar_container)
        self._sidebar_text_labels.append(self._search_bar_container)

        # Search icon shown ONLY when sidebar is collapsed (already exists, verified in Phase 4.1)
        self._search_icon_btn = self._make_icon_button("\U0001f50d", "Search sessions", self._expand_to_search)
        self._search_icon_btn.setVisible(False)  # hidden when expanded
        sb_layout.addWidget(self._search_icon_btn)

        sb_layout.addSpacing(8)

        # --- Separator ---
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setFixedHeight(1)
        sep1.setStyleSheet(f"background: {COLORS['divider']}; border: none;")
        sb_layout.addWidget(sep1)
        self._sidebar_separators.append(sep1)

        sb_layout.addSpacing(4)

        # --- Recents label ---
        self._recents_label = QLabel("Recents")
        self._recents_label.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 10px; font-weight: bold; letter-spacing: 1px;"
            f"padding: 2px 10px 4px 10px; background: transparent;"
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
        self._settings_btn = self._make_sidebar_btn("\u2699", "Settings", self._on_settings)
        sb_layout.addWidget(self._settings_btn)
        self._dcc_setup_btn = self._make_sidebar_btn("\u26a1", "DCC Setup", self._show_dcc_setup)
        sb_layout.addWidget(self._dcc_setup_btn)

        # --- Icon buttons for collapsed state - bottom section (Phase 4.1) ---
        # Create settings icon button
        self._settings_icon_btn = self._make_icon_button("\u2699", "Settings", self._on_settings)
        self._settings_icon_btn.setVisible(False)  # initially hidden (shown when collapsed)
        sb_layout.addWidget(self._settings_icon_btn)

        # Create DCC setup icon button
        self._dcc_setup_icon_btn = self._make_icon_button("\u26a1", "DCC Setup", self._show_dcc_setup)
        self._dcc_setup_icon_btn.setVisible(False)  # initially hidden (shown when collapsed)
        sb_layout.addWidget(self._dcc_setup_icon_btn)

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

        # Build collapsed sidebar (separate widget)
        self._collapsed_sidebar = self._build_collapsed_sidebar()
        self._collapsed_sidebar.setVisible(False)  # Initially hidden (sidebar starts expanded)

        root.addWidget(self.sidebar)
        root.addWidget(self._collapsed_sidebar)

        # === Right chat panel ===
        self.chat_panel = QWidget()
        chat_panel = self.chat_panel
        chat_panel.setStyleSheet(f"background: {COLORS['bg_panel']};")
        cp_layout = QVBoxLayout(chat_panel)
        cp_layout.setContentsMargins(0, 0, 0, 0)
        cp_layout.setSpacing(0)

        # Chat header row: label (left) + Doc Mode + Clear Chat (right)
        self.chat_header_widget = QWidget()
        _chat_header_widget = self.chat_header_widget
        _chat_header_widget.setFixedHeight(48)
        _chat_header_widget.setStyleSheet(f"""
            QWidget {{
                background: {COLORS['bg_panel']};
                border-bottom: 1px solid {COLORS['border']};
            }}
        """)
        _ch_row = QHBoxLayout(_chat_header_widget)
        _ch_row.setContentsMargins(16, 0, 12, 0)
        _ch_row.setSpacing(8)

        self.chat_header = QLabel("Select or create a session")
        self.chat_header.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 14px; font-weight: bold; background: transparent;"
        )
        _ch_row.addWidget(self.chat_header, 1)

        # --- Connection status dot ---
        self._conn_dot = QLabel("●")
        self._conn_dot.setFixedSize(16, 16)
        self._conn_dot.setAlignment(Qt.AlignCenter)
        self._conn_dot.setStyleSheet("color: #374151; font-size: 10px; background: transparent;")
        _ch_row.addWidget(self._conn_dot)

        # Connection check timer
        self._conn_timer = QTimer(self)
        self._conn_timer.timeout.connect(self._update_connection_indicator)
        self._conn_timer.start(3000)

        # --- Artifact toggle button ---
        _artifact_icon_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "svgs", "icon_artifact.svg"
        )
        self._artifact_btn = QPushButton()
        self._artifact_btn.setFixedHeight(28)
        self._artifact_btn.setFixedWidth(34)
        self._artifact_btn.setToolTip("View Artifacts")
        if os.path.exists(_artifact_icon_path):
            self._artifact_btn.setIcon(QIcon(_artifact_icon_path))
            self._artifact_btn.setIconSize(QSize(20, 20))
        else:
            self._artifact_btn.setText("📎")
        self._artifact_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                color: {COLORS['text_muted']};
                padding: 0px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                border-color: {COLORS['accent_teal']};
                color: {COLORS['accent_teal']};
            }}
        """)
        self._artifact_btn.clicked.connect(self._on_view_artifacts)
        _ch_row.addWidget(self._artifact_btn)

        # --- Doc Mode toggle button ---
        _header_btn_style = f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                color: {COLORS['text_muted']};
                padding: 0 10px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                border-color: {COLORS['accent_blue']};
                color: {COLORS['accent_blue']};
            }}
            QPushButton:checked {{
                background: #1e3a5f;
                border-color: {COLORS['accent_blue']};
                color: {COLORS['accent_blue']};
            }}
        """
        self._doc_mode_btn = QPushButton("\U0001f4c4 Doc")
        self._doc_mode_btn.setCheckable(True)
        self._doc_mode_btn.setFixedHeight(28)
        self._doc_mode_btn.setToolTip("Documentation mode \u2014 AI generates a structured scene report")
        self._doc_mode_btn.setStyleSheet(_header_btn_style)
        self._doc_mode_btn.clicked.connect(self._on_doc_mode_toggled)
        _ch_row.addWidget(self._doc_mode_btn)

        # --- Clear Chat button ---
        _clear_header_btn_style = f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                color: {COLORS['text_muted']};
                padding: 0 10px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                border-color: #ef4444;
                color: #ef4444;
                background: rgba(239, 68, 68, 0.08);
            }}
        """
        self._header_clear_btn = QPushButton("Clear")
        self._header_clear_btn.setFixedHeight(28)
        self._header_clear_btn.setToolTip("Clear chat history")
        self._header_clear_btn.setStyleSheet(_clear_header_btn_style)
        self._header_clear_btn.clicked.connect(self._clear_current_chat)
        _ch_row.addWidget(self._header_clear_btn)

        cp_layout.addWidget(_chat_header_widget)

        # Chat messages scroll area
        self.chat_scroll = QScrollArea()
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chat_content = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_content)
        self.chat_layout.setContentsMargins(16, 8, 16, 8)
        self.chat_layout.setSpacing(4)
        self.chat_layout.setAlignment(Qt.AlignTop)
        self.chat_scroll.setWidget(self.chat_content)
        _chat_bg = COLORS.get('bg_chat', COLORS['bg_dark'])
        self.chat_scroll.setStyleSheet(f"QScrollArea {{ background: {_chat_bg}; border: none; }}")
        self.chat_content.setStyleSheet(f"background: {_chat_bg};")
        self.chat_scroll.viewport().setStyleSheet(f"background: {_chat_bg};")
        cp_layout.addWidget(self.chat_scroll, 1)

        # ---------------------------------------------------------------
        # Input panel card — two rows inside a single rounded container
        # ---------------------------------------------------------------
        _btn_icon_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "svgs")
        _scan_scene_icon = os.path.join(_btn_icon_dir, "icon_scan_scene.svg")
        _scan_sel_icon = os.path.join(_btn_icon_dir, "icon_scan_selection.svg")

        self._bottom_wrapper = QWidget()
        self._bottom_wrapper.setObjectName("inputWrapper")
        _chat_bg_color = COLORS.get('bg_chat', COLORS['bg_panel'])
        self._bottom_wrapper.setStyleSheet(
            f"QWidget#inputWrapper {{ background: {_chat_bg_color}; }}"
        )
        _bw_layout = QHBoxLayout(self._bottom_wrapper)
        _bw_layout.setContentsMargins(48, 10, 48, 16)
        _bw_layout.setSpacing(0)

        _card = QFrame()
        _card.setObjectName("inputCard")
        self._input_frame = _card  # Store reference for theme updates
        _card.setStyleSheet(f"""
            QFrame#inputCard {{
                background: {COLORS['bg_input']};
                border: 1px solid {COLORS['border']};
                border-radius: 24px;
            }}
        """)
        _card_layout = QVBoxLayout(_card)
        _bw_layout.addWidget(_card)
        _card_layout.setContentsMargins(20, 14, 14, 12)
        _card_layout.setSpacing(4)

        # Row 1: Text input (auto-expanding)
        self.input_field = QTextEdit()
        self.input_field.setObjectName("chatInput")
        self.input_field.setPlaceholderText("Write a message...")
        self.input_field.setMinimumHeight(36)
        self.input_field.setMaximumHeight(36)
        self.input_field.setFrameShape(QFrame.NoFrame)
        self.input_field.document().setDocumentMargin(0)
        self.input_field.setContentsMargins(0, 0, 0, 0)
        self.input_field.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.input_field.setStyleSheet(f"""
            QTextEdit#chatInput {{
                background: transparent;
                border: 0px;
                color: {COLORS['text']};
                font-size: 14px;
                padding: 6px 6px;
                font-family: 'Segoe UI';
                outline: none;
            }}
        """)
        # Force viewport to be transparent (inherits card bg)
        self.input_field.viewport().setStyleSheet("background: transparent; border: 0px;")
        self.input_field.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.input_field.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.input_field.setAcceptRichText(False)
        # Auto-resize as user types
        self.input_field.textChanged.connect(self._auto_resize_input)
        # Handle Enter/Shift+Enter
        self.input_field.installEventFilter(self)
        _card_layout.addWidget(self.input_field)

        # Token counter — inside input frame, right-aligned between text and buttons
        self._token_label = QLabel("~0 tokens")
        self._token_label.setObjectName("tokenLabel")
        self._token_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._token_label.setFixedHeight(16)
        self._token_label.setStyleSheet(
            f"QLabel#tokenLabel {{ color: {COLORS['text_muted']}; font-size: 10px; "
            f"background: transparent; border: 0px; padding: 0 4px; }}"
        )
        self._token_label.setToolTip(
            "Estimated token usage for this session.\n"
            "Clear chat to reset. Tokens affect AI context length."
        )
        _card_layout.addWidget(self._token_label)

        # Row 2: Action bar
        _row2 = QWidget()
        _row2.setStyleSheet("background: transparent;")
        _row2_layout = QHBoxLayout(_row2)
        _row2_layout.setContentsMargins(0, 2, 0, 0)
        _row2_layout.setSpacing(6)
        _row2_layout.setAlignment(Qt.AlignVCenter)

        # [+] icon button
        self._plus_btn = QPushButton("+")
        self._plus_btn.setObjectName("plusBtn")
        self._plus_btn.setFixedSize(36, 36)
        self._plus_btn.setToolTip("More options")
        self._plus_btn.setVisible(True)
        self._plus_btn.setCursor(Qt.PointingHandCursor)
        self._plus_btn.setStyleSheet(f"""
            QPushButton#plusBtn {{
                background: {COLORS['btn_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 18px;
                color: {COLORS['text']};
                font-size: 18px;
                font-weight: bold;
                padding: 0px;
                margin: 0px;
            }}
            QPushButton#plusBtn:hover {{
                border-color: {COLORS['accent_blue']};
                background: {COLORS['btn_secondary_hover']};
                color: {COLORS['text']};
            }}
        """)
        self._plus_btn.clicked.connect(self._show_plus_menu)
        _row2_layout.addWidget(self._plus_btn)
        self._plus_btn.raise_()
        print(f"[UI] + button added: size={self._plus_btn.size()}, visible={self._plus_btn.isVisible()}, parent={self._plus_btn.parent()}")



        # Hidden stubs — required by _set_dcc_loading / _toggle_search
        self.screenshot_btn = QPushButton()
        self.screenshot_btn.setVisible(False)
        self.screenshot_btn.setEnabled(True)
        self.search_btn = QPushButton()
        self.search_btn.setCheckable(True)
        self.search_btn.setVisible(False)

        # Scan Scene pill button
        self._scan_btn = QPushButton(" Scan Scene")
        if os.path.exists(_scan_scene_icon):
            self._scan_btn.setIcon(QIcon(_scan_scene_icon))
            self._scan_btn.setIconSize(QSize(16, 16))
        else:
            self._scan_btn.setText("\u2299  Scan Scene")
        self._scan_btn.setMinimumHeight(32)
        self._scan_btn.setMaximumHeight(32)
        self._scan_btn.setToolTip("Scan full scene and send report to AI")
        self._scan_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {COLORS['border']};
                border-radius: 16px;
                color: {COLORS['text_muted']};
                font-size: 12px;
                padding: 0px 14px;
            }}
            QPushButton:hover {{
                border-color: {COLORS['accent_teal']};
                color: {COLORS['accent_teal']};
            }}
            QPushButton:disabled {{
                background: transparent;
                color: {COLORS['text_muted']};
                border-color: {COLORS['border']};
            }}
        """)
        self._scan_btn.clicked.connect(self._on_scan)
        _row2_layout.addWidget(self._scan_btn)

        # Scan Selection pill button
        self._quick_check_btn = QPushButton(" Scan Selection")
        if os.path.exists(_scan_sel_icon):
            self._quick_check_btn.setIcon(QIcon(_scan_sel_icon))
            self._quick_check_btn.setIconSize(QSize(16, 16))
        else:
            self._quick_check_btn.setText("\u2b21  Scan Selection")
        self._quick_check_btn.setMinimumHeight(32)
        self._quick_check_btn.setMaximumHeight(32)
        self._quick_check_btn.setToolTip("Analyze selected objects only")
        self._quick_check_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {COLORS['border']};
                border-radius: 16px;
                color: {COLORS['text_muted']};
                font-size: 12px;
                padding: 0px 14px;
            }}
            QPushButton:hover {{
                border-color: {COLORS['accent_teal']};
                color: {COLORS['accent_teal']};
            }}
            QPushButton:disabled {{
                background: transparent;
                color: {COLORS['text_muted']};
                border-color: {COLORS['border']};
            }}
        """)
        self._quick_check_btn.clicked.connect(self._on_quick_check)
        _row2_layout.addWidget(self._quick_check_btn)

        # Spacer
        _row2_layout.addStretch()

        # Mode dropdown
        self._current_mode = "normal"
        self._mode_btn = QPushButton("Normal \u25be")
        self._mode_btn.setMinimumHeight(32)
        self._mode_btn.setMaximumHeight(32)
        self._mode_btn.setMinimumWidth(90)
        self._mode_btn.setToolTip("Switch AI reasoning mode")
        self._mode_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {COLORS['border']};
                border-radius: 16px;
                color: {COLORS['text_muted']};
                font-size: 12px;
                padding: 0px 12px;
            }}
            QPushButton:hover {{
                border-color: {COLORS['accent_blue']};
                color: {COLORS['text']};
            }}
        """)
        self._mode_btn.clicked.connect(self._show_mode_menu)
        _row2_layout.addWidget(self._mode_btn)

        # Send button — teal arrow-up (text-based)
        self.send_btn = QPushButton()
        self.send_btn.setText("\u2191")
        self.send_btn.setFixedSize(36, 36)
        self.send_btn.setToolTip("Send (Enter)")
        self.send_btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['accent_teal']};
                border: none;
                border-radius: 18px;
                color: {COLORS.get('btn_primary_text', '#FFFFFF')};
                font-size: 18px;
                font-weight: bold;
                padding: 0px;
            }}
            QPushButton:hover {{
                background: {COLORS['accent_teal']};
            }}
            QPushButton:pressed {{
                background: {COLORS['accent_teal']};
            }}
            QPushButton:disabled {{
                background: {COLORS['border']};
                color: {COLORS['text_muted']};
            }}
        """)
        self.send_btn.clicked.connect(self._on_send)
        _row2_layout.addWidget(self.send_btn)

        _card_layout.addWidget(_row2)

        cp_layout.addWidget(self._bottom_wrapper)

        self._session_tokens = 0

        # Disclaimer under input card — matches chat area background
        self._disclaimer = QLabel("\u26a0 AI responses may contain errors \u2014 always review generated code before running.")
        self._disclaimer.setObjectName("inputDisclaimer")
        self._disclaimer.setAlignment(Qt.AlignCenter)
        _disc_bg = COLORS.get('bg_chat', COLORS['bg_dark'])
        self._disclaimer.setStyleSheet(
            f"QLabel#inputDisclaimer {{"
            f" color: {COLORS['text_muted']};"
            f" font-size: 10px;"
            f" padding: 8px 16px 10px 16px;"
            f" background: {_disc_bg};"
            f" border: none;"
            f"}}"
        )
        self._disclaimer.setWordWrap(True)
        cp_layout.addWidget(self._disclaimer)

        root.addWidget(chat_panel, 1)

        # === Unified Artifacts Panel (280px default, resizable via splitter) ===
        self._artifacts_panel = QWidget()
        self._artifacts_panel.setObjectName("artifactsPanel")
        self._artifacts_panel.setMinimumWidth(200)
        self._artifacts_panel.setMaximumWidth(600)
        self._artifacts_panel.setStyleSheet(f"""
            QWidget#artifactsPanel {{
                background: {COLORS['bg_sidebar']};
            }}
        """)
        _ap_main_layout = QVBoxLayout(self._artifacts_panel)
        _ap_main_layout.setContentsMargins(0, 0, 0, 0)
        _ap_main_layout.setSpacing(0)

        # --- State 1: List View ---
        self._ap_list_view = QWidget()
        _ap_lv_layout = QVBoxLayout(self._ap_list_view)
        _ap_lv_layout.setContentsMargins(12, 12, 12, 12)
        _ap_lv_layout.setSpacing(8)

        # List header: title + download-all
        _ap_header = QHBoxLayout()
        self._ap_title = QLabel("Artifacts")
        self._ap_title.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 14px; font-weight: bold; background: transparent;"
        )
        _ap_header.addWidget(self._ap_title)
        _ap_header.addStretch()

        self._ap_download_all_btn = QPushButton("\u2b07")
        self._ap_download_all_btn.setFixedSize(28, 28)
        self._ap_download_all_btn.setToolTip("Download all artifacts to Downloads folder")
        self._ap_download_all_btn.setCursor(Qt.PointingHandCursor)
        self._ap_download_all_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                color: {COLORS['text_muted']};
                font-size: 14px;
                padding: 0px;
            }}
            QPushButton:hover {{
                border-color: {COLORS['accent_teal']};
                color: {COLORS['accent_teal']};
            }}
        """)
        self._ap_download_all_btn.clicked.connect(self._download_all_artifacts)
        _ap_header.addWidget(self._ap_download_all_btn)

        # Trace log button — surface the tool-call audit trail as an artifact
        self._ap_trace_btn = QPushButton("\U0001f4cb")
        self._ap_trace_btn.setFixedSize(28, 28)
        self._ap_trace_btn.setToolTip("View tool-call trace for this session")
        self._ap_trace_btn.setCursor(Qt.PointingHandCursor)
        self._ap_trace_btn.setStyleSheet(self._ap_download_all_btn.styleSheet())
        self._ap_trace_btn.clicked.connect(self._show_trace_log)
        _ap_header.addWidget(self._ap_trace_btn)

        _ap_lv_layout.addLayout(_ap_header)

        # Scroll area for artifact rows
        self._ap_scroll = QScrollArea()
        self._ap_scroll.setWidgetResizable(True)
        self._ap_scroll.setFrameShape(QFrame.NoFrame)
        self._ap_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._ap_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._ap_content = QWidget()
        self._ap_content.setStyleSheet("background: transparent;")
        self._ap_list_layout = QVBoxLayout(self._ap_content)
        self._ap_list_layout.setContentsMargins(0, 0, 0, 0)
        self._ap_list_layout.setSpacing(4)
        self._ap_list_layout.addStretch()
        self._ap_scroll.setWidget(self._ap_content)
        _ap_lv_layout.addWidget(self._ap_scroll, 1)

        _ap_main_layout.addWidget(self._ap_list_view)

        # --- State 2: Viewer View ---
        self._ap_viewer_view = QWidget()
        _ap_vv_layout = QVBoxLayout(self._ap_viewer_view)
        _ap_vv_layout.setContentsMargins(0, 0, 0, 0)
        _ap_vv_layout.setSpacing(0)

        # Viewer header: Back + filename + Copy
        self._av_header = QWidget()
        self._av_header.setFixedHeight(44)
        self._av_header.setStyleSheet(f"background: {COLORS['bg_panel']}; border-bottom: 1px solid {COLORS['border']};")
        _av_h_layout = QHBoxLayout(self._av_header)
        _av_h_layout.setContentsMargins(8, 0, 8, 0)
        _av_h_layout.setSpacing(6)

        self._av_back_btn = QPushButton("\u2190 Back")
        self._av_back_btn.setFixedHeight(28)
        self._av_back_btn.setCursor(Qt.PointingHandCursor)
        self._av_back_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 6px;
                color: {COLORS['accent_teal']};
                font-size: 12px;
                padding: 0px 8px;
            }}
            QPushButton:hover {{
                background: {COLORS['btn_secondary']};
            }}
        """)
        self._av_back_btn.clicked.connect(self._artifact_viewer_back)
        _av_h_layout.addWidget(self._av_back_btn)

        self._av_filename = QLabel("")
        self._av_filename.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 12px; font-weight: 600; background: transparent;"
        )
        _av_h_layout.addWidget(self._av_filename, 1)

        self._av_copy_btn = QPushButton("\U0001f4cb Copy")
        self._av_copy_btn.setFixedHeight(28)
        self._av_copy_btn.setCursor(Qt.PointingHandCursor)
        self._av_copy_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                color: {COLORS['text_muted']};
                font-size: 11px;
                padding: 0px 8px;
            }}
            QPushButton:hover {{
                border-color: {COLORS['accent_teal']};
                color: {COLORS['accent_teal']};
            }}
        """)
        self._av_copy_btn.clicked.connect(self._copy_artifact_content)
        _av_h_layout.addWidget(self._av_copy_btn)

        # Run button (for .py artifacts)
        self._av_run_btn = QPushButton("\u25b6 Run")
        self._av_run_btn.setFixedHeight(28)
        self._av_run_btn.setCursor(Qt.PointingHandCursor)
        self._av_run_btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['accent_green']};
                border: none;
                border-radius: 6px;
                color: {COLORS.get('btn_primary_text', '#FFFFFF')};
                font-size: 11px;
                font-weight: bold;
                padding: 0px 10px;
            }}
            QPushButton:hover {{
                background: {COLORS['status_success']};
            }}
        """)
        self._av_run_btn.clicked.connect(self._run_artifact_code)
        _av_h_layout.addWidget(self._av_run_btn)

        _ap_vv_layout.addWidget(self._av_header)

        # Content area
        self._av_content = QTextEdit()
        self._av_content.setReadOnly(True)
        self._av_content.setStyleSheet(f"""
            QTextEdit {{
                background: #090C12;
                color: #E8E6E1;
                border: none;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 13px;
                padding: 16px;
            }}
        """)
        _ap_vv_layout.addWidget(self._av_content, 1)

        _ap_main_layout.addWidget(self._ap_viewer_view)

        # Start: viewer hidden, list hidden, whole panel hidden
        self._ap_viewer_view.setVisible(False)
        self._ap_list_view.setVisible(True)
        self._artifacts_panel.setVisible(False)
        self._current_artifact_path = None
        self._ap_state = "hidden"  # "hidden", "list", "viewer"

        # --- QSplitter between chat and artifacts panel ---
        self._chat_artifact_splitter = QSplitter(Qt.Horizontal)
        self._chat_artifact_splitter.setHandleWidth(4)
        self._chat_artifact_splitter.setChildrenCollapsible(False)
        self._chat_artifact_splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {COLORS['border']};
                width: 4px;
            }}
            QSplitter::handle:hover {{
                background-color: {COLORS['accent_teal']};
            }}
            QSplitter::handle:pressed {{
                background-color: {COLORS['accent_teal']};
            }}
        """)
        self._chat_artifact_splitter.addWidget(chat_panel)
        self._chat_artifact_splitter.addWidget(self._artifacts_panel)
        
        # Restore saved panel width
        saved_ap_width = self._settings.get("artifacts_panel_width", 280)
        # Start with panel hidden (0 width) — will animate open when needed
        self._chat_artifact_splitter.setSizes([1000, 0])
        
        # Save width on resize
        self._chat_artifact_splitter.splitterMoved.connect(self._on_artifacts_panel_resized)
        
        root.addWidget(self._chat_artifact_splitter, 1)

    def _apply_theme(self, theme_name):
        """Call this whenever theme changes."""
        self._current_theme_name = theme_name
        self._theme = THEMES.get(theme_name, THEMES["dark"])
        t = self._theme
        
        # Apply to all components
        if hasattr(self, '_input_frame'):
            self._apply_input_theme()
            self._apply_scan_buttons_theme()
            self._apply_plus_btn_theme()
        
        # If popup exists, restyle it
        if hasattr(self, '_plus_popup') and self._plus_popup:
            self._plus_popup._apply_popup_theme()
        
        # Main window background
        self.setStyleSheet(f"QMainWindow {{ background: {t['bg_dark']}; }}")
        
        # Chat panel
        if hasattr(self, 'chat_panel'):
            self.chat_panel.setStyleSheet(f"background: {t['bg_panel']};")

        # Chat scroll area — Bumble-inspired warm background
        if hasattr(self, 'chat_scroll'):
            _chat_bg = t.get('bg_chat', t['bg_dark'])
            self.chat_scroll.setStyleSheet(f"QScrollArea {{ background: {_chat_bg}; border: none; }}")
            self.chat_content.setStyleSheet(f"background: {_chat_bg};")
            self.chat_scroll.viewport().setStyleSheet(f"background: {_chat_bg};")

        # Chat header widget
        if hasattr(self, 'chat_header_widget'):
            self.chat_header_widget.setStyleSheet(f"QWidget {{ background: {t['bg_panel']}; }}")
        
        # Chat header label
        if hasattr(self, 'chat_header'):
            self.chat_header.setStyleSheet(
                f"color: {t['text']}; font-size: 14px; font-weight: bold; background: transparent;"
            )
        
        # Artifact toggle button
        if hasattr(self, '_artifact_btn'):
            self._artifact_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: 1px solid {t['border']};
                    border-radius: 6px;
                    color: {t['text_muted']};
                    padding: 0px;
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    border-color: {t['accent_teal']};
                    color: {t['accent_teal']};
                }}
            """)
        
        # Doc Mode button
        if hasattr(self, '_doc_mode_btn'):
            self._doc_mode_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {t['btn_secondary']};
                    border: 1px solid {t['border']};
                    border-radius: 6px;
                    color: {t['text']};
                    font-size: 12px;
                    padding: 4px 12px;
                }}
                QPushButton:hover {{
                    border-color: {t['border_hover']};
                    background: {t['bg_secondary']};
                }}
                QPushButton:checked {{
                    background: {t['accent_blue']};
                    border-color: {t['accent_blue']};
                    color: {t.get('btn_primary_text', t['text'])};
                }}
            """)
        
        # Clear button
        if hasattr(self, '_header_clear_btn'):
            self._header_clear_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {t['btn_secondary']};
                    border: 1px solid {t['border']};
                    border-radius: 6px;
                    color: {t['text']};
                    font-size: 12px;
                    padding: 4px 12px;
                }}
                QPushButton:hover {{
                    border-color: {t['accent_red']};
                    background: {t['btn_danger']};
                    color: {t.get('btn_primary_text', t['text'])};
                }}
            """)
        
        # Artifacts panel
        if hasattr(self, '_artifacts_panel'):
            t = self._theme
            self._artifacts_panel.setStyleSheet(f"""
                QWidget#artifactsPanel {{
                    background: {t['bg_sidebar']};
                }}
            """)
            if hasattr(self, '_ap_title'):
                self._ap_title.setStyleSheet(
                    f"color: {t['text']}; font-size: 14px; font-weight: bold; background: transparent;"
                )
            if hasattr(self, '_ap_download_all_btn'):
                self._ap_download_all_btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent;
                        border: 1px solid {t['border']};
                        border-radius: 6px;
                        color: {t['text_muted']};
                        font-size: 14px;
                        padding: 0px;
                    }}
                    QPushButton:hover {{
                        border-color: {t['accent_teal']};
                        color: {t['accent_teal']};
                    }}
                """)
            # Refresh rows with new theme colors
            if self._artifacts_panel.isVisible():
                self._refresh_artifacts_panel()
        
        # Splitter handle theme
        if hasattr(self, '_chat_artifact_splitter'):
            self._chat_artifact_splitter.setStyleSheet(f"""
                QSplitter::handle {{
                    background-color: {t['border']};
                    width: 4px;
                }}
                QSplitter::handle:hover {{
                    background-color: {t['accent_teal']};
                }}
                QSplitter::handle:pressed {{
                    background-color: {t['accent_teal']};
                }}
            """)

        # Sidebar
        if hasattr(self, 'sidebar'):
            self.sidebar.setStyleSheet(f"background: {t['bg_sidebar']};")
        
        # Sidebar title
        if hasattr(self, '_sidebar_title'):
            self._sidebar_title.setStyleSheet(
                f"color: {t['text']}; font-size: 15px; font-weight: 700;"
                f" letter-spacing: 0.3px; background: transparent;"
            )
        
        # Sidebar toggle button
        if hasattr(self, 'sidebar_toggle_btn'):
            self.sidebar_toggle_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    color: {t['text_muted']};
                    font-size: 16px;
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background: {t['btn_secondary']};
                    color: {t['text']};
                }}
            """)
            # Recreate icon with updated theme colors
            self.sidebar_toggle_btn.setIcon(self._create_sidebar_panel_icon())
        
        # New Session button
        if hasattr(self, '_new_session_btn'):
            self._apply_sidebar_button_theme(self._new_session_btn, t, is_new_session=True)
        
        # Settings button
        if hasattr(self, '_settings_btn'):
            self._apply_sidebar_button_theme(self._settings_btn, t, is_new_session=False)
        
        # DCC Setup button
        if hasattr(self, '_dcc_setup_btn'):
            self._apply_sidebar_button_theme(self._dcc_setup_btn, t, is_new_session=False)
        
        # Search bar
        if hasattr(self, '_search_bar'):
            self._search_bar.setStyleSheet(f"""
                QLineEdit {{
                    background: {t['bg_input']};
                    border: 1px solid {t['border']};
                    border-radius: 8px;
                    color: {t['text']};
                    font-size: 12px;
                    padding: 4px 8px;
                }}
                QLineEdit:focus {{
                    border-color: {t['border_hover']};
                }}
            """)
            palette = self._search_bar.palette()
            palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(t['text_muted']))
            self._search_bar.setPalette(palette)
        
        # Recents label
        if hasattr(self, '_recents_label'):
            self._recents_label.setStyleSheet(
                f"color: {t['text_muted']}; font-size: 10px; font-weight: bold; letter-spacing: 1px;"
                f"padding: 2px 10px 4px 10px; background: transparent;"
            )
        
        # Sidebar separators
        if hasattr(self, '_sidebar_separators'):
            for sep in self._sidebar_separators:
                sep.setStyleSheet(f"background: {t['divider']}; border: none;")
        
        # Update all session widgets
        if hasattr(self, '_session_widgets'):
            for widget in self._session_widgets.values():
                if hasattr(widget, 'update_theme'):
                    widget.update_theme(t)

        # Collapsed sidebar
        if hasattr(self, '_collapsed_sidebar'):
            self._apply_collapsed_sidebar_theme(t)

        # DCC tabs
        if hasattr(self, '_dcc_strip'):
            self._dcc_strip._apply_dcc_theme(t)
        
        # Restyle existing chat messages
        if hasattr(self, '_chat_message_widgets'):
            self._restyle_chat_messages()
    
    def _apply_sidebar_button_theme(self, button, t, is_new_session=False):
        """Apply theme to a sidebar button and its child widgets."""
        if is_new_session:
            button.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    border-radius: 8px;
                    text-align: left;
                    padding: 0;
                }}
                QPushButton:hover {{
                    background: {t['bg_secondary']};
                }}
                QPushButton:pressed {{
                    background: {t['border']};
                }}
            """)
            # Update icon and text labels inside the button
            layout = button.layout()
            if layout:
                for i in range(layout.count()):
                    widget = layout.itemAt(i).widget()
                    if isinstance(widget, QLabel):
                        # First label is icon (teal), second is text (muted)
                        if i == 0:  # Icon
                            widget.setStyleSheet(
                                f"color: {t['accent_teal']}; font-size: 20px; font-weight: bold; background: transparent;"
                            )
                        else:  # Text
                            widget.setStyleSheet(
                                f"color: {t['text_muted']}; font-size: 13px; background: transparent;"
                            )
        else:
            button.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    border-radius: 8px;
                    text-align: left;
                    padding: 0;
                }}
                QPushButton:hover {{
                    background: {t['bg_panel']};
                }}
                QPushButton:pressed {{
                    background: {t['bg_secondary']};
                }}
            """)
            # Update icon and text labels for Settings/DCC Setup buttons
            layout = button.layout()
            if layout:
                for i in range(layout.count()):
                    widget = layout.itemAt(i).widget()
                    if isinstance(widget, QLabel):
                        # Icon and text both use text_muted
                        widget.setStyleSheet(
                            f"color: {t['text_muted']}; font-size: {'20px' if i == 0 else '13px'}; background: transparent;"
                        )

    def _apply_collapsed_sidebar_theme(self, t):
        """Update collapsed sidebar theme colors."""
        # Update collapsed sidebar background
        self._collapsed_sidebar.setStyleSheet(f"""
            QWidget {{
                background: {t['bg_sidebar']};
            }}
        """)
        
        # Update toggle overlay button theme
        if hasattr(self, '_collapsed_toggle_overlay'):
            self._collapsed_toggle_overlay.setStyleSheet(f"""
                QPushButton#collapsedLogoOverlay {{
                    background: {t['bg_panel']};
                    border: none;
                    border-radius: 8px;
                    padding: 0px;
                }}
                QPushButton#collapsedLogoOverlay:hover {{
                    background: {t['bg_secondary']};
                }}
                QPushButton#collapsedLogoOverlay:pressed {{
                    background: {t['border']};
                }}
            """)
            
            # Recreate the icon with updated theme colors
            self._collapsed_toggle_overlay.setIcon(self._create_sidebar_panel_icon())
        
        # Update all icon buttons in collapsed sidebar
        if hasattr(self, '_collapsed_icon_buttons'):
            icon_button_style = f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    border-radius: 8px;
                    color: {t['text_muted']};
                    font-size: 20px;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background: {t['bg_panel']};
                }}
                QPushButton:pressed {{
                    background: {t['bg_secondary']};
                }}
            """
            for btn in self._collapsed_icon_buttons:
                btn.setStyleSheet(icon_button_style)

    def _restyle_chat_messages(self):
        """Update background of all existing message bubbles."""
        t = self._theme
        for widget in getattr(self, '_chat_message_widgets', []):
            role = getattr(widget, 'role', 'user')
            is_user = role == "user"
            margin = "2px 60px 2px 8px" if is_user else "2px 8px 2px 60px"
            
            if role == "user":
                border = "border: 1px solid #243050;"
                widget.setStyleSheet(f"MessageBubble {{ background: {t['bg_msg_user']}; border-radius: 12px; {border} margin: {margin}; }}")
                widget.content_label.setStyleSheet(f"color: {t.get('msg_text', t['text'])}; font-size: 13px; background: transparent; line-height: 1.5;")
            elif role == "system":
                widget.setStyleSheet(f"MessageBubble {{ background: {t['bg_msg_system']}; border-radius: 8px; border: none; margin: {margin}; }}")
                widget.content_label.setStyleSheet(f"color: {t.get('msg_text', t['text'])}; font-size: 13px; background: transparent; line-height: 1.5;")
            else:
                border = f"border: 1px solid #1a1f2e; border-left: 3px solid {t['accent_blue']};"
                widget.setStyleSheet(f"MessageBubble {{ background: {t['bg_msg_ai']}; border-radius: 12px; {border} margin: {margin}; }}")
                text_color = t.get('msg_text_ai', t.get('msg_text', t['text']))
                widget.content_label.setStyleSheet(f"color: {text_color}; font-size: 13px; background: transparent; line-height: 1.5;")

    def _apply_input_theme(self):
        t = self._theme
        # Outer wrapper — blends into chat scroll background
        _wrapper_bg = t.get('bg_chat', t['bg_panel'])
        self._bottom_wrapper.setStyleSheet(
            f"QWidget#inputWrapper {{ background: {_wrapper_bg}; }}"
        )
        # Inner rounded card — visually distinct, pill/capsule shape
        self._input_frame.setStyleSheet(f"""
            QFrame#inputCard {{
                background: {t['bg_input']};
                border: 1px solid {t['border']};
                border-radius: 24px;
            }}
        """)
        self.input_field.setStyleSheet(f"""
            QTextEdit#chatInput {{
                background: transparent;
                border: 0px;
                color: {t['text']};
                font-size: 14px;
                padding: 6px 6px;
                font-family: 'Segoe UI';
                outline: none;
            }}
        """)
        self.input_field.viewport().setStyleSheet("background: transparent; border: 0px;")
        # Disclaimer sits on the chat area background
        if hasattr(self, '_disclaimer'):
            _disc_bg = t.get('bg_chat', t['bg_dark'])
            self._disclaimer.setStyleSheet(
                f"QLabel#inputDisclaimer {{"
                f" color: {t['text_muted']};"
                f" font-size: 10px;"
                f" padding: 8px 16px 10px 16px;"
                f" background: {_disc_bg};"
                f" border: none;"
                f"}}"
            )
        
        # Mode dropdown button
        if hasattr(self, '_mode_btn'):
            self._mode_btn.setMinimumHeight(32)
            self._mode_btn.setMaximumHeight(32)
            self._mode_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {t['btn_secondary']};
                    border: 1px solid {t['border']};
                    border-radius: 16px;
                    color: {t['text']};
                    font-size: 12px;
                    padding: 0px 12px;
                }}
                QPushButton:hover {{
                    border-color: {t['border_hover']};
                    background: {t['bg_secondary']};
                }}
            """)
        
        # Send button
        if hasattr(self, 'send_btn'):
            self.send_btn.setFixedSize(36, 36)
            self.send_btn.setText("\u2191")
            self.send_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {t['accent_teal']};
                    border: none;
                    border-radius: 18px;
                    color: {t.get('btn_primary_text', '#FFFFFF')};
                    font-size: 18px;
                    font-weight: bold;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background: {t['accent_teal']};
                }}
                QPushButton:pressed {{
                    background: {t['accent_teal']};
                }}
                QPushButton:disabled {{
                    background: {t['border']};
                    color: {t['text_muted']};
                }}
            """)

    def _apply_plus_btn_theme(self):
        t = self._theme
        self._plus_btn.setFixedSize(36, 36)
        self._plus_btn.setVisible(True)
        self._plus_btn.setStyleSheet(f"""
            QPushButton#plusBtn {{
                background: {t['btn_secondary']};
                border: 1px solid {t['border']};
                border-radius: 18px;
                color: {t['text']};
                font-size: 18px;
                font-weight: bold;
                padding: 0px;
                margin: 0px;
            }}
            QPushButton#plusBtn:hover {{
                border-color: {t.get('accent_blue', t['border_hover'])};
                color: {t['text']};
                background: {t['btn_secondary_hover']};
            }}
        """)
        self._plus_btn.raise_()

    def _apply_scan_buttons_theme(self):
        t = self._theme
        for btn in [self._scan_btn, self._quick_check_btn]:
            btn.setMinimumHeight(32)
            btn.setMaximumHeight(32)
            
        border_col = t.get('btn_pill_border', t['accent_blue'])
        text_col = t.get('btn_pill_text', t['accent_blue'])
        hover_border = t.get('accent_blue', t['accent_blue'])
        hover_text = t.get('accent_blue', t['accent_blue'])
            
        self._scan_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {border_col};
                border-radius: 16px;
                color: {text_col};
                font-size: 12px;
                padding: 0px 14px;
            }}
            QPushButton:hover {{
                background: {t['btn_secondary']};
                border-color: {hover_border};
                color: {hover_text};
            }}
        """)
        
        self._quick_check_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {border_col};
                border-radius: 16px;
                color: {text_col};
                font-size: 12px;
                padding: 0px 14px;
            }}
            QPushButton:hover {{
                background: {t['btn_secondary']};
                border-color: {hover_border};
                color: {hover_text};
            }}
        """)

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
        
        if text == "New Session":
            row.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    border-radius: 8px;
                    text-align: left;
                    padding: 0;
                }}
                QPushButton:hover {{
                    background: {COLORS['bg_secondary']};
                }}
                QPushButton:pressed {{
                    background: {COLORS['border']};
                }}
            """)
        else:
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
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(10)

        icon_lbl = QLabel(icon)
        icon_lbl.setFixedSize(40, 40)
        icon_lbl.setAlignment(Qt.AlignCenter)
        
        if text == "New Session":
            icon_lbl.setStyleSheet(f"color: {COLORS['accent_teal']}; font-size: 20px; font-weight: bold; background: transparent;")
        else:
            icon_lbl.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 20px; font-weight: bold; background: transparent;")
        
        layout.addWidget(icon_lbl)

        text_label = QLabel(text)
        text_label.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 13px; background: transparent;"
        )
        layout.addWidget(text_label, 1)
        self._sidebar_text_labels.append(text_label)

        icon_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        text_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        
        # Hover effect for New Session text
        if text == "New Session":
            original_enter = row.enterEvent
            original_leave = row.leaveEvent
            
            def enterEvent(event):
                text_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 13px; background: transparent;")
                if original_enter: original_enter(event)
                
            def leaveEvent(event):
                text_label.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 13px; background: transparent;")
                if original_leave: original_leave(event)
                
            row.enterEvent = enterEvent
            row.leaveEvent = leaveEvent

        return row

    def _create_sidebar_panel_icon(self):
        """Create a sidebar panel icon (rounded rectangle with left panel divider).
        
        The icon visually represents a sidebar with a left panel divider, used for the
        toggle button to indicate the sidebar collapse/expand functionality.
        
        Preconditions:
            - QPainter and QPixmap are available from PySide6.QtGui
            - COLORS dictionary contains 'text_muted' key with valid color value
            - Qt rendering system is initialized
        
        Postconditions:
            - Returns valid QIcon object with 16x16 pixmap
            - Icon shows rounded rectangle with left panel divider
            - Icon uses antialiasing for smooth edges
            - Icon is suitable for button display at 16x16 size
        
        Returns:
            QIcon containing the rendered sidebar panel icon (16x16 pixels)
        """
        # Create 16x16 transparent pixmap as the drawing canvas
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        
        # Initialize QPainter with antialiasing enabled for smooth edges
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        
        # Set pen color to theme's muted text color with 1.5px width for visibility
        color = QColor(COLORS['text_muted'])
        painter.setPen(QPen(color, 1.5))
        painter.setBrush(Qt.NoBrush)  # No fill, outline only
        
        # Draw main panel outline: rounded rectangle with 2px margin from edges
        # Rectangle is 12x12 within the 16x16 canvas, with 2px corner radius
        rect = QRectF(2, 2, 12, 12)
        painter.drawRoundedRect(rect, 2, 2)
        
        # Draw vertical divider line representing the left panel separator
        # Line is positioned at x=6 (left third of icon) from y=3 to y=13
        painter.drawLine(6, 3, 6, 13)
        
        # Clean up painter resources
        painter.end()
        
        # Convert pixmap to QIcon for use in QPushButton
        return QIcon(pixmap)

    def _make_icon_button(self, icon_text, tooltip, callback):
        """Create an icon-only button for collapsed sidebar.
        
        Creates a styled button with an icon/emoji, hover states, and click handler.
        Used for the icon-only buttons displayed when the sidebar is collapsed to 56px.
        
        Preconditions:
            - icon_text is non-empty string (Unicode icon or emoji)
            - tooltip is non-empty string
            - callback is a valid callable function
            - COLORS dictionary contains required keys: 'text_muted', 'bg_panel', 'bg_secondary'
        
        Postconditions:
            - Returns configured QPushButton with 40px fixed height
            - Button displays centered icon text at 20px font size
            - Button has transparent background with hover/pressed states
            - Button has rounded corners (8px border-radius)
            - Button's clicked signal is connected to callback function
            - Button cursor changes to pointing hand on hover
        
        Args:
            icon_text: Unicode icon character or emoji to display (e.g., "+", "🔍", "⚙")
            tooltip: Tooltip text shown on hover (e.g., "New Session", "Search")
            callback: Click handler function to be called when button is clicked
            
        Returns:
            Configured QPushButton with icon styling and hover states
        """
        # Create button with icon text as the button label
        button = QPushButton(icon_text)
        
        # Set fixed height to 40px (width is flexible for horizontal centering)
        button.setFixedHeight(40)
        
        # Set tooltip for accessibility and user guidance
        button.setToolTip(tooltip)
        
        # Set cursor to pointing hand to indicate clickability
        button.setCursor(Qt.PointingHandCursor)
        
        # Apply stylesheet with three states: default (transparent), hover, and pressed
        # Default: transparent background with muted text color
        # Hover: panel background color for visual feedback
        # Pressed: secondary background color for click confirmation
        style = f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {COLORS['text_muted']};
                font-size: 20px;
                border-radius: 8px;
                padding: 0;
            }}
            QPushButton:hover {{
                background: {COLORS['bg_panel']};
            }}
            QPushButton:pressed {{
                background: {COLORS['bg_secondary']};
            }}
        """
        button.setStyleSheet(style)
        
        # Connect clicked signal to callback for button functionality
        button.clicked.connect(callback)
        
        # Return the fully configured button
        return button

    def _filter_sessions(self, query):
        """Show/hide session items based on a name search query."""
        q = query.strip().lower()
        active_dcc = getattr(self, "_active_dcc_filter", "all")
        
        for s in self._sessions:
            sid = s["session_id"]
            w = self._session_widgets.get(sid)
            if w is None:
                continue
            name = s.get("scene_name", "untitled").lower()
            dcc = s.get("dcc", "").lower()
            
            dcc_match = (active_dcc == "all" or dcc == active_dcc)
            search_match = (not q) or (q in name) or (q in dcc)
            
            w.setVisible(dcc_match and search_match)

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

        # Apply DCC filter if set
        active_dcc = getattr(self, "_active_dcc_filter", "all")
        filtered_sessions = [
            s for s in self._sessions
            if active_dcc == "all" or s.get("dcc", "").lower() == active_dcc
        ]

        for s in filtered_sessions:
            w = SessionItemWidget(s)
            w.clicked.connect(self._select_session)
            w.setContextMenuPolicy(Qt.CustomContextMenu)
            w.customContextMenuRequested.connect(lambda pos, sid=s["session_id"]: self._session_context_menu(sid, pos))
            self._session_widgets[s["session_id"]] = w
            self.session_list_layout.insertWidget(self.session_list_layout.count() - 1, w)
            
    def _on_dcc_filter_changed(self, dcc):
        """Filter sessions list by DCC."""
        self._active_dcc_filter = dcc
        self._load_sessions_list()
        
    def _show_plugin_store(self):
        store = PluginStoreWindow(self)
        store.dcc_installed.connect(self._dcc_strip.add_dcc)
        store.dcc_uninstalled.connect(self._dcc_strip.remove_dcc)
        store.exec()

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

        # Update artifact button state
        self._update_artifact_btn_state()

        self._render_chat_history()

    def _render_chat_history(self):
        # Clear chat
        self._chat_message_widgets = []
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
            self.chat_layout.addWidget(bubble)
            self._chat_message_widgets.append(bubble)

        QTimer.singleShot(50, self._scroll_to_bottom)

    def _on_new_session(self):
        """Start a new session — detect DCCs in background so UI never freezes."""
        # Show animated loading state immediately
        self._loading_dots = 0
        self._loading_dcc = "DCC"
        self.chat_header.setStyleSheet(
            f"color: {COLORS['accent_blue']}; font-size: 14px; font-weight: bold; background: transparent;"
        )
        self._loading_timer = QTimer(self)
        self._loading_timer.timeout.connect(self._pulse_loading)
        self._loading_timer.start(350)
        self._pulse_loading()

        # Detect DCCs in background thread (parallel, 0.5s timeout each)
        self._detect_worker = dcc_connector.DetectDCCWorker()
        self._detect_worker.finished.connect(self._on_dccs_detected)
        self._detect_worker.start()

    def _on_dccs_detected(self, dccs):
        """Called on main thread when DCC detection finishes."""
        if hasattr(self, "_loading_timer"):
            self._loading_timer.stop()

        if not dccs:
            # Restore header and show error
            self.chat_header.setStyleSheet(
                f"color: {COLORS['text']}; font-size: 14px; font-weight: bold; background: transparent;"
            )
            self.chat_header.setText("Select or create a session")
            QMessageBox.warning(self, "No DCC Found",
                "No Maya or Blender connection detected.\n\n"
                "Click '\u26a1 DCC Setup' in the sidebar\n"
                "to get the connection script for your DCC.")
            return

        # If multiple DCCs detected, let user choose
        if len(dccs) > 1:
            from PySide6.QtWidgets import QInputDialog
            labels = {"maya": "\U0001f537 Maya", "blender": "\U0001f7e0 Blender"}
            items = [labels.get(d, d) for d in dccs]
            choice, ok = QInputDialog.getItem(self, "Choose DCC",
                "Multiple DCCs detected. Connect to:", items, 0, False)
            if not ok:
                # User cancelled — restore header
                self.chat_header.setStyleSheet(
                    f"color: {COLORS['text']}; font-size: 14px; font-weight: bold; background: transparent;"
                )
                self.chat_header.setText("Select or create a session")
                return
            dcc = dccs[items.index(choice)]
        else:
            dcc = dccs[0]

        # Update loading animation with the chosen DCC name
        self._loading_dcc = dcc
        self._loading_timer = QTimer(self)
        self._loading_timer.timeout.connect(self._pulse_loading)
        self._loading_timer.start(350)
        self._pulse_loading()

        # Fetch scene info in background
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
        self.chat_header.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 14px; font-weight: bold; background: transparent;"
        )

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
            QPushButton {{ background: {COLORS['maya_color']}; color: {COLORS.get('btn_primary_text', COLORS['text'])};
                border-radius: 4px; padding: 6px 12px; font-size: 12px; }}
            QPushButton:hover {{ background: {COLORS['accent_blue']}; }}
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
            QPushButton {{ background: {COLORS['blender_color']}; color: {COLORS.get('btn_primary_text', COLORS['text'])};
                border-radius: 4px; padding: 6px 12px; font-size: 12px; }}
            QPushButton:hover {{ background: {COLORS['accent_orange']}; }}
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
        dlg.theme_changed.connect(self._apply_theme)
        if dlg.exec() == QDialog.Accepted:
            self._settings = dlg.get_settings()
            app_settings.save_settings(self._settings)
            mode = self._settings.get("mode", "single")
            # Apply theme first (resets all colors)
            theme = self._settings.get("theme", "dark")
            set_theme(theme)
            # THEN apply accent color override (after theme reset)
            accent = self._settings.get("accent_color")
            if accent:
                COLORS["accent_blue"] = accent
                COLORS["accent_teal"] = accent
                COLORS["accent_blue_hover"] = self._darken(accent, 0.85)
                COLORS["status_info"] = accent
            # Update global stylesheet + Fusion palette
            self._apply_global_palette()
            self._apply_theme(theme)

    @staticmethod
    def _darken(hex_color, factor=0.85):
        """Darken a hex color by a factor (0-1)."""
        hex_color = hex_color.lstrip("#")
        r = max(0, int(int(hex_color[0:2], 16) * factor))
        g = max(0, int(int(hex_color[2:4], 16) * factor))
        b = max(0, int(int(hex_color[4:6], 16) * factor))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _apply_global_palette(self):
        """Updates the QApplication stylesheet and palette using the active COLORS."""
        app = QApplication.instance()
        if not app:
            return
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

    def _toggle_sidebar(self):
        """Animate sidebar between the 56px icon rail and the 260px full panel."""
        self._sidebar_expanded = not self._sidebar_expanded
        
        if self._sidebar_expanded:
            self._collapsed_sidebar.setVisible(False)
            self.sidebar.setVisible(True)
            self.sidebar.setFixedWidth(self._sidebar_expanded_width)
        else:
            self.sidebar.setVisible(False)
            self._collapsed_sidebar.setVisible(True)
        
        # Update session widget expanded state
        for w in self._session_widgets.values():
            w.set_expanded(self._sidebar_expanded)
        
        # Save sidebar state to settings
        self._settings["sidebar_expanded"] = self._sidebar_expanded
        app_settings.save_settings(self._settings)

    def _restore_sidebar_state(self):
        """Restore sidebar expanded/collapsed state from settings (no animation)."""
        saved_expanded = self._settings.get("sidebar_expanded", True)
        if not saved_expanded:
            # Start collapsed — apply instantly without animation
            self._sidebar_expanded = False
            self.sidebar.setVisible(False)
            self._collapsed_sidebar.setVisible(True)

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

        self._current_session["chat_history"] = []
        session_manager.save_session(self._current_session)
        self._analyzer_history.clear()
        self._codewriter_history.clear()
        self._vision_history.clear()
        self._render_chat_history()
        self._add_system_msg("\U0001f5d1 Chat cleared")
        self._session_tokens = 0
        self._update_token_display()


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
        self.chat_layout.addWidget(bubble)
        self._chat_message_widgets.append(bubble)
        QTimer.singleShot(50, self._scroll_to_bottom)
        return bubble

    def _add_system_msg(self, text):
        self._add_bubble("system", text)
        if self._current_session:
            session_manager.add_message(self._current_session, "system", text)

    def _scroll_to_bottom(self):
        sb = self.chat_scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _update_connection_indicator(self):
        """Update the connection status dot in the header."""
        from dcc_connector import is_dcc_connected
        dcc = self._current_session.get("dcc", "") if self._current_session else ""
        
        if not dcc:
            self._conn_dot.setStyleSheet("color: #374151; font-size: 10px; background: transparent;")
            self._conn_dot.setToolTip("No session")
            return
        
        connected = is_dcc_connected(dcc)
        if connected:
            self._conn_dot.setStyleSheet("color: #22c55e; font-size: 10px; background: transparent;")
            self._conn_dot.setToolTip(f"{dcc.capitalize()} connected")
        else:
            self._conn_dot.setStyleSheet("color: #ef4444; font-size: 10px; background: transparent;")
            self._conn_dot.setToolTip(f"{dcc.capitalize()} not connected — open your DCC")

    def _build_session_context(self):
        """Build a context header with current DCC status."""
        from dcc_connector import is_dcc_connected
        
        dcc = self._current_session.get("dcc", "unknown") if self._current_session else "unknown"
        scene = self._current_session.get("scene_name", "untitled") if self._current_session else "untitled"
        connected = is_dcc_connected(dcc)
        
        status = "Connected ✓" if connected else "NOT connected ✗"
        
        return (
            f"[SESSION CONTEXT — checked in real-time]\n"
            f"DCC: {dcc.capitalize()}\n"
            f"Status: {status}\n"
            f"Scene: {scene}\n"
            f"[END CONTEXT]\n\n"
        )

    def _build_user_message(self, text):
        """Build full message with context + profile."""
        context = self._build_session_context()
        profile = self._settings.get("user_profile", "").strip()
        
        if profile:
            profile_context = (
                f"[USER PROFILE — use this to personalize your response]\n"
                f"{profile}\n"
                f"[END PROFILE]\n\n"
            )
            return context + profile_context + text
        return context + text

    def eventFilter(self, obj, event):
        """Handle Enter/Shift+Enter in the input field."""
        if obj == self.input_field and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if event.modifiers() == Qt.ShiftModifier:
                    return False  # Shift+Enter → newline (default behavior)
                else:
                    self._on_send()
                    return True  # Enter → send
        return super().eventFilter(obj, event)

    def _auto_resize_input(self):
        """Auto-resize input field based on content."""
        doc = self.input_field.document()
        doc_height = int(doc.size().height())
        if not self.input_field.toPlainText().strip():
            self.input_field.setMinimumHeight(36)
            self.input_field.setMaximumHeight(36)
            return
        height = doc_height + 16
        height = max(36, min(120, height))
        self.input_field.setMinimumHeight(height)
        self.input_field.setMaximumHeight(height)

    def _on_send(self):
        if self._is_busy or not self._current_session:
            return
        text = self.input_field.toPlainText().strip()
        img_b64 = self._pending_image_b64 or self._pending_screenshot
        if not text and not img_b64:
            return
        
        # Check if trying to send image with a non-vision model
        if img_b64:
            backend = self._settings.get("single_agent", {}).get("backend", 
                      self._settings.get("single", {}).get("backend", "ollama"))
            base_url = self._settings.get("single_agent", {}).get("base_url",
                       self._settings.get("single", {}).get("base_url", ""))
            model = self._settings.get("single_agent", {}).get("model",
                    self._settings.get("single", {}).get("model", ""))
            model_lower = model.lower()
            
            # Known vision-capable models (allow these)
            has_vision = any(v in model_lower for v in (
                'gpt-4o', 'gpt-4-vision', 'gemini', 'llava', 'llama-4', 'llama4',
                'scout', 'maverick', 'claude-3', 'pixtral', 'qwen-vl', 'internvl'
            ))
            
            # If model is NOT known to have vision, warn but still try
            # (don't block — let the API decide)
            if not has_vision:
                # Only hard-block known text-only models
                no_vision_confirmed = any(m in model_lower for m in (
                    'llama-3', 'llama3', 'mixtral', 'gemma-2', 'mistral-7b',
                    'deepseek-v2', 'phi-3'
                ))
                if no_vision_confirmed:
                    self._add_system_msg(
                        "\u26a0 Your current model doesn't support images.\n"
                        "Vision requires: gpt-4o, gemini-2.0-flash, llama-4-scout, or llava.\n"
                        "The screenshot was discarded."
                    )
                    self._pending_image_b64 = None
                    self._pending_screenshot = None
                    img_b64 = None
                    if not text:
                        return
        
        self.input_field.clear()
        self._agentic_iter = 0

        # Keep clean user text for display and history
        clean_text = text

        # Build full message with session context + profile (for AI only)
        if text:
            text = self._build_user_message(text)

        if self._search_mode and text:
            # Actually search the web and inject results into the prompt
            self._add_system_msg("\U0001f50d Searching the web...")
            # Add DCC context to search query for better results
            dcc_name = (self._current_session.get('dcc', '') or '').strip()
            search_query = clean_text
            if dcc_name and dcc_name.lower() not in clean_text.lower():
                search_query = f"{dcc_name} {clean_text}"
            search_results = self._web_search(search_query)
            if search_results:
                text = (
                    f"[SEARCH RESULTS] I searched the web for: \"{search_query}\"\n"
                    f"Here are the top results:\n\n{search_results}\n\n"
                    f"Based on these search results, answer the user's question: {clean_text}\n"
                    f"IMPORTANT: Only summarize the solution in plain text steps. "
                    f"Do NOT write code unless the user explicitly asks you to write or run code. "
                    f"Just explain what to do, include relevant links, and let the user decide if they want code."
                )
            else:
                text = f"[SEARCH_MODE] Please answer from your knowledge: {text}"
                self._add_system_msg("\u26a0 Web search failed \u2014 answering from AI knowledge")
            self.search_btn.setChecked(False)
            self._search_mode = False

        # Step-by-step mode — inject prefix (persistent, stays on until toggled off)
        if getattr(self, '_step_mode', False) and text:
            text = (
                "[STEP-BY-STEP MODE] Break your response into clear numbered steps. "
                "Each step should be short and actionable. "
                "Add a brief explanation of WHY before each step. "
                "Do NOT write code unless the user explicitly asks for code.\n\n"
                + text
            )

        # Plan mode — inject prefix (persistent, stays on until toggled off)
        if getattr(self, '_plan_mode', False) and text:
            text = (
                "[PLAN MODE] Before answering, create a detailed plan.\n"
                "Format:\n## Plan\n1. [step]\n2. [step]...\n\n## Answer\n"
                "[then answer based on the plan]\n\n"
                + text
            )

        # Inject documentation mode — scan selection and generate tech report
        if getattr(self, '_doc_mode_btn', None) and self._doc_mode_btn.isChecked() and text:
            import datetime
            dcc_name = (self._current_session.get('dcc', '') or '').capitalize()
            dcc_key = self._current_session.get('dcc', '')
            scene = self._current_session.get('scene_name', 'untitled')
            self._doc_mode_btn.setChecked(False)
            
            # Run a detailed scan of selected objects for documentation
            if dcc_key == "maya":
                doc_scan_code = (
                    "import maya.cmds as cmds, json\n"
                    "sel = cmds.ls(selection=True, long=True)\n"
                    "if not sel: sel = cmds.ls(dag=True, long=True, type='transform')[:20]\n"
                    "result = []\n"
                    "for obj in sel:\n"
                    "    nm = obj.split('|')[-1]\n"
                    "    info = {'name': nm, 'type': cmds.nodeType(obj)}\n"
                    "    shapes = cmds.listRelatives(obj, shapes=True, fullPath=True) or []\n"
                    "    if shapes:\n"
                    "        info['shape_type'] = cmds.nodeType(shapes[0])\n"
                    "        if cmds.nodeType(shapes[0]) == 'mesh':\n"
                    "            info['vertices'] = cmds.polyEvaluate(obj, v=True)\n"
                    "            info['faces'] = cmds.polyEvaluate(obj, f=True)\n"
                    "            info['edges'] = cmds.polyEvaluate(obj, e=True)\n"
                    "    info['translate'] = list(cmds.getAttr(obj+'.t')[0])\n"
                    "    info['rotate'] = list(cmds.getAttr(obj+'.r')[0])\n"
                    "    info['scale'] = list(cmds.getAttr(obj+'.s')[0])\n"
                    "    info['visible'] = cmds.getAttr(obj+'.v')\n"
                    "    conns = cmds.listConnections(obj, s=True, d=True) or []\n"
                    "    info['connections'] = list(set(conns))[:10]\n"
                    "    sg = cmds.listConnections(shapes[0], type='shadingEngine') if shapes else []\n"
                    "    info['material'] = list(set(sg or []))\n"
                    "    hist = cmds.listHistory(obj, pdo=True) or []\n"
                    "    info['history'] = [cmds.nodeType(h) for h in hist[:10]]\n"
                    "    attrs = cmds.listAttr(obj, userDefined=True) or []\n"
                    "    info['custom_attrs'] = attrs[:10]\n"
                    "    result.append(info)\n"
                    "print(json.dumps(result))\n"
                )
            elif dcc_key == "blender":
                doc_scan_code = (
                    "import bpy, json\n"
                    "sel = list(bpy.context.view_layer.objects.selected)\n"
                    "if not sel: sel = list(bpy.context.scene.objects)[:20]\n"
                    "result = []\n"
                    "for obj in sel:\n"
                    "    info = {'name': obj.name, 'type': obj.type}\n"
                    "    info['location'] = [round(v,3) for v in obj.location]\n"
                    "    info['rotation'] = [round(v,3) for v in obj.rotation_euler]\n"
                    "    info['scale'] = [round(v,3) for v in obj.scale]\n"
                    "    info['visible'] = obj.visible_get()\n"
                    "    if obj.type == 'MESH':\n"
                    "        m = obj.data\n"
                    "        info['vertices'] = len(m.vertices)\n"
                    "        info['faces'] = len(m.polygons)\n"
                    "        info['edges'] = len(m.edges)\n"
                    "        info['uv_layers'] = [uv.name for uv in m.uv_layers]\n"
                    "    info['materials'] = [s.material.name if s.material else 'None' for s in obj.material_slots]\n"
                    "    info['modifiers'] = [{'name':m.name,'type':m.type} for m in obj.modifiers]\n"
                    "    info['constraints'] = [{'name':c.name,'type':c.type} for c in obj.constraints]\n"
                    "    info['parent'] = obj.parent.name if obj.parent else None\n"
                    "    info['children'] = [c.name for c in obj.children]\n"
                    "    props = {k:str(v)[:50] for k,v in obj.items() if k != '_RNA_UI'}\n"
                    "    info['custom_props'] = props\n"
                    "    result.append(info)\n"
                    "print(json.dumps(result))\n"
                )
            else:
                doc_scan_code = None
            
            # Run the scan
            scan_data = ""
            if doc_scan_code:
                self._add_system_msg("\U0001f4c4 Scanning for documentation...")
                success, output = dcc_connector.send_code(dcc_key, doc_scan_code)
                if success:
                    scan_data = output
            
            doc_prefix = (
                "[DOCUMENTATION MODE] Generate a professional technical documentation report.\n"
                f"DCC: {dcc_name} | Scene: {scene} | Date: {datetime.date.today()}\n\n"
                "FORMAT as a shareable technical document with these sections:\n"
                "# Technical Documentation: {scene_name}\n"
                "## Overview (what this scene/selection contains)\n"
                "## Object Breakdown (for each object: type, geometry stats, key attributes)\n"
                "## Inputs & Outputs (connections, materials, constraints, modifiers)\n"
                "## Key Parameters (transforms, custom attributes, important settings)\n"
                "## Issues & Pitfalls (problems found, things to watch out for)\n"
                "## Recommendations (optimization tips, cleanup suggestions)\n\n"
                "RULES:\n"
                "- Be specific — include actual values, counts, names\n"
                "- Flag any issues with \U0001f534 \U0001f7e1 \U0001f7e2 severity\n"
                "- Keep it concise but complete — this is a reference document\n"
                "- Do NOT write code. This is documentation only.\n\n"
            )
            if scan_data:
                text = doc_prefix + f"SCAN DATA:\n{scan_data}\n\nUser note: {clean_text}"
            else:
                text = doc_prefix + f"User request: {clean_text}"
            
            # Force artifact creation for doc mode responses
            self._force_artifact_next = True

        # Thinking mode — prepend prefix if active (does not auto-disable)
        if getattr(self, '_current_mode', 'normal') == "thinking" and text:
            thinking_prefix = (
                "[THINKING MODE] Before answering, reason through this carefully step by step. "
                "Consider multiple approaches, evaluate trade-offs, then give your best answer. "
                "Show your reasoning process briefly before the final answer.\n\n"
            )
            text = thinking_prefix + text

        # Display ONLY clean user text in chat bubble
        self._add_bubble("user", clean_text or "[Image attached]")

        # Save ONLY clean user text to chat history
        session_manager.add_message(self._current_session, "user", clean_text, img_b64)
        if img_b64:
            self._pending_image_b64 = None
            self._pending_screenshot = None
        
        # --- Connection check: if DCC not connected, block scene interactions ---
        from dcc_connector import is_dcc_connected
        dcc = self._current_session.get("dcc", "")
        if dcc and not is_dcc_connected(dcc):
            # Smart detection: allow through ONLY if the message is clearly a
            # standalone knowledge question (long enough + has question structure).
            # Everything else is likely a scene follow-up → block it.
            user_lower = clean_text.lower().strip()
            word_count = len(user_lower.split())
            
            # A message is "general knowledge" if it:
            # - Is a full question (5+ words) AND
            # - Starts with a question word or "explain/tell me" pattern AND
            # - Does NOT reference "it/this/that/them" (which implies scene context)
            question_starters = ('what ', 'why ', 'how ', 'when ', 'where ', 'who ',
                                 'explain ', 'tell me ', 'define ', 'describe ')
            starts_as_question = any(user_lower.startswith(q) for q in question_starters)
            references_context = any(w in user_lower.split() for w in ('it', 'this', 'that', 'them', 'those', 'these'))
            
            is_standalone_question = (word_count >= 5 and starts_as_question and not references_context)
            
            if not is_standalone_question:
                dcc_name = dcc.capitalize()
                self._add_bubble("assistant",
                    f"Hold on \u2014 {dcc_name} isn't connected right now. \U0001f50c\n\n"
                    f"I need a live connection to help with your scene. "
                    f"Open {dcc_name} and make sure the addon is running.\n\n"
                    f"Once I see the green dot \U0001f7e2 up top, we're good to go!"
                )
                session_manager.add_message(
                    self._current_session, "assistant",
                    f"{dcc_name} not connected \u2014 blocked."
                )
                return
        
        # Send FULL prefixed message to AI
        self._original_msg_clean = clean_text  # Store clean text for intent detection
        self._start_ai(text, has_image=bool(img_b64))
        self._update_token_count()

    def _on_doc_mode_toggled(self, checked):
        """Show/hide a system message when doc mode is toggled."""
        if checked:
            self._add_system_msg(
                "\U0001f4c4 Documentation mode active \u2014 next message will generate a structured scene report"
            )
        else:
            self._add_system_msg("\U0001f4c4 Documentation mode off")

    # -----------------------------------------------------------------------
    # Automatic artifact creation — smart detection (Claude.ai-style)
    # -----------------------------------------------------------------------

    def _should_create_artifact(self, response, user_message=None):
        """
        Decide if the AI response should become an artifact.
        Logic mirrors Claude.ai behavior — smart, not keyword-dependent.
        """
        if user_message is None:
            user_message = getattr(self, '_original_msg', '')
        
        lines = response.strip().split('\n')
        response_lower = response.lower()
        user_lower = user_message.lower()
        # Strip system context from user message for detection
        user_lower = re.sub(r'\[.*?\]', '', user_lower).strip()

        # ── NEVER artifact these ──────────────────────────────────────

        # Too short — pure conversation
        if len(lines) < 5 and len(response) < 300:
            return False

        # Error or status messages
        error_patterns = ['error:', 'failed:', 'cannot', 'traceback', '\u26a0', '\u2705', '\u274c']
        if any(p in response_lower for p in error_patterns) and len(lines) < 10:
            return False

        # Simple yes/no or one-liner answers
        if len(lines) <= 3:
            return False

        # ── ALWAYS artifact these ─────────────────────────────────────

        # 1. Has code block with significant content (> 10 lines of actual code)
        code_blocks = re.findall(r'```[\w]*\n(.*?)```', response, re.DOTALL)
        if code_blocks:
            total_code_lines = sum(len(b.strip().split('\n')) for b in code_blocks)
            if total_code_lines > 10:
                return True

        # 2. Contains SVG or visual markup
        if '<svg' in response or 'viewBox' in response:
            return True

        # 3. Contains Mermaid diagram
        if '```mermaid' in response:
            return True

        # 4. User explicitly requested saving/exporting output
        # Detect intent: user wants the output preserved, not just displayed
        user_words = user_lower.split()
        save_intent = (
            'artifact' in user_lower or
            'save' in user_words or
            'export' in user_words or
            'download' in user_words or
            'as a file' in user_lower or
            'write it out' in user_lower
        )
        if save_intent:
            return True

        # ── SMART DETECTION — structural, not keyword-based ──────────

        # 5. User gave an imperative command to CREATE something
        # Only artifact if the response is also substantial (>10 lines or >500 chars)
        first_word = user_words[0] if user_words else ''
        is_creation_command = (
            first_word in ('create', 'generate', 'build', 'write', 'make', 'design', 'draw', 'draft')
            and len(user_words) >= 3
        )
        if is_creation_command and (len(lines) > 10 or len(response) > 500):
            return True

        # 6. Response is long AND has document structure (headers, lists, tables)
        is_long = len(lines) > 20 or len(response) > 1500
        has_headers = response.count('## ') >= 2 or response.count('### ') >= 2
        has_numbered_list = len(re.findall(r'^\d+\.', response, re.MULTILINE)) > 5
        has_table = response.count('| ') >= 3
        has_long_bullets = response.count('- ') >= 8
        is_structured = has_headers or has_numbered_list or has_table or has_long_bullets
        if is_long and is_structured:
            return True

        # 7. Response looks like a complete code file (multiple code constructs)
        code_constructs = sum(1 for p in ('def ', 'class ', 'import ', 'function ', 'const ')
                              if p in response)
        if code_constructs >= 3 and len(lines) > 15:
            return True

        return False

    def _detect_artifact_type(self, response):
        """Detect what kind of artifact to create."""
        # SVG
        if '<svg' in response or 'viewBox' in response:
            return 'svg', '.svg'

        # Mermaid
        if '```mermaid' in response:
            return 'mermaid', '.md'

        # Maya-run (DCC specific)
        if re.search(r'```(?:maya-run|scene-run)\n', response):
            return 'python', '.py'

        # Python
        if re.search(r'```(?:python|py)\n', response):
            return 'python', '.py'

        # JavaScript
        if re.search(r'```(?:javascript|js|typescript|ts)\n', response):
            return 'javascript', '.js'

        # Any other code block
        code_match = re.search(r'```(\w+)\n', response)
        if code_match:
            lang = code_match.group(1)
            ext_map = {
                'bash': '.sh', 'shell': '.sh',
                'sql': '.sql', 'html': '.html',
                'css': '.css', 'json': '.json',
                'yaml': '.yaml', 'xml': '.xml',
            }
            ext = ext_map.get(lang, f'.{lang}')
            return lang, ext

        # Markdown document
        return 'markdown', '.md'

    def _extract_artifact_content(self, response):
        """Extract the main content for the artifact. Merges and deduplicates code blocks."""
        # If has code blocks — extract and merge them
        code_blocks = re.findall(r'```[\w]*\n(.*?)```', response, re.DOTALL)
        if code_blocks:
            # Deduplicate
            seen = set()
            unique = []
            for block in code_blocks:
                stripped = block.strip()
                if stripped and stripped not in seen:
                    seen.add(stripped)
                    unique.append(stripped)
            
            if len(unique) > 1:
                parts = []
                for i, code in enumerate(unique, 1):
                    parts.append(f"# === Step {i} ===")
                    parts.append(code)
                    parts.append("")
                return "\n".join(parts)
            elif unique:
                return unique[0]

        # If SVG — extract it
        svg_match = re.search(r'(<svg.*?</svg>)', response, re.DOTALL)
        if svg_match:
            return svg_match.group(1).strip()

        # Otherwise — full response is the content
        return response.strip()

    def _generate_artifact_name(self, ext):
        """Generate a meaningful filename from the user's raw input."""
        user_message = getattr(self, '_original_msg', '').strip()
        # Strip system-injected context
        user_message = re.sub(r'\[SESSION CONTEXT.*?END CONTEXT\]', '', user_message, flags=re.DOTALL)
        user_message = re.sub(r'\[.*?\]', '', user_message).strip()

        # If too short/generic, try previous message
        if not user_message or len(user_message) < 5:
            user_message = self._get_previous_user_message()

        stop_words = {'a', 'an', 'the', 'me', 'please', 'can', 'you',
                      'create', 'make', 'build', 'write', 'generate',
                      'for', 'with', 'and', 'or', 'in', 'to', 'of',
                      'dcc', 'maya', 'blender', 'scene', 'context',
                      'session', 'status', 'connected', 'mode', 'step'}

        words = re.findall(r'\b\w+\b', user_message.lower())
        meaningful = [w for w in words if w not in stop_words and len(w) > 2]

        if meaningful:
            name = '_'.join(meaningful[:4])
        else:
            name = "artifact"

        name = re.sub(r'_+', '_', name).strip('_')
        if len(name) > 30:
            name = name[:30].rstrip('_')

        return f"{name}{ext}" if name else f"artifact{ext}"

    def _get_previous_user_message(self):
        """Get the most recent non-generic user message from chat history."""
        if not self._current_session:
            return "artifact"
        history = self._current_session.get("chat_history", [])
        generic = {"ok", "yes", "no", "do it", "go ahead", "in artifact",
                   "write it", "save it", "artifact", "file", "script"}
        for msg in reversed(history):
            if msg.get("role") == "user":
                content = msg.get("content", "").strip()
                content = re.sub(r'\[.*?\]', '', content).strip()
                if content and len(content) >= 5 and content.lower() not in generic:
                    if not content.startswith("Please analyse"):
                        return content
        return "artifact"

    def _clean_response_for_display(self, response):
        """Remove internal prefixes before showing in chat."""
        # Remove <think>...</think> reasoning blocks (LLM thinking out loud)
        response = re.sub(r'<think>.*?</think>\s*', '', response, flags=re.DOTALL)
        # Remove SESSION CONTEXT block
        response = re.sub(
            r'\[SESSION CONTEXT.*?\[END CONTEXT\]\n*',
            '', response, flags=re.DOTALL
        )
        # Remove mode prefixes
        prefixes = [
            r'\[STEP-BY-STEP MODE\].*?\n',
            r'\[PLAN MODE\].*?\n',
            r'\[THINKING MODE\].*?\n',
            r'\[SEARCH_MODE\].*?\n',
            r'\[DOCUMENTATION MODE\].*?\n',
            r'\[USER PROFILE.*?\[END PROFILE\]\n*',
        ]
        for pattern in prefixes:
            response = re.sub(pattern, '', response, flags=re.DOTALL)
        # Remove ## Plan section (keep ## Execution content only)
        response = re.sub(
            r'## Plan\n.*?## Execution\n',
            '', response, flags=re.DOTALL
        )
        # Remove ## Execution header itself
        response = response.replace('## Execution\n', '')
        return response.strip()

    # Keep old name as alias for backward compat within artifact logic
    def _strip_display_markers(self, text):
        return self._clean_response_for_display(text)

    def _maybe_create_artifact(self, response):
        """Create exactly ONE artifact per response using smart detection."""
        # Never create artifacts for scan/diagnostic responses
        if getattr(self, '_current_is_scan', False):
            return False
        
        user_message = getattr(self, '_original_msg', '')
        
        # Force artifact for doc mode
        force = getattr(self, '_force_artifact_next', False)
        if force:
            self._force_artifact_next = False
        
        if not force and not self._should_create_artifact(response, user_message):
            return False

        dcc = self._current_session.get("dcc", "unknown")
        session_id = self._current_session.get("session_id", "")

        # Detect type and extract content
        artifact_type, ext = self._detect_artifact_type(response)
        # For forced doc mode, always save as markdown with full response
        if force and ext != '.md':
            ext = '.md'
            artifact_type = 'markdown'
        content = self._extract_artifact_content(response)
        # For doc mode, save the full response (not just code blocks)
        if force:
            content = response

        if not content.strip():
            return False

        # Generate filename and save
        art_filename = self._generate_artifact_name(ext)
        art_dir = os.path.join(session_manager.SESSIONS_DIR, dcc, session_id, "artifacts")
        os.makedirs(art_dir, exist_ok=True)
        art_path = os.path.join(art_dir, art_filename)

        # Avoid overwriting
        if os.path.exists(art_path):
            import uuid
            base = os.path.splitext(art_filename)[0]
            art_filename = f"{base}_{uuid.uuid4().hex[:4]}{ext}"
            art_path = os.path.join(art_dir, art_filename)

        with open(art_path, "w", encoding="utf-8") as f:
            f.write(content)

        line_count = content.count('\n') + 1
        file_type_map = {
            '.py': 'Python', '.js': 'JavaScript', '.svg': 'SVG',
            '.md': 'Markdown', '.sh': 'Shell', '.sql': 'SQL',
            '.html': 'HTML', '.css': 'CSS', '.json': 'JSON',
        }
        file_type = file_type_map.get(ext, 'File')

        # Build summary from response text minus code blocks
        summary = re.sub(r'```[\w]*\n.*?```', '', response, flags=re.DOTALL)
        summary = self._strip_display_markers(summary).strip()
        if not summary:
            summary = f"Generated {line_count}-line {file_type.lower()}"

        # Update the chat bubble
        if self._current_bubble:
            # Clear code block widgets
            while self._current_bubble.code_container.count():
                item = self._current_bubble.code_container.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            # Show clean summary text
            current_text = self._current_bubble.content_label.text().strip()
            clean_text = self._strip_display_markers(current_text)
            if clean_text:
                self._current_bubble.content_label.setText(clean_text)
            else:
                self._current_bubble.content_label.setText(summary[:200])

            # Add artifact card
            card_widget = self._create_artifact_card_widget(
                art_path, os.path.splitext(art_filename)[0], file_type, ext, line_count
            )
            self._current_bubble.code_container.addWidget(card_widget)

        # Auto-open the viewer for the new artifact (with animation)
        self._refresh_artifacts_panel()
        if not self._artifacts_panel.isVisible():
            self._artifacts_panel.setVisible(True)
            self._animate_artifacts_panel(close=False)
        self._open_artifact_in_viewer(art_path)

        return True

    def _create_artifact_card_widget(self, fpath, art_id, file_type, ext, line_count):
        """Create a clickable artifact card widget for the chat bubble."""
        card = QFrame()
        card.setObjectName("artifactCard")
        card.setFixedHeight(60)
        card.setCursor(Qt.PointingHandCursor)
        card.setStyleSheet(f"""
            QFrame#artifactCard {{
                background: {COLORS['bg_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                margin: 4px 0;
            }}
            QFrame#artifactCard:hover {{
                border-color: {COLORS['accent_teal']};
            }}
        """)
        
        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)
        
        # Icon
        icon_lbl = QLabel("\U0001f5ce")
        icon_lbl.setStyleSheet("font-size: 20px; background: transparent; border: none;")
        layout.addWidget(icon_lbl)
        
        # Info
        info_widget = QWidget()
        info_widget.setStyleSheet("background: transparent; border: none;")
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(2)
        
        name_lbl = QLabel(f"{art_id}{ext}")
        name_lbl.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 12px; font-weight: 600; "
            f"background: transparent; border: none;"
        )
        info_layout.addWidget(name_lbl)
        
        meta_lbl = QLabel(f"{file_type} \u00b7 {line_count} lines")
        meta_lbl.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 10px; "
            f"background: transparent; border: none;"
        )
        info_layout.addWidget(meta_lbl)
        layout.addWidget(info_widget, 1)
        
        # View button
        view_btn = QPushButton("View")
        view_btn.setFixedSize(50, 26)
        view_btn.setCursor(Qt.PointingHandCursor)
        view_btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['btn_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                color: {COLORS['accent_teal']};
                font-size: 11px;
                padding: 0px;
            }}
            QPushButton:hover {{
                border-color: {COLORS['accent_teal']};
                background: {COLORS['bg_secondary']};
            }}
        """)
        view_btn.clicked.connect(lambda: self._open_artifact_in_viewer(fpath))
        layout.addWidget(view_btn)
        
        # Copy button
        copy_btn = QPushButton("Copy")
        copy_btn.setFixedSize(50, 26)
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['btn_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                color: {COLORS['text_muted']};
                font-size: 11px;
                padding: 0px;
            }}
            QPushButton:hover {{
                border-color: {COLORS['accent_teal']};
                color: {COLORS['accent_teal']};
            }}
        """)
        copy_btn.clicked.connect(lambda: self._copy_file_to_clipboard(fpath))
        layout.addWidget(copy_btn)
        
        return card

    def _copy_file_to_clipboard(self, fpath):
        """Copy file content to clipboard."""
        try:
            with open(fpath, encoding="utf-8") as f:
                QApplication.clipboard().setText(f.read())
            self._add_system_msg("\u2705 Copied to clipboard")
        except Exception:
            pass

    def _on_view_artifacts(self):
        """Toggle artifacts panel with smooth animation."""
        if self._artifacts_panel.isVisible():
            self._animate_artifacts_panel(close=True)
        else:
            # Show panel first, refresh content after animation starts
            self._ap_list_view.setVisible(True)
            self._ap_viewer_view.setVisible(False)
            self._artifacts_panel.setVisible(True)
            self._ap_state = "list"
            self._animate_artifacts_panel(close=False)
            # Refresh content slightly delayed so it doesn't block the animation
            QTimer.singleShot(50, self._refresh_artifacts_panel)

    def _animate_artifacts_panel(self, close=False):
        """Smooth animation for artifacts panel using splitter sizes."""
        if not hasattr(self, '_chat_artifact_splitter'):
            return
        
        target_width = self._settings.get("artifacts_panel_width", 280)
        
        self._ap_anim_step = 0
        self._ap_anim_steps = 8  # 8 frames at 16ms = ~130ms (snappy)
        
        if close:
            self._ap_anim_start = self._artifacts_panel.width()
            self._ap_anim_end = 0
        else:
            self._ap_anim_start = 0
            self._ap_anim_end = target_width
        
        if hasattr(self, '_ap_anim_timer') and self._ap_anim_timer.isActive():
            self._ap_anim_timer.stop()
        
        self._ap_anim_timer = QTimer(self)
        self._ap_anim_timer.setInterval(16)
        self._ap_anim_timer.timeout.connect(lambda: self._ap_anim_tick(close))
        self._ap_anim_timer.start()

    def _ap_anim_tick(self, closing):
        """Single animation frame for artifacts panel."""
        self._ap_anim_step += 1
        t = self._ap_anim_step / self._ap_anim_steps
        t = 1 - (1 - t) ** 2  # ease out quad (faster than cubic)
        
        current = int(self._ap_anim_start + (self._ap_anim_end - self._ap_anim_start) * t)
        total = self._chat_artifact_splitter.width()
        if total > 0:
            self._chat_artifact_splitter.setSizes([total - current, current])
        
        if self._ap_anim_step >= self._ap_anim_steps:
            self._ap_anim_timer.stop()
            if closing:
                self._artifacts_panel.setVisible(False)
                self._ap_state = "hidden"

    def _update_artifact_btn_state(self):
        """Update artifacts panel content if visible. Does NOT auto-open."""
        has_artifacts = self._session_has_artifacts()
        if not has_artifacts:
            # Hide panel if no artifacts
            self._artifacts_panel.setVisible(False)
            self._ap_state = "hidden"
            self._current_artifact_path = None
        elif self._artifacts_panel.isVisible():
            # Panel already open — just refresh the list
            self._refresh_artifacts_panel()

    def _artifact_viewer_back(self):
        """Switch from viewer view back to list view (same panel)."""
        self._ap_viewer_view.setVisible(False)
        self._ap_list_view.setVisible(True)
        self._ap_state = "list"
        self._current_artifact_path = None

    def _on_artifacts_panel_resized(self):
        """Save the artifacts panel width when user drags the splitter."""
        if hasattr(self, '_artifacts_panel') and self._artifacts_panel.isVisible():
            width = self._artifacts_panel.width()
            self._settings["artifacts_panel_width"] = width
            import settings as app_settings
            app_settings.save_settings(self._settings)

    def _session_has_artifacts(self):
        """Check if the current session has any artifact files."""
        if not self._current_session:
            return False
        dcc = self._current_session.get("dcc", "unknown")
        session_id = self._current_session.get("session_id", "")
        artifacts_path = os.path.join(
            session_manager.SESSIONS_DIR, dcc, session_id, "artifacts"
        )
        return os.path.isdir(artifacts_path) and bool(os.listdir(artifacts_path))

    def _get_artifacts_path(self):
        """Get the artifacts folder path for the current session."""
        if not self._current_session:
            return None
        dcc = self._current_session.get("dcc", "unknown")
        session_id = self._current_session.get("session_id", "")
        return os.path.join(session_manager.SESSIONS_DIR, dcc, session_id, "artifacts")

    def _refresh_artifacts_panel(self):
        """Rebuild the artifact rows in the panel."""
        # Clear existing rows
        while self._ap_list_layout.count() > 1:  # keep the stretch
            item = self._ap_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        artifacts_path = self._get_artifacts_path()
        if not artifacts_path or not os.path.isdir(artifacts_path):
            return

        _icon_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "svgs", "icon_artifact.svg"
        )

        for fname in sorted(os.listdir(artifacts_path)):
            fpath = os.path.join(artifacts_path, fname)
            if not os.path.isfile(fpath):
                continue
            name_no_ext = os.path.splitext(fname)[0]
            ext = os.path.splitext(fname)[1]
            file_type = {
                ".py": "Python",
                ".md": "Markdown",
                ".txt": "Text",
            }.get(ext, "File")

            row = self._make_artifact_row(fpath, name_no_ext, file_type, ext, _icon_path)
            self._ap_list_layout.insertWidget(self._ap_list_layout.count() - 1, row)

    def _make_artifact_row(self, fpath, name, file_type, ext, icon_path):
        """Create a single artifact row widget."""
        row = QFrame()
        row.setObjectName("artifactRow")
        row.setCursor(Qt.PointingHandCursor)
        row.setFixedHeight(52)
        row.setStyleSheet(f"""
            QFrame#artifactRow {{
                background: {COLORS['bg_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
            }}
            QFrame#artifactRow:hover {{
                border-color: {COLORS['accent_teal']};
            }}
        """)
        # Click to open in viewer
        row.mousePressEvent = lambda e, p=fpath: self._open_artifact_in_viewer(p)

        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 6, 8, 6)
        layout.setSpacing(8)

        # Icon
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(24, 24)
        icon_lbl.setAlignment(Qt.AlignCenter)
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path).scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon_lbl.setPixmap(pixmap)
        else:
            icon_lbl.setText("🗎")
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(icon_lbl)

        # Text info
        info = QWidget()
        info.setStyleSheet("background: transparent; border: none;")
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(1)

        # Truncate name if too long
        display_name = name if len(name) <= 20 else name[:18] + "…"
        name_lbl = QLabel(display_name)
        name_lbl.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 12px; font-weight: 600; "
            f"background: transparent; border: none;"
        )
        info_layout.addWidget(name_lbl)

        type_lbl = QLabel(f"{file_type} · {ext}")
        type_lbl.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 10px; "
            f"background: transparent; border: none;"
        )
        info_layout.addWidget(type_lbl)
        layout.addWidget(info, 1)

        # Download button
        dl_btn = QPushButton("⬇")
        dl_btn.setFixedSize(24, 24)
        dl_btn.setToolTip("Copy to Downloads folder")
        dl_btn.setCursor(Qt.PointingHandCursor)
        dl_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {COLORS['text_muted']};
                font-size: 12px;
                padding: 0px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                color: {COLORS['accent_teal']};
                background: {COLORS['btn_secondary']};
            }}
        """)
        dl_btn.clicked.connect(lambda checked, p=fpath: self._download_artifact(p))
        layout.addWidget(dl_btn)

        return row

    def _download_artifact(self, fpath):
        """Copy a single artifact file to the user's Downloads folder."""
        import shutil
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(downloads, exist_ok=True)
        dest = os.path.join(downloads, os.path.basename(fpath))
        try:
            shutil.copy2(fpath, dest)
            self._add_system_msg(f"✅ Copied to Downloads: {os.path.basename(fpath)}")
        except Exception as e:
            self._add_system_msg(f"⚠ Download failed: {e}")

    def _download_all_artifacts(self):
        """Copy all artifacts from the current session to Downloads."""
        import shutil
        artifacts_path = self._get_artifacts_path()
        if not artifacts_path or not os.path.isdir(artifacts_path):
            self._add_system_msg("No artifacts to download")
            return
        
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(downloads, exist_ok=True)
        count = 0
        for fname in os.listdir(artifacts_path):
            src = os.path.join(artifacts_path, fname)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(downloads, fname))
                count += 1
        
        if count:
            self._add_system_msg(f"✅ Downloaded {count} artifact(s) to Downloads folder")
        else:
            self._add_system_msg("No artifacts to download")

    def _open_artifact_in_viewer(self, fpath):
        """Switch the artifacts panel from list view to viewer view."""
        if not os.path.isfile(fpath):
            return
        
        self._current_artifact_path = fpath
        fname = os.path.basename(fpath)
        name_no_ext = os.path.splitext(fname)[0]
        ext = os.path.splitext(fname)[1]
        
        # Update header
        self._av_filename.setText(name_no_ext)
        
        # Read content
        try:
            with open(fpath, encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            content = f"Error reading file: {e}"
        
        # Display based on file type
        if ext == ".py":
            self._show_code_in_viewer(content)
        elif ext == ".md":
            self._show_markdown_in_viewer(content)
        else:
            self._show_code_in_viewer(content)
        
        # Switch panel from list to viewer
        self._ap_list_view.setVisible(False)
        self._ap_viewer_view.setVisible(True)
        self._ap_state = "viewer"
        
        # Show/hide Run button based on file type
        if hasattr(self, '_av_run_btn'):
            self._av_run_btn.setVisible(ext == '.py')
            self._av_run_btn.setEnabled(True)
            self._av_run_btn.setText("\u25b6 Run")

    def _show_code_in_viewer(self, code):
        """Display code as plain text — no HTML rendering."""
        # Strip any accidental HTML tags and unescape entities
        clean_code = re.sub(r'<[^>]+>', '', code)
        clean_code = (clean_code
                      .replace('&amp;', '&')
                      .replace('&lt;', '<')
                      .replace('&gt;', '>')
                      .replace('&quot;', '"')
                      .replace('&#x27;', "'"))
        self._av_content.setPlainText(clean_code)

    def _show_markdown_in_viewer(self, md_text):
        """Render markdown as formatted HTML."""
        import html
        lines = md_text.split('\n')
        html_parts = []
        
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('### '):
                html_parts.append(f'<h3 style="color:#E8E6E1; font-size:14px; margin:12px 0 4px 0;">{html.escape(stripped[4:])}</h3>')
            elif stripped.startswith('## '):
                html_parts.append(f'<h2 style="color:#E8E6E1; font-size:16px; margin:14px 0 6px 0;">{html.escape(stripped[3:])}</h2>')
            elif stripped.startswith('# '):
                html_parts.append(f'<h1 style="color:#E8E6E1; font-size:18px; margin:16px 0 8px 0;">{html.escape(stripped[2:])}</h1>')
            elif stripped.startswith('- ') or stripped.startswith('* '):
                html_parts.append(f'<p style="color:#E8E6E1; margin:2px 0 2px 16px;">\u2022 {html.escape(stripped[2:])}</p>')
            elif stripped.startswith('```'):
                html_parts.append('<div style="background:#090C12; border-radius:6px; padding:8px 12px; margin:4px 0;">')
            elif stripped == '```':
                html_parts.append('</div>')
            elif stripped:
                # Bold
                formatted = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', html.escape(stripped))
                html_parts.append(f'<p style="color:#E8E6E1; margin:4px 0; line-height:1.5;">{formatted}</p>')
            else:
                html_parts.append('<br>')
        
        full_html = f"""
        <div style="font-family: 'Segoe UI', sans-serif; font-size: 13px;
                    padding: 16px; background: #090C12;">
            {''.join(html_parts)}
        </div>
        """
        self._av_content.setHtml(full_html)

    def _copy_artifact_content(self):
        """Copy the current artifact's content to clipboard."""
        if not self._current_artifact_path or not os.path.isfile(self._current_artifact_path):
            return
        try:
            with open(self._current_artifact_path, encoding="utf-8") as f:
                content = f.read()
            QApplication.clipboard().setText(content)
            # Show "Copied!" briefly
            old_text = self._av_copy_btn.text()
            self._av_copy_btn.setText("\u2705 Copied!")
            QTimer.singleShot(1500, lambda: self._av_copy_btn.setText(old_text))
        except Exception:
            pass

    def _run_artifact_code(self):
        """Run the current artifact's code in the connected DCC."""
        if not self._current_artifact_path or not os.path.isfile(self._current_artifact_path):
            return
        if not self._current_session:
            self._add_system_msg("\u26a0 No session \u2014 can't run code")
            return
        
        ext = os.path.splitext(self._current_artifact_path)[1]
        if ext not in ('.py',):
            self._add_system_msg("\u26a0 Only .py files can be executed")
            return
        
        try:
            with open(self._current_artifact_path, encoding="utf-8") as f:
                code = f.read()
        except Exception as e:
            self._add_system_msg(f"\u26a0 Can't read file: {e}")
            return
        
        if not code.strip():
            self._add_system_msg("\u26a0 File is empty")
            return
        
        self._add_system_msg(f"\u25b6 Running {os.path.basename(self._current_artifact_path)}...")
        
        # Run via the existing _run_code method
        self._run_code(code)
        
        # Update button to show it ran
        self._av_run_btn.setText("\u2705 Sent!")
        self._av_run_btn.setEnabled(False)
        QTimer.singleShot(2000, lambda: (
            self._av_run_btn.setText("\u25b6 Run"),
            self._av_run_btn.setEnabled(True)
        ))
        QTimer.singleShot(2000, lambda: (
            self._av_run_btn.setText("\u25b6 Run"),
            self._av_run_btn.setEnabled(True)
        ))

    # -----------------------------------------------------------------------
    # + Menu and mode toggles
    # -----------------------------------------------------------------------
    def _show_plus_menu(self):
        """Show the popup menu from the + button."""
        if not hasattr(self, '_plus_popup'):
            self._plus_popup = PlusMenuPopup(self)
        
        # Sync toggle states
        self._plus_popup.set_toggle("search", getattr(self, '_search_mode', False))
        self._plus_popup.set_toggle("steps", getattr(self, '_step_mode', False))
        self._plus_popup.set_toggle("autorun", getattr(self, '_auto_run_mode', False))
        self._plus_popup.set_toggle("plan", getattr(self, '_plan_mode', False))
        
        pos = self._plus_btn.mapToGlobal(QPoint(0, 0))
        self._plus_popup.show_at(pos)

    def _toggle_search_mode(self, checked):
        self._search_mode = checked
        self.search_btn.setChecked(checked)
        if checked:
            self._add_system_msg("\U0001f50d Search mode on \u2014 next message will search the web for solutions (DCC tips, fixes, tutorials)")
        else:
            self._add_system_msg("\U0001f50d Search mode off")

    def _web_search(self, query):
        """Search the web using DuckDuckGo HTML (free, no API key needed).
        Returns formatted search results string, or empty string on failure."""
        import urllib.request
        import urllib.parse
        
        try:
            encoded = urllib.parse.quote_plus(query)
            url = f"https://html.duckduckgo.com/html/?q={encoded}"
            
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            })
            
            with urllib.request.urlopen(req, timeout=10) as response:
                html = response.read().decode("utf-8", errors="replace")
            
            import re
            results = []
            
            # DDG HTML version uses class="result__a" for title links
            links = re.findall(r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.DOTALL)
            # Snippets use class="result__snippet"
            snippets = re.findall(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
            
            for i, (raw_url, title) in enumerate(links[:5]):
                title = re.sub(r'<[^>]+>', '', title).strip()
                snippet = ""
                if i < len(snippets):
                    snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip()
                
                # Decode DDG redirect URL: //duckduckgo.com/l/?uddg=<encoded_url>&...
                actual_url = raw_url
                if 'uddg=' in raw_url:
                    match = re.search(r'uddg=([^&]+)', raw_url)
                    if match:
                        actual_url = urllib.parse.unquote(match.group(1))
                elif raw_url.startswith('//'):
                    actual_url = 'https:' + raw_url
                
                if title and actual_url:
                    entry = f"{i+1}. {title}\n"
                    if snippet:
                        entry += f"   {snippet[:200]}\n"
                    entry += f"   URL: {actual_url}\n"
                    results.append(entry)
            
            if results:
                return "\n".join(results)
            return ""
            
        except Exception as e:
            print(f"[Web Search Error] {e}")
            return ""

    def _toggle_step_mode(self, checked):
        self._step_mode = checked
        if checked:
            self._add_system_msg("\U0001f4cb Step-by-step mode on \u2014 AI will explain answers in numbered steps")
        else:
            self._add_system_msg("\U0001f4cb Step-by-step mode off")

    def _toggle_plan_mode(self, checked):
        self._plan_mode = checked
        if checked:
            self._add_system_msg("\U0001f4d0 Plan mode on \u2014 AI will plan before answering")
        else:
            self._add_system_msg("\U0001f4d0 Plan mode off")

    def _toggle_auto_run(self, checked):
        """Enable/disable auto-run with a one-time warning dialog."""
        if checked and not getattr(self, '_auto_run_warned', False):
            dialog = QMessageBox(self)
            dialog.setWindowTitle("\u26a0 Auto-run Code")
            dialog.setIcon(QMessageBox.Warning)
            dialog.setText(
                "Auto-run executes AI-generated code directly inside your DCC "
                "without asking for confirmation.\n\n"
                "\u26a0 This feature works best with powerful models like "
                "GPT-4o or Claude 3.5 Sonnet.\n\n"
                "Weaker models may generate incorrect code that could "
                "modify your scene unexpectedly.\n\n"
                "Use with caution \u2014 always save your scene first."
            )
            dialog.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
            dialog.setDefaultButton(QMessageBox.Cancel)
            dialog.setStyleSheet(f"""
                QMessageBox {{
                    background: {COLORS['bg_dark']};
                    color: {COLORS['text']};
                }}
                QLabel {{ color: {COLORS['text']}; font-size: 13px; }}
                QPushButton {{
                    background: {COLORS['bg_secondary']};
                    color: {COLORS['text']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 6px;
                    padding: 6px 16px;
                    min-width: 60px;
                }}
                QPushButton:hover {{ background: {COLORS['bg_panel']}; }}
            """)
            if dialog.exec() == QMessageBox.Cancel:
                self._auto_run_mode = False
                return
            self._auto_run_warned = True

        self._auto_run_mode = checked
        if checked:
            self._add_system_msg(
                "\U0001f916 Auto-run enabled \u2014 code will execute automatically after AI finishes. "
                "Recommended: GPT-4o or Claude 3.5 Sonnet."
            )
        else:
            self._add_system_msg("\U0001f916 Auto-run disabled")

    def _show_mode_menu(self):
        """Show mode selection popup — rounded, alien-style."""
        # Create a custom popup widget (same pattern as PlusMenuPopup)
        popup = QWidget(self, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        popup.setAttribute(Qt.WA_TranslucentBackground)
        
        outer = QVBoxLayout(popup)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)
        
        card = QFrame()
        card.setObjectName("modeMenuCard")
        card.setStyleSheet(f"""
            QFrame#modeMenuCard {{
                background: {COLORS['bg_input']};
                border: 1px solid {COLORS['accent_teal']};
                border-radius: 14px;
            }}
            QFrame#modeMenuCard QLabel {{
                background: transparent;
                border: none;
            }}
            QFrame#modeMenuCard QPushButton {{
                border: none;
                border-radius: 8px;
                padding: 10px 16px;
                font-size: 13px;
                text-align: left;
            }}
        """)
        outer.addWidget(card)
        
        # Teal glow
        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(45, 212, 191, 60))
        card.setGraphicsEffect(shadow)
        
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(8, 10, 8, 10)
        card_layout.setSpacing(2)
        
        current = getattr(self, '_current_mode', 'normal')
        
        # Normal option
        normal_btn = QPushButton(f"{'✓' if current == 'normal' else '   '}   Normal")
        normal_btn.setCursor(Qt.PointingHandCursor)
        normal_btn.setStyleSheet(f"""
            QPushButton {{
                background: {'%s' % COLORS['btn_secondary'] if current == 'normal' else 'transparent'};
                color: {COLORS['text']};
                border: none;
                border-radius: 8px;
                padding: 10px 16px;
                font-size: 13px;
                text-align: left;
            }}
            QPushButton:hover {{
                background: {COLORS['btn_secondary']};
            }}
        """)
        normal_btn.clicked.connect(lambda: (self._set_mode("normal"), popup.close()))
        card_layout.addWidget(normal_btn)
        
        # Thinking option
        thinking_btn = QPushButton(f"{'✓' if current == 'thinking' else '   '}   🧠  Adaptive Thinking")
        thinking_btn.setCursor(Qt.PointingHandCursor)
        thinking_btn.setStyleSheet(f"""
            QPushButton {{
                background: {'%s' % COLORS['btn_secondary'] if current == 'thinking' else 'transparent'};
                color: {COLORS['text']};
                border: none;
                border-radius: 8px;
                padding: 10px 16px;
                font-size: 13px;
                text-align: left;
            }}
            QPushButton:hover {{
                background: {COLORS['btn_secondary']};
            }}
        """)
        thinking_btn.clicked.connect(lambda: (self._set_mode("thinking"), popup.close()))
        card_layout.addWidget(thinking_btn)
        
        popup.setFixedWidth(260)
        popup.adjustSize()
        # Position above the button, but ensure it stays on screen
        btn_global = self._mode_btn.mapToGlobal(QPoint(0, 0))
        popup_h = popup.sizeHint().height()
        screen = QApplication.primaryScreen().availableGeometry()
        
        # Try above the button first
        y = btn_global.y() - popup_h - 4
        if y < screen.top():
            # Not enough room above — show below the button instead
            y = btn_global.y() + self._mode_btn.height() + 4
        
        # Ensure x doesn't go off-screen right
        x = btn_global.x()
        if x + 260 > screen.right():
            x = screen.right() - 260 - 8
        
        popup.move(x, y)
        popup.show()

    def _set_mode(self, mode):
        self._current_mode = mode
        if mode == "normal":
            self._mode_btn.setText("Normal \u25be")
            self._mode_btn.setStyleSheet(self._mode_btn.styleSheet())
        elif mode == "thinking":
            self._mode_btn.setText("\U0001f9e0 Thinking \u25be")
            self._add_system_msg(
                "\U0001f9e0 Adaptive Thinking enabled \u2014 AI will reason more carefully. "
                "Best with GPT-4o or Claude 3.5 Sonnet."
            )

    def _auto_execute_blocks(self, code_blocks):
        """Run all code blocks automatically (called via QTimer after streaming ends)."""
        if not self._current_session:
            return
        dcc = self._current_session.get("dcc", "")
        any_success = False
        for i, code in enumerate(code_blocks, 1):
            code = self._sanitize_node_names(code)
            undo_label = self._extract_undo_label(code)
            success, result = dcc_connector.send_code(dcc, code, undo_label)
            if success:
                self._log_trace(code, result)
                any_success = True
                preview = result.strip()[:120] if result.strip() not in ("", "OK") else "OK"
                self._add_system_msg(f"\u2705 Auto-run block {i}: {preview}")
            else:
                self._log_trace(code, result, error_msg=result)
                self._add_system_msg(f"\u26a0 Auto-run block {i} error: {result[:200]}")
        if any_success and dcc:
            self._add_system_msg(
                f"\u21a9 Press Ctrl+Z in {dcc.capitalize()} to undo any block above"
            )

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
            self._add_system_msg(f"\u26a0 Scan failed: {result}")
            return
        msg_text = (
            "Please analyse this scene scan data.\n\n"
            "RULES FOR YOUR RESPONSE:\n"
            "- List EVERY issue found — do not skip any\n"
            "- Explain each issue in simple terms (what it means, why it matters)\n"
            "- If no issues → say the scene looks clean\n"
            "- Do NOT write any code. Just explain the problems.\n"
            "- At the end, ask: 'Want me to fix any of these?'\n\n"
            "SCAN DATA:\n" + result
        )
        session_manager.add_message(self._current_session, "user", msg_text)
        self._start_ai(msg_text, is_scan=True)

    def _on_quick_check(self):
        """Scan only selected objects in the DCC — mesh health check (non-blocking)."""
        if not self._current_session:
            return
        dcc = self._current_session.get("dcc")
        if not dcc:
            return
        
        # Show loading state
        self._add_bubble("user", "\u2b21 Quick Check")
        self._set_dcc_loading("Scanning...")
        
        if dcc == "maya":
            code = (
                "import maya.cmds as cmds, json\n"
                "sel = cmds.ls(selection=True, long=True)\n"
                "if not sel:\n"
                "    print(json.dumps({'selected':[],'message':'Nothing selected'}))\n"
                "else:\n"
                "    result = []\n"
                "    for obj in sel:\n"
                "        nm = obj.split('|')[-1]\n"
                "        info = {'name': nm, 'type': cmds.nodeType(obj)}\n"
                "        shapes = cmds.listRelatives(obj, shapes=True, fullPath=True) or []\n"
                "        ms = [s for s in shapes if cmds.nodeType(s)=='mesh']\n"
                "        if ms:\n"
                "            shape = ms[0]\n"
                "            info['vertices'] = cmds.polyEvaluate(obj, v=True)\n"
                "            info['faces'] = cmds.polyEvaluate(obj, f=True)\n"
                "            info['edges'] = cmds.polyEvaluate(obj, e=True)\n"
                "            info['triangles'] = cmds.polyEvaluate(obj, t=True)\n"
                "            probs = []\n"
                "            nmv = cmds.polyInfo(obj, nmv=True) or []\n"
                "            if nmv: probs.append('Non-manifold vertices: %d' % len(nmv))\n"
                "            nme = cmds.polyInfo(obj, nme=True) or []\n"
                "            if nme: probs.append('Non-manifold edges: %d' % len(nme))\n"
                "            lf = cmds.polyInfo(obj, lf=True) or []\n"
                "            if lf: probs.append('Lamina faces: %d' % len(lf))\n"
                "            ie = cmds.polyInfo(obj, ie=True) or []\n"
                "            if ie: probs.append('Invalid edges: %d' % len(ie))\n"
                "            cmds.select(obj)\n"
                "            cmds.polySelectConstraint(mode=3, type=0x8000, where=1)\n"
                "            border = cmds.ls(selection=True, flatten=True)\n"
                "            cmds.polySelectConstraint(mode=0)\n"
                "            if border: probs.append('Border/hole edges: %d (mesh has holes)' % len(border))\n"
                "            cmds.select(obj)\n"
                "            cmds.polySelectConstraint(mode=3, type=8, size=1)\n"
                "            tris = cmds.ls(selection=True, flatten=True)\n"
                "            cmds.polySelectConstraint(mode=0)\n"
                "            if tris: probs.append('Triangles: %d' % len(tris))\n"
                "            cmds.select(obj)\n"
                "            cmds.polySelectConstraint(mode=3, type=8, size=3)\n"
                "            ngons = cmds.ls(selection=True, flatten=True)\n"
                "            cmds.polySelectConstraint(mode=0)\n"
                "            if ngons: probs.append('N-gons (>4 sides): %d' % len(ngons))\n"
                "            cmds.select(obj)\n"
                "            cmds.polySelectConstraint(mode=3, type=0x0001, where=1)\n"
                "            zero_edges = cmds.ls(selection=True, flatten=True)\n"
                "            cmds.polySelectConstraint(mode=0)\n"
                "            if zero_edges: probs.append('Zero-length edges: %d' % len(zero_edges))\n"
                "            cmds.select(obj)\n"
                "            cmds.polySelectConstraint(mode=3, type=8, geometricarea=True, geometricareabound=(0, 0.0001))\n"
                "            zero_faces = cmds.ls(selection=True, flatten=True)\n"
                "            cmds.polySelectConstraint(mode=0)\n"
                "            if zero_faces: probs.append('Zero-area faces: %d' % len(zero_faces))\n"
                "            cmds.select(sel)\n"
                "            t = cmds.getAttr(obj+'.t')[0]\n"
                "            r = cmds.getAttr(obj+'.r')[0]\n"
                "            s = cmds.getAttr(obj+'.s')[0]\n"
                "            if t != (0,0,0): probs.append('Non-zero translate')\n"
                "            if r != (0,0,0): probs.append('Non-zero rotation')\n"
                "            if s != (1,1,1): probs.append('Non-uniform scale')\n"
                "            hist = cmds.listHistory(obj, pdo=True) or []\n"
                "            ch = [h for h in hist if cmds.nodeType(h) not in ('mesh','groupId','shadingEngine')]\n"
                "            if ch: probs.append('History: %d nodes' % len(ch))\n"
                "            uvs = cmds.polyUVSet(obj, q=True, auv=True) or []\n"
                "            if not uvs: probs.append('No UVs')\n"
                "            sg = cmds.listConnections(shape, type='shadingEngine') or []\n"
                "            if not sg: probs.append('No material')\n"
                "            elif 'initialShadingGroup' in sg: probs.append('Default lambert1')\n"
                "            info['problems'] = probs\n"
                "            info['problem_count'] = len(probs)\n"
                "        # Animation checks (for any object type)\n"
                "        anim_info = {}\n"
                "        anim_problems = []\n"
                "        keys = cmds.keyframe(obj, q=True) or []\n"
                "        if keys:\n"
                "            anim_info['keyframe_count'] = len(keys)\n"
                "            anim_info['first_key'] = min(keys)\n"
                "            anim_info['last_key'] = max(keys)\n"
                "            animated_attrs = cmds.listAnimatable(obj) or []\n"
                "            keyed_attrs = [a for a in animated_attrs if cmds.keyframe(a, q=True)]\n"
                "            anim_info['animated_channels'] = len(keyed_attrs)\n"
                "        # Check animation curve quality\n"
                "        anim_curves = cmds.listConnections(obj, type='animCurve') or []\n"
                "        if anim_curves:\n"
                "            anim_info['anim_curves'] = len(anim_curves)\n"
                "            stepped = 0\n"
                "            linear = 0\n"
                "            spline = 0\n"
                "            flat_tangents = 0\n"
                "            broken_tangents = 0\n"
                "            for crv in anim_curves:\n"
                "                try:\n"
                "                    ott = cmds.keyTangent(crv, q=True, ott=True) or []\n"
                "                    itt = cmds.keyTangent(crv, q=True, itt=True) or []\n"
                "                    for t in ott:\n"
                "                        if t == 'step': stepped += 1\n"
                "                        elif t == 'linear': linear += 1\n"
                "                        elif t in ('spline','auto','clamped','plateau'): spline += 1\n"
                "                        elif t == 'flat': flat_tangents += 1\n"
                "                    # Check for broken (weighted) tangents\n"
                "                    wl = cmds.keyTangent(crv, q=True, weightLock=True) or []\n"
                "                    broken_tangents += sum(1 for w in wl if not w)\n"
                "                except: pass\n"
                "            if stepped: anim_info['stepped_keys'] = stepped\n"
                "            if linear: anim_info['linear_keys'] = linear\n"
                "            if spline: anim_info['spline_keys'] = spline\n"
                "            if flat_tangents: anim_info['flat_tangent_keys'] = flat_tangents\n"
                "            if broken_tangents: anim_info['broken_tangents'] = broken_tangents\n"
                "            # Detect smoothness issues\n"
                "            if stepped > 0 and spline > 0:\n"
                "                anim_problems.append('Mixed tangent types (stepped + spline) — animation may look jerky')\n"
                "            if stepped > spline and stepped > 0:\n"
                "                anim_problems.append('Mostly stepped keys — animation will look choppy, not smooth')\n"
                "            if broken_tangents > 0:\n"
                "                anim_problems.append('Broken tangents: %d — can cause unexpected motion' % broken_tangents)\n"
                "            if flat_tangents > spline and flat_tangents > 3:\n"
                "                anim_problems.append('Many flat tangents — animation may have dead spots')\n"
                "            # Check for keys outside playback range\n"
                "            pmin = cmds.playbackOptions(q=True, min=True)\n"
                "            pmax = cmds.playbackOptions(q=True, max=True)\n"
                "            if keys:\n"
                "                outside = [k for k in keys if k < pmin or k > pmax]\n"
                "                if outside:\n"
                "                    anim_problems.append('Keys outside playback range: %d' % len(outside))\n"
                "            # Check for sub-frame keys\n"
                "            subframe = [k for k in keys if k != int(k)] if keys else []\n"
                "            if subframe:\n"
                "                anim_problems.append('Sub-frame keys: %d — can cause interpolation issues' % len(subframe))\n"
                "        constraints = cmds.listRelatives(obj, type='constraint') or []\n"
                "        if constraints:\n"
                "            anim_info['constraints'] = [cmds.nodeType(c) for c in constraints]\n"
                "        if anim_problems:\n"
                "            anim_info['problems'] = anim_problems\n"
                "        if anim_info:\n"
                "            info['animation'] = anim_info\n"
                "        result.append(info)\n"
                "    # Timeline info\n"
                "    timeline = {}\n"
                "    timeline['start_frame'] = cmds.playbackOptions(q=True, min=True)\n"
                "    timeline['end_frame'] = cmds.playbackOptions(q=True, max=True)\n"
                "    timeline['current_frame'] = cmds.currentTime(q=True)\n"
                "    timeline['fps'] = cmds.currentUnit(q=True, time=True)\n"
                "    print(json.dumps({'selected': result, 'timeline': timeline}))\n"
            )
        elif dcc == "blender":
            code = (
                "import bpy, json, bmesh\n"
                "sel = list(bpy.context.view_layer.objects.selected)\n"
                "if not sel:\n"
                "    print(json.dumps({'selected':[],'message':'Nothing selected'}))\n"
                "else:\n"
                "    result = []\n"
                "    for obj in sel:\n"
                "        info = {'name': obj.name, 'type': obj.type}\n"
                "        if obj.type == 'MESH':\n"
                "            m = obj.data\n"
                "            info['vertices'] = len(m.vertices)\n"
                "            info['faces'] = len(m.polygons)\n"
                "            info['edges'] = len(m.edges)\n"
                "            probs = []\n"
                "            ngons = sum(1 for p in m.polygons if len(p.vertices)>4)\n"
                "            tris = sum(1 for p in m.polygons if len(p.vertices)==3)\n"
                "            if ngons: probs.append('N-gons (>4 sides): %d' % ngons)\n"
                "            if tris: probs.append('Triangles: %d' % tris)\n"
                "            bm = bmesh.new()\n"
                "            bm.from_mesh(m)\n"
                "            bm.verts.ensure_lookup_table()\n"
                "            bm.edges.ensure_lookup_table()\n"
                "            bm.faces.ensure_lookup_table()\n"
                "            nmv = sum(1 for v in bm.verts if not v.is_manifold)\n"
                "            nme = sum(1 for e in bm.edges if not e.is_manifold)\n"
                "            lv = sum(1 for v in bm.verts if not v.link_edges)\n"
                "            le = sum(1 for e in bm.edges if not e.link_faces)\n"
                "            border = sum(1 for e in bm.edges if e.is_boundary)\n"
                "            wire = sum(1 for e in bm.edges if e.is_wire)\n"
                "            ze = sum(1 for e in bm.edges if e.calc_length() < 0.0001)\n"
                "            zf = sum(1 for f in bm.faces if f.calc_area() < 0.0001)\n"
                "            doubles = 0\n"
                "            seen = set()\n"
                "            for v in bm.verts:\n"
                "                key = (round(v.co.x,4), round(v.co.y,4), round(v.co.z,4))\n"
                "                if key in seen: doubles += 1\n"
                "                else: seen.add(key)\n"
                "            bm.free()\n"
                "            if nmv: probs.append('Non-manifold vertices: %d' % nmv)\n"
                "            if nme: probs.append('Non-manifold edges: %d' % nme)\n"
                "            if lv: probs.append('Loose vertices: %d' % lv)\n"
                "            if le: probs.append('Loose edges (no face): %d' % le)\n"
                "            if border: probs.append('Border/hole edges: %d (mesh has holes)' % border)\n"
                "            if wire: probs.append('Wire edges (floating): %d' % wire)\n"
                "            if ze: probs.append('Zero-length edges: %d' % ze)\n"
                "            if zf: probs.append('Zero-area faces: %d' % zf)\n"
                "            if doubles: probs.append('Overlapping vertices: %d' % doubles)\n"
                "            if obj.location[:] != (0,0,0): probs.append('Non-zero location')\n"
                "            if obj.rotation_euler[:] != (0,0,0): probs.append('Non-zero rotation')\n"
                "            if obj.scale[:] != (1,1,1): probs.append('Non-uniform scale')\n"
                "            if not m.uv_layers: probs.append('No UVs')\n"
                "            if not obj.material_slots: probs.append('No material')\n"
                "            if obj.modifiers: probs.append('Unapplied modifiers: %d' % len(obj.modifiers))\n"
                "            info['problems'] = probs\n"
                "            info['problem_count'] = len(probs)\n"
                "        # Animation checks (for any object type)\n"
                "        anim_info = {}\n"
                "        anim_problems = []\n"
                "        if obj.animation_data and obj.animation_data.action:\n"
                "            action = obj.animation_data.action\n"
                "            anim_info['action_name'] = action.name\n"
                "            anim_info['channels'] = len(action.fcurves)\n"
                "            all_keys = []\n"
                "            constant_count = 0\n"
                "            linear_count = 0\n"
                "            bezier_count = 0\n"
                "            for fc in action.fcurves:\n"
                "                for kp in fc.keyframe_points:\n"
                "                    all_keys.append(kp.co[0])\n"
                "                    if kp.interpolation == 'CONSTANT': constant_count += 1\n"
                "                    elif kp.interpolation == 'LINEAR': linear_count += 1\n"
                "                    elif kp.interpolation == 'BEZIER': bezier_count += 1\n"
                "            if all_keys:\n"
                "                anim_info['keyframe_count'] = len(all_keys)\n"
                "                anim_info['first_key'] = min(all_keys)\n"
                "                anim_info['last_key'] = max(all_keys)\n"
                "            if constant_count: anim_info['constant_keys'] = constant_count\n"
                "            if linear_count: anim_info['linear_keys'] = linear_count\n"
                "            if bezier_count: anim_info['bezier_keys'] = bezier_count\n"
                "            # Smoothness issues\n"
                "            if constant_count > 0 and bezier_count > 0:\n"
                "                anim_problems.append('Mixed interpolation (constant + bezier) — animation may look jerky')\n"
                "            if constant_count > bezier_count and constant_count > 0:\n"
                "                anim_problems.append('Mostly constant/stepped keys — animation is NOT smooth')\n"
                "            if linear_count > bezier_count and linear_count > 3:\n"
                "                anim_problems.append('Mostly linear keys — animation looks robotic, not organic')\n"
                "            # Keys outside frame range\n"
                "            scene = bpy.context.scene\n"
                "            if all_keys:\n"
                "                outside = [k for k in all_keys if k < scene.frame_start or k > scene.frame_end]\n"
                "                if outside:\n"
                "                    anim_problems.append('Keys outside frame range: %d' % len(outside))\n"
                "            # Sub-frame keys\n"
                "            subframe = [k for k in all_keys if k != int(k)] if all_keys else []\n"
                "            if subframe:\n"
                "                anim_problems.append('Sub-frame keys: %d — can cause issues' % len(subframe))\n"
                "        if obj.animation_data and obj.animation_data.nla_tracks:\n"
                "            anim_info['nla_tracks'] = len(obj.animation_data.nla_tracks)\n"
                "        if obj.constraints:\n"
                "            anim_info['constraints'] = [c.type for c in obj.constraints]\n"
                "        if obj.animation_data and obj.animation_data.drivers:\n"
                "            anim_info['drivers'] = len(obj.animation_data.drivers)\n"
                "        if anim_problems:\n"
                "            anim_info['problems'] = anim_problems\n"
                "        if anim_info:\n"
                "            info['animation'] = anim_info\n"
                "        result.append(info)\n"
                "    # Timeline info\n"
                "    scene = bpy.context.scene\n"
                "    timeline = {}\n"
                "    timeline['start_frame'] = scene.frame_start\n"
                "    timeline['end_frame'] = scene.frame_end\n"
                "    timeline['current_frame'] = scene.frame_current\n"
                "    timeline['fps'] = scene.render.fps\n"
                "    print(json.dumps({'selected': result, 'timeline': timeline}))\n"
            )
        else:
            self._add_system_msg(f"\u26a0 Quick check not supported for {dcc}")
            return
        
        # Run on background thread to avoid UI freeze
        self._dcc_worker = DCCWorker(dcc_connector.send_code, dcc, code)
        self._dcc_worker.finished.connect(self._on_quick_check_done)
        self._dcc_worker.start()

    @Slot(bool, str)
    def _on_quick_check_done(self, success, output):
        """Handle quick check results from background thread."""
        self._clear_dcc_loading()
        if success:
            msg = (
                "Here are the scan results for the selected object(s).\n\n"
                "RULES FOR YOUR RESPONSE:\n"
                "- List EVERY problem from the 'problems' array — do not skip any\n"
                "- For each problem, explain briefly what it means in simple artist-friendly terms\n"
                "- If problem_count is 0 → say 'Looks clean! No issues found. \U0001f44d'\n"
                "- Do NOT write any code or fix scripts\n"
                "- At the end ask: 'Want me to fix these?' (only if problems exist)\n"
                "- Keep it conversational — like a colleague explaining, not a report\n\n"
                "SCAN DATA:\n" + output
            )
            session_manager.add_message(self._current_session, "user", msg)
            self._start_ai(msg, is_scan=True)
        else:
            self._add_system_msg(f"\u26a0 Quick check failed: {output}")

    def _on_screenshot(self):
        """Capture viewport screenshot. If fails, warn user — don't fake it."""
        if not self._current_session:
            return
        dcc = self._current_session.get("dcc")
        if not dcc:
            return
        
        from dcc_connector import is_dcc_connected, take_screenshot
        
        if not is_dcc_connected(dcc):
            self._add_system_msg(
                f"⚠ {dcc.capitalize()} is not connected — cannot capture screenshot."
            )
            return
        
        self._add_system_msg("📷 Capturing viewport...")
        
        success, b64 = take_screenshot(dcc)
        
        if not success or not b64:
            self._add_system_msg(
                "⚠ Screenshot failed — viewport image not attached.\n"
                f"Error: {b64 if b64 else 'Unknown error'}"
            )
            self._pending_screenshot = None
            return
        
        self._pending_screenshot = b64.strip().replace('\n', '').replace('\r', '')
        self._add_system_msg("\U0001f4f7 Screenshot ready \u2014 will attach to next message")

    def _set_dcc_loading(self, label="Working..."):
        """Show loading state on Send button and disable scan actions."""
        self.send_btn.setEnabled(False)
        # Keep arrow icon — never change button text
        self.send_btn.setToolTip(label)
        self.screenshot_btn.setEnabled(False)

    def _clear_dcc_loading(self):
        """Restore Send button and re-enable scan actions."""
        # Keep arrow icon — only restore tooltip
        self.send_btn.setToolTip("Send message")
        if not self._is_busy:
            self.send_btn.setEnabled(True)
        self.screenshot_btn.setEnabled(True)

    # -----------------------------------------------------------------------
    # AI streaming
    # -----------------------------------------------------------------------
    def _start_ai(self, user_text, has_image=False, is_scan=False):
        self._is_busy = True
        self._current_response = ""
        # Use clean text for intent detection (avoids mode prefixes triggering code writer)
        self._original_msg = getattr(self, '_original_msg_clean', user_text) or user_text
        self._original_msg_clean = None  # Reset after use
        self._current_is_scan = is_scan or is_scan_request(self._original_msg)
        self.send_btn.setEnabled(False)
        
        # Safety timeout — reset busy state if AI doesn't respond in 90 seconds
        if hasattr(self, '_busy_timeout'):
            self._busy_timeout.stop()
        self._busy_timeout = QTimer(self)
        self._busy_timeout.setSingleShot(True)
        self._busy_timeout.timeout.connect(self._on_busy_timeout)
        self._busy_timeout.start(90000)
        
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
            # Clean response text before finalize renders it
            self._current_bubble._text = self._clean_response_for_display(self._current_bubble._text)
            self._current_bubble.finalize()
        
        # --- Automatic artifact creation (exactly ONE per response) ---
        artifact_created = False
        if self._current_session and response.strip():
            # Snapshot existing artifacts before creation
            art_dir = self._get_artifacts_path()
            existing_before = set()
            if art_dir and os.path.isdir(art_dir):
                existing_before = set(os.listdir(art_dir))
            
            artifact_created = self._maybe_create_artifact(response)
            
            # Safety: ensure at most ONE new artifact was created
            if artifact_created and art_dir and os.path.isdir(art_dir):
                current_files = set(os.listdir(art_dir))
                new_files = sorted(current_files - existing_before)
                if len(new_files) > 1:
                    # Merge extras into the first one and delete the rest
                    first_path = os.path.join(art_dir, new_files[0])
                    merged_content = []
                    for i, fname in enumerate(new_files):
                        fpath = os.path.join(art_dir, fname)
                        with open(fpath, encoding="utf-8") as f:
                            merged_content.append(f"# === Part {i+1} ===\n{f.read()}")
                    with open(first_path, "w", encoding="utf-8") as f:
                        f.write("\n\n".join(merged_content))
                    # Delete extras
                    for fname in new_files[1:]:
                        os.remove(os.path.join(art_dir, fname))
        
        if self._current_session:
            session_manager.add_message(self._current_session, "assistant", response)
            session_manager.save_session(self._current_session)
            # Don't touch the artifacts panel — it stays in whatever state the user left it
            # (artifact creation already opened the viewer if needed)

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

        # Multi-agent: analyzer done → start codewriter (only if requested)
        if self._agent_phase == "analyzer" and mode == "multi":
            # Do NOT run Code Writer if this was just a scan
            if not getattr(self, '_current_is_scan', False) and needs_code_writer(self._original_msg):
                self._agent_phase = "codewriter"
                self._current_response = ""
                self._current_bubble = self._add_bubble("codewriter")
                # Build a rich handoff message with context
                cw_msg = (
                    f"Scene analysis:\n{response}\n\n"
                    f"User request: {self._original_msg}\n\n"
                    f"DCC: {dcc or 'unknown'}\n\n"
                    "Write ONE complete self-contained code block that addresses the user's request. "
                    "Use the analysis above for context (object names, issues found, etc.)."
                )
                self._codewriter_history.append({"role":"user","content":cw_msg})
                cw_settings = app_settings.get_agent_settings(self._settings, "codewriter", dcc)
                self._start_worker(self._codewriter_history, cw_settings)
                return

        # Context management
        self._msg_count_since_summary += 1

        # Auto-run: extract code blocks and execute without user click
        if getattr(self, '_auto_run_mode', False) and response:
            from ui_widgets import CodeBlockWidget
            blocks = []
            for pattern in (r'```scene-run\n(.*?)```', r'```python\n(.*?)```',
                            r'```maya-run\n(.*?)```'):
                import re as _re
                found = _re.findall(pattern, response, _re.DOTALL)
                if found:
                    blocks = found
                    break
            if blocks:
                QTimer.singleShot(600, lambda b=blocks: self._auto_execute_blocks(b))
                # Hide Run buttons on code blocks since auto-run will handle them
                if self._current_bubble:
                    for i in range(self._current_bubble.code_container.count()):
                        item = self._current_bubble.code_container.itemAt(i)
                        if item and item.widget() and isinstance(item.widget(), CodeBlockWidget):
                            item.widget().run_btn.hide()
                            item.widget().run_btn.setEnabled(False)

        self._reset_busy()
        self._update_token_count()

    def _reset_busy(self):
        self._agent_phase = "idle"
        self._is_busy = False
        self.send_btn.setEnabled(True)
        self._worker = None
        # Cancel safety timeout
        if hasattr(self, '_busy_timeout'):
            self._busy_timeout.stop()

    def _on_busy_timeout(self):
        """Safety reset if AI doesn't respond within 90 seconds."""
        if self._is_busy:
            self._add_system_msg("\u26a0 Request timed out \u2014 no response from AI. Try again.")
            self._reset_busy()

    # -----------------------------------------------------------------------
    # Token counter
    # -----------------------------------------------------------------------
    def _estimate_tokens(self, text):
        """Rough token estimation: ~4 chars per token."""
        return max(1, len(text) // 4)

    def _update_token_count(self):
        """Recalculate total tokens for current session."""
        total = 0
        if self._current_session:
            for msg in self._current_session.get("chat_history", []):
                content = msg.get("content", "")
                if isinstance(content, str):
                    total += self._estimate_tokens(content)
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict):
                            if part.get("type") == "text":
                                total += self._estimate_tokens(part.get("text", ""))
                            elif part.get("type") == "image_url":
                                total += 1000
        self._session_tokens = total
        self._update_token_display()

    def _update_token_display(self):
        """Update the token counter label."""
        t = self._session_tokens
        if t < 1000:
            display = f"~{t} tokens"
        elif t < 10000:
            display = f"~{t/1000:.1f}k tokens"
        else:
            display = f"~{t//1000}k tokens"
        
        if t < 50000:
            color = COLORS['text_muted']
        elif t < 100000:
            color = COLORS['status_warning']
        else:
            color = COLORS['status_critical']
        
        if hasattr(self, '_token_label'):
            self._token_label.setText(display)
            self._token_label.setStyleSheet(
                f"QLabel#tokenLabel {{ color: {color}; font-size: 10px; "
                f"background: transparent; border: 0px; padding: 0 4px; }}"
            )

    @Slot(str)
    def _on_error(self, msg):
        self._add_system_msg(f"\u26a0 Error: {msg}")
        self._agent_phase = "idle"
        self._is_busy = False
        self.send_btn.setEnabled(True)
        self._worker = None

    # -----------------------------------------------------------------------
    # Code execution
    # -----------------------------------------------------------------------
    def _extract_undo_label(self, code):
        """Pick a short label from the first comment in the code block.
        Falls back to 'Scene Doctor Fix' when no comment is present.
        """
        for line in code.split('\n'):
            stripped = line.strip()
            if stripped.startswith('#'):
                label = stripped.lstrip('#').strip()
                if label:
                    return label[:80]
        return "Scene Doctor Fix"

    def _log_trace(self, code, result, error_msg=""):
        """Append a tool-call trace entry to this session's JSONL trace file.
        One entry per execution — never raises, never blocks the UI.
        Trace file lives inside the session folder so it travels with it.
        """
        try:
            session = self._current_session or {}
            session_id = session.get("session_id", "unknown")
            dcc = session.get("dcc", "unknown")
            entry = {
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id,
                "dcc": dcc,
                "scene": session.get("scene_name", ""),
                "action": "code_execution",
                "label": self._extract_undo_label(code),
                "code": code,
                "result": "error" if error_msg else "success",
                "error_msg": error_msg or "",
                "undo_available": True,
            }
            session_dir = os.path.join(
                os.path.expanduser("~/Documents/SceneDoctor"),
                "sessions", dcc, session_id,
            )
            os.makedirs(session_dir, exist_ok=True)
            trace_file = os.path.join(session_dir, "trace.jsonl")
            with open(trace_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except Exception:
            # Trace logging must never break code execution
            pass

    def _show_trace_log(self):
        """Save the current session's trace log as a markdown artifact."""
        if not self._current_session:
            self._add_system_msg("No active session.")
            return

        session_id = self._current_session.get("session_id", "")
        dcc_key = self._current_session.get("dcc", "unknown")
        session_dir = os.path.join(
            os.path.expanduser("~/Documents/SceneDoctor"),
            "sessions", dcc_key, session_id,
        )
        trace_file = os.path.join(session_dir, "trace.jsonl")

        if not os.path.exists(trace_file):
            self._add_system_msg("No trace log for this session yet.")
            return

        entries = []
        try:
            with open(trace_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        continue
        except Exception as e:
            self._add_system_msg(f"\u26a0 Could not read trace log: {e}")
            return

        if not entries:
            self._add_system_msg("Trace log is empty.")
            return

        scene = self._current_session.get('scene_name', '')
        dcc = (self._current_session.get('dcc', '') or '').capitalize()
        report = ["# Tool-Call Trace", "",
                  f"**Session**: {scene}",
                  f"**DCC**: {dcc}",
                  f"**Entries**: {len(entries)}",
                  "", "---", ""]

        for i, entry in enumerate(entries, 1):
            status = "\u2705" if entry.get("result") == "success" else "\u274c"
            label = entry.get("label", "Code execution")
            report.append(f"## {i}. {status} {label}")
            report.append(f"**Time**: {entry.get('timestamp', '')}")
            report.append("")
            report.append("```python")
            report.append(entry.get("code", ""))
            report.append("```")
            report.append("")
            if entry.get("error_msg"):
                report.append(f"**Error**: {entry['error_msg']}")
                report.append("")
            report.append("---")
            report.append("")

        markdown = "\n".join(report)

        # Save as session artifact (reuses existing artifact storage)
        art_dir = os.path.join(
            session_manager.SESSIONS_DIR, dcc_key, session_id, "artifacts"
        )
        try:
            os.makedirs(art_dir, exist_ok=True)
        except Exception:
            pass

        art_filename = f"trace_{session_id[:8] or 'session'}.md"
        art_path = os.path.join(art_dir, art_filename)
        try:
            with open(art_path, "w", encoding="utf-8") as f:
                f.write(markdown)
        except Exception as e:
            self._add_system_msg(f"\u26a0 Could not save trace artifact: {e}")
            return

        # Surface it through the existing artifacts panel
        try:
            self._refresh_artifacts_panel()
            if not self._artifacts_panel.isVisible():
                self._artifacts_panel.setVisible(True)
                self._animate_artifacts_panel(close=False)
            self._open_artifact_in_viewer(art_path)
        except Exception:
            pass

        self._add_system_msg(
            f"\U0001f4cb Trace log saved as artifact ({len(entries)} "
            f"{'entry' if len(entries) == 1 else 'entries'})"
        )

    def _run_code(self, code):
        if not self._current_session:
            return
        dcc = self._current_session.get("dcc", "")
        code = self._sanitize_node_names(code)
        self._set_dcc_loading("Running...")

        # Wrap in undo chunk so the artist can Ctrl+Z this entire fix
        undo_label = self._extract_undo_label(code)
        self._dcc_worker = DCCWorker(
            dcc_connector.send_code, dcc, code, undo_label
        )

        def _on_run_done(success, result, _code=code, _dcc=dcc):
            self._clear_dcc_loading()
            if success:
                self._log_trace(_code, result)
                hint = (f" — press Ctrl+Z in {_dcc.capitalize()} to undo"
                        if _dcc else "")
                self._add_system_msg(
                    f"\u2705 Code executed{hint}\n{result[:200]}"
                )
                # Only auto-check for fix/repair operations, not creation
                # Skip agentic check for simple commands to avoid duplicates
            else:
                self._log_trace(_code, result, error_msg=result)
                self._add_system_msg(f"\u26a0 Execution error: {result}")
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
    # Force software OpenGL to prevent rendering glitches on Windows
    QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL)
    
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
