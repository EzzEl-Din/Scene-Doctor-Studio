"""
dcc_connector.py — Scene Doctor Studio

TCP socket connection to Maya (port 7001) and Blender (port 7002).

IMPORTANT PROTOCOL DIFFERENCES:
- Maya commandPort: Treats each newline as a SEPARATE command.
  Variables from one line are NOT available in the next.
  Solution: wrap multi-line code in exec("...") as one block.
  The return value is the LAST EXPRESSION — not print() output.
- Blender socket server: Captures stdout from exec() and sends it back.
  print() works normally. Multi-line code runs in one block.

Maya requires: cmds.commandPort(name=":7001", sourceType="python")
Blender requires: socket server in blender_addon.py (auto-started on register)

Built by Ezz El-Din
"""

import socket
import json
import os
import time
import base64
import concurrent.futures

PORTS = {
    "maya": 7001,
    "blender": 7002,
}

DCC_INFO = {
    "maya": {"label": "Maya", "color": "#4A90D9"},
    "blender": {"label": "Blender", "color": "#E87D0D"},
}

TIMEOUT = 10


def _check_port(dcc, port, timeout=0.5):
    """Check if a DCC port is open. Returns (dcc, is_open). Non-blocking."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex(("localhost", port))
        s.close()
        return dcc, result == 0
    except Exception:
        return dcc, False


def is_dcc_connected(dcc):
    """Quick check if DCC socket is alive. Non-blocking, 0.5s timeout."""
    port = PORTS.get(dcc)
    if not port:
        return False
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        result = s.connect_ex(("localhost", port))
        s.close()
        return result == 0
    except Exception:
        return False


def detect_connected_dccs():
    """Check all DCC ports in PARALLEL — no sequential blocking.
    Returns list of connected DCC names.
    """
    connected = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(PORTS)) as executor:
        futures = {
            executor.submit(_check_port, dcc, port): dcc
            for dcc, port in PORTS.items()
        }
        for future in concurrent.futures.as_completed(futures):
            dcc, is_open = future.result()
            if is_open:
                connected.append(dcc)
    return connected


def detect_connected_dcc():
    return (detect_connected_dccs() or [None])[0]


# ---------------------------------------------------------------------------
# QThread worker — run detect_connected_dccs() without blocking the UI
# ---------------------------------------------------------------------------
try:
    from PySide6.QtCore import QThread, Signal as _Signal

    class DetectDCCWorker(QThread):
        """Run detect_connected_dccs() on a background thread.
        Emits finished(list[str]) with the list of connected DCC names.
        """
        finished = _Signal(list)

        def run(self):
            dccs = detect_connected_dccs()
            self.finished.emit(dccs)

except ImportError:
    # PySide6 not available (e.g. running inside Blender) — skip
    DetectDCCWorker = None


# ---------------------------------------------------------------------------
# Low-level send
# ---------------------------------------------------------------------------

def _send_maya(code):
    """Send code to Maya's commandPort.
    Maya keeps the connection open, so we use a short recv timeout
    to detect end-of-response.
    """
    port = PORTS["maya"]
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(30)
        s.connect(("localhost", port))
        s.sendall(code.encode("utf-8") + b"\n")

        # Read response — longer timeout for scan operations
        chunks = []
        s.settimeout(8.0)
        try:
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        except socket.timeout:
            pass

        s.close()
        result = b"".join(chunks).decode("utf-8", errors="replace").strip()
        return True, result if result else "OK"
    except socket.timeout:
        return False, "Connection timed out — is Maya responding?"
    except ConnectionRefusedError:
        return False, "Cannot connect to Maya on port 7001. Did you run commandPort?"
    except Exception as e:
        return False, str(e)


def _send_blender(code):
    """Send code to Blender's socket server (captures stdout)."""
    port = PORTS["blender"]
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(TIMEOUT)
        s.connect(("localhost", port))
        s.sendall(code.encode("utf-8"))
        s.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
        s.close()
        result = b"".join(chunks).decode("utf-8", errors="replace").strip()
        return True, result
    except socket.timeout:
        return False, "Connection timed out — is Blender responding?"
    except ConnectionRefusedError:
        return False, "Cannot connect to Blender on port 7002. Is the addon enabled?"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Undo chunk wrapping — let artists Ctrl+Z any code Scene Doctor runs
# ---------------------------------------------------------------------------

def _indent(code, spaces=4):
    """Indent every line of a code block — used for wrapping in try/finally."""
    pad = " " * spaces
    return "\n".join(f"{pad}{line}" if line else line for line in code.split("\n"))


def _wrap_with_undo(dcc, code, undo_label):
    """Wrap user code in an undo chunk so it can be reversed with Ctrl+Z.
    Maya: openChunk / closeChunk in try/finally — chunk always closes.
    Blender: undo_push before, undo() on failure.
    """
    safe_label = str(undo_label).replace('"', "'").replace("\n", " ")[:120]

    if dcc == "maya":
        return (
            "import maya.cmds as cmds\n"
            f'cmds.undoInfo(openChunk=True, chunkName="{safe_label}")\n'
            "try:\n"
            f"{_indent(code)}\n"
            "finally:\n"
            "    cmds.undoInfo(closeChunk=True)\n"
        )
    if dcc == "blender":
        return (
            "import bpy\n"
            f'bpy.ops.ed.undo_push(message="{safe_label}")\n'
            "try:\n"
            f"{_indent(code)}\n"
            "except Exception as _sdr_err:\n"
            "    try: bpy.ops.ed.undo()\n"
            "    except Exception: pass\n"
            "    raise _sdr_err\n"
        )
    return code


def send_code(dcc, code, undo_label=None):
    """Send Python code to a DCC and return (success, result_string).

    For Maya multi-line: writes code to a temp .py file, then sends a single-line
    command to Maya that redirects stdout → temp .txt, exec's the .py, reads .txt back.
    This avoids all escaping issues with nested exec() strings.

    If `undo_label` is provided, the code is wrapped in a DCC-native undo chunk
    so the artist can Ctrl+Z to reverse the entire change. Pass None for
    read-only operations (scans, screenshots, scene info) to keep the undo
    history clean.
    """
    if undo_label:
        code = _wrap_with_undo(dcc, code, undo_label)

    if dcc == "maya":
        if "\n" in code.strip():
            import tempfile, os, time
            # Write user code to temp .py file (add None at end to suppress return value)
            code_file = tempfile.mktemp(suffix='_sdr_code.py').replace("\\", "/")
            out_file = tempfile.mktemp(suffix='_sdr_out.txt').replace("\\", "/")
            with open(code_file, "w", encoding="utf-8") as f:
                f.write(code + "\nNone\n")
            
            # Single-line Maya command: redirect stdout → file, exec code, restore
            # Using semicolons for single-line exec to avoid commandPort newline issues
            run_cmd = (
                f'import sys; _f=open("{out_file}","w",encoding="utf-8"); _o=sys.stdout; sys.stdout=_f; '
                f'exec(open("{code_file}",encoding="utf-8").read()); '
                f'sys.stdout=_o; _f.close()'
            )
            ok, err = _send_maya(run_cmd)
            
            # Read captured output
            result = ""
            time.sleep(0.2)  # small delay for file write
            try:
                if os.path.exists(out_file):
                    with open(out_file, "r", encoding="utf-8") as f:
                        result = f.read().strip()
            except Exception:
                pass
            
            # Cleanup temp files
            for fp in (code_file, out_file):
                try:
                    os.remove(fp)
                except Exception:
                    pass
            
            if not ok:
                return False, err
            return True, result if result else "OK"
        return _send_maya(code)
    elif dcc == "blender":
        return _send_blender(code)
    return False, f"Unknown DCC: {dcc}"


# ---------------------------------------------------------------------------
# Scene info
# ---------------------------------------------------------------------------

def get_scene_info(dcc):
    """Query current scene name and path from the DCC."""
    if dcc == "maya":
        # Use multi-line code with print() for reliable output
        code = (
            "import maya.cmds as cmds, json, os\n"
            "p = cmds.file(q=True, sn=True) or ''\n"
            "s = cmds.file(q=True, sn=True, shortName=True) or ''\n"
            "if p:\n"
            "    n = os.path.splitext(os.path.basename(p))[0]\n"
            "elif s:\n"
            "    n = os.path.splitext(s)[0]\n"
            "else:\n"
            "    n = 'untitled'\n"
            "print(json.dumps({'path': p, 'name': n}))\n"
        )
        success, result = send_code(dcc, code)
    elif dcc == "blender":
        code = (
            "import bpy, json, os\n"
            "path = bpy.data.filepath or ''\n"
            "if path:\n"
            "    name = os.path.splitext(os.path.basename(path))[0]\n"
            "else:\n"
            "    name = bpy.context.scene.name or 'untitled'\n"
            "print(json.dumps({'path': path, 'name': name}))\n"
        )
        success, result = _send_blender(code)
    else:
        return False, f"Unknown DCC: {dcc}"

    if not success:
        return False, result

    # Parse JSON — handle possible surrounding quotes that Maya adds to string results
    for line in result.strip().splitlines():
        candidate = line.strip().strip("'\"")
        if candidate.startswith("{"):
            try:
                return True, json.loads(candidate)
            except json.JSONDecodeError:
                continue
    return False, f"No JSON in response: {result[:200]}"



# ---------------------------------------------------------------------------
# Viewport screenshot
# ---------------------------------------------------------------------------

def take_screenshot(dcc):
    """Capture viewport screenshot. Returns (success, base64_string)."""
    if dcc == "maya":
        code = (
            "import maya.cmds as cmds, base64, tempfile, os\n"
            "tmp = tempfile.mktemp(suffix='.png')\n"
            "cmds.playblast(frame=cmds.currentTime(q=True), format='image',\n"
            "               cf=tmp, wh=[960,540], p=100, viewer=False,\n"
            "               compression='png')\n"
            "actual = tmp.replace('.png', '.0000.png')\n"
            "if not os.path.exists(actual): actual = tmp\n"
            "result = ''\n"
            "if os.path.exists(actual):\n"
            "    with open(actual, 'rb') as f:\n"
            "        result = base64.b64encode(f.read()).decode()\n"
            "    os.remove(actual)\n"
            "print(result)\n"
        )
    elif dcc == "blender":
        # Use bpy.data.images approach — create an image, copy viewport pixels
        # This avoids bpy.ops entirely and works from any thread
        import tempfile
        tmp_path = os.path.join(tempfile.gettempdir(), 'scene_doctor_blender_viewport.png')
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        
        # Escape the path for Python string
        tmp_escaped = tmp_path.replace('\\', '\\\\')
        
        code = (
            "import bpy, os\n"
            f"tmp = r'{tmp_path}'\n"
            "scene = bpy.context.scene\n"
            "old_engine = scene.render.engine\n"
            "old_path = scene.render.filepath\n"
            "old_fmt = scene.render.image_settings.file_format\n"
            "old_x = scene.render.resolution_x\n"
            "old_y = scene.render.resolution_y\n"
            "old_pct = scene.render.resolution_percentage\n"
            "scene.render.engine = 'BLENDER_WORKBENCH'\n"
            "scene.render.filepath = tmp\n"
            "scene.render.image_settings.file_format = 'PNG'\n"
            "scene.render.resolution_x = 960\n"
            "scene.render.resolution_y = 540\n"
            "scene.render.resolution_percentage = 100\n"
            "try:\n"
            "    bpy.ops.render.render(write_still=True)\n"
            "except Exception as e:\n"
            "    print('RENDER_ERROR:' + str(e))\n"
            "scene.render.engine = old_engine\n"
            "scene.render.filepath = old_path\n"
            "scene.render.image_settings.file_format = old_fmt\n"
            "scene.render.resolution_x = old_x\n"
            "scene.render.resolution_y = old_y\n"
            "scene.render.resolution_percentage = old_pct\n"
            "if os.path.exists(tmp):\n"
            "    print('SCREENSHOT_OK')\n"
            "else:\n"
            "    print('SCREENSHOT_FAILED')\n"
        )
        
        success, result = send_code(dcc, code)
        
        if not success:
            return False, f"Screenshot failed: {result[:100]}"
        
        # Check if file was created
        if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 100:
            with open(tmp_path, 'rb') as f:
                raw = f.read()
            os.remove(tmp_path)
            if raw[:4] == b'\x89PNG':
                return True, base64.b64encode(raw).decode('ascii')
            else:
                return False, "Screenshot failed — not a valid PNG"
        else:
            return False, f"Screenshot failed — file not created. Blender said: {result[:200]}"
    else:
        return False, f"Unknown DCC: {dcc}"

    success, result = send_code(dcc, code)
    if not success:
        return False, result

    lines = result.strip().splitlines()
    if lines:
        b64 = lines[-1].strip().replace('\n', '').replace('\r', '')
        if len(b64) > 100:
            return True, b64
    return False, f"Screenshot failed. Raw: {result[:200]}"


# ---------------------------------------------------------------------------
# Scene scan
# ---------------------------------------------------------------------------

def run_scan(dcc):
    """Execute the scene scanner inside the DCC and return the report text."""
    if dcc == "maya":
        # Multi-line code → send_code auto-wraps in exec() for Maya
        code = (
            "import sys, json\n"
            "scanner_dir = r'd:/work script/ai doctor/v4'\n"
            "if scanner_dir not in sys.path: sys.path.insert(0, scanner_dir)\n"
            "try:\n"
            "    from scanners import maya_scanner\n"
            "    report = maya_scanner.run_scan()\n"
            "    prompt = maya_scanner.scan_to_prompt(report)\n"
            "except Exception as e:\n"
            "    prompt = 'Scanner not found: ' + str(e)\n"
            "# Add animation overview\n"
            "import maya.cmds as cmds\n"
            "anim_summary = '\\n\\n## Animation Overview\\n'\n"
            "all_curves = cmds.ls(type='animCurve') or []\n"
            "anim_summary += 'Animation curves in scene: %d\\n' % len(all_curves)\n"
            "if all_curves:\n"
            "    stepped = 0\n"
            "    spline = 0\n"
            "    linear = 0\n"
            "    for crv in all_curves[:50]:\n"
            "        try:\n"
            "            ott = cmds.keyTangent(crv, q=True, ott=True) or []\n"
            "            for t in ott:\n"
            "                if t == 'step': stepped += 1\n"
            "                elif t == 'linear': linear += 1\n"
            "                elif t in ('spline','auto','clamped','plateau'): spline += 1\n"
            "        except: pass\n"
            "    anim_summary += 'Tangent breakdown: spline/auto=%d, linear=%d, stepped=%d\\n' % (spline, linear, stepped)\n"
            "    if stepped > spline:\n"
            "        anim_summary += 'WARNING: Mostly stepped tangents — animation is NOT smooth\\n'\n"
            "    if stepped > 0 and spline > 0:\n"
            "        anim_summary += 'WARNING: Mixed tangent types — may cause jerky motion\\n'\n"
            "fps = cmds.currentUnit(q=True, time=True)\n"
            "pmin = cmds.playbackOptions(q=True, min=True)\n"
            "pmax = cmds.playbackOptions(q=True, max=True)\n"
            "anim_summary += 'Timeline: %.0f - %.0f | FPS: %s\\n' % (pmin, pmax, fps)\n"
            "print(prompt + anim_summary)\n"
        )
    elif dcc == "blender":
        code = (
            "import sys, os\n"
            "scanner_dir = r'd:/work script/ai doctor/v4'\n"
            "if scanner_dir not in sys.path: sys.path.insert(0, scanner_dir)\n"
            "try:\n"
            "    from scanners import blender_scanner\n"
            "    report = blender_scanner.run_scan()\n"
            "    prompt = blender_scanner.scan_to_prompt(report)\n"
            "except Exception as e:\n"
            "    prompt = 'Scanner not found: ' + str(e)\n"
            "# Add animation overview\n"
            "import bpy\n"
            "anim_summary = '\\n\\n## Animation Overview\\n'\n"
            "animated_objs = [o for o in bpy.context.scene.objects if o.animation_data and o.animation_data.action]\n"
            "anim_summary += 'Animated objects: %d\\n' % len(animated_objs)\n"
            "if animated_objs:\n"
            "    constant = 0\n"
            "    linear = 0\n"
            "    bezier = 0\n"
            "    for obj in animated_objs:\n"
            "        for fc in obj.animation_data.action.fcurves:\n"
            "            for kp in fc.keyframe_points:\n"
            "                if kp.interpolation == 'CONSTANT': constant += 1\n"
            "                elif kp.interpolation == 'LINEAR': linear += 1\n"
            "                elif kp.interpolation == 'BEZIER': bezier += 1\n"
            "    anim_summary += 'Interpolation: bezier=%d, linear=%d, constant=%d\\n' % (bezier, linear, constant)\n"
            "    if constant > bezier:\n"
            "        anim_summary += 'WARNING: Mostly constant/stepped — animation is NOT smooth\\n'\n"
            "    if constant > 0 and bezier > 0:\n"
            "        anim_summary += 'WARNING: Mixed interpolation — may cause jerky motion\\n'\n"
            "scene = bpy.context.scene\n"
            "anim_summary += 'Timeline: %d - %d | FPS: %d\\n' % (scene.frame_start, scene.frame_end, scene.render.fps)\n"
            "print('__SCAN_START__')\n"
            "print(prompt + anim_summary)\n"
            "print('__SCAN_END__')\n"
        )
    else:
        return False, f"Unknown DCC: {dcc}"

    success, result = send_code(dcc, code)
    if not success:
        return False, result

    if not result:
        return False, "Scanner returned empty result. Is the scanner module installed?"

    # Clean up result — Maya may return the string wrapped in quotes
    cleaned = result.strip()
    # Strip surrounding quotes if present (Maya expression returns repr)
    if len(cleaned) > 2 and cleaned[0] in ("'", '"') and cleaned[-1] == cleaned[0]:
        try:
            cleaned = eval(cleaned)  # safely parse string literal
        except Exception:
            pass

    if cleaned in ("None", "OK", "", "''", '""'):
        return False, "Scanner returned empty result. Is the scanner module installed?"

    # Blender uses markers
    if "__SCAN_START__" in cleaned and "__SCAN_END__" in cleaned:
        start = cleaned.index("__SCAN_START__") + len("__SCAN_START__")
        end = cleaned.index("__SCAN_END__")
        return True, cleaned[start:end].strip()

    # Maya: stdout was captured via StringIO, result is the print output
    if len(cleaned) > 20:
        return True, cleaned

    return False, f"Scan output too short. Raw: {result[:300]}"


# ---------------------------------------------------------------------------
# Maya setup helper
# ---------------------------------------------------------------------------

MAYA_SETUP_COMMAND = 'import maya.cmds as cmds; cmds.commandPort(name=":7001", sourceType="python")'

MAYA_SETUP_INSTRUCTIONS = """
To connect Maya to Scene Doctor Studio:

1. Open Maya
2. Open the Script Editor (Windows > General Editors > Script Editor)
3. In the Python tab, paste and run:

   import maya.cmds as cmds
   cmds.commandPort(name=":7001", sourceType="python")

4. Maya is now listening on port 7001.
   You only need to do this once per Maya session.

Tip: Add this to your userSetup.py to auto-enable on startup.
""".strip()
