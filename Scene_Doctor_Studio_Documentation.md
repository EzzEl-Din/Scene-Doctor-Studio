# Scene Doctor Studio — Documentation

> **Built by Ezz El-Din** | AI-powered diagnostic and fix assistant for 3D DCC applications (Maya & Blender)

---

## What Is Scene Doctor Studio?

Scene Doctor Studio is a **desktop AI assistant** that connects to your 3D software (Maya or Blender) and helps you:
- **Diagnose** scene problems (bad naming, missing lights, performance issues, etc.)
- **Generate Python fixes** and run them directly inside the DCC
- **Chat conversationally** about your scene using AI
- **Capture viewport screenshots** and analyze them visually

It runs as a standalone Python/PySide6 application alongside your DCC software.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│              Scene Doctor Studio UI              │
│                   (main.py)                      │
│                                                  │
│  ┌──────────┐  ┌────────────┐  ┌─────────────┐  │
│  │ Sidebar  │  │  Chat Panel│  │ AI Backend  │  │
│  │ Sessions │  │  Messages  │  │ (Streaming) │  │
│  └──────────┘  └────────────┘  └─────────────┘  │
└────────────────────┬────────────────────────────┘
                     │ TCP Socket
        ┌────────────┴──────────────┐
        │                           │
  ┌─────┴──────┐             ┌──────┴─────┐
  │   Maya     │             │  Blender   │
  │  Port 7001 │             │  Port 7002 │
  └────────────┘             └────────────┘
```

---

## File Structure

| File | Purpose |
|------|---------|
| `main.py` | Main application window, sidebar, chat UI, session management |
| `ai_backend.py` | AI streaming workers (Ollama & OpenAI-compatible APIs) |
| `dcc_connector.py` | TCP socket communication to Maya & Blender |
| `session_manager.py` | Save/load/delete chat sessions (JSON files) |
| `ui_widgets.py` | Custom UI components (chat bubbles, code blocks, session items) |
| `settings.py` | Persistent settings (theme, API keys, models) |
| `studio_settings_dialog.py` | Settings dialog UI |
| `blender_addon.py` | Blender addon (socket server + UI panel inside Blender) |

---

## Core Features

### 1. Collapsible Sidebar
- **Expanded (260px)**: Shows session list, search bar, labels, and bottom action buttons
- **Collapsed (56px)**: Shows only icons (☰ toggle, +, 🔍, session dots, ⚙, ×, ⚡)
- **Animated**: 220ms smooth width animation with easing
- **Search**: Real-time session filtering by scene name or DCC type
- **Search icon in collapsed mode**: Click 🔍 → expands sidebar and focuses search field

### 2. Session Management
Each **session** stores:
- Scene name (auto-detected from DCC or chosen via file picker)
- DCC type (Maya / Blender)
- Scene file path
- Full chat history
- Agent conversation histories

**Session operations:**
- **New Session** — connects to DCC, gets scene info, creates session
- **Right-click → Rename** — rename any session
- **Right-click → Delete** — permanently remove a session
- **Click to open** — loads the session's chat history

### 3. New Session Flow
```
Click + New Session
  → detect_connected_dccs()  [fast port check]
  → If multiple DCCs: user picks one
  → Show animated "🔌 Connecting..." in header
  → GetSceneInfoWorker thread: queries scene name/path from DCC
  → If named scene open → session named after scene file (e.g. "test")
  → If untitled scene → file picker opens to select .mb/.ma/.blend
  → If picker cancelled → session named "Maya Scene" / "Blender Scene"
```

> **Non-blocking**: `get_scene_info()` runs in a background `QThread` so the UI never freezes.

### 4. AI Chat — Two Modes

#### Single Agent Mode
One AI model handles everything — analysis, code, and conversation.

#### Multi-Agent Mode
Four specialized agents work in a pipeline:

| Agent | Role | Recommended Model |
|-------|------|-------------------|
| 🔍 **Analyzer** | Reads scene data, describes issues in plain text | GPT-4o, Claude 3.5 |
| 🔧 **Code Writer** | Generates self-contained Maya Python fix blocks | GPT-4o, DeepSeek Coder |
| 👁 **Vision** | Analyzes viewport screenshots | GPT-4o, Gemini 2.0 Flash |
| 💬 **Summary** | Summarizes long conversations to save context | Any fast model |

#### Intent Classification
The app automatically routes messages to the right agent:
- Screenshot/image attached → **Vision agent**
- Code execution requested → **Code Writer**
- "scan", "analyze", "what's wrong" → **Analyzer**
- General chat → current mode's default

### 5. Scene Scanning
When the Analyzer needs fresh scene data, it emits `[SCAN_SCENE]`. The app:
1. Intercepts this token
2. Runs `dcc_connector.run_scan(dcc)` → executes `maya_scanner.py` or `blender_scanner.py` inside the DCC
3. Injects the scan report into the AI conversation
4. AI uses the fresh data to answer

### 6. Code Execution
AI responses with ` ```maya-run ``` ` blocks get a **▶ Run** button. Clicking it:
1. Sends the code to the DCC via TCP socket
2. Captures stdout/stderr
3. Displays the result in the chat

**Maya multi-line code**: Written to a temp `.py` file → executed via stdout redirect → result read from temp `.txt` file.

### 7. Viewport Screenshot
The 📷 camera button:
1. Calls `dcc_connector.take_screenshot(dcc)`
2. DCC renders a 960×540 PNG to a temp file
3. Image is base64-encoded and sent back over the socket
4. Displayed in chat and attached to the next AI message for visual analysis

### 8. Image Paste / Drag-and-Drop
- **Ctrl+V** — paste an image from clipboard
- **Drag & Drop** — drag an image file onto the window
- Image is base64-encoded and sent to the Vision agent with your next message

### 9. Clear Chat Warning
Clicking **× Clear Chat** shows a confirmation dialog:
- **Cancel** (default) — nothing happens
- **Yes** (red) — clears all messages in the current session and saves

---

## DCC Connection

### Maya Setup
```python
# Run once in Maya's Script Editor (Python tab):
import maya.cmds as cmds
cmds.commandPort(name=":7001", sourceType="python")
```
> Add to `userSetup.py` to auto-enable on every Maya launch.

### Blender Setup
The `blender_addon.py` file is installed as a Blender addon. It:
- Starts a socket server on **port 7002**
- Provides a panel in the N-panel → "Scene Doctor" tab
- Auto-starts the server when the addon loads

---

## AI Backend Configuration

Supports two backend types:

### Ollama (Local)
- Base URL: `http://localhost:11434`
- No API key required
- Models: `llama3`, `mistral`, `deepseek-coder`, etc.
- ⚠ Search mode not available with Ollama

### OpenAI-Compatible (External)
- Works with OpenAI, Anthropic, Google Gemini, Groq, Together AI, etc.
- Enter: Base URL + API Key + Model name
- Supports streaming via SSE
- Search mode (web tool) available

---

## Settings

Accessible via **⚙ Settings** in the sidebar.

| Setting | Description |
|---------|-------------|
| Theme | Dark / Light |
| Accent Color | Custom accent color for highlights |
| Mode | Single Agent / Multi-Agent |
| Per-agent config | Backend, Base URL, API Key, Model, System Prompt |

Settings are saved to a JSON file and persist across restarts.

---

## Session Storage

Sessions are saved as JSON files in the session directory. Each session contains:
```json
{
  "session_id": "uuid",
  "dcc": "maya",
  "scene_name": "test",
  "scene_path": "D:/work/test.mb",
  "chat_history": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
```

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Enter` | Send message |
| `Shift+Enter` | New line in message |
| `Ctrl+V` | Paste image from clipboard |

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| UI Framework | PySide6 (Qt 6) |
| Language | Python 3.10+ |
| DCC Communication | TCP Sockets |
| AI Streaming | `urllib` (no external deps) |
| Animations | QPropertyAnimation |
| Threading | QThread + Signal/Slot |
