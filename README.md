# 🩺 Scene Doctor Studio

> AI-powered diagnostic and fix assistant for 3D DCC applications

A standalone desktop app that connects to your 3D software (Maya & Blender) 
and helps you diagnose scene problems, generate Python fixes, and chat about 
your scene — all powered by any AI model you choose.

![Scene Doctor Studio](assets/scene_doctor_studio_logo.svg)

---

## ✨ Features

→ Connects to Maya and Blender via TCP sockets  
→ AI scans your scene and explains what's wrong  
→ Generates and runs Python fixes directly inside the DCC  
→ Full chat history saved per scene  
→ Vision support — send viewport screenshots to the AI  
→ Multi-Agent system (Analyzer, Code Writer, Vision, Summary)  
→ Works with any AI — Ollama (local) or any OpenAI-compatible API  
→ Collapsible sidebar with session management  

---

## 🚀 Getting Started

### Requirements
- Python 3.10+
- PySide6: `pip install PySide6`
- Maya 2020+ or Blender 3.0+
- Ollama (free) OR any OpenAI-compatible API key

### Run the App
```bash
cd Scene-Doctor-Studio
pip install PySide6
python main.py
```

### Connect Maya
Run once in Maya's Script Editor (Python tab):
```python
import maya.cmds as cmds
cmds.commandPort(name=":7001", sourceType="python")
```
Add to userSetup.py to auto-enable on every Maya launch.

### Connect Blender
Install blender_addon.py via:
Edit → Preferences → Add-ons → Install → select blender_addon.py

---

## 🧠 Architecture

```
Scene Doctor Studio (Desktop App)
         ↓ TCP Socket
   ┌─────┴─────┐
   │           │
 Maya        Blender
(Port 7001)  (Port 7002)
```

---

## 🤖 AI Backend

Works with any OpenAI-compatible API:
- Local: Ollama (http://localhost:11434)
- Cloud: OpenRouter, Groq, OpenAI, Anthropic, Mistral...

For best results use GPT-4o or Claude 3.5 Sonnet.

---

## 📁 File Structure

| File | Purpose |
|------|---------|
| main.py | Main app window + UI |
| ai_backend.py | AI streaming (Ollama & OpenAI) |
| dcc_connector.py | TCP socket to Maya/Blender |
| session_manager.py | Save/load chat sessions |
| ui_widgets.py | Custom UI components |
| settings.py | App settings |
| blender_addon.py | Blender addon (socket server) |

---

## 📜 License

MIT License — free to use, modify, and share.

---

Built with ❤️ by Ezz El-Din | LinkedIn