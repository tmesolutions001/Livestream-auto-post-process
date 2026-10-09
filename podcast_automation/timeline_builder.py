"""Media Pool / Timeline manipulation (spec §5 Phases 1–3).

API notes that shape this module:
  * There is no "blade" or "move clip" call. Trimming is done by appending
    only the [start, end) source range (identical to splitting at both
    timestamps and deleting the outside pieces). Moving a clip is done by
    deleting it and re-appending it at a new recordFrame.
  * Clip positions are absolute timeline frames, so the timeline start
    timecode is forced to 00:00:00:00 and every placement is offset from
    timeline.GetStartFrame().
"""

import logging

from . import config, fades
from .timecode import (fps_to_resolve_setting, frames_to_display, parse_fps,
                       resolve_trim, seconds_to_frames, timecode_to_frames)

log = logging.getLogger(__name__)

VIDEO_ONLY = 1
AUDIO_ONLY = 2
MAIN_TRACK = 1
INTRO_TRACK = 2


class EditError(RuntimeError):
    pass


def _clip_fps(item, default=None):
    value = item.GetClipProperty("FPS")
    try:
        return parse_fps(value)
    except ValueError:
        if default is None:
            raise EditError("Could not read the frame rate of %s" % item.GetName())
        return default


def _clip_frames(item, fps):
    """Clip length in frames, from 'Frames' or failing that 'Duration'."""
    frames = item.GetClipProperty("Frames")
    try:
        if frames not in (None, ""):
            return int(float(frames))
    except ValueError:
        pass
    duration = item.GetClipProperty("Duration")
    if duration:
        try:
            return timecode_to_frames(duration, fps)
        except ValueError:
            pass
    return None


class EpisodeEditor(object):
    def __init__(self, project, request, files, faded_audio_path=None):
        self.project = project
        self.media_pool = project.GetMediaPool()
        self.request = request
        self.files = files
        self.faded_audio_path = faded_audio_path

        self.timeline = None
        self.video_item = None
        self.intro_item = None
        self.faded_audio_item = None

        self.source_fps = None
        self.timeline_fps = None
        self.source_frames = None
        self.trim_start = None   # source frames, inclusive
        self.trim_end = None     # source frames, exclusive
        self.main_duration = None  # timeline frames

        self.main_clips = []     # TimelineItems currently representing the programme
        self.intro_clip = None

    # ---------------------------------------------------------------- import
    def import_media(self, bin_name):
        """Import video + intro into a fresh bin and read the source format."""
        root = self.media_pool.GetRootFolder()
        folder = self.media_pool.AddSubFolder(root, bin_name) or root
        self.media_pool.SetCurrentFolder(folder)

        self.video_item = self._import_one(self.files["video"])
        self.intro_item = self._import_one(self.files["intro"])

        self.source_fps = _clip_fps(self.video_item)
        self.source_frames = _clip_frames(self.video_item, self.source_fps)
        if not self.source_frames:
            raise EditError("Could not read the length of %s" % self.files["video"].name)
        log.info("Imported %s: %.3f fps, %d frames (%s)", self.files["video"].name,
                 self.source_fps, self.source_frames,
                 frames_to_display(self.source_frames, self.source_fps))

    def compute_trim(self):
        self.trim_start, self.trim_end = resolve_trim(
            self.request.start, self.request.end, self.source_fps, self.source_frames)
        log.info("Trim: %s -> %s", frames_to_display(self.trim_start, self.source_fps),
                 frames_to_display(self.trim_end, self.source_fps))
        return self.trim_start, self.trim_end

    def import_faded_audio(self, path):
        self.faded_audio_path = path
        self.faded_audio_item = self._import_one(path)

    def _import_one(self, path):
        items = self.media_pool.ImportMedia([str(path)])
        if not items:
            raise EditError("Resolve could not import %s" % path)
        return items[0]

    # -------------------------------------------------------------- timeline
    def create_timeline(self, name):
        timeline = self.media_pool.CreateEmptyTimeline(name)
        if not timeline:
            raise EditError("Could not create timeline %r (does it already exist?)" % name)
        self.timeline = timeline
        self.project.SetCurrentTimeline(timeline)

        rate = fps_to_resolve_setting(self.source_fps)
        timeline.SetSetting("useCustomSettings", "1")
        if not timeline.SetSetting("timelineFrameRate", rate):
            log.warning("Could not set timeline frame rate to %s", rate)
        try:
            self.timeline_fps = parse_fps(timeline.GetSetting("timelineFrameRate"))
        except ValueError:
            self.timeline_fps = self.source_fps
        if abs(self.timeline_fps - self.source_fps) > 0.01:
            log.warning("Timeline runs at %.3f fps but source is %.3f fps; durations are "
                        "taken from Resolve so placement stays correct.",
                        self.timeline_fps, self.source_fps)

        if not timeline.SetStartTimecode("00:00:00:00"):
            log.warning("SetStartTimecode failed; using timeline start frame %s",
                        timeline.GetStartFrame())

        self._ensure_tracks("video", 1)
        self._ensure_tracks("audio", 1)
        log.info("Created timeline %r", name)
        return timeline

    def _ensure_tracks(self, kind, count):
        while self.timeline.GetTrackCount(kind) < count:
            sub = "stereo" if kind == "audio" else None
            ok = self.timeline.AddTrack(kind, sub) if sub else self.timeline.AddTrack(kind)
            if not ok:
                raise EditError("Could not add %s track" % kind)

    @property
    def start_frame(self):
        return int(self.timeline.GetStartFrame())

    def _append(self, clip_infos):
        self.project.SetCurrentTimeline(self.timeline)
        result = self.media_pool.AppendToTimeline(clip_infos)
        if not result or len(result) != len(clip_infos):
            raise EditError("AppendToTimeline failed for %r" % [
                {k: v for k, v in ci.items() if k != "mediaPoolItem"} for ci in clip_infos])
        return list(result)

    def _end_frame(self, exclusive_end):
        return exclusive_end - 1 if config.APPEND_END_FRAME_INCLUSIVE else exclusive_end

    # ------------------------------------------------------- main programme
    def place_main(self, offset_frames, with_video_fade):
        """(Re)place the trimmed programme so it starts `offset_frames` into the timeline."""
        self.remove_main()
        record = self.start_frame + int(offset_frames)

        video = self._append([{
            "mediaPoolItem": self.video_item,
            "startFrame": self.trim_start,
            "endFrame": self._end_frame(self.trim_end),
            "trackIndex": MAIN_TRACK,
            "recordFrame": record,
            "mediaType": VIDEO_ONLY,
        }])[0]
        self.main_duration = int(video.GetDuration())

        if self.faded_audio_item is not None:
            audio_info = {
                "mediaPoolItem": self.faded_audio_item,
                "startFrame": 0,
                "endFrame": self._end_frame(self.main_duration),
            }
        else:
            audio_info = {
                "mediaPoolItem": self.video_item,
                "startFrame": self.trim_start,
                "endFrame": self._end_frame(self.trim_end),
            }
        audio_info.update({"trackIndex": MAIN_TRACK, "recordFrame": record, "mediaType": AUDIO_ONLY})
        audio = self._append([audio_info])[0]

        self.main_clips = [video, audio]
        if hasattr(self.timeline, "SetClipsLinked"):
            self.timeline.SetClipsLinked(self.main_clips, True)

        if audio.GetDuration() != self.main_duration:
            log.warning("Audio (%s f) and video (%s f) durations differ",
                        audio.GetDuration(), self.main_duration)
        log.info("Main programme placed at +%d f (%s), %d f long",
                 offset_frames, frames_to_display(offset_frames, self.timeline_fps),
                 self.main_duration)

        if with_video_fade and config.VIDEO_FADE_MODE == "fusion":
            fades.apply_video_fade(
                video,
                seconds_to_frames(config.FADE_IN_SECONDS, self.timeline_fps),
                seconds_to_frames(config.FADE_OUT_SECONDS, self.timeline_fps))
        return self.main_clips

    def remove_main(self):
        if self.main_clips:
            if not self.timeline.DeleteClips(self.main_clips, False):
                raise EditError("Could not remove the main clip from the timeline")
            self.main_clips = []

    # ----------------------------------------------------------------- intro
    def place_intro_with_overlap(self, with_video_fade=False):
        """Phase 2: intro on A2 at 0, programme starts INTRO_OVERLAP_SECONDS before it ends."""
        self.remove_main()
        self._ensure_tracks("audio", INTRO_TRACK)

        info = {"mediaPoolItem": self.intro_item, "trackIndex": INTRO_TRACK,
                "recordFrame": self.start_frame, "mediaType": AUDIO_ONLY}
        intro_frames = _clip_frames(self.intro_item, self.timeline_fps)
        if intro_frames:
            info.update({"startFrame": 0, "endFrame": self._end_frame(intro_frames)})
        self.intro_clip = self._append([info])[0]

        intro_end = (int(self.intro_clip.GetStart()) - self.start_frame
                     + int(self.intro_clip.GetDuration()))
        overlap = seconds_to_frames(config.INTRO_OVERLAP_SECONDS, self.timeline_fps)
        offset = max(0, intro_end - overlap)
        if intro_end < overlap:
            log.warning("Intro (%d f) is shorter than the %d f overlap; programme starts at 0",
                        intro_end, overlap)
        log.info("Intro on A%d: %d f; programme offset %d f", INTRO_TRACK, intro_end, offset)
        self.place_main(offset, with_video_fade=with_video_fade)
        return offset

    def remove_intro(self):
        """Phase 3: delete the intro clip and its audio track."""
        if self.intro_clip is not None:
            if not self.timeline.DeleteClips([self.intro_clip], False):
                raise EditError("Could not delete the intro clip")
            self.intro_clip = None
        if self.timeline.GetTrackCount("audio") >= INTRO_TRACK:
            if not self.timeline.DeleteTrack("audio", INTRO_TRACK):
                log.warning("Could not delete audio track %d (left empty)", INTRO_TRACK)

    # ------------------------------------------------------------- archiving
    def relink_to(self, folder):
        """After archiving, point the Media Pool clips at their new location."""
        items = [i for i in (self.video_item, self.intro_item, self.faded_audio_item) if i]
        try:
            return bool(self.media_pool.RelinkClips(items, str(folder)))
        except Exception as exc:  # best effort only
            log.warning("RelinkClips failed: %s", exc)
            return False
