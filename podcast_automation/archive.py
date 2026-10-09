"""Post-run archiving (spec §5 Phase 5)."""

import datetime
import logging
import re
import shutil
from pathlib import Path

log = logging.getLogger(__name__)


def safe_name(text, max_len=60):
    """Make a title safe for a folder/file name on Windows and macOS."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text).strip()
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._")
    return (cleaned[:max_len].rstrip("._") or "untitled")


def archive_folder_for(archive_root, title, today=None):
    """Archive/YYYY-MM-DD_Title/, with _2, _3... appended if it already exists."""
    today = today or datetime.date.today()
    base = Path(archive_root) / ("%s_%s" % (today.isoformat(), safe_name(title)))
    folder, n = base, 2
    while folder.exists():
        folder = base.with_name("%s_%d" % (base.name, n))
        n += 1
    return folder


def archive_files(paths, archive_root, title, today=None):
    """Move every existing path in `paths` into a new archive folder. Returns (folder, moved)."""
    folder = archive_folder_for(archive_root, title, today)
    folder.mkdir(parents=True)
    moved = []
    for src in paths:
        src = Path(src)
        if not src.exists():
            log.warning("Archive: %s does not exist, skipping", src)
            continue
        dest = folder / src.name
        if dest.exists():
            dest = folder / ("%s_%s%s" % (src.stem, len(moved), src.suffix))
        shutil.move(str(src), str(dest))
        moved.append(dest)
        log.info("Archived %s -> %s", src.name, dest)
    return folder, moved


def remove_if_empty(folder):
    folder = Path(folder)
    try:
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    except OSError:
        pass
