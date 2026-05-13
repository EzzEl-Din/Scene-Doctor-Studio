bl_info = {
    "name": "Scene Doctor AI",
    "author": "Ezz El-Din",
    "version": (4, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Scene Doctor",
    "description": "AI-powered scene diagnostics and fixes",
    "category": "3D View",
}

import bpy
import os
import sys
import json
import re
import queue
import tempfile
import base64

# ---------------------------------------------------------------------------
# Path setup — auto-detect from file location (works for any user)
# ---------------------------------------------------------------------------
addon_dir = os.path.dirname(os.path.abspath(__file__))
if addon_dir not in sys.path:
    sys.path.insert(0, addon_dir)

from platform_detect import get_scanner, get_system_prompt_prefix, get_codewriter_prompt_prefix
import ai_backend

_scanner = get_scanner("blender")

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
settings_path = os.path.join(addon_dir, "settings.json")


def load_settings():
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                return ai_backend.migrate_settings(json.load(f))
        except Exception as e:
            print("Failed to load settings:", e)
    import copy
    return copy.deepcopy(ai_backend.DEFAULT_SETTINGS)


def save_settings(data):
    try:
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print("Failed to save settings:", e)


_global_settings = load_settings()
_chat_history = []

# ---------------------------------------------------------------------------
# State globals
# ---------------------------------------------------------------------------
_token_queue = queue.Queue()
_is_busy = False

# Agent pipeline state: "idle", "analyzer", "codewriter"
_agent_phase = "idle"
_original_user_msg = ""
_current_response = ""          # accumulates tokens for the active agent
_pending_code_blocks = []       # code blocks extracted after streaming done
_code_exec_results = {}         # {index: (success, msg)} — results of executed blocks
_pending_screenshot_b64 = None  # viewport screenshot waiting to be sent
_screenshot_requested = False   # flag for socket→timer screenshot handoff
_screenshot_path = ""           # temp file path for screenshot

# In-panel chat display
_panel_chat = []  # [{"role": "user"|"analyzer"|"codewriter"|"system", "text": str}]

# ---------------------------------------------------------------------------
# Code extraction & execution  (Priority 1)
# ---------------------------------------------------------------------------

def extract_code_blocks(response_text):
    """Extract executable code blocks from AI response.
    Looks for ```scene-run blocks first, falls back to ```python.
    """
    pattern = r'```scene-run\n(.*?)```'
    blocks = re.findall(pattern, response_text, re.DOTALL)

    if not blocks:
        pattern = r'```python\n(.*?)```'
        blocks = re.findall(pattern, response_text, re.DOTALL)

    return blocks


# Blender context patch — prepended to all executed code so that
# `active_object` is always available even from a socket thread.
BLENDER_CONTEXT_PATCH = """
import bpy as _bpy
try:
    _vl = _bpy.context.view_layer
    _active = _vl.objects.active
    active_object = _active if _active else (list(_vl.objects.selected) or [None])[0]
except Exception:
    active_object = None
"""


def run_blender_code(code):
    """Execute a code string inside Blender safely with proper context helpers.
    Returns (success: bool, message: str).
    """
    import traceback

    # Build a namespace with safe, view_layer-based context helpers so that
    # AI-generated code using bpy.context.active_object works from any thread.
    try:
        vl = bpy.context.view_layer
        _active = vl.objects.active
        _selected = list(vl.objects.selected)
        namespace = {
            "bpy": bpy,
            "__builtins__": __builtins__,
            # Convenience aliases that mirror bpy.context.* but are socket-safe
            "active_object": _active if _active else (_selected[0] if _selected else None),
            "selected_objects": _selected,
            "scene": bpy.context.scene,
            "view_layer": vl,
        }
    except Exception:
        # Minimal fallback if even view_layer access fails
        namespace = {"bpy": bpy, "__builtins__": __builtins__}

    try:
        patched = BLENDER_CONTEXT_PATCH + "\n" + code
        exec(patched, namespace)
        return True, "Done"
    except Exception:
        return False, traceback.format_exc()


# ---------------------------------------------------------------------------
# Viewport screenshot  (Priority 4)
# ---------------------------------------------------------------------------

def capture_viewport():
    """Take a viewport screenshot and return base64-encoded PNG string.
    Uses a multi-fallback strategy that works from any thread context.
    """
    tmp = tempfile.mktemp(suffix=".png")

    # --- Method 1: OpenGL render (most reliable from socket context) ---
    try:
        scene = bpy.context.scene
        old_path = scene.render.filepath
        old_fmt = scene.render.image_settings.file_format
        scene.render.filepath = tmp
        scene.render.image_settings.file_format = 'PNG'

        # Try with context override to pick up the 3D viewport
        override = {}
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    for region in area.regions:
                        if region.type == 'WINDOW':
                            override = {
                                'window': window,
                                'screen': window.screen,
                                'area': area,
                                'region': region,
                                'space_data': area.spaces.active,
                            }
                            break

        if override:
            with bpy.context.temp_override(**override):
                bpy.ops.render.opengl(write_still=True)
        else:
            bpy.ops.render.opengl(write_still=True)

        scene.render.filepath = old_path
        scene.render.image_settings.file_format = old_fmt

        if os.path.exists(tmp):
            with open(tmp, "rb") as f:
                data = base64.b64encode(f.read()).decode()
            os.remove(tmp)
            return data
    except Exception as e:
        print(f"Scene Doctor: Screenshot method 1 failed: {e}")
        # Restore render settings even if we errored
        try:
            bpy.context.scene.render.filepath = old_path
            bpy.context.scene.render.image_settings.file_format = old_fmt
        except Exception:
            pass

    # --- Method 2: Save existing Render Result if available ---
    try:
        if "Render Result" in bpy.data.images:
            bpy.data.images["Render Result"].save_render(tmp)
            with open(tmp, "rb") as f:
                data = base64.b64encode(f.read()).decode()
            os.remove(tmp)
            return data
    except Exception as e:
        print(f"Scene Doctor: Screenshot method 2 failed: {e}")

    return None


# ---------------------------------------------------------------------------
# Chat helpers
# ---------------------------------------------------------------------------

def get_chat_text_block():
    """Get or create the Text Editor block for full chat log."""
    name = "SceneDoctor_Chat.txt"
    if name not in bpy.data.texts:
        text = bpy.data.texts.new(name)
        text.write("=== Scene Doctor AI Chat ===\n")
    return bpy.data.texts[name]


def append_to_chat(role, content):
    """Write to both the Text Editor (full log) and panel chat (summary)."""
    global _panel_chat

    text_block = get_chat_text_block()

    # Role labels for display
    label_map = {
        "user": "You",
        "analyzer": "🔍 Analyzer",
        "codewriter": "🔧 Code Writer",
        "assistant": "AI",
        "system": "⚙ System",
    }
    label = label_map.get(role, role)
    text_block.write(f"\n{label}: {content}\n")

    # Add to panel chat
    _panel_chat.append({"role": role, "text": content})

    # Redraw all areas
    for area in bpy.context.screen.areas:
        area.tag_redraw()


def _redraw_panels():
    """Force redraw of 3D view sidebars and text editors."""
    for area in bpy.context.screen.areas:
        if area.type in ('VIEW_3D', 'TEXT_EDITOR'):
            area.tag_redraw()


# ---------------------------------------------------------------------------
# Streaming token pump  (runs via bpy.app.timers)
# ---------------------------------------------------------------------------

def pump_tokens():
    """Timer callback — drains the token queue and writes to chat."""
    global _is_busy, _current_response, _agent_phase

    text_block = get_chat_text_block()
    updated = False

    while not _token_queue.empty():
        token = _token_queue.get()

        if token == "[DONE]":
            text_block.write("\n")
            _on_agent_done()
            updated = True
            continue
        elif token.startswith("[ERROR:"):
            text_block.write(token)
            updated = True
            continue

        # Accumulate for code extraction
        _current_response += token
        text_block.write(token)
        updated = True

    if updated:
        _redraw_panels()

    return 0.1 if _is_busy else None


def _on_agent_done():
    """Called when the current agent finishes streaming."""
    global _is_busy, _agent_phase, _current_response, _pending_code_blocks, _code_exec_results

    mode = _global_settings.get("mode", "single")
    finished_phase = _agent_phase

    if finished_phase == "analyzer" and mode == "multi":
        # Analyzer done → launch Code Writer
        analyzer_response = _current_response
        _current_response = ""

        # Store analyzer response in chat history
        _chat_history.append({"role": "assistant", "content": analyzer_response})

        # Start code writer
        _agent_phase = "codewriter"
        _start_codewriter(analyzer_response)
        return

    # Either codewriter is done, or single mode analyzer is done
    full_response = _current_response
    _current_response = ""

    # Store in chat history
    _chat_history.append({"role": "assistant", "content": full_response})

    # Extract code blocks (works in both single and multi mode)
    blocks = extract_code_blocks(full_response)
    _pending_code_blocks = blocks
    _code_exec_results = {}

    if blocks:
        count = len(blocks)
        append_to_chat("system", f"📋 Found {count} code block{'s' if count > 1 else ''} — use [▶ Run] in the panel")

    _agent_phase = "idle"
    _is_busy = False
    _redraw_panels()


def _start_codewriter(analyzer_response):
    """Launch the Code Writer agent with analyzer output as context."""
    global _original_user_msg

    append_to_chat("codewriter", "")

    codewriter_messages = [
        {"role": "user", "content": (
            f"Scene analysis:\n{analyzer_response}\n\n"
            f"User request: {_original_user_msg}\n\n"
            "Write ONE complete self-contained ```scene-run block to fix the issues."
        )}
    ]

    settings = dict(_global_settings.get("codewriter", {}))
    prefix = get_codewriter_prompt_prefix("blender")
    settings["system_prompt"] = prefix + settings.get("system_prompt", "")

    worker = ai_backend.StreamWorker(codewriter_messages, settings)
    worker.token.connect(on_token)
    worker.done.connect(on_done)
    worker.error.connect(on_error)
    worker.start()

    # Prevent GC
    SCENEDOCTOR_OT_scan._codewriter_worker = worker


# ---------------------------------------------------------------------------
# Signal callbacks (called from background thread)
# ---------------------------------------------------------------------------

def on_token(token):
    _token_queue.put(token)


def on_done():
    _token_queue.put("[DONE]")


def on_error(msg):
    _token_queue.put(f"\n[Error: {msg}]")
    _token_queue.put("[DONE]")


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class SCENEDOCTOR_OT_scan(bpy.types.Operator):
    """Scan the scene and send to AI for analysis"""
    bl_idname = "scenedoctor.scan"
    bl_label = "Scan Scene"

    # Class-level refs to prevent GC of workers
    _analyzer_worker = None
    _codewriter_worker = None

    def execute(self, context):
        global _is_busy, _agent_phase, _current_response, _original_user_msg
        global _pending_code_blocks, _code_exec_results

        if _is_busy:
            self.report({'WARNING'}, "AI is busy")
            return {'CANCELLED'}

        append_to_chat("user", "Scanning scene...")
        try:
            report = _scanner.run_scan()
            prompt = _scanner.scan_to_prompt(report)
        except Exception as e:
            append_to_chat("system", f"Scan failed: {e}")
            return {'CANCELLED'}

        msg = "Please analyse this scene:\n\n" + prompt
        _original_user_msg = msg
        _chat_history.append({"role": "user", "content": msg})

        # Reset state
        _current_response = ""
        _pending_code_blocks = []
        _code_exec_results = {}

        _is_busy = True
        _agent_phase = "analyzer"
        bpy.app.timers.register(pump_tokens)

        # Build analyzer settings
        settings = dict(_global_settings.get("analyzer", {}))
        prefix = get_system_prompt_prefix("blender")
        settings["system_prompt"] = prefix + settings.get("system_prompt", "")

        append_to_chat("analyzer", "")

        worker = ai_backend.StreamWorker(_chat_history, settings)
        worker.token.connect(on_token)
        worker.done.connect(on_done)
        worker.error.connect(on_error)
        worker.start()

        self.__class__._analyzer_worker = worker
        return {'FINISHED'}


class SCENEDOCTOR_OT_send(bpy.types.Operator):
    """Send a chat message to the AI"""
    bl_idname = "scenedoctor.send"
    bl_label = "Send Message"

    # Class-level refs
    _analyzer_worker = None
    _codewriter_worker = None

    def execute(self, context):
        global _is_busy, _agent_phase, _current_response, _original_user_msg
        global _pending_code_blocks, _code_exec_results, _pending_screenshot_b64

        if _is_busy:
            self.report({'WARNING'}, "AI is busy")
            return {'CANCELLED'}

        msg = context.scene.scenedoctor_input
        if not msg.strip():
            return {'CANCELLED'}

        append_to_chat("user", msg)
        _original_user_msg = msg

        # Build chat message — attach screenshot if pending
        chat_msg = {"role": "user", "content": msg}
        if _pending_screenshot_b64:
            chat_msg["image_b64"] = _pending_screenshot_b64
            _pending_screenshot_b64 = None
            append_to_chat("system", "📷 Screenshot attached to message")

        _chat_history.append(chat_msg)
        context.scene.scenedoctor_input = ""

        # Reset state
        _current_response = ""
        _pending_code_blocks = []
        _code_exec_results = {}

        _is_busy = True
        _agent_phase = "analyzer"
        bpy.app.timers.register(pump_tokens)

        # Build analyzer settings
        settings = dict(_global_settings.get("analyzer", {}))
        prefix = get_system_prompt_prefix("blender")
        settings["system_prompt"] = prefix + settings.get("system_prompt", "")

        append_to_chat("analyzer", "")

        worker = ai_backend.StreamWorker(_chat_history, settings)
        worker.token.connect(on_token)
        worker.done.connect(on_done)
        worker.error.connect(on_error)
        worker.start()

        self.__class__._analyzer_worker = worker
        return {'FINISHED'}


class SCENEDOCTOR_OT_run_code(bpy.types.Operator):
    """Execute a code block from the AI response"""
    bl_idname = "scenedoctor.run_code"
    bl_label = "Run Fix"

    code_index: bpy.props.IntProperty(default=0)

    def execute(self, context):
        global _code_exec_results

        if self.code_index < 0 or self.code_index >= len(_pending_code_blocks):
            self.report({'ERROR'}, "Invalid code block index")
            return {'CANCELLED'}

        code = _pending_code_blocks[self.code_index]
        success, msg = run_blender_code(code)
        _code_exec_results[self.code_index] = (success, msg)

        if success:
            append_to_chat("system", f"✅ Code block {self.code_index + 1} executed successfully")
        else:
            append_to_chat("system", f"⚠ Code block {self.code_index + 1} error: {msg}")

        _redraw_panels()
        return {'FINISHED'}


class SCENEDOCTOR_OT_run_all_code(bpy.types.Operator):
    """Execute all pending code blocks"""
    bl_idname = "scenedoctor.run_all_code"
    bl_label = "Run All"

    def execute(self, context):
        global _code_exec_results

        if not _pending_code_blocks:
            self.report({'WARNING'}, "No code blocks to run")
            return {'CANCELLED'}

        total = len(_pending_code_blocks)
        passed = 0
        for i, code in enumerate(_pending_code_blocks):
            success, msg = run_blender_code(code)
            _code_exec_results[i] = (success, msg)
            if success:
                passed += 1
            else:
                append_to_chat("system", f"⚠ Block {i + 1} error: {msg}")

        append_to_chat("system", f"✅ Executed {passed}/{total} blocks successfully")
        _redraw_panels()
        return {'FINISHED'}


class SCENEDOCTOR_OT_screenshot(bpy.types.Operator):
    """Capture viewport screenshot to attach to next message"""
    bl_idname = "scenedoctor.screenshot"
    bl_label = "Capture Viewport"

    def execute(self, context):
        global _pending_screenshot_b64

        b64 = capture_viewport()
        if b64:
            _pending_screenshot_b64 = b64
            append_to_chat("system", "📷 Viewport captured — will attach to your next message")
            self.report({'INFO'}, "Viewport captured")
        else:
            self.report({'WARNING'}, "Failed to capture viewport")

        _redraw_panels()
        return {'FINISHED'}


class SCENEDOCTOR_OT_clear_chat(bpy.types.Operator):
    """Clear the chat history and panel"""
    bl_idname = "scenedoctor.clear_chat"
    bl_label = "Clear Chat"

    def execute(self, context):
        global _panel_chat, _chat_history, _pending_code_blocks, _code_exec_results

        _panel_chat = []
        _chat_history = []
        _pending_code_blocks = []
        _code_exec_results = {}

        # Clear text block
        name = "SceneDoctor_Chat.txt"
        if name in bpy.data.texts:
            bpy.data.texts.remove(bpy.data.texts[name])

        _redraw_panels()
        self.report({'INFO'}, "Chat cleared")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Panel  (Priority 3 — in-panel chat + code blocks + screenshot)
# ---------------------------------------------------------------------------

class SCENEDOCTOR_PT_panel(bpy.types.Panel):
    bl_label = "Scene Doctor AI"
    bl_idname = "SCENEDOCTOR_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Scene Doctor"

    def draw(self, context):
        layout = self.layout

        # --- Status bar ---
        if _is_busy:
            phase_labels = {
                "analyzer": "🔍 Analyzing...",
                "codewriter": "🔧 Writing code...",
            }
            status = phase_labels.get(_agent_phase, "⏳ Thinking...")
            row = layout.row()
            row.alert = True
            row.label(text=status, icon='SORTTIME')
            layout.separator()

        # --- Chat messages (last 6) ---
        if _panel_chat:
            box = layout.box()
            # Show last 6 messages for context
            visible = _panel_chat[-6:]
            for msg in visible:
                role = msg["role"]
                text = msg["text"]

                if not text.strip():
                    continue

                # Truncate long messages
                display = text.replace("\n", " ")
                if len(display) > 80:
                    display = display[:77] + "..."

                row = box.row()

                if role == "user":
                    row.label(text=f"You: {display}", icon='USER')
                elif role == "analyzer":
                    row.label(text=f"🔍 {display}")
                elif role == "codewriter":
                    row.label(text=f"🔧 {display}")
                elif role == "system":
                    row.label(text=display, icon='INFO')
                else:
                    row.label(text=f"AI: {display}")

            layout.separator()

        # --- Code blocks with Run buttons ---
        if _pending_code_blocks:
            box = layout.box()
            header = box.row()
            header.label(text=f"📋 {len(_pending_code_blocks)} Code Block(s)", icon='SCRIPT')

            # Run All button
            if len(_pending_code_blocks) > 1:
                header.operator("scenedoctor.run_all_code", text="Run All", icon='PLAY')

            for i, code in enumerate(_pending_code_blocks):
                block_box = box.box()
                row = block_box.row()

                # Show result status if executed
                if i in _code_exec_results:
                    success, msg = _code_exec_results[i]
                    if success:
                        row.label(text=f"Block {i + 1}: ✅ Done", icon='CHECKMARK')
                    else:
                        row.label(text=f"Block {i + 1}: ⚠ Error", icon='ERROR')
                        # Show error detail
                        err_row = block_box.row()
                        err_display = msg[:60] + "..." if len(msg) > 60 else msg
                        err_row.label(text=err_display)
                else:
                    # Show preview of code
                    preview = code.strip().split('\n')[0][:50]
                    row.label(text=f"Block {i + 1}: {preview}", icon='SCRIPT')

                    # Run button
                    op = row.operator("scenedoctor.run_code", text="▶ Run", icon='PLAY')
                    op.code_index = i

            layout.separator()

        # --- Screenshot indicator ---
        if _pending_screenshot_b64:
            row = layout.row()
            row.label(text="📷 Screenshot attached — ready to send", icon='IMAGE_DATA')
            layout.separator()

        # --- Input area ---
        layout.prop(context.scene, "scenedoctor_input", text="")

        # --- Action buttons ---
        row = layout.row(align=True)
        row.operator("scenedoctor.scan", text="Scan", icon='ZOOM_ALL')
        row.operator("scenedoctor.send", text="Send", icon='PLAY')
        row.operator("scenedoctor.screenshot", text="", icon='CAMERA_DATA')
        row.operator("scenedoctor.clear_chat", text="", icon='TRASH')

        # --- Footer ---
        layout.separator()
        mode = _global_settings.get("mode", "single")
        mode_label = "Multi-Agent" if mode == "multi" else "Single Agent"
        row = layout.row()
        row.scale_y = 0.7
        row.label(text=f"Mode: {mode_label} | Full log → Text Editor")


# ---------------------------------------------------------------------------
# Socket server for Scene Doctor Studio  (port 7002)
# ---------------------------------------------------------------------------
import socket
import threading
import io

_socket_server = None
_socket_thread = None

def start_socket_server(port=7002):
    """Start a TCP socket server so Scene Doctor Studio can send code."""
    global _socket_server, _socket_thread

    if _socket_server is not None:
        return  # Already running

    try:
        _socket_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _socket_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _socket_server.bind(("localhost", port))
        _socket_server.listen(5)
        _socket_server.settimeout(1.0)  # So we can check _running flag
    except OSError as e:
        print(f"Scene Doctor: Socket server failed to start on port {port}: {e}")
        _socket_server = None
        return

    def _serve():
        while _socket_server is not None:
            try:
                conn, addr = _socket_server.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                # Receive all code
                chunks = []
                while True:
                    data = conn.recv(65536)
                    if not data:
                        break
                    chunks.append(data)
                code = b"".join(chunks).decode("utf-8", errors="replace")

                # Special command: viewport screenshot (needs main thread)
                if code.strip() == "__VIEWPORT_SCREENSHOT__":
                    import tempfile
                    tmp = os.path.join(tempfile.gettempdir(), 'scene_doctor_viewport.png')
                    if os.path.exists(tmp):
                        os.remove(tmp)
                    
                    # Flag for the timer to pick up
                    global _screenshot_requested, _screenshot_path
                    _screenshot_path = tmp
                    _screenshot_requested = True
                    
                    # Wait for the main thread timer to capture (max 5s)
                    import time
                    for _ in range(50):
                        time.sleep(0.1)
                        if os.path.exists(tmp) and os.path.getsize(tmp) > 100:
                            break
                    
                    if os.path.exists(tmp) and os.path.getsize(tmp) > 100:
                        with open(tmp, 'rb') as f:
                            output = base64.b64encode(f.read()).decode()
                        os.remove(tmp)
                    else:
                        output = "SCREENSHOT_FAILED"
                    
                    conn.sendall(output.encode("utf-8"))
                    conn.close()
                    continue

                # Execute with stdout capture, using the safe context-aware helper
                old_stdout = sys.stdout
                sys.stdout = capture = io.StringIO()
                try:
                    success, msg = run_blender_code(code)
                    output = capture.getvalue()
                    if not output:
                        output = msg if not success else "OK"
                except Exception as e:
                    output = f"ERROR: {e}"
                finally:
                    sys.stdout = old_stdout

                conn.sendall(output.encode("utf-8"))
            except Exception as e:
                try:
                    conn.sendall(f"ERROR: {e}".encode("utf-8"))
                except Exception:
                    pass
            finally:
                conn.close()

    _socket_thread = threading.Thread(target=_serve, daemon=True)
    _socket_thread.start()
    print(f"Scene Doctor: Socket server listening on port {port}")


def stop_socket_server():
    """Shut down the socket server."""
    global _socket_server, _socket_thread
    if _socket_server:
        try:
            _socket_server.close()
        except Exception:
            pass
        _socket_server = None
    _socket_thread = None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    SCENEDOCTOR_OT_scan,
    SCENEDOCTOR_OT_send,
    SCENEDOCTOR_OT_run_code,
    SCENEDOCTOR_OT_run_all_code,
    SCENEDOCTOR_OT_screenshot,
    SCENEDOCTOR_OT_clear_chat,
    SCENEDOCTOR_PT_panel,
)


def _screenshot_timer():
    """Timer callback — captures viewport screenshot when requested by socket server.
    Runs on main thread so it has full OpenGL/viewport context."""
    global _screenshot_requested, _screenshot_path
    
    if not _screenshot_requested:
        return 0.1  # check again in 100ms
    
    _screenshot_requested = False
    tmp = _screenshot_path
    
    try:
        scene = bpy.context.scene
        old_path = scene.render.filepath
        old_fmt = scene.render.image_settings.file_format
        scene.render.filepath = tmp
        scene.render.image_settings.file_format = 'PNG'
        
        # Try opengl render with context override (we're on main thread now!)
        override = {}
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    for region in area.regions:
                        if region.type == 'WINDOW':
                            override = {
                                'window': window,
                                'screen': window.screen,
                                'area': area,
                                'region': region,
                                'space_data': area.spaces.active,
                            }
                            break
                    break
            if override:
                break
        
        if override:
            with bpy.context.temp_override(**override):
                bpy.ops.render.opengl(write_still=True)
        
        scene.render.filepath = old_path
        scene.render.image_settings.file_format = old_fmt
    except Exception as e:
        print(f"Scene Doctor: Screenshot timer error: {e}")
    
    return 0.1  # keep running


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.scenedoctor_input = bpy.props.StringProperty(
        name="Input",
        description="Ask Scene Doctor a question",
        default=""
    )
    start_socket_server()
    # Register screenshot timer (runs on main thread, checks for requests)
    bpy.app.timers.register(_screenshot_timer, persistent=True)


def unregister():
    stop_socket_server()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.scenedoctor_input


if __name__ == "__main__":
    register()
