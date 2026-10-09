"""ffmpeg helpers.

The Resolve scripting API cannot create audio fades, so the trimmed segment of
the programme audio is pre-rendered with the fades baked in and placed on A1
in place of the camera audio. Because the WAV starts at exactly the trimmed
start frame and is exactly as long as the trimmed video, it stays in sync and
the fades land correctly in both the MP3 (with intro overlap) and the MP4.
"""

import logging
import os
import shutil
import subprocess

from . import config

log = logging.getLogger(__name__)


class FFmpegError(RuntimeError):
    pass


def ffmpeg_path():
    path = shutil.which(config.FFMPEG_BIN)
    if not path and os.path.isfile(config.FFMPEG_BIN):
        path = config.FFMPEG_BIN
    if not path:
        raise FFmpegError(
            "ffmpeg not found (FFMPEG_BIN=%r). Install ffmpeg or set AUDIO_FADE_MODE=none."
            % config.FFMPEG_BIN)
    return path


def _run(args):
    log.debug("ffmpeg: %s", " ".join(str(a) for a in args))
    proc = subprocess.run([str(a) for a in args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace")[-2000:]
        raise FFmpegError("ffmpeg failed (exit %d):\n%s" % (proc.returncode, tail))


def render_faded_segment(source, dest, start_seconds, duration_seconds,
                         fade_in_seconds, fade_out_seconds, sample_rate=48000):
    """Extract [start, start+duration) of `source`'s audio to a 24-bit WAV with fades."""
    fade_in = max(0.0, min(fade_in_seconds, duration_seconds / 2.0))
    fade_out = max(0.0, min(fade_out_seconds, duration_seconds / 2.0))
    filters = []
    if fade_in > 0:
        filters.append("afade=t=in:st=0:d=%.6f" % fade_in)
    if fade_out > 0:
        filters.append("afade=t=out:st=%.6f:d=%.6f" % (duration_seconds - fade_out, fade_out))
    args = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
            # -ss before -i: fast seek; ffmpeg's input seeking is sample-accurate for audio.
            "-ss", "%.6f" % start_seconds, "-i", source,
            "-t", "%.6f" % duration_seconds, "-vn", "-map", "0:a:0"]
    if filters:
        args += ["-af", ",".join(filters)]
    args += ["-ar", str(sample_rate), "-c:a", "pcm_s24le", dest]
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(args)
    if not dest.is_file() or dest.stat().st_size == 0:
        raise FFmpegError("ffmpeg produced no output at %s" % dest)
    return dest


def transcode_to_mp3(source, dest, bitrate_kbps):
    args = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-i", source,
            "-vn", "-c:a", "libmp3lame", "-b:a", "%dk" % bitrate_kbps, dest]
    _run(args)
    if not dest.is_file() or dest.stat().st_size == 0:
        raise FFmpegError("ffmpeg produced no MP3 at %s" % dest)
    return dest
