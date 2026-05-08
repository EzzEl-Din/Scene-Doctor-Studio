"""
ui_widgets.py — Scene Doctor Studio
Custom PySide6 widgets for the chat interface.

Built by Ezz El-Din
"""
import re
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy, QScrollArea, QTextEdit, QLineEdit, QApplication
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QColor, QPalette, QFontDatabase, QImage

# ---------------------------------------------------------------------------
# Color themes — "Elegant AI" (Claude-inspired)
# ---------------------------------------------------------------------------
THEMES = {
    "dark": {
        "bg_dark": "#1b1b1f",
        "bg_secondary": "#232329",
        "bg_panel": "#27272e",
        "bg_sidebar": "#18181c",
        "bg_input": "#2a2a32",
        "bg_msg_user": "#3d3d47",
        "bg_msg_ai": "#27272e",
        "bg_msg_system": "#1f1f24",
        "bg_code": "#16161a",
        "text": "#e8e4df",
        "text_muted": "#8e8b87",
        "text_code": "#a8c7e6",
        "accent_blue": "#6b8aad",
        "accent_blue_hover": "#5a7899",
        "accent_teal": "#5a9e6f",
        "accent_orange": "#c4964a",
        "accent_green": "#5a9e6f",
        "accent_red": "#c25d5d",
        "accent_purple": "#9a7dba",
        "border": "#35353d",
        "border_hover": "#4a4a55",
        "divider": "#2d2d34",
        "btn_danger": "#4a2a2a",
        "btn_danger_hover": "#5c3535",
        "btn_secondary": "#35353d",
        "btn_secondary_hover": "#42424d",
        "btn_disabled": "#2d2d34",
        "status_success": "#5a9e6f",
        "status_warning": "#c4964a",
        "status_critical": "#c25d5d",
        "status_info": "#6b8aad",
        "maya_color": "#5a8fc4",
        "blender_color": "#d48a3a",
        "btn_primary_text": "#ffffff",
    },
    "light": {
        "bg_dark": "#f5f3ef",
        "bg_secondary": "#eae7e1",
        "bg_panel": "#ffffff",
        "bg_sidebar": "#ebe8e3",
        "bg_input": "#f9f7f4",
        "bg_msg_user": "#e6e3dd",
        "bg_msg_ai": "#ffffff",
        "bg_msg_system": "#f0ede8",
        "bg_code": "#1b1b1f",
        "text": "#2d2b28",
        "text_muted": "#7a7672",
        "text_code": "#a8c7e6",
        "accent_blue": "#5a7d9e",
        "accent_blue_hover": "#4a6b8a",
        "accent_teal": "#3d8a55",
        "accent_orange": "#b07d2e",
        "accent_green": "#3d8a55",
        "accent_red": "#b04a4a",
        "accent_purple": "#7a5d9a",
        "border": "#d8d4cd",
        "border_hover": "#c0bbb4",
        "divider": "#e2dfd9",
        "btn_danger": "#e8c8c8",
        "btn_danger_hover": "#d4a0a0",
        "btn_secondary": "#e6e3dd",
        "btn_secondary_hover": "#d8d4cd",
        "btn_disabled": "#dad6cf",
        "status_success": "#3d8a55",
        "status_warning": "#b07d2e",
        "status_critical": "#b04a4a",
        "status_info": "#5a7d9e",
        "maya_color": "#4a7ab0",
        "blender_color": "#c07a2e",
        "btn_primary_text": "#2d2b28",
    },
}

# Active palette — mutable, swapped by set_theme()
COLORS = dict(THEMES["dark"])


def set_theme(theme_name):
    """Switch the active color palette. Call before building/refreshing UI."""
    src = THEMES.get(theme_name, THEMES["dark"])
    COLORS.clear()
    COLORS.update(src)

FONT_FAMILY = "Segoe UI"
MONO_FONT = "Consolas"

# Agent labels & colors (matching V4 ai_backend.py)
AGENT_LABELS = {
    "analyzer": "🔍 Analyzer",
    "codewriter": "🔧 Code Writer",
    "vision": "👁 Vision",
    "summary": "💬 Summary",
    "assistant": "🤖 Scene Doctor",
    "system": "⚙️ System",
}

AGENT_COLORS = {
    "analyzer": "#3abfb0",
    "codewriter": "#d4a843",
    "vision": "#a78bda",
    "summary": "#5b9bd5",
    "assistant": "#3abfb0",
    "user": "#2d9cdb",
    "system": "#7a8a9e",
}

AGENT_TOOLTIPS = {
    "analyzer": "Understands your scene. Use a smart model — gpt-4o, claude-3-5-sonnet",
    "codewriter": "Writes DCC Python. Use a code-focused model — gpt-4o, deepseek-coder",
    "vision": "Reads images. Must support vision — gpt-4o, gemini-2.0-flash",
    "summary": "Summarises chat. Any fast model works — llama3, mistral-small",
}


# ---------------------------------------------------------------------------
# Style helpers
# ---------------------------------------------------------------------------
def get_app_stylesheet():
    return f"""
    QMainWindow, QWidget {{
        background-color: {COLORS['bg_dark']};
        color: {COLORS['text']};
        font-family: '{FONT_FAMILY}';
        font-size: 13px;
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: {COLORS['bg_secondary']};
        width: 8px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: {COLORS['border']};
        border-radius: 4px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {COLORS['border_hover']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QLineEdit, QTextEdit {{
        background: {COLORS['bg_input']};
        color: {COLORS['text']};
        border: 1px solid {COLORS['border']};
        border-radius: 8px;
        padding: 8px 12px;
        font-size: 13px;
    }}
    QLineEdit:focus, QTextEdit:focus {{
        border-color: {COLORS['accent_blue']};
    }}
    QPushButton {{
        background: {COLORS['accent_blue']};
        color: {COLORS.get('btn_primary_text', '#ffffff')};
        border: none;
        border-radius: 6px;
        padding: 8px 16px;
        font-weight: bold;
        font-size: 13px;
    }}
    QPushButton:hover {{
        background: {COLORS['accent_blue_hover']};
    }}
    QPushButton:pressed {{
        background: {COLORS['accent_blue']};
    }}
    QPushButton:disabled {{
        background: {COLORS['btn_disabled']};
        color: {COLORS['text_muted']};
        border: 1px solid {COLORS['border']};
    }}
    """


# ---------------------------------------------------------------------------
# ChatLineEdit — supports Ctrl+V image paste
# ---------------------------------------------------------------------------
class ChatLineEdit(QLineEdit):
    """Custom line edit that intercepts Ctrl+V to detect pasted images."""
    pasted_image = Signal(QImage)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_V and (event.modifiers() & Qt.ControlModifier):
            clipboard = QApplication.clipboard()
            mime = clipboard.mimeData()
            if mime.hasImage():
                image = clipboard.image()
                if not image.isNull():
                    self.pasted_image.emit(image)
                    return
        super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Chat message bubble
# ---------------------------------------------------------------------------
class MessageBubble(QFrame):
    run_code = Signal(str)  # emits code string
    dismiss_code = Signal(int)
    user_bubble_color = COLORS["bg_msg_user"]  # updated from settings

    def __init__(self, role, text="", parent=None):
        super().__init__(parent)
        self.role = role
        self._text = text
        self._code_blocks = []
        self._setup_ui()

    def _setup_ui(self):
        self.setFrameShape(QFrame.NoFrame)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(4)

        is_user = self.role == "user"
        is_system = self.role == "system"

        if is_user:
            bg = COLORS["bg_msg_user"]
            align = Qt.AlignRight
        elif is_system:
            bg = COLORS["bg_msg_system"]
            align = Qt.AlignCenter
        else:
            bg = COLORS["bg_msg_ai"]
            align = Qt.AlignLeft

        self.setStyleSheet(f"""
            MessageBubble {{
                background: {bg};
                border-radius: 12px;
                margin: 2px {'60px 2px 8px' if is_user else '8px 2px 60px'};
            }}
        """)

        # Role label
        if not is_user:
            role_label_text = AGENT_LABELS.get(self.role, self.role)
            role_color = AGENT_COLORS.get(self.role, COLORS['text_muted'])
            role_label = QLabel(role_label_text)
            role_label.setStyleSheet(
                f"color: {role_color}; font-size: 11px; "
                f"font-weight: bold; background: transparent;"
            )
            layout.addWidget(role_label)

        # Content label
        self.content_label = QLabel(self._text)
        self.content_label.setWordWrap(True)
        self.content_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.content_label.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 13px; "
            f"background: transparent; line-height: 1.5;"
        )
        layout.addWidget(self.content_label)

        # Code blocks container
        self.code_container = QVBoxLayout()
        layout.addLayout(self.code_container)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def set_text(self, text):
        self._text = text
        display = text
        self._code_blocks = []

        for pattern in [r'```scene-run\n(.*?)```', r'```maya-run\n(.*?)```',
                        r'```python\n(.*?)```', r'```maya-python\n(.*?)```']:
            for match in re.finditer(pattern, text, re.DOTALL):
                self._code_blocks.append(match.group(1))
                display = display.replace(match.group(0), "")

        self.content_label.setText(display.strip())
        self._render_code_blocks()

    def append_text(self, token):
        self._text += token
        self.content_label.setText(self._text)

    def finalize(self):
        """Called when streaming is done — parse code blocks."""
        self.set_text(self._text)

    def _render_code_blocks(self):
        while self.code_container.count():
            item = self.code_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, code in enumerate(self._code_blocks):
            block = CodeBlockWidget(code, i)
            block.run_clicked.connect(lambda c=code: self.run_code.emit(c))
            self.code_container.addWidget(block)


# ---------------------------------------------------------------------------
# Code block widget with Run/Dismiss — EDITABLE code
# ---------------------------------------------------------------------------
class CodeBlockWidget(QFrame):
    run_clicked = Signal(str)

    def __init__(self, code, index=0, parent=None):
        super().__init__(parent)
        self.code = code
        self.index = index
        self._dismissed = False
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet(f"""
            CodeBlockWidget {{
                background: {COLORS['bg_code']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                margin: 4px 0;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # Header
        header = QHBoxLayout()
        title = QLabel(f"📋 Code Block {self.index + 1}")
        title.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; "
            f"font-weight: bold; background: transparent;"
        )
        header.addWidget(title)
        header.addStretch()

        self.run_btn = QPushButton("▶ Run")
        self.run_btn.setFixedSize(70, 28)
        self.run_btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['accent_green']};
                color: white; border-radius: 4px;
                font-size: 12px; padding: 2px 8px;
            }}
            QPushButton:hover {{ background: #16a34a; }}
        """)
        self.run_btn.clicked.connect(self._on_run)
        header.addWidget(self.run_btn)

        self.dismiss_btn = QPushButton("✕ Dismiss")
        self.dismiss_btn.setFixedSize(80, 28)
        self.dismiss_btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['btn_danger']};
                color: {COLORS['text']}; border-radius: 4px;
                font-size: 12px; padding: 2px 8px;
            }}
            QPushButton:hover {{ background: {COLORS['btn_danger_hover']}; }}
        """)
        self.dismiss_btn.clicked.connect(self._dismiss)
        header.addWidget(self.dismiss_btn)

        layout.addLayout(header)

        # Editable code text (QTextEdit)
        self.code_edit = QTextEdit()
        self.code_edit.setPlainText(self.code.strip())
        self.code_edit.setReadOnly(False)
        self.code_edit.setStyleSheet(
            f"color: {COLORS['text_code']}; "
            f"font-family: '{MONO_FONT}', 'Courier New', monospace; "
            f"font-size: 12px; background: transparent; border: none;"
        )
        lines = self.code.strip().count('\n') + 1
        self.code_edit.setFixedHeight(min(200, max(40, lines * 16 + 20)))
        layout.addWidget(self.code_edit)

        # Result area
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet(
            f"background: transparent; font-size: 12px;"
        )
        self.result_label.hide()
        layout.addWidget(self.result_label)

    def _on_run(self):
        """Emit the current (possibly edited) code."""
        current_code = self.code_edit.toPlainText()
        self.code = current_code
        self.run_clicked.emit(current_code)

    def _dismiss(self):
        """Grey out the code and disable buttons."""
        self._dismissed = True
        self.setStyleSheet(f"""
            CodeBlockWidget {{
                background: #2d2d2d;
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                margin: 4px 0;
            }}
        """)
        self.code_edit.setStyleSheet(
            f"color: #666666; font-family: '{MONO_FONT}'; "
            f"font-size: 12px; background: transparent; border: none;"
        )
        self.code_edit.setReadOnly(True)
        self.run_btn.hide()
        self.dismiss_btn.hide()

    def show_result(self, success, message):
        if success:
            self.result_label.setText(f"✅ {message}")
            self.result_label.setStyleSheet(
                f"color: {COLORS['accent_green']}; "
                f"background: transparent; font-size: 12px;"
            )
            self.run_btn.setText("✅ Done")
            self.run_btn.setEnabled(False)
        else:
            self.result_label.setText(f"⚠ {message}")
            self.result_label.setStyleSheet(
                f"color: {COLORS['accent_red']}; "
                f"background: transparent; font-size: 12px;"
            )
            self.run_btn.setText("⚠ Error")
        self.result_label.show()


# ---------------------------------------------------------------------------
# Session list item widget
# ---------------------------------------------------------------------------
class SessionItemWidget(QFrame):
    clicked = Signal(str)  # session_id

    def __init__(self, session_data, parent=None):
        super().__init__(parent)
        self.session_id = session_data.get("session_id", "")
        self.dcc = session_data.get("dcc", "unknown")
        self._selected = False
        self._expanded = True
        self._setup_ui(session_data)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"{session_data.get('scene_name', 'untitled')} • {self.dcc.capitalize()}")

    def _setup_ui(self, data):
        self.setFixedHeight(44)
        self.setStyleSheet(self._get_style(False))

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(10, 6, 10, 6)
        self._layout.setSpacing(10)

        dot_color = COLORS.get(f"{self.dcc}_color", COLORS['text_muted'])
        self._dot = QLabel("\u25cf")
        self._dot.setFixedSize(20, 32)
        self._dot.setAlignment(Qt.AlignCenter)
        self._dot.setStyleSheet(
            f"color: {dot_color}; font-size: 14px; background: transparent;"
        )
        self._layout.addWidget(self._dot)

        # Text info container
        self._info_widget = QWidget()
        info_layout = QVBoxLayout(self._info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(1)

        self._name_label = QLabel(data.get("scene_name", "untitled"))
        self._name_label.setStyleSheet(
            f"color: {COLORS['text']}; font-weight: bold; "
            f"font-size: 13px; background: transparent;"
        )
        info_layout.addWidget(self._name_label)

        self._dcc_label = QLabel(data.get("dcc", "").capitalize())
        self._dcc_label.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; "
            f"background: transparent;"
        )
        info_layout.addWidget(self._dcc_label)
        self._layout.addWidget(self._info_widget)
        self._layout.addStretch()

    def _get_style(self, selected):
        bg = COLORS['bg_panel'] if selected else "transparent"
        border = COLORS['accent_blue'] if selected else "transparent"
        return f"""
            SessionItemWidget {{
                background: {bg};
                border-left: 3px solid {border};
                border-radius: 6px;
            }}
            SessionItemWidget:hover {{
                background: {COLORS['bg_panel']};
            }}
        """

    def set_selected(self, sel):
        self._selected = sel
        self.setStyleSheet(self._get_style(sel))

    def set_expanded(self, expanded):
        """Show/hide text labels for sidebar collapse. Center dot when collapsed."""
        self._expanded = expanded
        self._info_widget.setVisible(expanded)
        if expanded:
            self._layout.setContentsMargins(10, 6, 10, 6)
            self._dot.setFixedSize(20, 32)
        else:
            # Stretch dot to fill the full 56px rail width so it centers
            self._layout.setContentsMargins(0, 6, 0, 6)
            self._dot.setFixedSize(56, 32)

    def mousePressEvent(self, event):
        self.clicked.emit(self.session_id)
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# Typing indicator
# ---------------------------------------------------------------------------
class TypingIndicator(QFrame):
    def __init__(self, phase="analyzer", parent=None):
        super().__init__(parent)
        labels = {
            "analyzer": "🔍 Analyzing...",
            "codewriter": "🔧 Writing code...",
            "vision": "👁 Checking viewport...",
            "single": "🤖 Thinking...",
            "assistant": "🤖 Thinking...",
        }
        self.setStyleSheet(f"""
            TypingIndicator {{
                background: {COLORS['bg_msg_ai']};
                border-radius: 12px;
                margin: 2px 8px 2px 60px;
            }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        lbl = QLabel(labels.get(phase, "⏳ Thinking..."))
        lbl.setStyleSheet(
            f"color: {COLORS['accent_blue']}; font-size: 12px; "
            f"background: transparent;"
        )
        layout.addWidget(lbl)
