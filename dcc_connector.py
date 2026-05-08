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

PORTS = {
    "maya": 7001,
    "blender": 7002,
}

DCC_INFO = {
    "maya": {"label": "Maya", "color": "#4A90D9"},
    "blender": {"label": "Blender", "color": "#E87D0D"},
}

TIMEOUT = 10


def detect_connected_dccs():
    """Check which DCCs are running and have socket servers open."""
    connected = []
    for dcc, port in PORTS.items():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect(("localhost", port))
            s.close()
            connected.append(dcc)
        except Exception:
            continue
    return connected


def detect_connected_dcc():
    return (detect_connected_dccs() or [None])[0]


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


def send_code(dcc, code):
    """Send Python code to a DCC and return (success, result_string).
    
    For Maya multi-line: writes code to a temp .py file, then sends a single-line
    command to Maya that redirects stdout → temp .txt, exec's the .py, reads .txt back.
    This avoids all escaping issues with nested exec() strings.
    """
    if dcc == "maya":
        if "\n" in code.strip():
            import tempfile, os, time
            # Write user code to temp .py file
            code_file = tempfile.mktemp(suffix='_sdr_code.py').replace("\\", "/")
            out_file = tempfile.mktemp(suffix='_sdr_out.txt').replace("\\", "/")
            with open(code_file, "w", encoding="utf-8") as f:
                f.write(code)
            
            # Single-line Maya command: redirect stdout → file, exec code, restore
            run_cmd = (
                f'exec("import sys\\n'
                f'_f=open(\'{out_file}\',\'w\',encoding=\'utf-8\')\\n'
                f'_o=sys.stdout\\n'
                f'sys.stdout=_f\\n'
                f'try:\\n'
                f'    exec(open(\'{code_file}\',encoding=\'utf-8\').read())\\n'
                f'except Exception as _e:\\n'
                f'    print(str(_e))\\n'
                f'finally:\\n'
                f'    sys.stdout=_o\\n'
                f'    _f.close()")'
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
        # Single-line expression — Maya commandPort returns the last expression value directly.
        # Using shortName=True as primary since it's most reliable.
        code = (
            "import maya.cmds as cmds, json, os; "
            "p=cmds.file(q=True,sn=True) or ''; "
            "s=cmds.file(q=True,sn=True,shortName=True) or ''; "
            "n=os.path.splitext(p.replace(chr(92),'/').split('/')[-1])[0] if p else "
            "(os.path.splitext(s)[0] if s else 'untitled'); "
            "json.dumps({'path':p,'name':n})"
        )
        success, result = _send_maya(code)
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
        code = (
            "import bpy, base64, tempfile, os\n"
            "tmp = tempfile.mktemp(suffix='.png')\n"
            "scene = bpy.context.scene\n"
            "old_path = scene.render.filepath\n"
            "old_fmt = scene.render.image_settings.file_format\n"
            "scene.render.filepath = tmp\n"
            "scene.render.image_settings.file_format = 'PNG'\n"
            "bpy.ops.render.opengl(write_still=True)\n"
            "scene.render.filepath = old_path\n"
            "scene.render.image_settings.file_format = old_fmt\n"
            "if os.path.exists(tmp):\n"
            "    with open(tmp, 'rb') as f:\n"
            "        print(base64.b64encode(f.read()).decode())\n"
            "    os.remove(tmp)\n"
        )
    else:
        return False, f"Unknown DCC: {dcc}"

    success, result = send_code(dcc, code)
    if not success:
        return False, result

    lines = result.strip().splitlines()
    if lines:
        b64 = lines[-1].strip()
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
            "import sys\n"
            "scanner_dir = r'd:/work script/ai doctor/v4'\n"
            "if scanner_dir not in sys.path: sys.path.insert(0, scanner_dir)\n"
            "from scanners import maya_scanner\n"
            "report = maya_scanner.run_scan()\n"
            "prompt = maya_scanner.scan_to_prompt(report)\n"
            "print(prompt)\n"
        )
    elif dcc == "blender":
        code = (
            "import sys, os\n"
            "scanner_dir = r'd:/work script/ai doctor/v4'\n"
            "if scanner_dir not in sys.path: sys.path.insert(0, scanner_dir)\n"
            "from scanners import blender_scanner\n"
            "report = blender_scanner.run_scan()\n"
            "prompt = blender_scanner.scan_to_prompt(report)\n"
            "print('__SCAN_START__')\n"
            "print(prompt)\n"
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
