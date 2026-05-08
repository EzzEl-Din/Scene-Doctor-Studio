"""
session_manager.py — Scene Doctor Studio

Manages chat sessions on disk.
Save location: ~/Documents/SceneDoctor/sessions/<dcc>/
File naming: {scene_name}_{hash8}.json

Sessions are organized into DCC-specific subfolders:
  sessions/
  ├── maya/
  │   └── test_scene_766e394d.json
  └── blender/
      └── untitled_e405239a.json

Built by Ezz El-Din
"""

import os
import json
import hashlib
import shutil
from datetime import datetime

SESSIONS_DIR = os.path.join(os.path.expanduser("~"), "Documents", "SceneDoctor", "sessions")


def _ensure_dir(dcc=None):
    """Ensure the sessions directory (and optional DCC subfolder) exists."""
    target = os.path.join(SESSIONS_DIR, dcc) if dcc else SESSIONS_DIR
    os.makedirs(target, exist_ok=True)
    return target


def _migrate_flat_sessions():
    """One-time migration: move old flat session files into DCC subfolders."""
    if not os.path.isdir(SESSIONS_DIR):
        return
    for fname in os.listdir(SESSIONS_DIR):
        filepath = os.path.join(SESSIONS_DIR, fname)
        # Only migrate .json files sitting directly in sessions/
        if not fname.endswith(".json") or os.path.isdir(filepath):
            continue
        try:
            with open(filepath, encoding="utf-8") as fp:
                data = json.load(fp)
            dcc = data.get("dcc", "unknown").lower()
            dcc_dir = _ensure_dir(dcc)
            dest = os.path.join(dcc_dir, fname)
            if not os.path.exists(dest):
                shutil.move(filepath, dest)
            else:
                os.remove(filepath)  # duplicate, remove old flat copy
        except Exception:
            continue


def get_session_id(dcc, scene_path):
    """Generate a short 8-char hash from DCC + scene path."""
    key = f"{dcc}:{scene_path}"
    return hashlib.md5(key.encode()).hexdigest()[:8]


def get_session_path(dcc, scene_name, session_id):
    """Build the full file path for a session inside its DCC subfolder."""
    dcc_dir = _ensure_dir(dcc)
    # Sanitize scene_name for filesystem
    safe_name = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in scene_name)
    filename = f"{safe_name}_{session_id}.json"
    return os.path.join(dcc_dir, filename)


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


def _iter_all_session_files():
    """Iterate over all session JSON files across all DCC subfolders.
    Yields (filepath, filename) tuples."""
    _ensure_dir()
    _migrate_flat_sessions()
    for entry in os.listdir(SESSIONS_DIR):
        dcc_dir = os.path.join(SESSIONS_DIR, entry)
        if not os.path.isdir(dcc_dir):
            continue
        for fname in os.listdir(dcc_dir):
            if fname.endswith(".json"):
                yield os.path.join(dcc_dir, fname), fname


def load_all_sessions():
    """Return all sessions sorted by last_opened (newest first)."""
    sessions = []
    for filepath, _ in _iter_all_session_files():
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
    for filepath, fname in _iter_all_session_files():
        if session_id in fname:
            try:
                with open(filepath, encoding="utf-8") as fp:
                    return json.load(fp)
            except Exception:
                return None
    return None


def delete_session(session_id):
    """Delete a session file from disk."""
    for filepath, fname in _iter_all_session_files():
        if session_id in fname:
            try:
                os.remove(filepath)
                return True
            except Exception:
                return False
    return False


def rename_session(session_id, new_name):
    """Rename a session's scene_name. Deletes old file and saves with new name."""
    for filepath, fname in _iter_all_session_files():
        if session_id in fname:
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
