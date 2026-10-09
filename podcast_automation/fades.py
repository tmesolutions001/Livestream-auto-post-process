"""Video fade in/out on a timeline clip.

Resolve's scripting API has no fade-handle or transition call, so the fade is
built as a Fusion comp on the clip: MediaIn -> BrightnessContrast -> MediaOut,
with the BrightnessContrast Gain keyframed 0 -> 1 at the head and 1 -> 0 at
the tail (fade from / to black).
"""

import logging

log = logging.getLogger(__name__)

FADE_TOOL_NAME = "PodcastFade"


def _comp_range(comp, fallback_duration):
    attrs = comp.GetAttrs() or {}
    start = attrs.get("COMPN_RenderStart")
    end = attrs.get("COMPN_RenderEnd")
    if start is None or end is None:
        start, end = 0, fallback_duration - 1
    return int(start), int(end)


def apply_video_fade(timeline_item, fade_in_frames, fade_out_frames):
    """Add a fade-from-black / fade-to-black Fusion comp. Returns True on success."""
    if fade_in_frames <= 0 and fade_out_frames <= 0:
        return True

    comp = timeline_item.AddFusionComp()
    if not comp:
        log.warning("AddFusionComp() failed; video fade skipped for %s", timeline_item.GetName())
        return False

    duration = int(timeline_item.GetDuration())
    first, last = _comp_range(comp, duration)
    fade_in_frames = min(fade_in_frames, duration // 2)
    fade_out_frames = min(fade_out_frames, duration // 2)

    comp.Lock()
    try:
        media_in = comp.FindTool("MediaIn1")
        media_out = comp.FindTool("MediaOut1")
        if not media_in or not media_out:
            log.warning("Fusion comp has no MediaIn1/MediaOut1; video fade skipped")
            return False

        bc = comp.AddTool("BrightnessContrast", -32768, -32768)
        bc.SetAttrs({"TOOLS_Name": FADE_TOOL_NAME})
        bc.ConnectInput("Input", media_in)
        media_out.ConnectInput("Input", bc)

        bc.AddModifier("Gain", "BezierSpline")
        keys = []
        if fade_in_frames > 0:
            keys += [(first, 0.0), (first + fade_in_frames, 1.0)]
        else:
            keys += [(first, 1.0)]
        if fade_out_frames > 0:
            keys += [(last - fade_out_frames, 1.0), (last, 0.0)]
        for frame, value in keys:
            bc.SetInput("Gain", value, frame)
    finally:
        comp.Unlock()

    log.info("Video fade applied (in %d f, out %d f, comp range %d-%d)",
             fade_in_frames, fade_out_frames, first, last)
    return True
