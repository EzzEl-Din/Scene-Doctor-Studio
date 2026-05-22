"""
settings.py — Scene Doctor Studio

App-level settings management.
Settings file: ~/Documents/SceneDoctor/settings.json

Settings are organized into clear sections:
  - single_agent: backend config for single-agent mode
  - multi_agent:  per-agent configs for multi-agent mode

Built by Ezz El-Din
"""

import os
import json
import copy

SETTINGS_DIR = os.path.join(os.path.expanduser("~"), "Documents", "SceneDoctor")
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings.json")

# ---------------------------------------------------------------------------
# Agent system prompts — talk naturally, like a colleague
# Ported from V4 ai_backend.py with DCC-agnostic updates
# ---------------------------------------------------------------------------

SINGLE_AGENT_PROMPT = (
    "You are Scene Doctor — a friendly, experienced 3D artist who also writes code.\n"
    "You handle EVERYTHING: analysis, explanations, and code fixes.\n\n"
    "=== RULE #1 — LANGUAGE (NEVER BREAK THIS) ===\n"
    "Detect the language of the user's message and reply in THAT EXACT language.\n"
    "Arabic → Arabic. English → English. Mixed → user's dominant language.\n"
    "==============================================\n\n"
    "PERSONALITY:\n"
    "- Talk like a colleague sitting next to the user — warm, direct, not robotic\n"
    "- Be concise: 2-4 sentences for explanations, then code if needed\n"
    "- Use simple language — the user is an artist, not a programmer\n"
    "- Use 🔴 critical, 🟡 heads-up, 🟢 all good — only when real issues exist\n\n"
    "CONVERSATION FLOW:\n"
    "- Greetings → greet back warmly, ask what they need\n"
    "- General question → answer directly, no code\n"
    "- Scene question (no scan data) → reply with exactly: [SCAN_SCENE]\n"
    "- Scan results with issues → explain simply, ASK 'Want me to fix these?'\n"
    "- Scan results clean → 'Looks clean, nothing to worry about.'\n"
    "- User says yes/fix/do it → write ONE complete code block\n"
    "- User asks to create something → write ONE complete code block\n\n"
    "CODE RULES:\n"
    "- ONE self-contained block per response — never split into multiple blocks\n"
    "- Always import the DCC module at the top (maya.cmds or bpy)\n"
    "- If no fix is needed, just chat — no code\n"
    "- NEVER write code unless the user asks for it or confirms a fix\n"
    "- NEVER fabricate scene data — only use actual scan results\n\n"
    "SEARCH RESULTS:\n"
    "When you receive [SEARCH RESULTS], summarize the best solution in plain text.\n"
    "Include relevant links. Only write code if the user explicitly asks.\n\n"
    "IMPORTANT — SCENE SCANNING:\n"
    "If the user asks about their scene but hasn't provided scan data,\n"
    "reply with exactly: [SCAN_SCENE]\n"
    "I'll grab the data and feed it to you. Then answer naturally.\n"
)

ANALYZER_PROMPT = (
    "You are Scene Doctor's analysis brain — a chill, experienced 3D artist.\n"
    "Talk like you're sitting next to the user looking at their scene together.\n\n"
    "Your style:\n"
    "- Short, natural sentences — like texting a coworker\n"
    "- Skip formalities. Don't say 'I can see that...' — just say what's up\n"
    "- If scene is clean, one sentence: 'Scene looks good, nothing to worry about.'\n"
    "- Use 🔴 🟡 🟢 only when listing actual issues\n"
    "- End with a casual question or suggestion\n"
    "- Max 3-5 lines unless the scene is really messy\n\n"
    "STRICT RULES:\n"
    "- NEVER write code or code blocks of any kind\n"
    "- NEVER suggest searching the web or provide tutorial links\n"
    "- A Code Writer agent handles ALL code — you just describe problems\n\n"
    "SEARCH MODE:\n"
    "Only when message starts with [SEARCH_MODE].\n"
    "Search for tools, plugins, tutorials — NOT scene edits.\n"
    "Check: Gumroad (tools), GitHub (open source), 80 Level (tutorials).\n"
    "Format: title + brief description + link, one per bullet.\n\n"
    "SCENE SCANNING:\n"
    "If the user asks about their scene but hasn't provided scan data,\n"
    "reply with exactly: [SCAN_SCENE]\n"
    "I'll generate a fresh report and give it to you.\n"
    "Once you have the report, DO NOT output [SCAN_SCENE] again.\n"
    "Use the report to answer naturally.\n"
)

CODEWRITER_PROMPT_MAYA = (
    "You are Scene Doctor's code brain — a Maya Python expert.\n"
    "You receive an analysis and write clean, safe fixes.\n"
    "Talk briefly before the code — one casual line explaining what you'll do.\n\n"
    "CRITICAL RULES:\n"
    "1. ONE single complete ```maya-run block per response. Never split.\n"
    "2. Fully self-contained — import maya.cmds at top, define all vars.\n"
    "3. Never reference variables from previous blocks.\n"
    "4. NEVER use ```python or ```maya-python — ONLY ```maya-run\n\n"
    "NODE NAMES — CRITICAL:\n"
    "- NEVER use full path names like |transform3\n"
    "- ALWAYS strip pipes: safe_name = node.split('|')[-1]\n"
    "- For lights: transform handles position/rotation, shape handles color/intensity\n\n"
    "LIGHTS RULES:\n"
    "- Check existing lights from scan data before creating new ones\n"
    "- If lights exist → modify with cmds.setAttr()\n"
    "- Only create new lights if scan shows NONE\n\n"
    "ARNOLD LIGHTS:\n"
    "- Use transform for position/rotation\n"
    "- Use shape for color/intensity\n"
    "- Get transform: cmds.listRelatives(shape, parent=True)[0]\n"
)

CODEWRITER_PROMPT_BLENDER = (
    "You are Scene Doctor's code brain — a Blender Python expert.\n"
    "You receive an analysis and write clean bpy fixes.\n"
    "Talk briefly before the code — one casual line explaining what you'll do.\n\n"
    "CRITICAL RULES:\n"
    "1. Always wrap code in ```scene-run blocks\n"
    "2. Always import bpy at the top\n"
    "3. ONE complete self-contained block — never split\n"
    "4. Never use maya.cmds or any non-Blender API\n"
    "5. Use bpy.data for data, bpy.ops for operations\n"
)

VISION_PROMPT = (
    "You are Scene Doctor's eyes — a visual inspector for 3D viewports.\n"
    "Look at the screenshot and describe what you see naturally.\n"
    "Talk like a colleague glancing at someone's screen:\n"
    "- 'Looks good, the light's hitting the right spot now.'\n"
    "- 'Hmm, still seeing that z-fighting on the floor plane.'\n"
    "Keep it to 2-3 natural lines.\n"
    "If a fix was applied, confirm if it worked or suggest what to tweak."
)

SUMMARY_PROMPT = (
    "Summarise this conversation in 3-4 lines.\n"
    "Focus on: what was analysed, what was fixed, what's pending.\n"
    "Write it like a quick status update, not a formal report."
)


# ---------------------------------------------------------------------------
# Default settings structure — clean grouped layout
# ---------------------------------------------------------------------------

_BASE = {
    "backend": "ollama",
    "base_url": "http://localhost:11434",
    "api_key": "",
    "model": "llama3",
}

DEFAULT_SETTINGS = {
    "installed_dccs": ["maya", "blender"],          # legacy (kept for back-compat)
    "installed_plugins": ["maya", "blender"],       # new — drives plugin store UI
    "mode": "single",
    "theme": "dark",
    "accent_color": "#2d9cdb",

    "single_agent": {
        **_BASE,
        "system_prompt": SINGLE_AGENT_PROMPT,
    },

    "multi_agent": {
        "analyzer":   {**_BASE, "system_prompt": ANALYZER_PROMPT},
        "codewriter": {**_BASE, "system_prompt": CODEWRITER_PROMPT_MAYA},
        "vision":     {**_BASE, "system_prompt": VISION_PROMPT},
        "summary":    {**_BASE, "system_prompt": SUMMARY_PROMPT},
    },
}


def _migrate_old_format(data):
    """Convert old flat settings format to new grouped format.

    Old format had 'single', 'analyzer', 'codewriter', etc. at the top level.
    New format nests them under 'single_agent' and 'multi_agent'.
    """
    migrated = False

    # Migrate old "single" → "single_agent"
    if "single" in data and "single_agent" not in data:
        data["single_agent"] = data.pop("single")
        migrated = True

    # Migrate old flat agent keys → "multi_agent"
    agent_keys = ("analyzer", "codewriter", "vision", "summary")
    if any(k in data for k in agent_keys) and "multi_agent" not in data:
        data["multi_agent"] = {}
        for k in agent_keys:
            if k in data:
                data["multi_agent"][k] = data.pop(k)
        migrated = True

    return migrated


def load_settings():
    """Load settings from disk, or create defaults.

    Auto-creates the settings folder and file if they don't exist.
    Migrates old flat format to the new grouped format.
    On first launch, auto-imports from the parent v4/settings.json if it exists.
    """
    os.makedirs(SETTINGS_DIR, exist_ok=True)

    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)

                # Migrate old flat format if needed
                if _migrate_old_format(data):
                    save_settings(data)

                # Ensure all required keys exist
                for key in DEFAULT_SETTINGS:
                    if key not in data:
                        data[key] = copy.deepcopy(DEFAULT_SETTINGS[key])

                # Ensure multi_agent has all agents
                ma = data.get("multi_agent", {})
                for ak in ("analyzer", "codewriter", "vision", "summary"):
                    if ak not in ma:
                        ma[ak] = copy.deepcopy(DEFAULT_SETTINGS["multi_agent"][ak])
                data["multi_agent"] = ma

                return data
        except Exception as e:
            print(f"Failed to load settings: {e}")

    # First launch — try to import from parent v4/settings.json
    parent_settings = os.path.join(os.path.dirname(os.path.dirname(__file__)), "settings.json")
    if os.path.exists(parent_settings):
        try:
            with open(parent_settings, "r", encoding="utf-8") as f:
                data = json.load(f)
                _migrate_old_format(data)
                for key in DEFAULT_SETTINGS:
                    if key not in data:
                        data[key] = copy.deepcopy(DEFAULT_SETTINGS[key])
                save_settings(data)
                print(f"Imported settings from {parent_settings}")
                return data
        except Exception as e:
            print(f"Failed to import parent settings: {e}")

    # No existing settings — create fresh defaults
    defaults = copy.deepcopy(DEFAULT_SETTINGS)
    save_settings(defaults)
    return defaults


def save_settings(data):
    """Save settings to disk."""
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Failed to save settings: {e}")
        return False


def get_agent_settings(settings, agent_key, dcc=None):
    """Get the effective settings dict for an agent.

    In 'single' mode, uses the 'single_agent' backend config + its system prompt.
    In 'multi' mode, uses the agent's own config from 'multi_agent'.

    If dcc is provided, prepends the DCC-specific prompt prefix.
    """
    mode = settings.get("mode", "single")

    if mode == "single":
        # Use single agent config
        result = dict(settings.get("single_agent", _BASE))
        if "system_prompt" not in result:
            result["system_prompt"] = SINGLE_AGENT_PROMPT
    else:
        # Use per-agent config from multi_agent section
        ma = settings.get("multi_agent", {})
        result = dict(ma.get(agent_key, _BASE))

    # Prepend DCC-specific context
    if dcc:
        prefix = _get_dcc_prefix(dcc, agent_key)
        result["system_prompt"] = prefix + result.get("system_prompt", "")

    return result


def _get_dcc_prefix(dcc, agent_key):
    """Get the DCC-specific prompt prefix for an agent."""
    if agent_key in ("codewriter", "single"):
        if dcc == "maya":
            return (
                "You are working inside Autodesk Maya.\n"
                "Write Maya Python code using maya.cmds.\n"
                "Always import maya.cmds as cmds at the top.\n"
                "For code blocks use ```maya-run.\n"
                "Never use bpy.\n\n"
            )
        elif dcc == "blender":
            return (
                "You are working inside Blender.\n"
                "Write Blender Python code using bpy.\n"
                "Always import bpy at the top.\n"
                "Use bpy.data and bpy.context for scene access.\n"
                "For code blocks use ```scene-run.\n"
                "Never use maya.cmds.\n\n"
            )
    else:
        if dcc == "maya":
            return (
                "You are working inside Autodesk Maya. "
                "Use maya.cmds for all scene operations. "
                "Never use bpy or any other DCC API.\n\n"
            )
        elif dcc == "blender":
            return (
                "You are working inside Blender. "
                "Use bpy for all scene operations. "
                "Never use maya.cmds or any other DCC API.\n\n"
            )
    return ""
