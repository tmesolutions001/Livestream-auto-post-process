"""End-to-end orchestration of spec §5 Phases 1–5."""

import datetime
import json
import logging

from . import archive, audio_prep, config
from .render import Renderer
from .timeline_builder import EpisodeEditor
from .uploads import custom_api, youtube

log = logging.getLogger(__name__)


class PipelineResult(object):
    def __init__(self):
        self.mp3_path = None
        self.mp4_path = None
        self.youtube_video_id = None
        self.custom_api_response = None
        self.archive_folder = None
        self.errors = []
        self.intermediate_files = []

    @property
    def ok(self):
        return not self.errors

    def summary(self):
        lines = ["SUCCESS" if self.ok else "FINISHED WITH ERRORS", ""]
        lines.append("MP3: %s" % (self.mp3_path or "-"))
        lines.append("MP4: %s" % (self.mp4_path or "-"))
        if self.youtube_video_id:
            lines.append("YouTube (private): https://youtu.be/%s" % self.youtube_video_id)
        if self.archive_folder:
            lines.append("Archived to: %s" % self.archive_folder)
        elif self.mp4_path or self.mp3_path:
            lines.append("Files left in staging (not archived).")
        for err in self.errors:
            lines.append("ERROR: %s" % err)
        return "\n".join(lines)

    def to_dict(self):
        return {k: (str(v) if v is not None and not isinstance(v, (list, dict, bool)) else v)
                for k, v in self.__dict__.items() if k != "intermediate_files"}


def get_project(project_manager):
    name = config.RESOLVE_PROJECT_NAME
    if not name:
        project = project_manager.GetCurrentProject()
        if not project:
            raise RuntimeError("No project is open in Resolve")
        return project
    project = project_manager.LoadProject(name) or project_manager.CreateProject(name)
    if not project:
        raise RuntimeError("Could not load or create Resolve project %r" % name)
    return project


def run(ctx, request, today=None):
    """Execute the whole automation for one EpisodeRequest. Never raises; see result.errors."""
    result = PipelineResult()
    today = today or datetime.date.today()
    code = request.language_code
    files = config.staged_files(code)
    base_name = config.OUTPUT_NAME_TEMPLATE.format(
        date=today.isoformat(), code=code, title=archive.safe_name(request.title))
    timeline_name = config.TIMELINE_NAME_TEMPLATE.format(
        date=today.isoformat(), code=code, title=archive.safe_name(request.title))
    log.info("=== Podcast automation: %r ===", request)

    editor = None
    try:
        project_manager = ctx.project_manager
        project = get_project(project_manager)
        editor = EpisodeEditor(project, request, files)
        renderer = Renderer(project, config.RENDER_OUTPUT_DIR)

        # ---------------- Phase 1: media setup & trimming
        log.info("--- Phase 1: media setup & trimming")
        editor.import_media(bin_name=timeline_name)
        trim_start, trim_end = editor.compute_trim()

        if config.AUDIO_FADE_MODE == "ffmpeg":
            faded = config.WORK_DIR / ("%s_programme_audio.wav" % base_name)
            audio_prep.render_faded_segment(
                files["video"], faded,
                start_seconds=trim_start / editor.source_fps,
                duration_seconds=(trim_end - trim_start) / editor.source_fps,
                fade_in_seconds=config.FADE_IN_SECONDS,
                fade_out_seconds=config.FADE_OUT_SECONDS)
            result.intermediate_files.append(faded)
            editor.import_faded_audio(faded)
        elif config.AUDIO_FADE_MODE != "none":
            raise ValueError("Unknown AUDIO_FADE_MODE %r" % config.AUDIO_FADE_MODE)

        timeline = editor.create_timeline(timeline_name)
        editor.place_main(0, with_video_fade=True)

        # ---------------- Phase 2: MP3 with intro overlap
        log.info("--- Phase 2: MP3 render")
        # Video isn't exported in the MP3, so skip the (slow) Fusion fade here.
        editor.place_intro_with_overlap(with_video_fade=False)
        result.mp3_path = renderer.render_mp3(timeline, base_name)
        if renderer.output_dir.joinpath(base_name + "_master.wav").exists():
            result.intermediate_files.append(renderer.output_dir / (base_name + "_master.wav"))

        # ---------------- Phase 3: MP4
        log.info("--- Phase 3: MP4 render")
        editor.remove_intro()
        editor.place_main(0, with_video_fade=True)
        result.mp4_path = renderer.render_mp4(timeline, base_name)

        project_manager.SaveProject()
    except Exception as exc:
        log.exception("Edit/render failed")
        result.errors.append("Edit/render: %s" % exc)
        return result

    # ---------------- Phase 4: uploads (both attempted even if one fails)
    log.info("--- Phase 4: uploads")
    try:
        result.custom_api_response = custom_api.upload_mp3(
            result.mp3_path, request.title, request.description, code)
    except Exception as exc:
        log.exception("MP3 upload failed")
        result.errors.append("MP3 upload: %s" % exc)
    try:
        result.youtube_video_id = youtube.upload_video(
            result.mp4_path, files["thumb"], request.title, request.description, code)
    except Exception as exc:
        log.exception("YouTube upload failed")
        result.errors.append("YouTube upload: %s" % exc)

    # ---------------- Phase 5: cleanup & archiving
    if not result.ok:
        log.warning("Not archiving because of earlier errors; staging left untouched.")
        return result
    if not config.ARCHIVE_ENABLED:
        log.info("Archiving disabled (ARCHIVE_ENABLED=false)")
        return result

    log.info("--- Phase 5: archiving")
    try:
        to_move = [files["video"], files["intro"], files["thumb"],
                   result.mp3_path, result.mp4_path] + result.intermediate_files
        folder, _ = archive.archive_files(to_move, config.ARCHIVE_DIR, request.title, today)
        result.archive_folder = folder
        archive.remove_if_empty(config.WORK_DIR)
        if editor is not None:
            editor.relink_to(folder)
            ctx.project_manager.SaveProject()
        (folder / "run_summary.json").write_text(
            json.dumps(dict(result.to_dict(), title=request.title, language=code,
                            start=request.start, end=request.end), indent=2),
            encoding="utf-8")
    except Exception as exc:
        log.exception("Archiving failed")
        result.errors.append("Archive: %s" % exc)
    return result
