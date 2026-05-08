"""
ai_backend.py — Maya Scene Doctor AI  (V3 — Multi-Agent)

Handles AI communication for 4 specialized agents:
  - Analyzer     : scene analysis and issue identification
  - Code Writer  : Maya Python fix generation
  - Vision       : viewport screenshot evaluation
  - Summary      : conversation summarisation

Supports:
  - Local  : Ollama  (http://localhost:11434)
  - External: Any OpenAI-compatible API (user provides base_url + api_key + model)

Built by Ezz El-Din | LinkedIn: https://www.linkedin.com/in/ezzel-din-tarek-mostafa

Streaming is done in a QThread so the UI never freezes.
"""

import json
import urllib.request
import urllib.error

try:
    from PySide2.QtCore import QThread, Signal
except ImportError:
    try:
        from PySide6.QtCore import QThread, Signal
    except ImportError:
        # Fallback for headless or DCCs without Qt (like Blender)
        import threading
        class Signal:
            def __init__(self, *types):
                self._callbacks = []
            def connect(self, callback):
                self._callbacks.append(callback)
            def emit(self, *args):
                for cb in self._callbacks:
                    try:
                        cb(*args)
                    except Exception as e:
                        print("Signal emit error:", e)
        
        class QThread(threading.Thread):
            def __init__(self, parent=None):
                super().__init__()
            def stop(self):
                self._running = False
            def wait(self, ms=None):
                self.join(timeout=ms / 1000.0 if ms else None)



# ---------------------------------------------------------------------------
# Agent system prompts — hardcoded defaults (editable in Settings > Advanced)
# ---------------------------------------------------------------------------

AGENT_PROMPTS = {
    "analyzer": (
        "=== RULE #1 — LANGUAGE (NEVER BREAK THIS) ===\n"
        "Detect the language of the user's message and reply in THAT EXACT language.\n"
        "Arabic message → Arabic reply. English message → English reply.\n"
        "Mixed → use the user's dominant language.\n"
        "DO NOT reply in English if the user wrote in Arabic.\n"
        "==============================================\n\n"
        "You are Scene Doctor — a friendly, experienced 3D artist and Maya/Blender expert.\n"
        "You help users understand and fix issues in their 3D scenes.\n"
        "You are NOT a general coding assistant or a chatbot. Stay focused on 3D/DCC work.\n\n"
        "TONE:\n"
        "- Talk like a helpful colleague — warm, direct, not robotic\n"
        "- Be concise — 2-4 sentences is usually enough\n"
        "- No stiff report format. Talk naturally\n"
        "- Use 🔴 🟡 🟢 only when real issues exist\n\n"
        "STRICT RULES:\n"
        "- NEVER write code — that's the Code Writer's job\n"
        "- NEVER suggest links unless user asks\n"
        "- Stay focused on the 3D scene context\n\n"
        "SEARCH MODE:\n"
        "Only activated when user message starts with [SEARCH_MODE].\n"
        "Search only for external tools, plugins, tutorials.\n"
        "- Check: Gumroad, GitHub, 80 Level\n"
        "- One result per bullet with title, description, link\n\n"
        "SCAN PERMISSION:\n"
        "If the user asks about their scene state and no fresh scan data exists, "
        "reply with exactly this and nothing else:\n"
        "[SCAN_SCENE]\n"
        "Once scan data is provided, use it to answer naturally. Never output [SCAN_SCENE] again."
    ),
    "codewriter": (
        "=== RULE #1 — LANGUAGE (NEVER BREAK THIS) ===\n"
        "Detect the language of the user's message and reply in THAT EXACT language.\n"
        "Arabic message → Arabic reply. English message → English reply.\n"
        "Code comments may stay in English. Your explanation text must match the user's language.\n"
        "==============================================\n\n"
        "You are a Maya Python expert and a friendly assistant.\n"
        "You write clean, working Python fixes and explain them briefly in plain language.\n\n"
        "TONE:\n"
        "- Be helpful and natural — explain what the code does in 1-2 plain sentences\n"
        "- Don't dump code with zero explanation\n"
        "- If there's something to watch out for, mention it casually\n\n"
        "CRITICAL RULES — CODE BLOCKS:\n\n"
        "1. ALWAYS write ONE single complete maya-run block per task.\n"
        "   Never split code into multiple blocks.\n"
        "   Never write a \"verify\" block after the main block.\n"
        "   All logic must be in ONE block.\n\n"
        "2. Every block must be fully self-contained:\n"
        "   - Import maya.cmds at the top\n"
        "   - Define all variables inside the block\n"
        "   - Never reference variables from previous blocks\n\n"
        "3. NODE NAMES — CRITICAL:\n"
        "   - NEVER use full path names like |transform3 or |directLightShape\n"
        "   - ALWAYS strip the pipe character from node names:\n"
        "     safe_name = node_name.split('|')[-1]\n\n"
        "4. NEVER use ```python or ```maya-python — ONLY ```maya-run\n\n"
        "LIGHTS RULES:\n"
        "- ALWAYS check existing lights from the scan data before doing anything\n"
        "- If lights exist in scan data → ALWAYS modify them with cmds.setAttr()\n"
        "- NEVER create new lights if lights already exist in the scene\n\n"
        "ARNOLD LIGHTS — CRITICAL:\n"
        "Arnold area lights have a transform node AND a shape node.\n"
        "ALWAYS use the transform node for position/rotation.\n"
        "ALWAYS use the shape node for color/intensity.\n\n"
        "Correct way to get both:\n"
        "```maya-run\n"
        "import maya.cmds as cmds\n"
        "shapes = cmds.ls(type='aiAreaLight')\n"
        "if shapes:\n"
        "    transform = cmds.listRelatives(shapes[0], parent=True, fullPath=True)[0]\n"
        "    cmds.setAttr(shapes[0] + '.color', 0, 0, 1, type='double3')\n"
        "    cmds.setAttr(transform + '.translateX', -5)\n"
        "```\n\n"
        "NEVER do this (causes NoneType error):\n"
        "```\n"
        "node = cmds.listConnections(light + '.message', d=False)[0]\n"
        "```"
    ),
    "vision": (
        "You are a sharp-eyed 3D artist reviewing a viewport screenshot.\n\n"
        "LANGUAGE RULE — CRITICAL:\n"
        "Always reply in the SAME language the user writes in.\n\n"
        "TONE:\n"
        "- Talk naturally, like you're looking over their shoulder\n"
        "- 2-3 sentences is usually enough\n"
        "- If a fix was applied, confirm if it looks right or suggest a tweak\n"
        "- No robotic report format"
    ),
    "summary": (
        "You are summarising a conversation between a 3D artist and an AI assistant.\n\n"
        "LANGUAGE RULE — CRITICAL:\n"
        "Write the summary in the same language that was dominant in the conversation.\n\n"
        "Write 3-4 natural sentences covering:\n"
        "- What was looked at\n"
        "- What was fixed or changed\n"
        "- What still needs attention\n"
        "Keep it concise and friendly — not a formal report."
    ),
}


# ---------------------------------------------------------------------------
# Tooltip hints — shown on the model field in the Settings dialog
# ---------------------------------------------------------------------------

AGENT_TOOLTIPS = {
    "analyzer":   "Understands your scene. Use a smart model \u2014 gpt-4o, claude-3-5-sonnet",
    "codewriter": "Writes Maya Python. Use a code-focused model \u2014 gpt-4o, deepseek-coder",
    "vision":     "Reads images. Must support vision \u2014 gpt-4o, gemini-2.0-flash",
    "summary":    "Summarises chat. Any fast model works \u2014 llama3, mistral-small",
}

# Human-readable labels for the UI
AGENT_LABELS = {
    "analyzer":   "🔍 Analyzer",
    "codewriter": "🔧 Code Writer",
    "vision":     "👁 Vision",
    "summary":    "💬 Summary",
}


# ---------------------------------------------------------------------------
# Default settings — per-agent backend configuration
# ---------------------------------------------------------------------------

_BASE_AGENT_SETTINGS = {
    "backend":  "ollama",
    "base_url": "http://localhost:11434",
    "api_key":  "",
    "model":    "llama3",
}


def _build_agent_defaults(agent_key):
    """Build default settings for one agent, including its system prompt."""
    settings = dict(_BASE_AGENT_SETTINGS)
    settings["system_prompt"] = AGENT_PROMPTS.get(agent_key, "")
    return settings


DEFAULT_SETTINGS = {
    "mode": "single",
    "single": dict(_BASE_AGENT_SETTINGS),
    "analyzer":   _build_agent_defaults("analyzer"),
    "codewriter": _build_agent_defaults("codewriter"),
    "vision":     _build_agent_defaults("vision"),
    "summary":    _build_agent_defaults("summary"),
}


# ---------------------------------------------------------------------------
# Settings migration  (V2.5 flat → V3 per-agent)
# ---------------------------------------------------------------------------

def migrate_settings(data):
    """
    Migrate V2.5 flat settings to V3 per-agent format.

    V2.5 format:
        {"backend": "...", "base_url": "...", "api_key": "...",
         "model": "...", "system_prompt": "..."}

    V3 format:
        {"mode": "single"|"multi",
         "single": {"backend": ..., "base_url": ..., "api_key": ..., "model": ...},
         "analyzer": {...}, "codewriter": {...},
         "vision": {...}, "summary": {...}}

    Returns the (possibly migrated) settings dict.
    """
    # Already V3 format — just ensure all agent keys exist
    if "analyzer" in data and isinstance(data.get("analyzer"), dict):
        for agent_key in ("analyzer", "codewriter", "vision", "summary"):
            if agent_key not in data:
                data[agent_key] = _build_agent_defaults(agent_key)
            else:
                # Ensure system_prompt key exists (fill from defaults if missing)
                if "system_prompt" not in data[agent_key]:
                    data[agent_key]["system_prompt"] = AGENT_PROMPTS.get(agent_key, "")
        # Default mode to "multi" for existing V3 configs, "single" for new
        if "mode" not in data:
            data["mode"] = "multi"
        if "single" not in data:
            # Seed single config from analyzer
            a = data.get("analyzer", {})
            data["single"] = {
                "backend":  a.get("backend", "ollama"),
                "base_url": a.get("base_url", ""),
                "api_key":  a.get("api_key", ""),
                "model":    a.get("model", "llama3"),
            }
        return data

    # V2.5 flat format → migrate to single mode
    base = {
        "backend":  data.get("backend",  "ollama"),
        "base_url": data.get("base_url", "http://localhost:11434"),
        "api_key":  data.get("api_key",  ""),
        "model":    data.get("model",    "llama3"),
    }

    migrated = {"mode": "single", "single": dict(base)}
    for agent_key in ("analyzer", "codewriter", "vision", "summary"):
        agent = dict(base)
        agent["system_prompt"] = AGENT_PROMPTS[agent_key]
        migrated[agent_key] = agent

    # Preserve the old system prompt so the user can reference it
    old_prompt = data.get("system_prompt", "")
    if old_prompt:
        migrated["legacy_system_prompt"] = old_prompt

    return migrated


# ---------------------------------------------------------------------------
# Language detection — Unicode-based, no external libraries needed
# ---------------------------------------------------------------------------

def detect_language(text: str) -> str:
    """
    Detect the dominant language of a text string using Unicode ranges.
    Returns a human-readable language name used to inject a language directive.
    """
    if not text or not text.strip():
        return "English"

    # Count characters in each script
    counts = {"arabic": 0, "japanese": 0, "cjk": 0, "korean": 0, "latin": 0}
    total = 0

    for ch in text:
        cp = ord(ch)
        if 0x0600 <= cp <= 0x06FF or 0x0750 <= cp <= 0x077F:  # Arabic / Arabic Supplement
            counts["arabic"] += 1
        elif 0x3040 <= cp <= 0x309F or 0x30A0 <= cp <= 0x30FF:  # Hiragana / Katakana
            counts["japanese"] += 1
        elif 0xAC00 <= cp <= 0xD7A3 or 0x1100 <= cp <= 0x11FF:  # Korean Hangul
            counts["korean"] += 1
        elif 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF:  # CJK Unified
            counts["cjk"] += 1
        elif ch.isalpha():
            counts["latin"] += 1
        if ch.strip():
            total += 1

    if total == 0:
        return "English"

    # Determine dominant script (threshold: >15% of total chars)
    threshold = total * 0.15
    if counts["arabic"] > threshold:
        return "Arabic"
    if counts["japanese"] > threshold:
        return "Japanese"
    if counts["korean"] > threshold:
        return "Korean"
    if counts["cjk"] > threshold:
        return "Chinese"
    return "English"  # default for Latin scripts


# Language → directive injected into each user message
_LANG_DIRECTIVES = {
    "Arabic":   "[RESPOND IN ARABIC — اكتب ردك بالعربية فقط]",
    "Japanese": "[RESPOND IN JAPANESE — 日本語で回答してください]",
    "Korean":   "[RESPOND IN KOREAN — 한국어로 답하세요]",
    "Chinese":  "[RESPOND IN CHINESE — 请用中文回答]",
    "English":  "",  # no directive needed — models default to English
}


# ---------------------------------------------------------------------------
# Streaming worker — lives in a background QThread
# ---------------------------------------------------------------------------

class StreamWorker(QThread):
    """
    Sends a message to the AI and emits tokens one by one.

    Signals:
        token(str)   — one streamed chunk of text
        done()       — streaming finished successfully
        error(str)   — something went wrong
    """

    token = Signal(str)
    done  = Signal()
    error = Signal(str)

    def __init__(self, messages, settings, parent=None, search_mode=False):
        """
        Args:
            messages (list[dict]): Full conversation history
                                   [{"role": "user"|"assistant", "content": "..."}]
            settings (dict):       **Per-agent** settings dict
                                   (must include backend, base_url, api_key, model,
                                    and optionally system_prompt)
        """
        super().__init__(parent)
        self.messages = messages
        self.settings = settings
        self.search_mode = search_mode
        self._running = True

    def stop(self):
        self._running = False

    # ------------------------------------------------------------------
    def run(self):
        backend = self.settings.get("backend", "ollama")
        try:
            if backend == "ollama":
                self._stream_ollama()
            else:
                self._stream_openai()
        except urllib.error.HTTPError as e:
            code = e.code
            # Try to read the error body for details
            detail = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
                err_json = json.loads(body)
                detail = err_json.get("error", {}).get("message", "")
            except Exception:
                detail = body[:300] if body else ""

            if detail:
                msg = "API Error {}: {}".format(code, detail)
            elif code == 401:
                msg = ("Authentication failed (401). "
                       "Please check your API key in Settings.")
            elif code == 403:
                msg = ("Forbidden (403). Possible causes:\n"
                       "• API key invalid or expired\n"
                       "• Model may be blocked in your account\n"
                       "• Check model permissions at your provider's console")
            elif code == 404:
                msg = ("Not found (404). The API URL might be wrong. "
                       "Check Settings > Base URL.")
            elif code == 429:
                msg = ("Rate limited (429). Too many requests — "
                       "wait a moment and try again.")
            else:
                msg = "HTTP Error {}: {}".format(code, e.reason)
            self.error.emit(msg)
        except urllib.error.URLError as e:
            self.error.emit(
                "Cannot connect to {}. Is the server running?\n{}".format(
                    self.settings.get("base_url", "?"), str(e.reason)
                )
            )
        except Exception as e:
            self.error.emit("Error: {}".format(str(e)))

    # ------------------------------------------------------------------
    # Ollama  — POST /api/chat  (NDJSON stream)
    # ------------------------------------------------------------------
    def _stream_ollama(self):
        if self.search_mode:
            self.error.emit("⚠ Search mode requires an external API — not available with Ollama")
            self.done.emit()
            return

        url   = self.settings.get("base_url", "http://localhost:11434").rstrip("/")
        url  += "/api/chat"
        model = self.settings.get("model", "llama3")

        # Prepend system message if set
        messages = self._with_system()

        payload = json.dumps({
            "model":    model,
            "messages": messages,
            "stream":   True,
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "MayaSceneDoctor/3.0",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=120) as response:
            for raw_line in response:
                if not self._running:
                    break
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    text  = chunk.get("message", {}).get("content", "")
                    if text:
                        self.token.emit(text)
                    if chunk.get("done", False):
                        break
                except json.JSONDecodeError:
                    continue

        self.done.emit()

    # ------------------------------------------------------------------
    # OpenAI-compatible  — POST /chat/completions  (SSE stream)
    # ------------------------------------------------------------------
    def _stream_openai(self):
        base_url = self.settings.get("base_url", "").rstrip("/")
        api_key  = self.settings.get("api_key",  "").strip()
        model    = self.settings.get("model",    "gpt-4o")

        if not api_key and "localhost" not in base_url and "127.0.0.1" not in base_url:
            self.error.emit("Wait! Your API key is empty! Go to Settings and enter your key.")
            self.done.emit()
            return

        # Build correct endpoint regardless of what the user typed
        if base_url.endswith("/chat/completions"):
            pass  # already correct
        elif base_url.endswith("/v1"):
            base_url = base_url + "/chat/completions"
        else:
            base_url = base_url.rstrip("/") + "/v1/chat/completions"

        messages = self._with_system()

        payload_dict = {
            "model":    model,
            "messages": messages,
            "stream":   True,
        }
        
        if self.search_mode:
            payload_dict["tools"] = [{
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web for Maya tools, tutorials, and resources",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query"
                            }
                        },
                        "required": ["query"]
                    }
                }
            }]

        payload = json.dumps(payload_dict).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "MayaSceneDoctor/3.0",
        }
        if api_key:
            headers["Authorization"] = "Bearer {}".format(api_key)

        req = urllib.request.Request(
            base_url,
            data=payload,
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=120) as response:
            for raw_line in response:
                if not self._running:
                    break
                line = raw_line.decode("utf-8").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk   = json.loads(data)
                    choices = chunk.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        text  = delta.get("content", "")
                        if text:
                            self.token.emit(text)
                except json.JSONDecodeError:
                    continue

        self.done.emit()

    # ------------------------------------------------------------------
    def _with_system(self):
        """Prepend system prompt, inject language directive, and format images."""
        backend = self.settings.get("backend", "ollama")
        processed_msgs = []

        system = self.settings.get("system_prompt", "").strip()
        if system:
            processed_msgs.append({"role": "system", "content": system})

        # Detect language from the last user message
        last_user_text = ""
        for msg in reversed(self.messages):
            if msg.get("role") == "user":
                last_user_text = msg.get("content", "")
                break
        lang = detect_language(last_user_text)
        directive = _LANG_DIRECTIVES.get(lang, "")

        for i, msg in enumerate(self.messages):
            new_msg = {"role": msg.get("role", "user")}
            text = msg.get("content", "")
            img_b64 = msg.get("image_b64")

            # Inject language directive into the last user message only
            if directive and msg.get("role") == "user" and msg is self.messages[-1]:
                text = f"{directive}\n{text}"

            if img_b64:
                if backend == "ollama":
                    new_msg["content"] = text
                    new_msg["images"] = [img_b64]
                else:
                    new_msg["content"] = [
                        {"type": "text", "text": text},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + img_b64}}
                    ]
            else:
                new_msg["content"] = text

            processed_msgs.append(new_msg)

        return processed_msgs


# ---------------------------------------------------------------------------
# Summary worker — non-streaming, returns a single response
# ---------------------------------------------------------------------------

class SummaryWorker(QThread):
    """
    Non-streaming worker that sends messages to the AI and returns
    a single complete response.  Used for conversation summarisation.

    Signals:
        result(str)  — the full summary text
        error(str)   — something went wrong
    """

    result = Signal(str)
    error  = Signal(str)

    def __init__(self, messages, settings, parent=None):
        """
        Args:
            messages (list[dict]): Messages to summarise
            settings (dict):       Summary agent's settings dict
        """
        super().__init__(parent)
        self.messages = messages
        self.settings = settings

    # ------------------------------------------------------------------
    def run(self):
        backend = self.settings.get("backend", "ollama")
        try:
            if backend == "ollama":
                self._call_ollama()
            else:
                self._call_openai()
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
                detail = body[:300]
            except Exception:
                pass
            self.error.emit("Summary API Error {}: {}".format(e.code, detail))
        except urllib.error.URLError as e:
            self.error.emit(
                "Summary: Cannot connect to {}. {}".format(
                    self.settings.get("base_url", "?"), str(e.reason)
                )
            )
        except Exception as e:
            self.error.emit("Summary error: {}".format(str(e)))

    # ------------------------------------------------------------------
    def _build_messages(self):
        """Prepend the system prompt to the message list."""
        processed = []
        system = self.settings.get("system_prompt", "").strip()
        if system:
            processed.append({"role": "system", "content": system})

        for msg in self.messages:
            processed.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            })
        return processed

    # ------------------------------------------------------------------
    # Ollama  — POST /api/chat  (non-streaming)
    # ------------------------------------------------------------------
    def _call_ollama(self):
        url   = self.settings.get("base_url", "http://localhost:11434").rstrip("/")
        url  += "/api/chat"
        model = self.settings.get("model", "llama3")

        payload = json.dumps({
            "model":    model,
            "messages": self._build_messages(),
            "stream":   False,
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "MayaSceneDoctor/3.0",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=120) as response:
            body = response.read().decode("utf-8")
            data = json.loads(body)
            text = data.get("message", {}).get("content", "")
            self.result.emit(text.strip())

    # ------------------------------------------------------------------
    # OpenAI-compatible  — POST /chat/completions  (non-streaming)
    # ------------------------------------------------------------------
    def _call_openai(self):
        base_url = self.settings.get("base_url", "").rstrip("/")
        api_key  = self.settings.get("api_key",  "").strip()
        model    = self.settings.get("model",    "gpt-4o")

        if not api_key and "localhost" not in base_url and "127.0.0.1" not in base_url:
            self.error.emit("Summary agent: API key is empty. Check Settings.")
            return

        # Build correct endpoint
        if base_url.endswith("/chat/completions"):
            pass
        elif base_url.endswith("/v1"):
            base_url = base_url + "/chat/completions"
        else:
            base_url = base_url.rstrip("/") + "/v1/chat/completions"

        payload = json.dumps({
            "model":    model,
            "messages": self._build_messages(),
            "stream":   False,
        }).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "MayaSceneDoctor/3.0",
        }
        if api_key:
            headers["Authorization"] = "Bearer {}".format(api_key)

        req = urllib.request.Request(
            base_url,
            data=payload,
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=120) as response:
            body = response.read().decode("utf-8")
            data = json.loads(body)
            choices = data.get("choices", [])
            if choices:
                text = choices[0].get("message", {}).get("content", "")
                self.result.emit(text.strip())
            else:
                self.result.emit("")
