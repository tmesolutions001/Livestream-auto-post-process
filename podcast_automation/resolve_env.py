"""Locating the DaVinci Resolve scripting objects.

Works in both situations:
  * launched from Resolve's Workspace > Scripts menu (Resolve injects
    `resolve` / `bmd` / `fusion` / `app` into the script's globals), and
  * launched externally (`python -m podcast_automation`) while Resolve Studio
    is running with Preferences > System > General > External scripting = Local.
"""

import importlib
import os
import sys

_DEFAULT_MODULE_DIRS = {
    "darwin": "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
    "win32": os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
                          "Blackmagic Design", "DaVinci Resolve", "Support",
                          "Developer", "Scripting", "Modules"),
    "linux": "/opt/resolve/Developer/Scripting/Modules",
}
_DEFAULT_LIBS = {
    "darwin": "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so",
    "win32": r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll",
    "linux": "/opt/resolve/libs/Fusion/fusionscript.so",
}


class ResolveNotAvailable(RuntimeError):
    pass


class ResolveContext(object):
    """Bundle of the handles the rest of the code needs."""

    def __init__(self, resolve, bmd=None, fusion=None):
        self.resolve = resolve
        self.bmd = bmd
        self.fusion = fusion

    @property
    def project_manager(self):
        return self.resolve.GetProjectManager()

    @property
    def ui_manager(self):
        fusion = self.fusion or self.resolve.Fusion()
        if fusion is None:
            return None
        return getattr(fusion, "UIManager", None)

    def ui_dispatcher(self):
        ui = self.ui_manager
        if ui is None or self.bmd is None or not hasattr(self.bmd, "UIDispatcher"):
            return None, None
        return ui, self.bmd.UIDispatcher(ui)


def _platform_key():
    if sys.platform.startswith("win"):
        return "win32"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def _import_dvr_module():
    try:
        return importlib.import_module("DaVinciResolveScript")
    except ImportError:
        pass
    key = _platform_key()
    modules_dir = os.environ.get("RESOLVE_SCRIPT_API")
    modules_dir = os.path.join(modules_dir, "Modules") if modules_dir else _DEFAULT_MODULE_DIRS[key]
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", _DEFAULT_LIBS[key])
    if modules_dir not in sys.path:
        sys.path.append(modules_dir)
    try:
        return importlib.import_module("DaVinciResolveScript")
    except ImportError as exc:
        raise ResolveNotAvailable(
            "Could not import DaVinciResolveScript (looked in %s). Is Resolve Studio "
            "installed and is RESOLVE_SCRIPT_API / RESOLVE_SCRIPT_LIB set?" % modules_dir) from exc


def connect(script_globals=None):
    """Return a ResolveContext, preferring objects injected by Resolve."""
    g = script_globals or {}
    resolve = g.get("resolve")
    bmd = g.get("bmd")
    fusion = g.get("fusion") or g.get("fu")
    app = g.get("app")

    if resolve is None and app is not None and hasattr(app, "GetResolve"):
        resolve = app.GetResolve()
    if resolve is None and bmd is not None and hasattr(bmd, "scriptapp"):
        resolve = bmd.scriptapp("Resolve")

    if resolve is None:
        dvr = _import_dvr_module()
        bmd = bmd or dvr
        resolve = dvr.scriptapp("Resolve")
    elif bmd is None:
        # Only needed for UIDispatcher (the dialog); --no-gui works without it.
        try:
            bmd = _import_dvr_module()
        except ResolveNotAvailable:
            bmd = None

    if resolve is None:
        raise ResolveNotAvailable(
            "DaVinci Resolve is not reachable. Start Resolve Studio and enable "
            "Preferences > System > General > External scripting using: Local.")

    if fusion is None:
        try:
            fusion = resolve.Fusion()
        except Exception:
            fusion = None
    return ResolveContext(resolve, bmd=bmd, fusion=fusion)
