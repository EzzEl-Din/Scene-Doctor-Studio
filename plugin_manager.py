"""
plugin_manager.py — Scene Doctor Studio

GitHub-backed plugin registry. Users install only the DCCs they need.
Local plugin storage lives outside the app folder so reinstalls / updates
of Scene Doctor itself don't wipe user-installed plugins.

Layout:
    ~/Documents/SceneDoctor/plugins/
        maya/
            plugin.json
            scanner.py
        blender/
            plugin.json
            scanner.py
        installed.json   ← list of installed plugin IDs

Built by Ezz El-Din
"""

import urllib.request
import json
import os
import shutil


PLUGINS_DIR = os.path.join(
    os.path.expanduser("~"), "Documents", "SceneDoctor", "plugins"
)
REGISTRY_URL = (
    "https://raw.githubusercontent.com/EzzEl-Din/Scene-Doctor-Studio/"
    "main/plugins/registry.json"
)
BASE_URL = (
    "https://raw.githubusercontent.com/EzzEl-Din/Scene-Doctor-Studio/"
    "main/plugins"
)
INSTALLED_FILE = os.path.join(PLUGINS_DIR, "installed.json")

# Bundled fallback metadata — used when offline so the store still renders
# something for Maya/Blender (scanners are also bundled in `scanners/`).
_BUILTIN_FALLBACK = {
    "maya": {
        "id": "maya",
        "name": "Maya",
        "version": "1.0.0",
        "description": "Autodesk Maya — scene scanning, rigging, rendering",
        "color": "#5a8fc4",
        "port": 7001,
        "files": ["scanner.py"],
        "coming_soon": False,
    },
    "blender": {
        "id": "blender",
        "name": "Blender",
        "version": "1.0.0",
        "description": "Blender 3D — scene scanning, materials, modifiers",
        "color": "#f97316",
        "port": 7002,
        "files": ["scanner.py"],
        "coming_soon": False,
    },
}


def _ensure_plugins_dir():
    try:
        os.makedirs(PLUGINS_DIR, exist_ok=True)
    except Exception:
        pass


class PluginManager:
    """Install / uninstall / update DCC plugins from the GitHub registry."""

    # ------------------------------------------------------------------
    # Local state
    # ------------------------------------------------------------------
    def get_installed(self):
        """Return list of installed plugin IDs.
        First call ever seeds the built-in plugins (maya, blender) so the
        store can show Remove / Update for them right away.
        """
        self._ensure_builtins_seeded()
        if not os.path.exists(INSTALLED_FILE):
            return []
        try:
            with open(INSTALLED_FILE, 'r', encoding='utf-8') as f:
                return json.load(f).get("installed", [])
        except Exception:
            return []

    def _write_installed(self, installed):
        _ensure_plugins_dir()
        try:
            with open(INSTALLED_FILE, 'w', encoding='utf-8') as f:
                json.dump(
                    {"installed": installed, "last_updated": ""},
                    f, indent=2, ensure_ascii=False,
                )
        except Exception:
            pass

    def _ensure_builtins_seeded(self):
        """One-time seeding so Maya/Blender appear as installed even before
        the user opens the store. Writes plugin.json from the built-in
        fallback so per-plugin versions render correctly. Idempotent.
        """
        if os.path.exists(INSTALLED_FILE):
            return
        _ensure_plugins_dir()
        seeded = []
        for pid, manifest in _BUILTIN_FALLBACK.items():
            plugin_dir = os.path.join(PLUGINS_DIR, pid)
            try:
                os.makedirs(plugin_dir, exist_ok=True)
                manifest_path = os.path.join(plugin_dir, "plugin.json")
                if not os.path.exists(manifest_path):
                    with open(manifest_path, 'w', encoding='utf-8') as f:
                        json.dump(manifest, f, indent=2, ensure_ascii=False)
                seeded.append(pid)
            except Exception:
                continue
        if seeded:
            self._write_installed(seeded)

    # ------------------------------------------------------------------
    # Remote registry
    # ------------------------------------------------------------------
    def fetch_registry(self):
        """Fetch available plugin IDs from GitHub. Returns [] on failure."""
        try:
            with urllib.request.urlopen(REGISTRY_URL, timeout=10) as r:
                data = json.loads(r.read())
                return list(data.get("plugins", []))
        except Exception:
            return []

    def fetch_plugin_manifest(self, plugin_id):
        """Fetch plugin.json from GitHub. Returns None on failure."""
        url = f"{BASE_URL}/{plugin_id}/plugin.json"
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                return json.loads(r.read())
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Install / uninstall / update
    # ------------------------------------------------------------------
    def install(self, plugin_id, progress_callback=None):
        """Download plugin files from GitHub into the local plugins folder.
        Returns (success: bool, message: str).
        progress_callback(message) is invoked for UI updates.
        """
        manifest = self.fetch_plugin_manifest(plugin_id)
        if not manifest:
            return False, "Could not fetch plugin manifest"

        _ensure_plugins_dir()
        plugin_dir = os.path.join(PLUGINS_DIR, plugin_id)
        os.makedirs(plugin_dir, exist_ok=True)

        # Save manifest locally
        try:
            with open(os.path.join(plugin_dir, "plugin.json"),
                      'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
        except Exception as e:
            return False, f"Could not save manifest: {e}"

        # Download each file listed in the manifest
        for filename in manifest.get("files", []):
            if progress_callback:
                try:
                    progress_callback(f"Downloading {filename}...")
                except Exception:
                    pass

            url = f"{BASE_URL}/{plugin_id}/{filename}"
            dest = os.path.join(plugin_dir, filename)
            os.makedirs(os.path.dirname(dest) or plugin_dir, exist_ok=True)

            try:
                urllib.request.urlretrieve(url, dest)
            except Exception as e:
                return False, f"Failed to download {filename}: {e}"

        # Mark as installed
        installed = self.get_installed()
        if plugin_id not in installed:
            installed.append(plugin_id)
        self._write_installed(installed)

        return True, f"{manifest.get('name', plugin_id)} installed successfully"

    def uninstall(self, plugin_id):
        """Remove plugin files and unregister it. Session history is kept."""
        plugin_dir = os.path.join(PLUGINS_DIR, plugin_id)
        if os.path.exists(plugin_dir):
            try:
                shutil.rmtree(plugin_dir)
            except Exception as e:
                return False, f"Could not remove files: {e}"

        installed = self.get_installed()
        if plugin_id in installed:
            installed.remove(plugin_id)
            self._write_installed(installed)

        return True, "Plugin uninstalled"

    def update(self, plugin_id, progress_callback=None):
        """Re-download all files for a plugin. Triggers uninstall + install."""
        self.uninstall(plugin_id)
        return self.install(plugin_id, progress_callback)

    # ------------------------------------------------------------------
    # Local manifest / scanner helpers
    # ------------------------------------------------------------------
    def get_local_manifest(self, plugin_id):
        """Read local plugin.json. Returns None if not installed."""
        path = os.path.join(PLUGINS_DIR, plugin_id, "plugin.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def get_scanner_path(self, plugin_id):
        """Return path to scanner.py for an installed plugin."""
        return os.path.join(PLUGINS_DIR, plugin_id, "scanner.py")

    def load_scanner(self, plugin_id):
        """Dynamically import the scanner module for an installed plugin.
        Returns the module, or None if not installed / fails to load.
        """
        import importlib.util
        scanner_path = self.get_scanner_path(plugin_id)
        if not os.path.exists(scanner_path):
            return None
        try:
            spec = importlib.util.spec_from_file_location(
                f"{plugin_id}_scanner", scanner_path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Convenience for UI
    # ------------------------------------------------------------------
    def fallback_manifest(self, plugin_id):
        """Return a built-in manifest if the registry can't be reached.
        Lets the store render Maya/Blender even when offline.
        """
        return _BUILTIN_FALLBACK.get(plugin_id)
