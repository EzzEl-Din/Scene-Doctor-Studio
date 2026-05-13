"""
studio_settings_dialog.py — Full Settings Dialog (ported from V4 main.py)
Single/Multi agent mode, per-agent tabs, advanced system prompts, chat color.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QFormLayout, QComboBox, QDialogButtonBox, QTabWidget, QGroupBox,
    QRadioButton, QButtonGroup, QSizePolicy, QTextEdit, QWidget
)
from PySide6.QtCore import Qt, QTimer, Signal
from ui_widgets import COLORS, AGENT_LABELS, AGENT_TOOLTIPS
import settings as app_settings

_AGENTS = ("analyzer", "codewriter", "vision", "summary")

def _get_style():
    """Minimal settings dialog stylesheet — avoid complex styles that cause glitches."""
    return f"""
QGroupBox {{ font-weight: bold; border: 1px solid {COLORS['border']}; border-radius: 6px;
  margin-top: 8px; padding: 12px 10px 8px 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; }}
QLineEdit {{ background: {COLORS['bg_input']}; border: 1px solid {COLORS['border']};
  border-radius: 4px; padding: 5px 8px; }}
QLineEdit:focus {{ border-color: {COLORS['accent_blue']}; }}
"""


class SettingsDialog(QDialog):
    theme_changed = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Agent Settings")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.resize(550, 650)
        self.setMinimumSize(500, 400)
        self.setStyleSheet(_get_style())
        from PySide6.QtGui import QPalette, QColor
        pal = self.palette()
        pal.setColor(QPalette.Window, QColor(COLORS['bg_dark']))
        self.setPalette(pal)
        self.setAutoFillBackground(True)
        self._raw_settings = settings  # keep reference for non-agent keys
        # Multi-agent configs from the nested multi_agent section
        ma = settings.get("multi_agent", {})
        self._agents = {}
        for k in _AGENTS:
            self._agents[k] = dict(ma.get(k, {}))
        self._mode = settings.get("mode", "single")
        self._single_cfg = dict(settings.get("single_agent", {}))
        self._accent_color = settings.get("accent_color", "#6b8aad")
        self._theme = settings.get("theme", "dark")
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Mode toggle
        mg = QGroupBox("AI Mode")
        mr = QHBoxLayout(mg)
        self._mode_single = QRadioButton("Single Agent")
        self._mode_multi = QRadioButton("Multi Agent")
        bg = QButtonGroup(self)
        bg.addButton(self._mode_single)
        bg.addButton(self._mode_multi)
        (self._mode_multi if self._mode == "multi" else self._mode_single).setChecked(True)
        mr.addWidget(self._mode_single)
        mr.addWidget(self._mode_multi)
        mr.addStretch()
        layout.addWidget(mg)

        # Backend toggle
        bbg = QGroupBox("Backend")
        br = QHBoxLayout(bbg)
        self._bk_ollama = QRadioButton("Local (Ollama)")
        self._bk_api = QRadioButton("External API")
        bkg = QButtonGroup(self)
        bkg.addButton(self._bk_ollama)
        bkg.addButton(self._bk_api)
        init_bk = self._single_cfg.get("backend") or self._agents.get("analyzer", {}).get("backend", "ollama")
        (self._bk_api if init_bk == "openai" else self._bk_ollama).setChecked(True)
        br.addWidget(self._bk_ollama)
        br.addWidget(self._bk_api)
        br.addStretch()
        layout.addWidget(bbg)

        # Appearance — Theme + Accent
        ag = QGroupBox("Appearance")
        al = QVBoxLayout(ag)

        # Theme toggle
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Theme:"))
        self._theme_dark = QRadioButton("🌙 Dark")
        self._theme_light = QRadioButton("☀️ Light")
        tg = QButtonGroup(self)
        tg.addButton(self._theme_dark)
        tg.addButton(self._theme_light)
        (self._theme_light if self._theme == "light" else self._theme_dark).setChecked(True)
        theme_row.addWidget(self._theme_dark)
        theme_row.addWidget(self._theme_light)
        theme_row.addStretch()
        al.addLayout(theme_row)

        # Accent swatches
        accent_lbl = QLabel("Accent color:")
        accent_lbl.setStyleSheet("margin-top: 6px;")
        al.addWidget(accent_lbl)
        swatch_row = QHBoxLayout()
        self._accent_presets = {
            "Blue": "#6b8aad",
            "Cyan": "#2d9cdb",
            "Teal": "#5a9e6f",
            "Purple": "#9a7dba",
            "Amber": "#c4964a",
            "Rose": "#b06070",
        }
        for name, hex_color in self._accent_presets.items():
            btn = QPushButton()
            btn.setFixedSize(28, 28)
            btn.setToolTip(name)
            selected = "2px solid #fff" if hex_color == self._accent_color else "2px solid transparent"
            btn.setStyleSheet(
                f"background: {hex_color}; border: {selected}; border-radius: 14px;")
            btn.clicked.connect(lambda checked=False, c=hex_color: self._set_accent(c))
            swatch_row.addWidget(btn)
        custom_btn = QPushButton("...")
        custom_btn.setFixedSize(28, 28)
        custom_btn.setToolTip("Custom color")
        custom_btn.setStyleSheet(
            "background: #555; border: 2px solid transparent; border-radius: 14px; font-size: 10px; color: #ccc;")
        custom_btn.clicked.connect(self._pick_custom_accent)
        swatch_row.addWidget(custom_btn)
        swatch_row.addStretch()
        al.addLayout(swatch_row)
        self._accent_preview = QLabel(f"● {self._accent_color}")
        self._accent_preview.setStyleSheet(f"color: {self._accent_color}; font-size: 11px; font-weight: bold;")
        al.addWidget(self._accent_preview)
        layout.addWidget(ag)

        # Single agent fields
        self._single_w = QGroupBox("Single Agent")
        sf = QFormLayout(self._single_w)
        sf.setSpacing(8)
        s = self._single_cfg or self._agents.get("analyzer", {})
        self._s_url = QLineEdit(s.get("base_url", ""))
        self._s_url.setPlaceholderText("http://localhost:11434")
        sf.addRow("Base URL:", self._s_url)
        self._s_key = QLineEdit(s.get("api_key", ""))
        self._s_key.setPlaceholderText("sk-... (leave blank for Ollama)")
        self._s_key.setEchoMode(QLineEdit.Password)
        sf.addRow("API Key:", self._s_key)
        self._s_model = QLineEdit(s.get("model", "llama3"))
        self._s_model.setPlaceholderText("llama3 / gpt-4o / mistral ...")
        sf.addRow("Model:", self._s_model)
        # Multi agent tabs
        self._multi_w = QWidget()
        ml = QVBoxLayout(self._multi_w)
        ml.setContentsMargins(0, 0, 0, 0)
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)  # Simpler rendering, less glitchy
        self._agent_widgets = {}
        for ak in _AGENTS:
            tab, widgets = self._build_tab(ak)
            self._tabs.addTab(tab, AGENT_LABELS.get(ak, ak))
            self._agent_widgets[ak] = widgets
        ml.addWidget(self._tabs)
        copy_btn = QPushButton("\ud83d\udccb Copy to all agents")
        copy_btn.clicked.connect(self._copy_all)
        ml.addWidget(copy_btn)

        # Agents section (no nested tab widget — flat layout)
        agents_section = QWidget()
        al = QVBoxLayout(agents_section)
        al.setContentsMargins(0, 4, 0, 0)
        al.setSpacing(4)
        al.addWidget(self._single_w)
        al.addWidget(self._multi_w)
        layout.addWidget(agents_section, 1)

        # Profile section — "About You" with quick-add chips
        profile_group = QGroupBox("About You")
        pg_layout = QVBoxLayout(profile_group)
        pg_layout.setContentsMargins(10, 16, 10, 8)
        pg_layout.setSpacing(6)
        
        desc = QLabel("Tell the AI who you are and what you work on.")
        desc.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 11px;")
        pg_layout.addWidget(desc)
        
        self._profile_input = QTextEdit()
        self._profile_input.setPlaceholderText(
            "Example: I'm a Character Rigger working in Maya on game characters for Unity. "
            "I focus on deformation quality and performance optimization."
        )
        self._profile_input.setFixedHeight(60)
        saved_profile = self._raw_settings.get("user_profile", "")
        self._profile_input.setPlainText(saved_profile)
        pg_layout.addWidget(self._profile_input)
        
        # Quick-add chips
        chips_layout = QHBoxLayout()
        chips_layout.setSpacing(6)
        for suggestion in ["Rigger", "Animator", "Lighter", "Modeler", "TD", "VFX Artist"]:
            chip = QPushButton(suggestion)
            chip.setFixedHeight(24)
            chip.setStyleSheet(f"""
                QPushButton {{
                    background: {COLORS['bg_input']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 12px;
                    color: {COLORS['text_muted']};
                    font-size: 10px;
                    padding: 0 8px;
                }}
                QPushButton:hover {{
                    border-color: {COLORS['accent_blue']};
                    color: {COLORS['accent_blue']};
                }}
            """)
            chip.clicked.connect(lambda checked, s=suggestion: self._append_to_profile(s))
            chips_layout.addWidget(chip)
        chips_layout.addStretch()
        pg_layout.addLayout(chips_layout)
        
        layout.addWidget(profile_group)

        # Buttons
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._mode_single.toggled.connect(self._on_mode)
        self._on_mode()

    def _on_mode(self):
        is_s = self._mode_single.isChecked()
        self._single_w.setVisible(is_s)
        self._multi_w.setVisible(not is_s)

    def _set_accent(self, color):
        self._accent_color = color
        self._accent_preview.setText(f"Current: {color}")
        self._accent_preview.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: bold;")

    def _pick_custom_accent(self):
        from PySide6.QtWidgets import QColorDialog
        from PySide6.QtGui import QColor
        color = QColorDialog.getColor(QColor(self._accent_color), self, "Choose Accent Color")
        if color.isValid():
            self._set_accent(color.name())

    def _build_tab(self, ak):
        w = QWidget()
        f = QFormLayout(w)
        f.setSpacing(10)
        s = self._agents[ak]
        url = QLineEdit(s.get("base_url", ""))
        url.setPlaceholderText("http://localhost:11434")
        f.addRow("Base URL:", url)
        key = QLineEdit(s.get("api_key", ""))
        key.setPlaceholderText("sk-...")
        key.setEchoMode(QLineEdit.Password)
        f.addRow("API Key:", key)
        model = QLineEdit(s.get("model", "llama3"))
        model.setToolTip(AGENT_TOOLTIPS.get(ak, ""))
        f.addRow("Model:", model)
        hint = QLabel(AGENT_TOOLTIPS.get(ak, ""))
        hint.setStyleSheet("color: #888; font-size: 11px; font-style: italic;")
        hint.setWordWrap(True)
        f.addRow("", hint)
        return w, {"url": url, "key": key, "model": model}



    def _build_profile_tab(self):
        """Build the Profile tab — personal context for AI."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # Header
        title = QLabel("About You")
        title.setStyleSheet(f"color: {COLORS['text']}; font-size: 15px; font-weight: 600;")
        layout.addWidget(title)
        
        desc = QLabel(
            "Tell the AI who you are and what you work on.\n"
            "It will tailor every response to your workflow."
        )
        desc.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 12px; line-height: 1.5;")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        # Text area
        self._profile_input = QTextEdit()
        self._profile_input.setPlaceholderText(
            "Example:\n"
            "I'm a Character Rigger working in Maya on game characters for Unity. "
            "I focus on deformation quality and performance optimization. "
            "I'm comfortable with Python but prefer simple, readable code. "
            "My pipeline uses Arnold for rendering and I work in a small team."
        )
        self._profile_input.setMinimumHeight(120)
        self._profile_input.setMaximumHeight(160)
        self._profile_input.setStyleSheet(f"""
            QTextEdit {{
                background: {COLORS['bg_input']};
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
                color: {COLORS['text']};
                font-size: 13px;
                padding: 12px;
                line-height: 1.6;
            }}
            QTextEdit:focus {{
                border-color: {COLORS['accent_blue']};
            }}
        """)
        
        # Load saved profile
        saved_profile = self._raw_settings.get("user_profile", "")
        self._profile_input.setPlainText(saved_profile)
        
        layout.addWidget(self._profile_input)
        
        # Suggestions chips
        suggestions_label = QLabel("Quick add:")
        suggestions_label.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 11px;")
        layout.addWidget(suggestions_label)
        
        chips_layout = QHBoxLayout()
        chips_layout.setSpacing(8)
        
        suggestions = [
            "Rigger", "Animator", "Lighter", "Modeler",
            "TD", "Environment Artist", "VFX Artist"
        ]
        
        for suggestion in suggestions:
            chip = QPushButton(suggestion)
            chip.setFixedHeight(26)
            chip.setStyleSheet(f"""
                QPushButton {{
                    background: {COLORS['bg_input']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 13px;
                    color: {COLORS['text_muted']};
                    font-size: 11px;
                    padding: 0 10px;
                }}
                QPushButton:hover {{
                    border-color: {COLORS['accent_blue']};
                    color: {COLORS['accent_blue']};
                }}
            """)
            chip.clicked.connect(
                lambda checked, s=suggestion: self._append_to_profile(s)
            )
            chips_layout.addWidget(chip)
        
        chips_layout.addStretch()
        layout.addLayout(chips_layout)
        layout.addStretch()
        
        return widget

    def _append_to_profile(self, text):
        current = self._profile_input.toPlainText()
        if text.lower() not in current.lower():
            if current and not current.endswith("\n"):
                current += "\n"
            self._profile_input.setPlainText(current + f"I'm a {text}.")
            # Move cursor to end
            cursor = self._profile_input.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self._profile_input.setTextCursor(cursor)

    def _copy_all(self):
        idx = self._tabs.currentIndex()
        keys = list(_AGENTS)
        if idx >= len(keys):
            return
        src = self._agent_widgets[keys[idx]]
        for ak in _AGENTS:
            if ak == keys[idx]:
                continue
            d = self._agent_widgets[ak]
            d["url"].setText(src["url"].text())
            d["key"].setText(src["key"].text())
            d["model"].setText(src["model"].text())

    def _save(self):
        is_single = self._mode_single.isChecked()
        backend = "ollama" if self._bk_ollama.isChecked() else "openai"
        
        new_theme = "light" if self._theme_light.isChecked() else "dark"
        old_theme = self._theme
        
        self._result = {
            "mode": "single" if is_single else "multi",
            "accent_color": self._accent_color,
            "theme": new_theme,
        }
        if is_single:
            self._result["single_agent"] = {
                "backend": backend, "base_url": self._s_url.text().strip(),
                "api_key": self._s_key.text().strip(), "model": self._s_model.text().strip(),
                "system_prompt": app_settings.SINGLE_AGENT_PROMPT,
            }
            # Keep multi_agent prompts in sync
            multi = {}
            for ak in _AGENTS:
                multi[ak] = {
                    "backend": backend, "base_url": self._s_url.text().strip(),
                    "api_key": self._s_key.text().strip(), "model": self._s_model.text().strip(),
                    "system_prompt": self._agents[ak].get("system_prompt", ""),
                }
            self._result["multi_agent"] = multi
        else:
            # Preserve single_agent config
            self._result["single_agent"] = self._single_cfg
            multi = {}
            for ak in _AGENTS:
                w = self._agent_widgets[ak]
                multi[ak] = {
                    "backend": backend, "base_url": w["url"].text().strip(),
                    "api_key": w["key"].text().strip(), "model": w["model"].text().strip(),
                    "system_prompt": self._agents[ak].get("system_prompt", ""),
                }
            self._result["multi_agent"] = multi
        self._result["user_profile"] = self._profile_input.toPlainText().strip()
        
        if new_theme != old_theme:
            self.theme_changed.emit(new_theme)
            
        self.accept()

    def get_settings(self):
        return self._result
