"""
blender_scanner.py — Scene Doctor AI
Collects scene data from Blender using bpy.

Built by Ezz El-Din | LinkedIn: https://www.linkedin.com/in/ezzel-din-tarek-mostafa
"""
import bpy
import os


def scan_meshes():
    meshes = [obj for obj in bpy.data.objects if obj.type == 'MESH']
    issues = []
    data = []

    for obj in meshes:
        mesh_issues = []

        # Default names
        if obj.name.startswith(("Cube", "Sphere", "Cylinder", "Plane", "Torus")):
            mesh_issues.append("default name — rename before production")
            issues.append({"object": obj.name, "issue": "default name"})

        # No material
        if not obj.data.materials:
            mesh_issues.append("no material assigned")
            issues.append({"object": obj.name, "issue": "no material"})

        # Hidden
        if obj.hide_viewport:
            mesh_issues.append("hidden in viewport")

        data.append({
            "name": obj.name,
            "vertices": len(obj.data.vertices),
            "faces": len(obj.data.polygons),
            "materials": [m.name for m in obj.data.materials if m],
            "visible": not obj.hide_viewport,
            "issues": mesh_issues,
        })

    return {"meshes": data, "total": len(data), "issues": issues}


def scan_materials():
    materials = bpy.data.materials
    issues = []
    data = []

    for mat in materials:
        mat_issues = []

        # No users
        if mat.users == 0:
            mat_issues.append("unused material")
            issues.append({"material": mat.name, "issue": "no users"})

        # No nodes
        if not mat.use_nodes:
            mat_issues.append("not using nodes")

        data.append({
            "name": mat.name,
            "users": mat.users,
            "use_nodes": mat.use_nodes,
            "issues": mat_issues,
        })

    return {"materials": data, "total": len(data), "issues": issues}


def scan_lights():
    lights = [obj for obj in bpy.data.objects if obj.type == 'LIGHT']
    issues = []
    data = []

    for obj in lights:
        light = obj.data
        light_issues = []

        if light.energy == 0:
            light_issues.append("energy is 0 — no effect")
            issues.append({"light": obj.name, "issue": "energy is 0"})

        if obj.hide_viewport:
            light_issues.append("hidden in viewport")

        data.append({
            "name": obj.name,
            "type": light.type,
            "energy": light.energy,
            "color": list(light.color),
            "visible": not obj.hide_viewport,
            "issues": light_issues,
        })

    return {"lights": data, "total": len(data), "issues": issues}


def scan_cameras():
    cameras = [obj for obj in bpy.data.objects if obj.type == 'CAMERA']
    issues = []
    data = []

    for obj in cameras:
        cam = obj.data
        cam_issues = []

        # Check if it's the active camera
        is_active = bpy.context.scene.camera == obj

        data.append({
            "name": obj.name,
            "lens": cam.lens,
            "clip_start": cam.clip_start,
            "clip_end": cam.clip_end,
            "is_active": is_active,
            "issues": cam_issues,
        })

    if not any(d["is_active"] for d in data) and data:
        issues.append({"issue": "no active render camera set"})

    return {"cameras": data, "total": len(data), "issues": issues}


def scan_scene_info():
    scene = bpy.context.scene
    return {
        "name": scene.name,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "fps": scene.render.fps,
        "renderer": scene.render.engine,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
    }


def run_scan():
    return {
        "platform": "blender",
        "scene_info": scan_scene_info(),
        "meshes": scan_meshes(),
        "materials": scan_materials(),
        "lights": scan_lights(),
        "cameras": scan_cameras(),
    }


def scan_to_prompt(scan_data=None):
    """Convert scan data to a text prompt for the AI."""
    if scan_data is None:
        scan_data = run_scan()

    lines = []
    lines.append("=== BLENDER SCENE DIAGNOSTIC REPORT ===\n")

    # Scene info
    info = scan_data.get("scene_info", {})
    lines.append("Scene: {}".format(info.get("name", "untitled")))
    lines.append("Renderer: {}".format(info.get("renderer", "unknown")))
    lines.append("Resolution: {}".format(info.get("resolution", [0, 0])))
    lines.append("Frame Range: {} - {}\n".format(
        info.get("frame_start"), info.get("frame_end")))

    # Meshes
    mesh_data = scan_data.get("meshes", {})
    lines.append("### Meshes ({} total)".format(mesh_data.get("total", 0)))
    for m in mesh_data.get("meshes", []):
        flag_parts = []
        if m.get("issues"):
            flag_parts = m["issues"]
        flag_str = "  ⚠ " + " | ".join(flag_parts) if flag_parts else "  ✓ clean"
        lines.append("- `{}` — {} verts, {} faces{}".format(
            m["name"], m["vertices"], m["faces"], flag_str))
    for issue in mesh_data.get("issues", []):
        lines.append("  ⚠ {} → {}".format(issue["object"], issue["issue"]))
    lines.append("")

    # Materials
    mat_data = scan_data.get("materials", {})
    lines.append("### Materials ({} total)".format(mat_data.get("total", 0)))
    for issue in mat_data.get("issues", []):
        lines.append("  ⚠ {} → {}".format(issue["material"], issue["issue"]))
    lines.append("")

    # Lights
    light_data = scan_data.get("lights", {})
    lines.append("### Lights ({} total)".format(light_data.get("total", 0)))
    for lt in light_data.get("lights", []):
        issue_str = ""
        if lt.get("issues"):
            issue_str = "  ⚠ " + " | ".join(lt["issues"])
        else:
            issue_str = "  ✓ ok"
        lines.append("- `{}` — type: {} | energy: {} | visible: {}{}".format(
            lt["name"], lt["type"], lt["energy"], lt["visible"], issue_str))
    for issue in light_data.get("issues", []):
        lines.append("  ⚠ {} → {}".format(issue["light"], issue["issue"]))
    lines.append("")

    # Cameras
    cam_data = scan_data.get("cameras", {})
    lines.append("### Cameras ({} total)".format(cam_data.get("total", 0)))
    for cam in cam_data.get("cameras", []):
        active_str = "active" if cam["is_active"] else "NOT active"
        lines.append("- `{}` — lens: {} | clip: {} – {} | {}".format(
            cam["name"], cam["lens"], cam["clip_start"],
            cam["clip_end"], active_str))
    for issue in cam_data.get("issues", []):
        lines.append("  ⚠ {}".format(issue["issue"]))

    lines.append("\n=== END OF REPORT ===")
    lines.append("")
    lines.append(
        "Please analyse this scene, identify all problems, prioritise them "
        "by severity (Critical / Warning / Info), suggest fixes for each, "
        "and give an overall scene health score out of 10."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Standalone test — run inside Blender's Python console to verify
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    report = run_scan()
    prompt = scan_to_prompt(report)
    print(prompt)
