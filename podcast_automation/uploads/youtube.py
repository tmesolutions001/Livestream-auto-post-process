"""YouTube Data API v3 upload (spec §5 Phase 4).

Setup (one time):
  1. Google Cloud Console -> enable "YouTube Data API v3".
  2. Create an OAuth client of type "Desktop app", download the JSON and save
     it at config.YOUTUBE_CLIENT_SECRETS_FILE.
  3. Run `python -m podcast_automation --youtube-auth EN` (and ES) once. A
     browser opens to pick the channel; the token is cached in
     config.YOUTUBE_TOKEN_FILES[code] and refreshed automatically afterwards.

Note: custom thumbnails require the channel to be phone-verified.
"""

import logging
import time

from .. import config

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube"]
_RETRIABLE_STATUS = (500, 502, 503, 504)
_MAX_RETRIES = 8


class YouTubeError(RuntimeError):
    pass


def _imports():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise YouTubeError(
            "Google API libraries missing in this Python (%s). Install with:\n"
            "  pip install -r requirements.txt\n"
            "using the same Python interpreter Resolve runs scripts with." % exc) from exc
    return Request, Credentials, InstalledAppFlow, build, HttpError, MediaFileUpload


def get_credentials(language_code, interactive=True):
    Request, Credentials, InstalledAppFlow, _, _, _ = _imports()
    token_file = config.YOUTUBE_TOKEN_FILES[language_code]
    creds = None
    if token_file.is_file():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not interactive:
            raise YouTubeError("No YouTube token for %s. Run: python -m podcast_automation "
                               "--youtube-auth %s" % (language_code, language_code))
        secrets = config.YOUTUBE_CLIENT_SECRETS_FILE
        if not secrets.is_file():
            # TODO: download your OAuth "Desktop app" client JSON to this path.
            raise YouTubeError("YouTube client secrets not found at %s" % secrets)
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent")
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    return creds


def build_metadata(title, description, language_code):
    iso = config.language_iso(language_code)
    snippet = {
        "title": title,
        "description": description,
        "categoryId": config.YOUTUBE_CATEGORY_ID,
        "defaultLanguage": iso,
        "defaultAudioLanguage": iso,
    }
    if config.YOUTUBE_TAGS:
        snippet["tags"] = list(config.YOUTUBE_TAGS)
    return {
        "snippet": snippet,
        "status": {
            "privacyStatus": config.YOUTUBE_PRIVACY_STATUS,
            "selfDeclaredMadeForKids": config.YOUTUBE_MADE_FOR_KIDS,
        },
    }


def upload_video(video_path, thumbnail_path, title, description, language_code):
    """Upload as Private, set the thumbnail, return the video id."""
    body = build_metadata(title, description, language_code)
    if config.DRY_RUN_UPLOADS:
        log.info("[dry run] YouTube upload %s with %r", video_path, body)
        return "DRY_RUN_VIDEO_ID"
    if not config.YOUTUBE_ENABLED:
        log.info("YouTube upload disabled (YOUTUBE_ENABLED=false)")
        return None

    _, _, _, build, HttpError, MediaFileUpload = _imports()
    creds = get_credentials(language_code, interactive=True)
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    media = MediaFileUpload(str(video_path), mimetype="video/mp4",
                            chunksize=8 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response, retries = None, 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                log.info("  YouTube upload %d%%", int(status.progress() * 100))
        except HttpError as exc:
            if exc.resp.status not in _RETRIABLE_STATUS or retries >= _MAX_RETRIES:
                raise YouTubeError("YouTube upload failed: %s" % exc) from exc
            retries += 1
            time.sleep(min(2 ** retries, 60))
        except (IOError, OSError) as exc:
            if retries >= _MAX_RETRIES:
                raise YouTubeError("YouTube upload failed: %s" % exc) from exc
            retries += 1
            time.sleep(min(2 ** retries, 60))

    video_id = response.get("id")
    if not video_id:
        raise YouTubeError("YouTube did not return a video id: %r" % response)
    log.info("YouTube video uploaded (private): https://youtu.be/%s", video_id)

    if thumbnail_path:
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg"),
            ).execute()
            log.info("Thumbnail set from %s", thumbnail_path)
        except HttpError as exc:
            raise YouTubeError("Video %s uploaded but thumbnail failed: %s" % (video_id, exc)) from exc
    return video_id
