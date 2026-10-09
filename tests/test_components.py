import datetime
import json
import subprocess
import unittest
from unittest import mock

from podcast_automation import archive, audio_prep, config, ui_dialog
from podcast_automation.uploads import custom_api, youtube

from fake_resolve import FakeDispatcher, FakeUI
from helpers import HAVE_FFMPEG, ConfigSandbox, make_media


class EnvFileTest(ConfigSandbox):
    def test_parse(self):
        env = self.tmp / ".env"
        env.write_text("# comment\nA=1\nexport B = 'x # y'\nC=fusion   # fusion | none\n"
                       "D=\nE=#notvalue\nbroken line\n", encoding="utf-8")
        self.assertEqual(config._load_env_file(env),
                         {"A": "1", "B": "x # y", "C": "fusion", "D": "", "E": ""})

    def test_example_file_parses(self):
        values = config._load_env_file(config.REPO_ROOT / ".env.example")
        self.assertEqual(values["VIDEO_FADE_MODE"], "fusion")
        self.assertEqual(values["DRY_RUN_UPLOADS"], "true")


class ArchiveTest(ConfigSandbox):
    def test_safe_name(self):
        self.assertEqual(archive.safe_name('Ep 1: "Hello/World"?'), "Ep_1_HelloWorld")
        self.assertEqual(archive.safe_name("   "), "untitled")
        self.assertEqual(archive.safe_name("¿Qué tal, amigos?"), "¿Qué_tal,_amigos")

    def test_folder_collision(self):
        day = datetime.date(2026, 1, 2)
        a = self.staging / "a.txt"
        a.write_text("a")
        folder1, moved = archive.archive_files([a], self.tmp / "arc", "Show", day)
        self.assertEqual(folder1.name, "2026-01-02_Show")
        self.assertEqual(moved, [folder1 / "a.txt"])
        self.assertFalse(a.exists())
        a.write_text("again")
        folder2, _ = archive.archive_files([a, self.staging / "missing"], self.tmp / "arc", "Show", day)
        self.assertEqual(folder2.name, "2026-01-02_Show_2")


class ValidateInputsTest(ConfigSandbox):
    def test_missing_files(self):
        req, err = ui_dialog.validate_inputs("English", "", "", "T", "D")
        self.assertIsNone(req)
        self.assertIn("video_EN.mp4", err)

    def test_valid_and_invalid(self):
        for name in ("video_ES.mp4", "intro_ES.mp3", "thumb_ES.jpg"):
            (self.staging / name).write_bytes(b"x")
        req, err = ui_dialog.validate_inputs("Spanish", " 00:01:00 ", "", " Título ", "Desc")
        self.assertIsNone(err)
        self.assertEqual((req.language_code, req.start, req.end, req.title), ("ES", "00:01:00", "", "Título"))
        cases = [("Spanish", "", "", "", "d", "Title is required"),
                 ("Spanish", "", "", "x" * 101, "d", "100 characters"),
                 ("Spanish", "", "", "a<b", "d", "'<'"),
                 ("Spanish", "00:10", "00:05", "t", "d", "after the start"),
                 ("Spanish", "nope", "", "t", "d", "Could not read"),
                 ("French", "", "", "t", "d", "Unknown language")]
        for lang, s, e, t, d, msg in cases:
            req, err = ui_dialog.validate_inputs(lang, s, e, t, d)
            self.assertIsNone(req)
            self.assertIn(msg, err)


class DialogTest(ConfigSandbox):
    def setUp(self):
        super().setUp()
        for name in ("video_ES.mp4", "intro_ES.mp3", "thumb_ES.jpg"):
            (self.staging / name).write_bytes(b"x")

    def test_start_with_error_then_fix(self):
        def fill_bad(win):
            items = win.GetItems()
            self.assertEqual(items["Language"].items_added, ["English", "Spanish"])
            items["Language"].CurrentIndex = 1
            items["Start"].Text = "00:00:05"
            items["End"].Text = "00:00:01"
            items["Title"].Text = "Hola"
            items["Description"].PlainText = "Descripción"
            win.On.StartBtn.Clicked(None)

        def check_error_and_fix(win):
            items = win.GetItems()
            self.assertIn("after the start", items["Status"].Text)
            items["End"].Text = "01:00:00"
            win.On.StartBtn.Clicked(None)

        disp = FakeDispatcher([fill_bad, check_error_and_fix])
        req = ui_dialog.show_dialog(FakeUI(), disp)
        self.assertEqual((req.language_code, req.start, req.end, req.title, req.description),
                         ("ES", "00:00:05", "01:00:00", "Hola", "Descripción"))
        self.assertFalse(disp.windows[0].shown)

    def test_cancel(self):
        disp = FakeDispatcher([lambda win: win.On.CancelBtn.Clicked(None)])
        self.assertIsNone(ui_dialog.show_dialog(FakeUI(), disp))

    def test_close_window(self):
        disp = FakeDispatcher([lambda win: getattr(win.On, ui_dialog.WINDOW_ID).Close(None)])
        self.assertIsNone(ui_dialog.show_dialog(FakeUI(), disp))

    def test_message(self):
        disp = FakeDispatcher([lambda win: win.On.OkBtn.Clicked(None)])
        ui_dialog.show_message(FakeUI(), disp, "T", "body")


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe required")
class AudioPrepTest(ConfigSandbox):
    def _volume(self, path, start, duration):
        out = subprocess.run(["ffmpeg", "-v", "info", "-ss", str(start), "-t", str(duration), "-i", str(path),
                              "-af", "volumedetect", "-f", "null", "-"],
                             stderr=subprocess.PIPE).stderr.decode()
        line = [l for l in out.splitlines() if "mean_volume" in l][0]
        return float(line.split("mean_volume:")[1].split("dB")[0])

    def test_faded_segment(self):
        files = make_media(self.staging, "EN", video_seconds=10, intro_seconds=1)
        dest = self.tmp / "out" / "faded.wav"
        audio_prep.render_faded_segment(files["video"], dest, 2.0, 5.0, 1.0, 2.0)
        info = json.loads(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=duration,sample_rate,codec_name",
             "-of", "json", str(dest)], stdout=subprocess.PIPE, check=True).stdout)["streams"][0]
        self.assertAlmostEqual(float(info["duration"]), 5.0, places=2)
        self.assertEqual((info["codec_name"], info["sample_rate"]), ("pcm_s24le", "48000"))
        full = self._volume(self.staging / "video_EN.mp4", 4.0, 0.5)  # lavfi sine is ~-21 dB
        self.assertAlmostEqual(self._volume(dest, 2.0, 0.5), full, delta=1.0)  # untouched middle
        self.assertLess(self._volume(dest, 0, 0.05), full - 20)      # fading in
        self.assertLess(self._volume(dest, 4.95, 0.05), full - 20)   # faded out

    def test_missing_ffmpeg(self):
        self.set_config(FFMPEG_BIN="definitely-not-ffmpeg")
        with self.assertRaises(audio_prep.FFmpegError):
            audio_prep.ffmpeg_path()


class UploadsTest(ConfigSandbox):
    OVERRIDES = {"DRY_RUN_UPLOADS": False}

    def test_youtube_metadata_private(self):
        self.set_config(YOUTUBE_TAGS=["podcast"])
        body = youtube.build_metadata("T", "D", "ES")
        self.assertEqual(body["status"]["privacyStatus"], "private")
        self.assertEqual(body["snippet"]["defaultAudioLanguage"], "es")
        self.assertEqual(body["snippet"]["tags"], ["podcast"])

    def test_custom_api_requires_url(self):
        self.set_config(CUSTOM_API_URL="")
        mp3 = self.staging / "a.mp3"
        mp3.write_bytes(b"x")
        with self.assertRaises(custom_api.CustomApiError):
            custom_api.upload_mp3(mp3, "T", "D", "EN")

    def test_custom_api_post(self):
        self.set_config(CUSTOM_API_URL="https://example.invalid/upload", CUSTOM_API_TOKEN="secret")
        mp3 = self.staging / "a.mp3"
        mp3.write_bytes(b"ID3")
        response = mock.Mock(status_code=201, text="ok")
        response.json.return_value = {"id": 7}
        with mock.patch("requests.post", return_value=response) as post:
            self.assertEqual(custom_api.upload_mp3(mp3, "T", "D", "ES"), {"id": 7})
        kwargs = post.call_args.kwargs
        self.assertEqual(post.call_args.args[0], "https://example.invalid/upload")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(kwargs["data"]["language"], "es")
        self.assertEqual(kwargs["files"]["file"][0], "a.mp3")

        response.status_code = 500
        with mock.patch("requests.post", return_value=response):
            with self.assertRaises(custom_api.CustomApiError):
                custom_api.upload_mp3(mp3, "T", "D", "ES")

    def test_youtube_missing_libraries_message(self):
        with mock.patch.dict("sys.modules", {"googleapiclient": None, "googleapiclient.discovery": None}):
            with self.assertRaises(youtube.YouTubeError) as ctx:
                youtube.upload_video(self.staging / "v.mp4", None, "T", "D", "EN")
        self.assertIn("pip install", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
