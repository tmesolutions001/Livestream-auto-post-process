"""Launcher for DaVinci Resolve's Workspace > Scripts menu.

Copy this file into Resolve's Utility scripts folder:
  macOS:   ~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/
  Windows: %APPDATA%\\Blackmagic Design\\DaVinci Resolve\\Support\\Fusion\\Scripts\\Utility\\
  Linux:   ~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/
then set PROJECT_DIR below to wherever this repository lives.
"""

import os
import sys

# TODO: set this to the folder that contains `podcast_automation/`.
PROJECT_DIR = r"/path/to/Livestream-auto-post-process"

if not os.path.isdir(os.path.join(PROJECT_DIR, "podcast_automation")):
    # Fallback: running straight from the repo checkout.
    try:
        PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        pass
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from podcast_automation.entry import main  # noqa: E402

main(script_globals=globals(), argv=[])
