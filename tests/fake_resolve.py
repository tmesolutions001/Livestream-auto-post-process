"""In-memory stand-in for the DaVinci Resolve scripting API.

Implements only the calls the automation uses, with the same signatures and
return conventions (falsy on failure, lists of items, {desc: name} dicts),
and records the timeline layout at each render so tests can assert on it.
Media metadata is read from the real files with ffprobe.
"""

import json
import subprocess
from pathlib import Path


def ffprobe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,r_frame_rate,nb_frames",
         "-of", "json", str(path)], stdout=subprocess.PIPE, check=True).stdout
    return json.loads(out)


def _fps_from_ratio(text):
    num, _, den = text.partition("/")
    return float(num) / float(den or 1)


class FakeMediaPoolItem(object):
    def __init__(self, path, project_fps):
        self.path = Path(path)
        info = ffprobe(path)
        duration = float(info["format"]["duration"])
        video = [s for s in info.get("streams", []) if s["codec_type"] == "video"
                 and self.path.suffix.lower() in (".mp4", ".mov")]
        if video:
            self.fps = _fps_from_ratio(video[0]["r_frame_rate"])
            self.frames = int(video[0].get("nb_frames") or round(duration * self.fps))
            self.is_audio = False
        else:
            self.fps = project_fps
            self.frames = int(round(duration * project_fps))
            self.is_audio = True

    def GetName(self):
        return self.path.name

    def GetClipProperty(self, key=None):
        fps_int = int(round(self.fps))
        f = self.frames
        tc = "%02d:%02d:%02d:%02d" % (f // fps_int // 3600, f // fps_int // 60 % 60, f // fps_int % 60, f % fps_int)
        props = {"FPS": self.fps, "Duration": tc, "File Path": str(self.path)}
        if not self.is_audio:
            props["Frames"] = str(self.frames)
        if key is None:
            return props
        return props.get(key, "")


class FakeTool(object):
    def __init__(self, reg_id, name):
        self.reg_id = reg_id
        self.attrs = {"TOOLS_Name": name}
        self.inputs = {}
        self.modifiers = {}
        self.keyframes = {}

    def SetAttrs(self, attrs):
        self.attrs.update(attrs)

    def ConnectInput(self, name, tool):
        self.inputs[name] = tool
        return True

    def AddModifier(self, name, kind):
        self.modifiers[name] = kind
        return True

    def SetInput(self, name, value, frame=None):
        if frame is not None and name in self.modifiers:
            self.keyframes.setdefault(name, {})[frame] = value
        else:
            self.inputs[name] = value


class FakeComp(object):
    def __init__(self, duration):
        self.tools = {"MediaIn1": FakeTool("MediaIn", "MediaIn1"),
                      "MediaOut1": FakeTool("MediaOut", "MediaOut1")}
        self.duration = duration
        self.locked = 0

    def GetAttrs(self):
        return {"COMPN_RenderStart": 0.0, "COMPN_RenderEnd": float(self.duration - 1)}

    def Lock(self):
        self.locked += 1

    def Unlock(self):
        self.locked -= 1

    def FindTool(self, name):
        return self.tools.get(name)

    def AddTool(self, reg_id, x, y):
        tool = FakeTool(reg_id, "%s%d" % (reg_id, len(self.tools)))
        self.tools[tool.attrs["TOOLS_Name"]] = tool
        return tool


class FakeTimelineItem(object):
    def __init__(self, mpi, kind, track, start, duration, src_start):
        self.mpi = mpi
        self.kind = kind
        self.track = track
        self.start = start
        self.duration = duration
        self.src_start = src_start
        self.comps = []

    def GetName(self):
        return self.mpi.GetName()

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.start + self.duration

    def GetDuration(self):
        return self.duration

    def AddFusionComp(self):
        comp = FakeComp(self.duration)
        self.comps.append(comp)
        return comp

    def describe(self):
        return {"name": self.GetName(), "kind": self.kind, "track": self.track,
                "start": self.start, "duration": self.duration, "src_start": self.src_start,
                "fusion_keys": [dict(t.keyframes.get("Gain", {})) for c in self.comps
                                for t in c.tools.values() if t.keyframes]}


class FakeTimeline(object):
    def __init__(self, name):
        self.name = name
        self.settings = {"timelineFrameRate": "24", "useCustomSettings": "0"}
        self.start_frame = 86400
        self.tracks = {"video": 1, "audio": 1, "subtitle": 0}
        self.items = []
        self.linked = []

    def GetName(self):
        return self.name

    def SetSetting(self, key, value):
        self.settings[key] = value
        return True

    def GetSetting(self, key=None):
        return self.settings.get(key, "")

    def SetStartTimecode(self, tc):
        assert tc == "00:00:00:00"
        self.start_frame = 0
        return True

    def GetStartFrame(self):
        return self.start_frame

    def GetTrackCount(self, kind):
        return self.tracks[kind]

    def AddTrack(self, kind, sub=None):
        self.tracks[kind] += 1
        return True

    def DeleteTrack(self, kind, index):
        if index > self.tracks[kind]:
            return False
        if any(i.kind == kind and i.track == index for i in self.items):
            self.items = [i for i in self.items if not (i.kind == kind and i.track == index)]
        self.tracks[kind] -= 1
        return True

    def DeleteClips(self, items, ripple=False):
        ids = {id(i) for i in items}
        if not ids.issubset({id(i) for i in self.items}):
            return False
        self.items = [i for i in self.items if id(i) not in ids]
        return True

    def SetClipsLinked(self, items, linked):
        self.linked.append(list(items))
        return True

    def snapshot(self):
        return {"tracks": dict(self.tracks), "start_frame": self.start_frame,
                "items": sorted((i.describe() for i in self.items),
                                key=lambda d: (d["kind"], d["track"], d["start"]))}


class FakeMediaPool(object):
    def __init__(self, project):
        self.project = project
        self.root = {"name": "Master", "children": []}
        self.current_folder = self.root
        self.imported = []
        self.relinked = None

    def GetRootFolder(self):
        return self.root

    def AddSubFolder(self, parent, name):
        folder = {"name": name, "children": []}
        parent["children"].append(folder)
        return folder

    def SetCurrentFolder(self, folder):
        self.current_folder = folder
        return True

    def ImportMedia(self, paths):
        items = []
        for p in paths:
            if not Path(p).is_file():
                return []
            items.append(FakeMediaPoolItem(p, self.project.fps_hint))
        self.imported.extend(items)
        return items

    def CreateEmptyTimeline(self, name):
        if any(t.name == name for t in self.project.timelines):
            return None
        tl = FakeTimeline(name)
        self.project.timelines.append(tl)
        return tl

    def AppendToTimeline(self, infos):
        tl = self.project.current_timeline
        out = []
        for info in infos:
            mpi = info["mediaPoolItem"]
            start = info.get("startFrame", 0)
            end = info.get("endFrame", mpi.frames - 1)
            if end >= mpi.frames or start < 0 or end < start:
                return []
            kind = "audio" if info.get("mediaType") == 2 or mpi.is_audio else "video"
            track = info.get("trackIndex", 1)
            if track > tl.tracks[kind]:
                return []
            item = FakeTimelineItem(mpi, kind, track, info.get("recordFrame", tl.start_frame),
                                    end - start + 1, start)  # endFrame inclusive
            tl.items.append(item)
            out.append(item)
        return out

    def RelinkClips(self, items, folder):
        self.relinked = (list(items), folder)
        return True


class FakeProject(object):
    def __init__(self, fps_hint=30.0, mp3_supported=True):
        self.fps_hint = fps_hint
        self.timelines = []
        self.current_timeline = None
        self.media_pool = FakeMediaPool(self)
        self.mp3_supported = mp3_supported
        self.format = None
        self.render_settings = {}
        self.jobs = {}
        self.renders = []  # (settings, format, codec, snapshot, output)

    def GetMediaPool(self):
        return self.media_pool

    def SetCurrentTimeline(self, tl):
        self.current_timeline = tl
        return True

    def GetRenderFormats(self):
        fmts = {"MP4": "mp4", "QuickTime": "mov", "Wave": "wav"}
        if self.mp3_supported:
            fmts["MP3"] = "mp3"
        return fmts

    def GetRenderCodecs(self, fmt):
        return {"mp4": {"H.264": "H264", "H.265": "H265"},
                "mov": {"H.264": "H264"},
                "wav": {"Linear PCM": "LinearPCM"},
                "mp3": {"MP3": "mp3"}}.get(fmt, {})

    def SetCurrentRenderFormatAndCodec(self, fmt, codec):
        if codec not in self.GetRenderCodecs(fmt).values():
            return False
        self.format = (fmt, codec)
        return True

    _KNOWN = {"SelectAllFrames", "TargetDir", "CustomName", "ExportVideo", "ExportAudio", "AudioCodec"}

    def SetRenderSettings(self, settings):
        if not set(settings).issubset(self._KNOWN):
            return False
        self.render_settings.update(settings)
        return True

    def AddRenderJob(self):
        job = "job-%d" % (len(self.jobs) + 1)
        self.jobs[job] = {"settings": dict(self.render_settings), "format": self.format,
                          "snapshot": self.current_timeline.snapshot(), "status": "Ready"}
        return job

    def StartRendering(self, jobs, interactive=False):
        for job in jobs:
            data = self.jobs[job]
            s = data["settings"]
            out = Path(s["TargetDir"]) / ("%s.%s" % (s["CustomName"], data["format"][0]))
            if data["format"][0] == "wav":
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                                "sine=frequency=440:duration=1", str(out)], check=True)
            else:
                out.write_bytes(b"fake render " + json.dumps(data["snapshot"]).encode())
            data["status"] = "Complete"
            self.renders.append(dict(data, output=out))
        return True

    def GetRenderJobStatus(self, job):
        return {"JobStatus": self.jobs[job]["status"], "CompletionPercentage": 100}

    def IsRenderingInProgress(self):
        return False

    def DeleteRenderJob(self, job):
        return True

    def StopRendering(self):
        pass


class FakeProjectManager(object):
    def __init__(self, project):
        self.project = project
        self.saved = 0

    def GetCurrentProject(self):
        return self.project

    def SaveProject(self):
        self.saved += 1
        return True


class FakeResolve(object):
    def __init__(self, project):
        self.pm = FakeProjectManager(project)

    def GetProjectManager(self):
        return self.pm

    def Fusion(self):
        return None


# ------------------------------------------------------------------ UIManager
class _Widget(object):
    def __init__(self, kind, props, children=None):
        self.kind = kind
        self.props = dict(props or {})
        self.children = children or []
        self.items_added = []
        self.Text = self.props.get("Text", "")
        self.PlainText = ""
        self.CurrentIndex = -1

    def AddItem(self, text):
        self.items_added.append(text)

    @property
    def CurrentText(self):
        return self.items_added[self.CurrentIndex] if self.CurrentIndex >= 0 else ""


class FakeUI(object):
    def __getattr__(self, kind):
        def make(*args):
            props, children = {}, []
            for a in args:
                if isinstance(a, dict):
                    props = a
                elif isinstance(a, list):
                    children = a
            return _Widget(kind, props, children)
        return make


class _Handlers(object):
    def __init__(self):
        object.__setattr__(self, "_targets", {})

    def __getattr__(self, name):
        return self._targets.setdefault(name, _HandlerSet())


class _HandlerSet(object):
    pass


class FakeWindow(object):
    def __init__(self, props, root):
        self.props = props
        self.root = root
        self.On = _Handlers()
        self.shown = False

    def GetItems(self):
        found = {}

        def walk(w):
            if "ID" in w.props:
                found[w.props["ID"]] = w
            for c in w.children:
                walk(c)
        walk(self.root)
        return found

    def Show(self):
        self.shown = True

    def Hide(self):
        self.shown = False


class FakeDispatcher(object):
    """`script` is a list of callables run in order inside RunLoop, each
    receiving the window; they simulate the user typing and clicking."""

    def __init__(self, script=None):
        self.script = list(script or [])
        self.windows = []
        self.exited = False

    def AddWindow(self, props, root):
        win = FakeWindow(props, root)
        self.windows.append(win)
        return win

    def RunLoop(self):
        self.exited = False
        win = self.windows[-1]
        while self.script and not self.exited:
            self.script.pop(0)(win)
        if not self.exited:
            raise AssertionError("RunLoop would block forever (no ExitLoop)")

    def ExitLoop(self):
        self.exited = True
