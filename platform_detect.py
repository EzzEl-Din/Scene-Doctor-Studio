"""
platform_detect.py — Scene Doctor Studio

Auto-detects the current DCC and resolves scanner modules.
Scanner resolution order:
    1. User-installed plugin in ~/Documents/SceneDoctor/plugins/{platform}/scanner.py
    2. Bundled fallback in ./scanners/{platform}_scanner.py (Maya / Blender only)

Named platform_detect.py to avoid clashing with Python's built-in `platform`.

Built by Ezz El-Din
"""

from plugin_manager import PluginManager

_plugin_manager = PluginManager()


def detect_platform():
    """Returns: 'maya', 'blender', or 'unknown'."""
    try:
        import maya.cmds  # noqa: F401
        return "maya"
    except ImportError:
        pass
    try:
        import bpy  # noqa: F401
        return "blender"
    except ImportError:
        pass
    return "unknown"


def get_scene_name(platform):
    """Returns the current scene file name for chat history key."""
    if platform == "maya":
        import maya.cmds as cmds
        return cmds.file(query=True, sceneName=True) or "untitled"
    elif platform == "blender":
        import bpy
        return bpy.data.filepath or "untitled"
    return "untitled"


def get_scanner(platform):
    """Returns the scanner module for a platform.
    Tries the installed plugin first, then falls back to bundled scanners.
    """
    module = _plugin_manager.load_scanner(platform)
    if module is not None:
        return module

    # Bundled fallback for the two built-ins
    if platform == "maya":
        try:
            from scanners import maya_scanner
            return maya_scanner
        except ImportError:
            return None
    if platform == "blender":
        try:
            from scanners import blender_scanner
            return blender_scanner
        except ImportError:
            return None
    return None


def get_system_prompt_prefix(platform):
    """Returns DCC-specific prefix for all agent prompts."""
    if platform == "maya":
        return (
            "You are working inside Autodesk Maya. "
            "Use maya.cmds for all scene operations. "
            "Never use bpy or any other DCC API.\n\n"
        )
    elif platform == "blender":
        return (
            "You are working inside Blender. "
            "Use bpy for all scene operations. "
            "Never use maya.cmds or any other DCC API.\n\n"
        )
    return ""


BLENDER_CODEWRITER_RULES = """
BLENDER PYTHON — CRITICAL RULES:

1. ALWAYS use Blender's built-in operators — NEVER calculate geometry manually:

   CORRECT — use operators:
   bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(0,0,0))
   bpy.ops.mesh.primitive_cube_add(size=2, location=(0,0,0))
   bpy.ops.mesh.primitive_cylinder_add(radius=1, depth=2)
   bpy.ops.mesh.primitive_plane_add(size=2)

   WRONG — never do this:
   verts = []
   edges = []
   faces = []
   # manually calculating vertices with math

2. NEVER import math or mathutils unless absolutely necessary.
   For colors, use simple RGB tuples — no math:

   CORRECT — red material:
   mat = bpy.data.materials.new(name="RedMaterial")
   mat.use_nodes = True
   bsdf = mat.node_tree.nodes["Principled BSDF"]
   bsdf.inputs["Base Color"].default_value = (1, 0, 0, 1)  # R,G,B,A

   WRONG:
   import mathutils
   color = mathutils.Color()

3. To assign material to object:
   if obj.data.materials:
       obj.data.materials[0] = mat
   else:
       obj.data.materials.append(mat)

4. To link object to scene:
   bpy.context.collection.objects.link(obj)
   bpy.context.view_layer.objects.active = obj

5. ONE complete self-contained scene-run block only.
   Import bpy at the top. Never split into multiple blocks.
"""


def get_codewriter_prompt_prefix(platform):
    """Returns DCC-specific prefix specifically for the Code Writer agent."""
    if platform == "maya":
        return (
            "You are writing Maya Python code using maya.cmds.\n"
            "Always import maya.cmds as cmds at the top.\n"
            "For code blocks use ```maya-run.\n"
            "Never use bpy.\n\n"
        )
    elif platform == "blender":
        return BLENDER_CODEWRITER_RULES
    return ""
