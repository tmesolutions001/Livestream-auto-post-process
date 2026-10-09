import logging
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from podcast_automation import config

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def make_media(staging, code="EN", video_seconds=20, intro_seconds=5, fps=30):
    """Generate small real media files following the staging naming convention."""
    staging.mkdir(parents=True, exist_ok=True)
    video = staging / config.VIDEO_FILENAME.format(code=code)
    intro = staging / config.INTRO_FILENAME.format(code=code)
    thumb = staging / config.THUMB_FILENAME.format(code=code)
    run = lambda *a: subprocess.run(["ffmpeg", "-v", "error", "-y"] + list(a), check=True)
    run("-f", "lavfi", "-i", "testsrc=size=160x90:rate=%d:duration=%d" % (fps, video_seconds),
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=%d:sample_rate=48000" % video_seconds,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video))
    run("-f", "lavfi", "-i", "sine=frequency=300:duration=%d" % intro_seconds,
        "-c:a", "libmp3lame", str(intro))
    run("-f", "lavfi", "-i", "color=c=blue:size=128x72", "-frames:v", "1", str(thumb))
    return {"video": video, "intro": intro, "thumb": thumb}


class ConfigSandbox(unittest.TestCase):
    """Points every configured folder at a temp dir and restores config afterwards."""

    OVERRIDES = {}

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.staging = self.tmp / "staging"
        self.staging.mkdir()
        values = {
            "STAGING_DIR": self.staging,
            "THUMBNAIL_DIR": self.staging,
            "RENDER_OUTPUT_DIR": self.staging,
            "WORK_DIR": self.staging / "_work",
            "ARCHIVE_DIR": self.tmp / "archive",
            "LOG_DIR": self.tmp / "logs",
            "DRY_RUN_UPLOADS": True,
            "RENDER_POLL_SECONDS": 0.0,
        }
        values.update(self.OVERRIDES)
        self._saved = {k: getattr(config, k) for k in values}
        for k, v in values.items():
            setattr(config, k, v)

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(config, k, v)
        self._tmp.cleanup()

    def set_config(self, **values):
        for k, v in values.items():
            self._saved.setdefault(k, getattr(config, k))
            setattr(config, k, v)
