# Changelog

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
