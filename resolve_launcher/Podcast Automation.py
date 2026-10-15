"""Launcher for DaVinci Resolve's Workspace > Scripts menu.

Copy this file into Resolve's Utility scripts folder:
  macOS:   ~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/
  Windows: %APPDATA%\\Blackmagic Design\\DaVinci Resolve\\Support\\Fusion\\Scripts\\Utility\\
  Linux:   ~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/
then set PROJECT_DIR below to wherever this repository lives.

If clicking the menu item seems to do nothing, open the diagnostic log this
launcher writes to your home folder: podcast_automation_launcher.log
"""

import datetime
import os
import sys
import traceback

# TODO: set this to the folder that contains `podcast_automation/`.
PROJECT_DIR = r"/path/to/Livestream-auto-post-process"

LAUNCHER_LOG = os.path.join(os.path.expanduser("~"), "podcast_automation_launcher.log")


def _log(message):
    print(message)
    try:
        with open(LAUNCHER_LOG, "a") as fh:
            fh.write(message + "\n")
    except Exception:
        pass


def _show_error(text):
    """Show the error in a Resolve window so failures are never silent."""
    try:
        g = globals()
        fusion = g.get("fusion") or g.get("fu")
        if fusion is None and g.get("resolve") is not None:
            fusion = g["resolve"].Fusion()
        bmd_mod = g.get("bmd")
        if bmd_mod is None:
            import DaVinciResolveScript as bmd_mod  # noqa: N813
        ui = fusion.UIManager
        disp = bmd_mod.UIDispatcher(ui)
        win = disp.AddWindow(
            {"ID": "PodcastLauncherError", "WindowTitle": "Podcast Automation - error",
             "Geometry": [200, 200, 720, 420]},
            ui.VGroup([
                ui.TextEdit({"ID": "Body", "Text": text, "ReadOnly": True}),
                ui.HGroup({"Weight": 0}, [ui.HGap(0, 1), ui.Button({"ID": "OkBtn", "Text": "OK"})]),
            ]))

        def close(ev):
            disp.ExitLoop()

        win.On.PodcastLauncherError.Close = close
        win.On.OkBtn.Clicked = close
        win.Show()
        disp.RunLoop()
        win.Hide()
    except Exception:
        _log("(could not open error window: %s)" % traceback.format_exc())


def _find_project_dir():
    candidates = [PROJECT_DIR, os.environ.get("PODCAST_AUTOMATION_HOME", "")]
    try:
        candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    except NameError:
        pass
    for path in candidates:
        if path and os.path.isdir(os.path.join(path, "podcast_automation")):
            return path
    return None


def _launch():
    _log("\n=== %s  Podcast Automation launcher ===" % datetime.datetime.now().isoformat(" ", "seconds"))
    _log("Python %s at %s" % (sys.version.split()[0], sys.executable))
    _log("Resolve globals present: %s" % sorted(
        k for k in ("resolve", "bmd", "fusion", "fu", "app") if globals().get(k) is not None))

    project_dir = _find_project_dir()
    if project_dir is None:
        raise RuntimeError(
            "Could not find the 'podcast_automation' folder.\n\n"
            "Open this launcher file in a text editor and set PROJECT_DIR to the folder "
            "you cloned the repository into (the one that contains 'podcast_automation').\n\n"
            "Currently PROJECT_DIR = %r\nLauncher file: %s" % (PROJECT_DIR, globals().get("__file__", "?")))
    _log("Using PROJECT_DIR = %s" % project_dir)
    if project_dir not in sys.path:
        sys.path.insert(0, project_dir)

    # Pick up code changes (git pull) without restarting Resolve, which keeps
    # one Python interpreter alive between script runs.
    for name in [m for m in sys.modules if m == "podcast_automation" or m.startswith("podcast_automation.")]:
        del sys.modules[name]

    from podcast_automation.entry import main
    code = main(script_globals=globals(), argv=[])
    _log("Finished with exit code %s" % code)
    if code == 2:  # stopped before the run started (e.g. no UIManager); reason is in the log
        _show_error("The automation could not start. Details are in the newest file in:\n%s"
                    % os.path.join(project_dir, "logs"))


try:
    _launch()
except SystemExit:
    pass
except Exception:
    details = traceback.format_exc()
    _log(details)
    _show_error("The automation stopped with an error:\n\n%s\nA copy is in:\n%s" % (details, LAUNCHER_LOG))
