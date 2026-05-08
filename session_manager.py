"""
session_manager.py — Scene Doctor Studio

Manages chat sessions on disk.
Save location: ~/Documents/SceneDoctor/sessions/
File naming: {dcc}_{scene_name}_{hash8}.json

Built by Ezz El-Din
"""

import os
import json
import hashlib
from datetime import datetime

SESSIONS_DIR = os.path.join(os.path.expanduser("~"), "Documents", "SceneDoctor", "sessions")


def _ensure_dir():
    os.makedirs(SESSIONS_DIR, exist_ok=True)


def get_session_id(dcc, scene_path):
    """Generate a short 8-char hash from DCC + scene path."""
    key = f"{dcc}:{scene_path}"
    return hashlib.md5(key.encode()).hexdigest()[:8]


def get_session_path(dcc, scene_name, session_id):
    """Build the full file path for a session."""
    _ensure_dir()
    # Sanitize scene_name for filesystem
    safe_name = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in scene_name)
    filename = f"{dcc}_{safe_name}_{session_id}.json"
    return os.path.join(SESSIONS_DIR, filename)


def create_session(dcc, scene_name, scene_path=""):
    """Create a new session dict (not saved until save_session is called)."""
    session_id = get_session_id(dcc, scene_path or scene_name)
    return {
        "session_id": session_id,
        "scene_name": scene_name,
        "scene_path": scene_path,
        "dcc": dcc,
        "created": datetime.now().isoformat(),
        "last_opened": datetime.now().isoformat(),
        "chat_history": [],
    }


def save_session(session_data):
    """Save a session to disk. Updates last_opened timestamp."""
    session_data["last_opened"] = datetime.now().isoformat()
    path = get_session_path(
        session_data["dcc"],
        session_data["scene_name"],
        session_data["session_id"],
    )
    with open(path, "w", encoding="utf-8") as f:
        json.dump(session_data, f, indent=2, ensure_ascii=False)
    return path


def load_all_sessions():
    """Return all sessions sorted by last_opened (newest first)."""
    _ensure_dir()
    sessions = []
    for fname in os.listdir(SESSIONS_DIR):
        if not fname.endswith(".json"):
            continue
        filepath = os.path.join(SESSIONS_DIR, fname)
        try:
            with open(filepath, encoding="utf-8") as fp:
                data = json.load(fp)
                # Ensure required keys exist
                if "session_id" in data and "dcc" in data:
                    sessions.append(data)
        except Exception:
            continue
    return sorted(sessions, key=lambda x: x.get("last_opened", ""), reverse=True)


def load_session(session_id):
    """Load a specific session by its ID."""
    _ensure_dir()
    for fname in os.listdir(SESSIONS_DIR):
        if session_id in fname and fname.endswith(".json"):
            filepath = os.path.join(SESSIONS_DIR, fname)
            try:
                with open(filepath, encoding="utf-8") as fp:
                    return json.load(fp)
            except Exception:
                return None
    return None


def delete_session(session_id):
    """Delete a session file from disk."""
    _ensure_dir()
    for fname in os.listdir(SESSIONS_DIR):
        if session_id in fname and fname.endswith(".json"):
            filepath = os.path.join(SESSIONS_DIR, fname)
            try:
                os.remove(filepath)
                return True
            except Exception:
                return False
    return False


def rename_session(session_id, new_name):
    """Rename a session's scene_name. Deletes old file and saves with new name."""
    _ensure_dir()
    for fname in os.listdir(SESSIONS_DIR):
        if session_id in fname and fname.endswith(".json"):
            filepath = os.path.join(SESSIONS_DIR, fname)
            try:
                with open(filepath, encoding="utf-8") as fp:
                    data = json.load(fp)
                data["scene_name"] = new_name
                os.remove(filepath)  # delete old-named file
                save_session(data)   # save with new name in filename
                return data
            except Exception:
                return None
    return None


def add_message(session_data, role, content, image_b64=None):
    """Append a message to the session's chat history."""
    msg = {"role": role, "content": content}
    if image_b64:
        msg["image_b64"] = image_b64
    session_data["chat_history"].append(msg)
    return session_data

