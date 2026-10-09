import datetime
import json
import subprocess
import unittest
from unittest import mock

from podcast_automation import config, pipeline
from podcast_automation.resolve_env import ResolveContext
from podcast_automation.ui_dialog import EpisodeRequest

from fake_resolve import FakeProject, FakeResolve
from helpers import HAVE_FFMPEG, ConfigSandbox, make_media

TODAY = datetime.date(2026, 10, 9)
FPS = 30


def _items(snapshot, kind, track=None):
    return [i for i in snapshot["items"] if i["kind"] == kind and (track is None or i["track"] == track)]


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe required")
class PipelineTest(ConfigSandbox):
    def setUp(self):
        super().setUp()
        self.files = make_media(self.staging, "EN", video_seconds=20, intro_seconds=5, fps=FPS)
        self.project = FakeProject(fps_hint=FPS)
        self.ctx = ResolveContext(FakeResolve(self.project))
        self.request = EpisodeRequest("EN", "00:00:02", "00:00:12", "My Episode: Part 1?", "Desc")

    def run_pipeline(self):
        return pipeline.run(self.ctx, self.request, today=TODAY)

    def test_full_run(self):
        result = self.run_pipeline()
        self.assertTrue(result.ok, result.errors)
        mp3_job, mp4_job = self.project.renders

        # --- Phase 2: MP3 render, intro on A2 from 0, programme 1 s before intro ends
        self.assertEqual(mp3_job["format"], ("mp3", "mp3"))
        self.assertFalse(mp3_job["settings"]["ExportVideo"])
        self.assertTrue(mp3_job["settings"]["ExportAudio"])
        snap = mp3_job["snapshot"]
        self.assertEqual(snap["start_frame"], 0)
        intro = _items(snap, "audio", 2)
        self.assertEqual(len(intro), 1)
        self.assertEqual(intro[0]["start"], 0)
        intro_frames = intro[0]["duration"]
        self.assertAlmostEqual(intro_frames, 5 * FPS, delta=2)
        main_audio = _items(snap, "audio", 1)[0]
        main_video = _items(snap, "video", 1)[0]
        self.assertEqual(main_audio["start"], intro_frames - FPS)
        self.assertEqual(main_video["start"], intro_frames - FPS)
        self.assertEqual(main_video["src_start"], 2 * FPS)
        self.assertEqual(main_video["duration"], 10 * FPS)
        self.assertEqual(main_audio["duration"], 10 * FPS)
        self.assertTrue(main_audio["name"].endswith("_programme_audio.wav"))

        # --- Phase 3: MP4 render, intro track gone, programme at 00:00:00:00, faded
        self.assertEqual(mp4_job["format"], ("mp4", "H264"))
        self.assertTrue(mp4_job["settings"]["ExportVideo"])
        snap = mp4_job["snapshot"]
        self.assertEqual(snap["tracks"]["audio"], 1)
        self.assertEqual(len(_items(snap, "audio")), 1)
        main_video = _items(snap, "video", 1)[0]
        self.assertEqual(main_video["start"], 0)
        self.assertEqual(_items(snap, "audio", 1)[0]["start"], 0)
        keys = main_video["fusion_keys"][0]
        last = 10 * FPS - 1
        fade_in = round(config.FADE_IN_SECONDS * FPS)
        fade_out = round(config.FADE_OUT_SECONDS * FPS)
        self.assertEqual(keys, {0: 0.0, fade_in: 1.0, last - fade_out: 1.0, last: 0.0})

        # --- Phase 5: everything archived, staging empty
        folder = config.ARCHIVE_DIR / "2026-10-09_My_Episode_Part_1"
        self.assertEqual(result.archive_folder, folder)
        self.assertEqual(list(self.staging.iterdir()), [])
        names = sorted(p.name for p in folder.iterdir())
        base = "2026-10-09_EN_My_Episode_Part_1"
        self.assertEqual(names, sorted([
            "video_EN.mp4", "intro_EN.mp3", "thumb_EN.jpg", base + ".mp3", base + ".mp4",
            base + "_programme_audio.wav", "run_summary.json"]))
        summary = json.loads((folder / "run_summary.json").read_text())
        self.assertEqual(summary["youtube_video_id"], "DRY_RUN_VIDEO_ID")
        self.assertEqual(self.project.media_pool.relinked[1], str(folder))

    def test_other_language_files_untouched(self):
        es = make_media(self.staging, "ES", video_seconds=3, intro_seconds=1)
        result = self.run_pipeline()
        self.assertTrue(result.ok, result.errors)
        for path in es.values():
            self.assertTrue(path.is_file(), path)

    def test_no_audio_fade_uses_camera_audio(self):
        self.set_config(AUDIO_FADE_MODE="none", VIDEO_FADE_MODE="none")
        result = self.run_pipeline()
        self.assertTrue(result.ok, result.errors)
        snap = self.project.renders[1]["snapshot"]
        audio = _items(snap, "audio", 1)[0]
        self.assertEqual(audio["name"], "video_EN.mp4")
        self.assertEqual(audio["src_start"], 2 * FPS)
        self.assertEqual(_items(snap, "video", 1)[0]["fusion_keys"], [])

    def test_mp3_fallback_via_wav(self):
        self.project.mp3_supported = False
        result = self.run_pipeline()
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(self.project.renders[0]["format"], ("wav", "LinearPCM"))
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name",
                              "-of", "csv=p=0", str(result.archive_folder / (
                                  "2026-10-09_EN_My_Episode_Part_1.mp3"))],
                             stdout=subprocess.PIPE, check=True).stdout.decode().strip()
        self.assertEqual(out, "mp3")
        self.assertTrue((result.archive_folder / "2026-10-09_EN_My_Episode_Part_1_master.wav").is_file())

    def test_upload_failure_blocks_archive(self):
        with mock.patch("podcast_automation.uploads.youtube.upload_video",
                        side_effect=RuntimeError("quota exceeded")):
            result = self.run_pipeline()
        self.assertFalse(result.ok)
        self.assertIn("YouTube upload: quota exceeded", result.errors)
        self.assertIsNone(result.archive_folder)
        self.assertTrue(self.files["video"].is_file())
        self.assertTrue(result.mp4_path.is_file())

    def test_bad_end_timestamp_reports_error(self):
        self.request.end = "00:05:00"
        result = self.run_pipeline()
        self.assertFalse(result.ok)
        self.assertIn("past the end", result.errors[0])
        self.assertEqual(self.project.renders, [])

    def test_render_failure_reported(self):
        self.project.GetRenderJobStatus = lambda job: {"JobStatus": "Failed", "Error": "disk full"}
        result = self.run_pipeline()
        self.assertFalse(result.ok)
        self.assertIn("disk full", result.errors[0])
        self.assertTrue(self.files["video"].is_file())


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe required")
class EntryPointTest(ConfigSandbox):
    """Runs entry.main() the way the Resolve menu launcher does."""

    def setUp(self):
        super().setUp()
        make_media(self.staging, "ES", video_seconds=6, intro_seconds=2, fps=FPS)
        self.project = FakeProject(fps_hint=FPS)

    def test_gui_flow(self):
        from fake_resolve import FakeDispatcher, FakeUI
        from podcast_automation import entry

        def fill(win):
            items = win.GetItems()
            items["Language"].CurrentIndex = 1
            items["Start"].Text = "1"
            items["Title"].Text = "Episodio 3"
            items["Description"].PlainText = "Hola"
            win.On.StartBtn.Clicked(None)

        dispatcher = FakeDispatcher([fill, lambda win: win.On.OkBtn.Clicked(None)])
        bmd = mock.Mock(UIDispatcher=mock.Mock(return_value=dispatcher))
        fusion = mock.Mock(UIManager=FakeUI())
        code = entry.main({"resolve": FakeResolve(self.project), "bmd": bmd, "fusion": fusion}, argv=[])
        self.assertEqual(code, 0)
        self.assertIn("SUCCESS", dispatcher.windows[1].GetItems()["Body"].Text)
        self.assertEqual(len(self.project.renders), 2)
        self.assertEqual(list(self.staging.iterdir()), [])

    def test_no_gui_flow(self):
        from podcast_automation import entry
        code = entry.main({"resolve": FakeResolve(self.project), "bmd": object()},
                          argv=["--no-gui", "--language", "es", "--title", "Ep", "--end", "5"])
        self.assertEqual(code, 0)
        self.assertEqual(self.project.renders[1]["snapshot"]["items"][0]["duration"], 5 * FPS)

    def test_no_gui_validation_error(self):
        from podcast_automation import entry
        code = entry.main({"resolve": FakeResolve(self.project), "bmd": object()},
                          argv=["--no-gui", "--language", "EN", "--title", "Ep"])
        self.assertEqual(code, 2)
        self.assertEqual(self.project.renders, [])
