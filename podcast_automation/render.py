"""Render Queue automation (spec §5 Phases 2–3)."""

import logging
import time

from . import audio_prep, config

log = logging.getLogger(__name__)


class RenderError(RuntimeError):
    pass


def _find_key(mapping, wanted):
    """Resolve returns {description: name}. Match `wanted` against either side."""
    wanted_l = wanted.lower().replace(".", "").replace(" ", "")
    for desc, name in (mapping or {}).items():
        for candidate in (name, desc):
            if str(candidate).lower().replace(".", "").replace(" ", "") == wanted_l:
                return name
    return None


def resolve_format_codec(project, fmt, codec):
    """Return (format_name, codec_name) understood by this Resolve build, or (None, None)."""
    formats = project.GetRenderFormats() or {}
    fmt_name = _find_key(formats, fmt) or (fmt if fmt in formats.values() else None)
    if not fmt_name:
        return None, None
    codecs = project.GetRenderCodecs(fmt_name) or {}
    codec_name = _find_key(codecs, codec)
    if not codec_name:
        return fmt_name, None
    return fmt_name, codec_name


class Renderer(object):
    def __init__(self, project, output_dir):
        self.project = project
        self.output_dir = output_dir

    def _wait(self, job_id):
        deadline = time.time() + config.RENDER_TIMEOUT_SECONDS
        last_pct = -1
        while True:
            status = self.project.GetRenderJobStatus(job_id) or {}
            state = status.get("JobStatus", "")
            pct = int(status.get("CompletionPercentage", 0) or 0)
            if pct != last_pct and pct % 10 == 0:
                log.info("  render %s: %s %d%%", job_id, state, pct)
                last_pct = pct
            if state == "Complete":
                return status
            if state in ("Failed", "Cancelled"):
                raise RenderError("Render job %s %s: %s" % (
                    job_id, state.lower(), status.get("Error", "") or "no details"))
            if not self.project.IsRenderingInProgress() and state not in ("Rendering", "Ready", ""):
                raise RenderError("Render job %s stopped in state %r" % (job_id, state))
            if time.time() > deadline:
                self.project.StopRendering()
                raise RenderError("Render job %s timed out" % job_id)
            time.sleep(config.RENDER_POLL_SECONDS)

    def _render(self, timeline, fmt_name, codec_name, settings, base_name, extension,
                optional_settings=None):
        self.project.SetCurrentTimeline(timeline)
        if not self.project.SetCurrentRenderFormatAndCodec(fmt_name, codec_name):
            raise RenderError("Resolve rejected render format %s / codec %s" % (fmt_name, codec_name))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        full = {"SelectAllFrames": True, "TargetDir": str(self.output_dir), "CustomName": base_name}
        full.update(settings)
        if not self.project.SetRenderSettings(full):
            raise RenderError("Resolve rejected render settings %r" % full)
        # Keys whose names vary between Resolve builds: try each, keep going if rejected.
        for key, value in (optional_settings or {}).items():
            if not self.project.SetRenderSettings({key: value}):
                log.info("Render setting %s=%r not supported by this build; using default", key, value)

        job_id = self.project.AddRenderJob()
        if not job_id:
            raise RenderError("AddRenderJob failed")
        log.info("Rendering %s.%s (job %s)", base_name, extension, job_id)
        try:
            if not self.project.StartRendering([job_id], False):
                raise RenderError("StartRendering failed for job %s" % job_id)
            self._wait(job_id)
        finally:
            self.project.DeleteRenderJob(job_id)

        output = self.output_dir / ("%s.%s" % (base_name, extension))
        if not output.is_file() or output.stat().st_size == 0:
            raise RenderError("Render reported complete but %s is missing/empty" % output)
        log.info("Rendered %s (%.1f MB)", output, output.stat().st_size / 1e6)
        return output

    # ------------------------------------------------------------------ MP3
    def render_mp3(self, timeline, base_name):
        audio_settings = {"ExportVideo": False, "ExportAudio": True}
        fmt, codec = resolve_format_codec(self.project, config.MP3_RENDER_FORMAT, config.MP3_RENDER_CODEC)
        if fmt and codec:
            settings = dict(audio_settings, AudioCodec=codec)
            optional = {"AudioBitRate": config.MP3_AUDIO_BITRATE_KBPS}
            return self._render(timeline, fmt, codec, settings, base_name, "mp3", optional)

        if not config.MP3_FALLBACK_VIA_WAV:
            raise RenderError("This Resolve build has no MP3 render format and the WAV fallback is off")
        log.info("No MP3 render format in this Resolve build; rendering WAV and transcoding")
        fmt, codec = resolve_format_codec(self.project, "wav", "LinearPCM")
        if not fmt or not codec:
            raise RenderError("Neither MP3 nor WAV render formats are available")
        wav = self._render(timeline, fmt, codec, dict(audio_settings, AudioCodec=codec),
                           base_name + "_master", "wav")
        mp3 = self.output_dir / ("%s.mp3" % base_name)
        audio_prep.transcode_to_mp3(wav, mp3, config.MP3_AUDIO_BITRATE_KBPS)
        return mp3

    # ------------------------------------------------------------------ MP4
    def render_mp4(self, timeline, base_name):
        fmt, codec = resolve_format_codec(self.project, config.MP4_RENDER_FORMAT, config.MP4_RENDER_CODEC)
        if not fmt or not codec:
            raise RenderError("Render format %s / codec %s not available in this Resolve build"
                              % (config.MP4_RENDER_FORMAT, config.MP4_RENDER_CODEC))
        settings = {"ExportVideo": True, "ExportAudio": True, "AudioCodec": config.MP4_AUDIO_CODEC}
        return self._render(timeline, fmt, codec, settings, base_name, "mp4")
