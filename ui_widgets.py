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
        # Backgrounds — deep navy family matching logo
        "bg_dark":       "#0E1016",   # logo background — deepest
        "bg_secondary":  "#141820",   # panels
        "bg_panel":      "#0F1525",   # chat panel — distinct from bubbles
        "bg_sidebar":    "#111419",   # sidebar
        "bg_input":      "#171D2C",   # input box — slightly lighter than bg_dark
        "bg_msg_user":   "#1a2540",   # user message — blue tint
        "bg_msg_ai":     "#0d1117",   # AI message — darker
        "bg_msg_system": "#111419",   # system message
        "bg_code":       "#090C12",   # code blocks — always dark

        # Text
        "text":          "#E8E6E1",
        "text_muted":    "#6B7280",
        "msg_text":      "#E8E6E1",
        "text_code":     "#5EEAD4",   # teal-tinted code text

        # Accent — teal from logo
        "accent_blue":       "#2DD4BF",   # calm teal primary
        "accent_blue_hover": "#25B8A6",   # hover
        "accent_teal":       "#2DD4BF",
        "accent_orange":     "#B4853A",
        "accent_green":      "#488E5E",
        "accent_red":        "#B24C4C",
        "accent_purple":     "#8A6DAA",

        # Chat area
        "bg_chat":       "#141820",   # slate blue — cohesive with dark AI theme

        # Borders — subtle navy
        "border":        "#1E2330",
        "border_hover":  "#252B3B",
        "divider":       "#1E2330",

        # Buttons
        "btn_danger":          "#3A1E1E",
        "btn_danger_hover":    "#4A2828",
        "btn_secondary":       "#1E2330",
        "btn_secondary_hover": "#252B3B",
        "btn_disabled":        "#121720",
        "btn_primary_text":    "#FFFFFF",

        # Status
        "status_success":  "#488E5E",
        "status_warning":  "#B4853A",
        "status_critical": "#B24C4C",
        "status_info":     "#2DD4BF",   # teal for info

        # DCC colors
        "maya_color":    "#5A8FC4",
        "blender_color": "#D48A3A",
    },

    "light": {
        # Backgrounds — cool light gray / professional
        "bg_dark":       "#F7F5F2",   # main chat area
        "bg_secondary":  "#EFEBE5",   # hover states
        "bg_panel":      "#FFFFFF",   # header bar
        "bg_sidebar":    "#F0EDE8",   # sidebar
        "bg_input":      "#FFFFFF",   # input card
        "bg_msg_user":   "#EDE9E3",   # user msg
        "bg_msg_ai":     "#FFFFFF",   # AI msg
        "bg_msg_system": "#F0EDE8",   # system msg
        "bg_code":       "#090C12",   # code blocks — keep dark

        # Text
        "text":          "#1C1917",   # primary text
        "text_muted":    "#78716C",   # placeholder / muted
        "msg_text":      "#1C1917",   # user msg text
        "msg_text_ai":   "#1C1917",   # AI msg text
        "text_code":     "#5EEAD4",   # code text stays

        # Accent — keep teal
        "accent_blue":       "#2DD4BF",   # primary accent
        "accent_blue_hover": "#25B8A6",
        "accent_teal":       "#2DD4BF",
        "accent_orange":     "#A06D1E",
        "accent_green":      "#2D7A45",
        "accent_red":        "#A03A3A",
        "accent_purple":     "#6A4D8A",

        # Chat area
        "bg_chat":       "#F5F3F0",   # neutral off-white — clean, no warmth

        # Borders
        "border":        "#E0D9D0",
        "border_hover":  "#D0C9C0",
        "divider":       "#E0D9D0",

        # Custom UI Elements
        "border_msg_ai":       "#E0D9D0",
        "bg_session_hover":    "#EFEBE5",
        "bg_session_selected": "#E5E0D8",
        "btn_pill_border":     "#D0C9C0",
        "btn_pill_text":       "#78716C",
        "sidebar_text_sec":    "#78716C",

        # Buttons
        "btn_danger":          "#FCE8E8",
        "btn_danger_hover":    "#F5CCCC",
        "btn_secondary":       "#EFEBE5",
        "btn_secondary_hover": "#E0D9D0",
        "btn_disabled":        "#EFEBE5",
        "btn_primary_text":    "#ffffff",

        # Status
        "status_success":  "#2D7A45",
        "status_warning":  "#A06D1E",
        "status_critical": "#A03A3A",
        "status_info":     "#2DD4BF",

        # DCC colors
        "maya_color":    "#4A7AB0",
        "blender_color": "#C07A2E",
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
    QTextEdit#chatInput {{
        background: transparent;
        border: 0px;
        border-radius: 0px;
        padding: 6px;
        font-size: 14px;
        color: {COLORS['text']};
        outline: none;
    }}
    QTextEdit#chatInput:focus {{
        border: 0px;
        outline: none;
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

        # User bubble: simple border, no accent
        # AI bubble: left teal accent border
        if is_user:
            border = f"border: 1px solid #243050;"
        elif is_system:
            border = "border: none;"
        else:
            border = f"border: 1px solid #1a1f2e; border-left: 3px solid {COLORS['accent_blue']};"
        
        self.setStyleSheet(f"""
            MessageBubble {{
                background: {bg};
                border-radius: 12px;
                {border}
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
        text_color = COLORS.get('msg_text', COLORS['text'])
        if not is_user and not is_system:
            text_color = COLORS.get('msg_text_ai', text_color)
            
        self.content_label.setStyleSheet(
            f"color: {text_color}; font-size: 13px; "
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
                color: {COLORS.get('btn_primary_text', COLORS['text'])};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                font-size: 12px; padding: 2px 8px;
            }}
            QPushButton:hover {{ 
                background: {COLORS['status_success']};
                border-color: {COLORS['border_hover']};
            }}
        """)
        self.run_btn.clicked.connect(self._on_run)
        header.addWidget(self.run_btn)

        self.dismiss_btn = QPushButton("✕ Dismiss")
        self.dismiss_btn.setFixedSize(80, 28)
        self.dismiss_btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['btn_danger']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                font-size: 12px; padding: 2px 8px;
            }}
            QPushButton:hover {{ 
                background: {COLORS['btn_danger_hover']};
                border-color: {COLORS['border_hover']};
            }}
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
        """Emit the current (possibly edited) code. Prevents double execution."""
        if getattr(self, '_already_run', False):
            return
        self._already_run = True
        self.run_btn.setEnabled(False)
        self.run_btn.setText("Running...")
        current_code = self.code_edit.toPlainText()
        self.code = current_code
        self.run_clicked.emit(current_code)

    def _dismiss(self):
        """Grey out the code and disable buttons."""
        self._dismissed = True
        self.setStyleSheet(f"""
            CodeBlockWidget {{
                background: {COLORS['bg_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                margin: 4px 0;
            }}
        """)
        self.code_edit.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-family: '{MONO_FONT}'; "
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
            f"color: {COLORS['text_muted']}; font-weight: bold; "
            f"font-size: 13px; background: transparent;"
        )
        info_layout.addWidget(self._name_label)

        self._dcc_label = QLabel(data.get("dcc", "").capitalize())
        self._dcc_label.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 10px; "
            f"background: transparent;"
        )
        info_layout.addWidget(self._dcc_label)
        self._layout.addWidget(self._info_widget)
        self._layout.addStretch()

    def _get_style(self, selected):
        bg = COLORS['bg_secondary'] if selected else "transparent"
        border = COLORS['accent_teal'] if selected else "transparent"
        hover_bg = COLORS['bg_secondary']
        return f"""
            SessionItemWidget {{
                background: {bg};
                border-left: 3px solid {border};
                border-radius: 6px;
            }}
            SessionItemWidget:hover {{
                background: {hover_bg};
            }}
        """

    def set_selected(self, sel):
        self._selected = sel
        self.setStyleSheet(self._get_style(sel))
        if sel:
            self._name_label.setStyleSheet(
                f"color: {COLORS['text']}; font-weight: bold; "
                f"font-size: 13px; background: transparent;"
            )
        else:
            self._name_label.setStyleSheet(
                f"color: {COLORS['text_muted']}; font-weight: bold; "
                f"font-size: 13px; background: transparent;"
            )

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
    
    def update_theme(self, theme):
        """Update widget colors when theme changes."""
        # Update frame style
        self.setStyleSheet(self._get_style(self._selected))
        
        # Update dot color
        dot_color = theme.get(f"{self.dcc}_color", theme['text_muted'])
        self._dot.setStyleSheet(
            f"color: {dot_color}; font-size: 14px; background: transparent;"
        )
        
        # Update name label
        if self._selected:
            self._name_label.setStyleSheet(
                f"color: {theme['text']}; font-weight: bold; "
                f"font-size: 13px; background: transparent;"
            )
        else:
            self._name_label.setStyleSheet(
                f"color: {theme['text_muted']}; font-weight: bold; "
                f"font-size: 13px; background: transparent;"
            )
        
        # Update DCC label
        self._dcc_label.setStyleSheet(
            f"color: {theme['text_muted']}; font-size: 10px; "
            f"background: transparent;"
        )

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
