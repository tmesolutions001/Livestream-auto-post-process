"""Timestamp parsing and frame math.

Accepted timestamp formats (all relative to the start of the source file):
    "1:02:03"        H:MM:SS
    "02:03"          MM:SS
    "1:02:03.500"    with fractional seconds
    "01:02:03:12"    SMPTE H:MM:SS:FF (non-drop, FF counted at the clip's rounded fps)
    "3723.5"         plain seconds
    ""               blank = start of file (start) / end of file (end)
"""

import math
import re

_SECONDS_RE = re.compile(r"^\d+(\.\d+)?$")


class TimestampError(ValueError):
    pass


def parse_timestamp(text, fps):
    """Return a frame offset (int) for `text` at `fps`, or None if blank."""
    if text is None:
        return None
    value = str(text).strip()
    if not value:
        return None
    if fps <= 0:
        raise TimestampError("Invalid frame rate: %r" % fps)

    if _SECONDS_RE.match(value):
        return int(round(float(value) * fps))

    parts = value.split(":")
    try:
        if len(parts) == 4:
            h, m, s, f = (int(p) for p in parts)
            nominal = int(round(fps))
            if f >= nominal:
                raise TimestampError("Frame field %d >= %d fps in %r" % (f, nominal, value))
            _check_ms(m, s, value)
            return (h * 3600 + m * 60 + s) * nominal + f
        if len(parts) in (2, 3):
            if len(parts) == 2:
                h, m, s = 0, int(parts[0]), float(parts[1])
            else:
                h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
            _check_ms(m, s, value)
            return int(round((h * 3600 + m * 60 + s) * fps))
    except TimestampError:
        raise
    except ValueError:
        pass
    raise TimestampError(
        "Could not read timestamp %r. Use HH:MM:SS, MM:SS, HH:MM:SS.mmm, "
        "HH:MM:SS:FF or seconds." % value)


def _check_ms(m, s, value):
    if m >= 60 or s >= 60 or m < 0 or s < 0:
        raise TimestampError("Minutes/seconds out of range in %r" % value)


def resolve_trim(start_text, end_text, fps, total_frames):
    """Turn UI timestamps into a validated [start, end) frame range."""
    start = parse_timestamp(start_text, fps)
    end = parse_timestamp(end_text, fps)
    start = 0 if start is None else start
    end = total_frames if end is None else end
    if total_frames and end > total_frames:
        raise TimestampError(
            "End timestamp %s is past the end of the video (%s)."
            % (frames_to_display(end, fps), frames_to_display(total_frames, fps)))
    if end <= start:
        raise TimestampError("End timestamp must be after the start timestamp.")
    return start, end


def seconds_to_frames(seconds, fps):
    return int(round(seconds * fps))


def frames_to_seconds(frames, fps):
    return frames / float(fps)


def frames_to_display(frames, fps):
    """H:MM:SS.mmm, for logs and error messages."""
    total = frames / float(fps)
    h = int(total // 3600)
    m = int((total % 3600) // 60)
    s = total - h * 3600 - m * 60
    return "%d:%02d:%06.3f" % (h, m, s)


def parse_fps(value):
    """Resolve returns FPS as e.g. '29.97', 29.97, '25', or '23.976 DF'."""
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(\.\d+)?", str(value or ""))
    if not match:
        raise ValueError("Could not read frame rate from %r" % value)
    return float(match.group(0))


def timecode_to_frames(tc, fps):
    """Resolve 'HH:MM:SS:FF' (or ';' drop-frame separator) -> frames, non-drop math."""
    nominal = int(round(fps))
    parts = re.split(r"[:;]", str(tc).strip())
    if len(parts) != 4:
        raise ValueError("Not a timecode: %r" % tc)
    h, m, s, f = (int(p) for p in parts)
    return (h * 3600 + m * 60 + s) * nominal + f


def fps_to_resolve_setting(fps):
    """Map a float fps to the string Resolve's timelineFrameRate setting expects."""
    known = {23.976: "23.976", 24.0: "24", 25.0: "25", 29.97: "29.97", 30.0: "30",
             47.952: "47.952", 48.0: "48", 50.0: "50", 59.94: "59.94", 60.0: "60",
             119.88: "119.88", 120.0: "120"}
    for k, v in known.items():
        if math.isclose(fps, k, abs_tol=0.01):
            return v
    return ("%.3f" % fps).rstrip("0").rstrip(".")
