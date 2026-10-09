# Livestream Auto Post-Process

Python automation for **DaVinci Resolve Studio** that turns a raw bilingual (EN/ES)
podcast recording into a trimmed, faded MP3 (with intro) and MP4. It uploads both
and then archives everything.

```
Resolve dialog ─► import + trim ─► fades ─► intro on A2, 1 s overlap ─► render MP3
              ─► drop intro, snap to 00:00:00:00 ─► render MP4
              ─► upload MP3 (custom API) + MP4 (YouTube, Private, thumbnail)
              ─► move raw files + renders to Archive/YYYY-MM-DD_Title/
```

## Layout

| Path | Purpose |
|---|---|
| `podcast_automation/config.py` | **All paths, keys and settings.** Overridable via `.env` / env vars |
| `podcast_automation/ui_dialog.py` | UIManager pop-up (language, start/end, title, description) and input validation |
| `podcast_automation/timeline_builder.py` | Media Pool import, timeline creation, trimming, placement, intro alignment |
| `podcast_automation/fades.py` | Video fade-in/out using a keyframed Fusion comp |
| `podcast_automation/audio_prep.py` | ffmpeg: pre-faded programme audio, WAV→MP3 fallback |
| `podcast_automation/render.py` | Render Queue: MP3 (audio-only) and MP4/H.264 jobs, polling, output checks |
| `podcast_automation/uploads/custom_api.py` | MP3 upload via `requests` (**TODO: confirm endpoint contract**) |
| `podcast_automation/uploads/youtube.py` | YouTube Data API v3 resumable upload, Private, thumbnail |
| `podcast_automation/archive.py` | Timestamped archive folder plus `shutil.move` |
| `podcast_automation/pipeline.py` | Runs Phases 1–5 in order and collects errors |
| `podcast_automation/entry.py` | CLI / menu entry point |
| `resolve_launcher/Podcast Automation.py` | Drop-in script for Resolve's **Workspace ▸ Scripts** menu |
| `tests/` | Test suite run against a fake Resolve API with real ffmpeg-generated media |

## Setup

1. **Paths and keys:** `cp .env.example .env` and fill in `STAGING_DIR`, `ARCHIVE_DIR`,
   `CUSTOM_API_URL`/`CUSTOM_API_TOKEN`. You can also edit the defaults in `config.py` directly.
   Leave `DRY_RUN_UPLOADS=true` until the APIs are configured.
2. **Python packages:** `pip install -r requirements.txt`, using the Python that Resolve runs
   scripts with (Resolve ▸ Preferences ▸ System ▸ General shows the version it detected).
3. **ffmpeg:** must be installed and on PATH, or set `FFMPEG_BIN` to its full path.
   It is used for the audio fades and the MP3 fallback.
4. **Resolve:** Preferences ▸ System ▸ General ▸ *External scripting using* = **Local**.
5. **Menu launcher:** copy `resolve_launcher/Podcast Automation.py` into Resolve's
   `Fusion/Scripts/Utility/` folder (paths are listed in the file) and set `PROJECT_DIR` in it.
6. **YouTube (one time):** create an OAuth *Desktop app* client in Google Cloud with the
   YouTube Data API v3 enabled. Save the JSON as `credentials/client_secret.json`, then run:
   ```
   python -m podcast_automation --youtube-auth EN
   python -m podcast_automation --youtube-auth ES
   ```
   Each command opens a browser so you can pick that language's channel. Point both token
   files at the same path if you only use one channel.

## Running

- **In Resolve:** Workspace ▸ Scripts ▸ Utility ▸ *Podcast Automation*.
- **Headless / testing:** `python -m podcast_automation --no-gui --language EN --start 00:02:10 --end 1:04:30 --title "..." --description-file desc.txt [--dry-run-uploads]`

Timestamps accept `HH:MM:SS`, `MM:SS`, `HH:MM:SS.mmm`, `HH:MM:SS:FF` or plain seconds.
They are measured from the start of the raw file. Leave Start blank to begin at the start
of the file, and End blank to run to its end.

Every run writes a log to `logs/`. Successful runs also write `run_summary.json` (with the
YouTube id) into the archive folder.

## How the Resolve API limits were handled

The Resolve scripting API has **no** calls for blade/split, moving a clip, transitions,
or fades. The workarounds:

- **Trim:** only the `[start, end)` source range is appended (`AppendToTimeline` with
  `startFrame`/`endFrame`). The result is the same as cutting at both timestamps and
  deleting the outer pieces.
- **Shift / snap back:** the clip is deleted and re-appended at a new `recordFrame`.
  The timeline start is set to `00:00:00:00`.
- **Video fade:** a Fusion comp is added to the clip (MediaIn → BrightnessContrast → MediaOut)
  with Gain keyframed 0→1 at the head and 1→0 at the tail. It is skipped for the MP3 pass
  because no video is exported there.
- **Audio fade:** ffmpeg writes the trimmed programme audio to a 48 kHz/24-bit WAV with the
  fades baked in. That WAV replaces the camera audio on A1, starting on the same frame, so the
  fades fall in the right place in both the MP3 (under the intro overlap) and the MP4.
  Set `AUDIO_FADE_MODE=none` to use the camera audio without fades.
- **MP3 export:** the script uses Resolve's MP3 render format if the build offers one.
  Otherwise it renders WAV and transcodes it with ffmpeg (`MP3_FALLBACK_VIA_WAV`).

## Behaviour notes

- Archiving runs only if both renders and both uploads succeed. Otherwise staging is left
  untouched. Re-running after a failed YouTube upload will upload the MP3 again.
- Only the selected language's files (plus this run's renders and intermediates) are moved.
  An EN run will not touch staged ES files.
- After archiving, the Media Pool clips are relinked to the archive folder, so the Resolve
  timeline stays online.
- A new bin and timeline named `YYYY-MM-DD_<CODE>_<Title>` are created in the current project
  (or in `RESOLVE_PROJECT_NAME`).

## Tests

```
python3 -m unittest discover -s tests -t tests
```
The tests need `ffmpeg`/`ffprobe` on PATH. They generate small real media files and run the
whole pipeline against `tests/fake_resolve.py`, an in-memory Resolve API that records the
timeline layout at each render. They check:
- intro placement and the 1-second overlap
- trim ranges
- fade keyframes
- render settings
- archive contents
- the UI dialog wiring
- error paths (render failure, upload failure, bad timestamps)

They do not exercise a real Resolve install. Do the first real run with `DRY_RUN_UPLOADS=true`.
