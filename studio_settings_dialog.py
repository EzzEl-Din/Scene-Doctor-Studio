"""
studio_settings_dialog.py — Full Settings Dialog (ported from V4 main.py)
Single/Multi agent mode, per-agent tabs, advanced system prompts, chat color.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QFormLayout, QComboBox, QDialogButtonBox, QTabWidget, QGroupBox,
    QRadioButton, QButtonGroup, QSizePolicy, QTextEdit, QWidget
)
from PySide6.QtCore import Qt, QTimer
from ui_widgets import COLORS, AGENT_LABELS, AGENT_TOOLTIPS
import settings as app_settings

_AGENTS = ("analyzer", "codewriter", "vision", "summary")

def _get_style():
    """Generate settings dialog stylesheet from current COLORS."""
    return f"""
QDialog {{ background-color: {COLORS['bg_dark']}; color: {COLORS['text']}; font-size: 13px; }}
QGroupBox {{ font-weight: bold; color: {COLORS['text_muted']}; border: 1px solid {COLORS['border']};
  border-radius: 6px; margin-top: 8px; padding: 12px 10px 8px 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {COLORS['text']}; }}
QRadioButton {{ color: {COLORS['text']}; spacing: 6px; }}
QLineEdit {{ background: {COLORS['bg_input']}; border: 1px solid {COLORS['border']};
  border-radius: 4px; padding: 5px 8px; color: {COLORS['text']}; }}
QLineEdit:focus {{ border-color: {COLORS['accent_blue']}; }}
QTabWidget::pane {{ border: 1px solid {COLORS['border']}; border-radius: 4px; background: {COLORS['bg_panel']}; }}
QTabBar::tab {{ background: {COLORS['bg_input']}; color: {COLORS['text_muted']}; padding: 6px 12px; margin-right: 2px;
  border-top-left-radius: 4px; border-top-right-radius: 4px; }}
QTabBar::tab:selected {{ background: {COLORS['bg_panel']}; color: {COLORS['text']}; }}
QTabBar::tab:hover {{ color: {COLORS['text']}; }}
QPushButton {{ background: {COLORS['btn_secondary']}; color: {COLORS['text']}; border: 1px solid {COLORS['border']};
  border-radius: 4px; padding: 6px 14px; }}
QPushButton:hover {{ background: {COLORS['btn_secondary_hover']}; }}
QTextEdit {{ background: {COLORS['bg_input']}; border: 1px solid {COLORS['border']};
  border-radius: 4px; color: {COLORS['text']}; }}
QLabel {{ color: {COLORS['text']}; }}
"""


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Agent Settings")
        self.setMinimumWidth(500)
        self.setMaximumHeight(550)
        self.setStyleSheet(_get_style())
        self._settings = {}
        for k in _AGENTS:
            self._settings[k] = dict(settings.get(k, {}))
        self._mode = settings.get("mode", "single")
        self._single_cfg = dict(settings.get("single", {}))
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
        init_bk = self._single_cfg.get("backend") or self._settings.get("analyzer", {}).get("backend", "ollama")
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
        s = self._single_cfg or self._settings.get("analyzer", {})
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
        layout.addWidget(self._single_w)

        # Multi agent tabs
        self._multi_w = QGroupBox("Multi Agent")
        ml = QVBoxLayout(self._multi_w)
        self._tabs = QTabWidget()
        self._tabs.setFixedHeight(200)
        self._agent_widgets = {}
        for ak in _AGENTS:
            tab, widgets = self._build_tab(ak)
            self._tabs.addTab(tab, AGENT_LABELS.get(ak, ak))
            self._agent_widgets[ak] = widgets
        adv, self._prompt_edits = self._build_advanced()
        self._tabs.addTab(adv, "\u2699 Advanced")
        ml.addWidget(self._tabs)
        copy_btn = QPushButton("\ud83d\udccb Copy to all agents")
        copy_btn.clicked.connect(self._copy_all)
        ml.addWidget(copy_btn)
        layout.addWidget(self._multi_w)

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
        self.layout().activate()
        QTimer.singleShot(50, lambda: self.adjustSize())

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
        s = self._settings[ak]
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

    def _build_advanced(self):
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(6)
        note = QLabel("Edit system prompts. Leave blank for defaults.")
        note.setStyleSheet("color: #aaa; font-size: 11px;")
        lo.addWidget(note)
        edits = {}
        for ak in _AGENTS:
            lbl = QLabel(AGENT_LABELS.get(ak, ak))
            lbl.setStyleSheet("font-weight: bold; margin-top: 4px;")
            lo.addWidget(lbl)
            ed = QTextEdit()
            cur = self._settings[ak].get("system_prompt", "")
            default = getattr(app_settings, {
                "analyzer": "ANALYZER_PROMPT", "codewriter": "CODEWRITER_PROMPT_MAYA",
                "vision": "VISION_PROMPT", "summary": "SUMMARY_PROMPT"
            }.get(ak, ""), "")
            ed.setPlainText(cur if cur else default)
            ed.setFixedHeight(70)
            ed.setStyleSheet("font-size: 11px;")
            lo.addWidget(ed)
            edits[ak] = ed
        reset = QPushButton("\u21bb Reset All Prompts")
        reset.clicked.connect(lambda: [e.setPlainText(getattr(app_settings, {
            "analyzer": "ANALYZER_PROMPT", "codewriter": "CODEWRITER_PROMPT_MAYA",
            "vision": "VISION_PROMPT", "summary": "SUMMARY_PROMPT"
        }.get(k, ""), "")) for k, e in edits.items()])
        lo.addWidget(reset)
        lo.addStretch()
        return w, edits

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
        self._settings["accent_color"] = self._accent_color
        self._settings["theme"] = "light" if self._theme_light.isChecked() else "dark"
        if is_single:
            self._settings["mode"] = "single"
            self._settings["single"] = {
                "backend": backend, "base_url": self._s_url.text().strip(),
                "api_key": self._s_key.text().strip(), "model": self._s_model.text().strip(),
                "system_prompt": app_settings.SINGLE_AGENT_PROMPT,
            }
            for ak in _AGENTS:
                self._settings[ak] = {
                    "backend": backend, "base_url": self._s_url.text().strip(),
                    "api_key": self._s_key.text().strip(), "model": self._s_model.text().strip(),
                    "system_prompt": self._prompt_edits[ak].toPlainText().strip(),
                }
        else:
            self._settings["mode"] = "multi"
            for ak in _AGENTS:
                w = self._agent_widgets[ak]
                self._settings[ak] = {
                    "backend": backend, "base_url": w["url"].text().strip(),
                    "api_key": w["key"].text().strip(), "model": w["model"].text().strip(),
                    "system_prompt": self._prompt_edits[ak].toPlainText().strip(),
                }
        self.accept()

    def get_settings(self):
        return self._settings
