"""
Central configuration for the podcast automation pipeline.

==========================================================================
 FILL THESE IN  (or set them in a `.env` file next to this repo's README)
==========================================================================
Every value below can be overridden by an environment variable of the same
name, or by a line `NAME=value` in `<repo>/.env`. Environment variables win
over `.env`, and `.env` wins over the defaults written here.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"


def _load_env_file(path):
    """Minimal `.env` parser (no python-dotenv dependency, since Resolve's
    bundled Python may not have it). Supports KEY=value, quotes, # comments."""
    values = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        elif value.startswith("#"):
            value = ""
        else:
            value = value.split(" #", 1)[0].strip()  # inline comment
        values[key] = value
    return values


_ENV_FILE_VALUES = _load_env_file(ENV_FILE)


def _get(name, default):
    if name in os.environ:
        return os.environ[name]
    return _ENV_FILE_VALUES.get(name, default)


def _get_path(name, default):
    path = Path(os.path.expanduser(str(_get(name, default))))
    return path if path.is_absolute() else REPO_ROOT / path


def _get_bool(name, default):
    value = _get(name, None)
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _get_float(name, default):
    return float(_get(name, default))


# --------------------------------------------------------------------------
# 1. FOLDERS  -- TODO: replace with your real paths
# --------------------------------------------------------------------------
# Where the raw recording, intro and thumbnail are dropped before each run.
STAGING_DIR = _get_path("STAGING_DIR", "~/Desktop/Podcast_Staging")

# Root of the archive. Each run creates Archive/YYYY-MM-DD_Title/ inside it.
ARCHIVE_DIR = _get_path("ARCHIVE_DIR", "~/Desktop/Podcast_Archive")

# Where thumbnails are read from. Defaults to the staging folder (spec §3).
THUMBNAIL_DIR = _get_path("THUMBNAIL_DIR", str(STAGING_DIR))

# Where Resolve writes the MP3/MP4 renders. Defaults to the staging folder so
# the archive step sweeps them up together with the raw files.
RENDER_OUTPUT_DIR = _get_path("RENDER_OUTPUT_DIR", str(STAGING_DIR))

# Scratch space for intermediate files (pre-faded audio, WAV->MP3 fallback).
# Contents produced by a run are archived along with everything else.
WORK_DIR = _get_path("WORK_DIR", str(STAGING_DIR / "_work"))

LOG_DIR = _get_path("LOG_DIR", str(REPO_ROOT / "logs"))

# --------------------------------------------------------------------------
# 2. FILE NAMING CONVENTION (spec §3)
# --------------------------------------------------------------------------
LANGUAGES = {
    # UI label -> code used in filenames and API metadata
    "English": {"code": "EN", "iso": "en"},
    "Spanish": {"code": "ES", "iso": "es"},
}
VIDEO_FILENAME = "video_{code}.mp4"
INTRO_FILENAME = "intro_{code}.mp3"
THUMB_FILENAME = "thumb_{code}.jpg"

# --------------------------------------------------------------------------
# 3. EDIT SETTINGS
# --------------------------------------------------------------------------
FADE_IN_SECONDS = _get_float("FADE_IN_SECONDS", 1.0)
FADE_OUT_SECONDS = _get_float("FADE_OUT_SECONDS", 2.0)

# Main programme starts this many seconds before the intro audio ends (spec §5 Phase 2).
INTRO_OVERLAP_SECONDS = _get_float("INTRO_OVERLAP_SECONDS", 1.0)

# Video fade implementation: "fusion" (keyframed Fusion comp) or "none".
VIDEO_FADE_MODE = _get("VIDEO_FADE_MODE", "fusion")
# Audio fade implementation: "ffmpeg" (pre-rendered faded WAV replaces the
# camera audio on A1) or "none". The Resolve API has no audio-fade call.
AUDIO_FADE_MODE = _get("AUDIO_FADE_MODE", "ffmpeg")
FFMPEG_BIN = _get("FFMPEG_BIN", "ffmpeg")

# Resolve project handling: use whatever project is open, or create/load one.
# Leave empty to use the current project.
RESOLVE_PROJECT_NAME = _get("RESOLVE_PROJECT_NAME", "")
TIMELINE_NAME_TEMPLATE = "{date}_{code}_{title}"

# Resolve's AppendToTimeline treats endFrame as inclusive in current versions.
# If your trims come out one frame long/short, flip this.
APPEND_END_FRAME_INCLUSIVE = _get_bool("APPEND_END_FRAME_INCLUSIVE", True)

# --------------------------------------------------------------------------
# 4. RENDER SETTINGS
# --------------------------------------------------------------------------
# Format/codec names as returned by project.GetRenderFormats() /
# project.GetRenderCodecs(format). The renderer also searches the lists
# returned by Resolve, so these only need to be close.
MP3_RENDER_FORMAT = _get("MP3_RENDER_FORMAT", "mp3")
MP3_RENDER_CODEC = _get("MP3_RENDER_CODEC", "mp3")
MP3_AUDIO_BITRATE_KBPS = int(_get("MP3_AUDIO_BITRATE_KBPS", "192"))
# If this Resolve build cannot export MP3 directly, render WAV and transcode
# with ffmpeg instead.
MP3_FALLBACK_VIA_WAV = _get_bool("MP3_FALLBACK_VIA_WAV", True)

MP4_RENDER_FORMAT = _get("MP4_RENDER_FORMAT", "mp4")
MP4_RENDER_CODEC = _get("MP4_RENDER_CODEC", "H264")  # e.g. H264_NVIDIA on NVENC
MP4_AUDIO_CODEC = _get("MP4_AUDIO_CODEC", "aac")

RENDER_POLL_SECONDS = _get_float("RENDER_POLL_SECONDS", 2.0)
RENDER_TIMEOUT_SECONDS = _get_float("RENDER_TIMEOUT_SECONDS", 6 * 3600)

OUTPUT_NAME_TEMPLATE = "{date}_{code}_{title}"

# --------------------------------------------------------------------------
# 5. CUSTOM MP3 ENDPOINT  -- TODO: fill in
# --------------------------------------------------------------------------
CUSTOM_API_ENABLED = _get_bool("CUSTOM_API_ENABLED", True)
CUSTOM_API_URL = _get("CUSTOM_API_URL", "")          # TODO e.g. https://example.com/api/episodes
CUSTOM_API_TOKEN = _get("CUSTOM_API_TOKEN", "")      # TODO bearer token / API key
CUSTOM_API_FILE_FIELD = _get("CUSTOM_API_FILE_FIELD", "file")
CUSTOM_API_TIMEOUT_SECONDS = _get_float("CUSTOM_API_TIMEOUT_SECONDS", 600)

# --------------------------------------------------------------------------
# 6. YOUTUBE  -- TODO: fill in
# --------------------------------------------------------------------------
YOUTUBE_ENABLED = _get_bool("YOUTUBE_ENABLED", True)
# OAuth "Desktop app" client downloaded from Google Cloud Console.
YOUTUBE_CLIENT_SECRETS_FILE = _get_path(
    "YOUTUBE_CLIENT_SECRETS_FILE", str(REPO_ROOT / "credentials" / "client_secret.json"))
# Cached OAuth tokens. One per language so EN/ES can go to different channels;
# point both at the same file to use a single channel.
YOUTUBE_TOKEN_FILES = {
    "EN": _get_path("YOUTUBE_TOKEN_FILE_EN", str(REPO_ROOT / "credentials" / "youtube_token_EN.json")),
    "ES": _get_path("YOUTUBE_TOKEN_FILE_ES", str(REPO_ROOT / "credentials" / "youtube_token_ES.json")),
}
YOUTUBE_PRIVACY_STATUS = "private"  # spec §5 Phase 4 — always private
YOUTUBE_CATEGORY_ID = _get("YOUTUBE_CATEGORY_ID", "22")  # 22 = People & Blogs
YOUTUBE_TAGS = [t.strip() for t in _get("YOUTUBE_TAGS", "").split(",") if t.strip()]
YOUTUBE_MADE_FOR_KIDS = _get_bool("YOUTUBE_MADE_FOR_KIDS", False)

# --------------------------------------------------------------------------
# 7. SAFETY
# --------------------------------------------------------------------------
# When true, uploads are logged instead of sent (renders/archiving still run).
DRY_RUN_UPLOADS = _get_bool("DRY_RUN_UPLOADS", False)
# When false, files stay in staging after a successful run.
ARCHIVE_ENABLED = _get_bool("ARCHIVE_ENABLED", True)


def language_code(label_or_code):
    """Accepts 'English' / 'Spanish' / 'EN' / 'es' and returns 'EN' / 'ES'."""
    value = str(label_or_code).strip()
    for label, info in LANGUAGES.items():
        if value.lower() in (label.lower(), info["code"].lower(), info["iso"].lower()):
            return info["code"]
    raise ValueError("Unknown language: %r" % label_or_code)


def language_iso(code):
    for info in LANGUAGES.values():
        if info["code"] == code:
            return info["iso"]
    raise ValueError("Unknown language code: %r" % code)


def staged_files(code):
    """Expected input paths for a language code (spec §3)."""
    return {
        "video": STAGING_DIR / VIDEO_FILENAME.format(code=code),
        "intro": STAGING_DIR / INTRO_FILENAME.format(code=code),
        "thumb": THUMBNAIL_DIR / THUMB_FILENAME.format(code=code),
    }
