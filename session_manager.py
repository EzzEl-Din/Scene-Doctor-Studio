"""
session_manager.py — Scene Doctor Studio

Manages chat sessions on disk with artifact extraction.

New folder structure:
  Documents/SceneDoctor/sessions/
  ├── maya/
  │   └── {session_id}/
  │       ├── chat.json
  │       └── artifacts/
  │           └── {artifact_id}.py
  └── blender/
      └── {session_id}/
          ├── chat.json
          └── artifacts/
              └── {artifact_id}.md

Artifacts: Code blocks (```maya-run```, ```python```) or long step-by-step
responses (>20 lines) are extracted into separate files. In chat.json they
are replaced with: {"type": "artifact", "artifact_id": "abc123"}

Built by Ezz El-Din
"""

import os
import re
import json
import hashlib
import shutil
import uuid
from datetime import datetime

SESSIONS_DIR = os.path.join(os.path.expanduser("~"), "Documents", "SceneDoctor", "sessions")

# Patterns for code blocks that should become artifacts
_CODE_BLOCK_PATTERNS = [
    r'```(?:maya-run|scene-run)\n(.*?)```',
    r'```(?:python|maya-python)\n(.*?)```',
]


def _ensure_dir(dcc=None):
    """Ensure the sessions directory (and optional DCC subfolder) exists."""
    target = os.path.join(SESSIONS_DIR, dcc) if dcc else SESSIONS_DIR
    os.makedirs(target, exist_ok=True)
    return target


def _session_folder(dcc, session_id):
    """Return the path to a session's folder, creating it if needed."""
    dcc_dir = _ensure_dir(dcc)
    folder = os.path.join(dcc_dir, session_id)
    os.makedirs(folder, exist_ok=True)
    return folder


def _artifacts_folder(dcc, session_id):
    """Return the path to a session's artifacts subfolder, creating it if needed."""
    folder = _session_folder(dcc, session_id)
    art_dir = os.path.join(folder, "artifacts")
    os.makedirs(art_dir, exist_ok=True)
    return art_dir


def _generate_artifact_id():
    """Generate a short unique artifact ID."""
    return uuid.uuid4().hex[:12]


def _detect_artifact_extension(content):
    """Determine file extension based on content."""
    # If it looks like Python code
    if any(kw in content for kw in ("import ", "def ", "class ", "cmds.", "bpy.")):
        return ".py"
    # If it has markdown-like structure
    if content.startswith("#") or "\n## " in content or "\n- " in content:
        return ".md"
    return ".txt"


def _should_extract_artifact(content):
    """Check if content should be extracted as an artifact.
    Returns True for code blocks or long step-by-step responses (>20 lines).
    """
    # Check for code blocks
    for pattern in _CODE_BLOCK_PATTERNS:
        if re.search(pattern, content, re.DOTALL):
            return True
    # Check for long responses (>20 lines)
    if content.count('\n') > 20:
        return True
    return False


def _extract_artifacts(content, dcc, session_id):
    """Extract code blocks and long content into artifact files.
    Returns (modified_content, list_of_artifact_refs).
    
    For code blocks: extracts the code, saves to file, replaces in content.
    For long content without code blocks: saves entire content as artifact.
    """
    art_dir = _artifacts_folder(dcc, session_id)
    artifacts = []
    modified = content

    # Extract code blocks first
    has_code_blocks = False
    for pattern in _CODE_BLOCK_PATTERNS:
        for match in re.finditer(pattern, content, re.DOTALL):
            has_code_blocks = True
            code = match.group(1)
            art_id = _generate_artifact_id()
            ext = ".py"
            art_path = os.path.join(art_dir, f"{art_id}{ext}")
            with open(art_path, "w", encoding="utf-8") as f:
                f.write(code)
            artifacts.append(art_id)
            # Replace the code block with a reference marker
            modified = modified.replace(
                match.group(0),
                f'[artifact:{art_id}]'
            )

    # If no code blocks but content is long (>20 lines), save whole thing
    if not has_code_blocks and content.count('\n') > 20:
        art_id = _generate_artifact_id()
        ext = _detect_artifact_extension(content)
        art_path = os.path.join(art_dir, f"{art_id}{ext}")
        with open(art_path, "w", encoding="utf-8") as f:
            f.write(content)
        artifacts.append(art_id)
        modified = None  # entire content replaced

    return modified, artifacts


def _load_artifact(dcc, session_id, artifact_id):
    """Load artifact content from disk."""
    art_dir = os.path.join(SESSIONS_DIR, dcc, session_id, "artifacts")
    if not os.path.isdir(art_dir):
        return f"[artifact {artifact_id} not found]"
    # Find the file (could be .py, .md, .txt)
    for fname in os.listdir(art_dir):
        if fname.startswith(artifact_id):
            fpath = os.path.join(art_dir, fname)
            with open(fpath, encoding="utf-8") as f:
                return f.read()
    return f"[artifact {artifact_id} not found]"


def _reconstruct_content(message, dcc, session_id):
    """Reconstruct message content by loading artifacts."""
    if message.get("type") == "artifact":
        # Entire message is an artifact
        art_id = message.get("artifact_id", "")
        return _load_artifact(dcc, session_id, art_id)
    
    content = message.get("content", "")
    # Replace inline artifact references
    for match in re.finditer(r'\[artifact:([a-f0-9]+)\]', content):
        art_id = match.group(1)
        art_content = _load_artifact(dcc, session_id, art_id)
        # Wrap back in code block for display
        content = content.replace(match.group(0), f"```python\n{art_content}```")
    
    return content


# ---------------------------------------------------------------------------
# Migration from old flat JSON files
# ---------------------------------------------------------------------------

def _migrate_flat_sessions():
    """Migrate old flat JSON session files into the new folder structure.
    
    Old format: sessions/<dcc>/<scene_name>_<session_id>.json
    New format: sessions/<dcc>/<session_id>/chat.json
    """
    if not os.path.isdir(SESSIONS_DIR):
        return

    # First: migrate files sitting directly in sessions/ (very old format)
    for fname in os.listdir(SESSIONS_DIR):
        filepath = os.path.join(SESSIONS_DIR, fname)
        if not fname.endswith(".json") or os.path.isdir(filepath):
            continue
        try:
            with open(filepath, encoding="utf-8") as fp:
                data = json.load(fp)
            dcc = data.get("dcc", "unknown").lower()
            session_id = data.get("session_id", fname.replace(".json", ""))
            _migrate_single_session(filepath, data, dcc, session_id)
        except Exception:
            continue

    # Second: migrate files inside DCC subfolders (current format)
    for entry in os.listdir(SESSIONS_DIR):
        dcc_dir = os.path.join(SESSIONS_DIR, entry)
        if not os.path.isdir(dcc_dir):
            continue
        for fname in os.listdir(dcc_dir):
            filepath = os.path.join(dcc_dir, fname)
            # Only migrate .json files (not folders which are already new format)
            if not fname.endswith(".json") or os.path.isdir(filepath):
                continue
            try:
                with open(filepath, encoding="utf-8") as fp:
                    data = json.load(fp)
                dcc = data.get("dcc", entry).lower()
                session_id = data.get("session_id", fname.replace(".json", ""))
                _migrate_single_session(filepath, data, dcc, session_id)
            except Exception:
                continue


def _migrate_single_session(old_path, data, dcc, session_id):
    """Migrate a single old-format session file to the new folder structure."""
    folder = _session_folder(dcc, session_id)
    chat_path = os.path.join(folder, "chat.json")
    
    # Don't re-migrate if already done
    if os.path.exists(chat_path):
        # Remove old file if new one exists
        if os.path.exists(old_path):
            os.remove(old_path)
        return
    
    # Save as chat.json in the new location
    with open(chat_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    # Remove old flat file
    if os.path.exists(old_path):
        os.remove(old_path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_session_id(dcc, scene_path):
    """Generate a short 8-char hash from DCC + scene path."""
    key = f"{dcc}:{scene_path}"
    return hashlib.md5(key.encode()).hexdigest()[:8]


def get_session_path(dcc, scene_name, session_id):
    """Build the full path to a session's chat.json file."""
    folder = _session_folder(dcc, session_id)
    return os.path.join(folder, "chat.json")


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
    """Save a session to disk. Updates last_opened timestamp.
    Note: Artifact creation is handled by the UI layer (main.py), not here."""
    session_data["last_opened"] = datetime.now().isoformat()
    dcc = session_data["dcc"]
    session_id = session_data["session_id"]
    
    # Save chat.json directly — no artifact extraction here
    path = get_session_path(dcc, session_data["scene_name"], session_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(session_data, f, indent=2, ensure_ascii=False)
    return path


def _iter_all_session_folders():
    """Iterate over all session folders across all DCC subfolders.
    Yields (folder_path, session_id, dcc) tuples."""
    _ensure_dir()
    _migrate_flat_sessions()
    for dcc_entry in os.listdir(SESSIONS_DIR):
        dcc_dir = os.path.join(SESSIONS_DIR, dcc_entry)
        if not os.path.isdir(dcc_dir):
            continue
        for session_entry in os.listdir(dcc_dir):
            session_dir = os.path.join(dcc_dir, session_entry)
            chat_file = os.path.join(session_dir, "chat.json")
            if os.path.isdir(session_dir) and os.path.exists(chat_file):
                yield session_dir, session_entry, dcc_entry


def load_all_sessions():
    """Return all sessions sorted by last_opened (newest first).
    Reconstructs artifact content for display."""
    sessions = []
    for folder, session_id, dcc in _iter_all_session_folders():
        chat_path = os.path.join(folder, "chat.json")
        try:
            with open(chat_path, encoding="utf-8") as fp:
                data = json.load(fp)
            if "session_id" in data and "dcc" in data:
                # Reconstruct artifact content for display
                _resolve_artifacts_in_session(data)
                sessions.append(data)
        except Exception:
            continue
    return sorted(sessions, key=lambda x: x.get("last_opened", ""), reverse=True)


def load_session(session_id):
    """Load a specific session by its ID, resolving artifacts."""
    for folder, sid, dcc in _iter_all_session_folders():
        if sid == session_id or session_id in sid:
            chat_path = os.path.join(folder, "chat.json")
            try:
                with open(chat_path, encoding="utf-8") as fp:
                    data = json.load(fp)
                _resolve_artifacts_in_session(data)
                return data
            except Exception:
                return None
    return None


def _resolve_artifacts_in_session(session_data):
    """Resolve all artifact references in a session's chat history."""
    dcc = session_data.get("dcc", "unknown")
    session_id = session_data.get("session_id", "")
    
    resolved_history = []
    for msg in session_data.get("chat_history", []):
        if msg.get("type") == "artifact":
            # Entire message is an artifact — load it
            content = _reconstruct_content(msg, dcc, session_id)
            resolved_history.append({
                "role": msg.get("role", "assistant"),
                "content": content,
            })
        elif "[artifact:" in msg.get("content", ""):
            # Message has inline artifact references
            content = _reconstruct_content(msg, dcc, session_id)
            new_msg = dict(msg)
            new_msg["content"] = content
            # Remove artifact metadata from display
            new_msg.pop("artifacts", None)
            resolved_history.append(new_msg)
        else:
            resolved_history.append(msg)
    
    session_data["chat_history"] = resolved_history


def delete_session(session_id):
    """Delete a session folder from disk."""
    for folder, sid, dcc in _iter_all_session_folders():
        if sid == session_id or session_id in sid:
            try:
                shutil.rmtree(folder)
                return True
            except Exception:
                return False
    return False


def rename_session(session_id, new_name):
    """Rename a session's scene_name. Updates chat.json in place."""
    for folder, sid, dcc in _iter_all_session_folders():
        if sid == session_id or session_id in sid:
            chat_path = os.path.join(folder, "chat.json")
            try:
                with open(chat_path, encoding="utf-8") as fp:
                    data = json.load(fp)
                data["scene_name"] = new_name
                with open(chat_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                # Resolve artifacts before returning
                _resolve_artifacts_in_session(data)
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
