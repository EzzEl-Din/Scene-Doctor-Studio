# Changelog

## v1.2.0 — Trust + Plugin Store (2026-05-22)

Trust-building features and a redesigned plugin store.

### Added — Undo & Trace
- Undo-chunk wrapping for every code execution (Run button + auto-run):
  - Maya: `cmds.undoInfo(openChunk / closeChunk)` inside try/finally
  - Blender: `bpy.ops.ed.undo_push()` before, `bpy.ops.ed.undo()` on failure
- "Press Ctrl+Z to undo" hint after every successful run
- Tool-call trace log: one JSONL entry per execution stored in
  `~/Documents/SceneDoctor/sessions/{dcc}/{session_id}/trace.jsonl`
  (timestamp, label, code, success/error, undo flag)
- Trace viewer: 📋 button in the artifacts panel renders the JSONL
  as a markdown report saved as a session artifact

### Added — GitHub Plugin Store
- New `plugin_manager.py` — install / uninstall / update plugins from a
  GitHub registry (`plugins/registry.json` + per-plugin `plugin.json`)
- New `platform_detect.py` — scanner resolution falls through
  `PluginManager.load_scanner()` first, then bundled `scanners/` for
  Maya / Blender
- `PluginStoreWindow` redesigned: Install / Coming Soon / ✓ Installed +
  Remove / ↑ Update buttons with live download status
- Confirmation dialog before uninstall; sessions and chat history are
  always kept
- `DCCTabStrip` gains `remove_dcc()`; the strip refreshes immediately
  on install and uninstall
- `settings.installed_plugins` (legacy `installed_dccs` mirrored)

### Changed
- `dcc_connector.send_code(dcc, code, undo_label=None)` — read-only
  callers (scans, screenshots, scene info) keep `undo_label=None` so
  the undo history stays clean
- README updated with new Undo & Trace and Plugin Store sections,
  project structure, data-storage layout, and roadmap status

### Removed
- Hard-coded `AVAILABLE_PLUGINS` dict in `PluginStoreWindow` (replaced
  by the GitHub registry)

## v1.0.0-beta — Beta v1 (2025-05-13)

First public beta release of Scene Doctor Studio.

### Features
- AI-powered scene diagnostics for Maya and Blender
- Single Agent and Multi Agent modes
- Full scene scan with geometry + animation health check
- Selection scan with detailed mesh analysis
- Viewport screenshot capture (Maya playblast / Blender Workbench)
- Streaming AI responses with code execution
- Artifacts system (auto-detect, save, view, run, copy, download)
- Documentation mode (auto-generates tech reports)
- Web search (DuckDuckGo) for solutions and tutorials
- Adaptive Thinking mode (AI reasons step-by-step)
- Step-by-step and Plan mode toggles (persistent)
- Auto-run code mode
- Dark/Light themes with accent color customization
- Session management with DCC filtering
- Collapsible sidebar (animated 260px ↔ 56px)
- Token counter with color-coded warnings
- Keyboard shortcuts (Ctrl+K, Ctrl+B)
- Drag & drop images into chat
- Personal profile ("About You") for AI context
- Smart intent detection (questions vs commands)
- Connection-aware (blocks scene questions when DCC disconnected)

### Supported DCCs
- Autodesk Maya 2022+ (port 7001)
- Blender 3.2+ (port 7002)

### Supported AI Backends
- Ollama (local)
- Any OpenAI-compatible API (Groq, OpenAI, Google, DeepSeek, etc.)
