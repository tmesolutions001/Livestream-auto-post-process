"""Upload of the MP3 to the custom external program (spec §5 Phase 4).

TODO: confirm with the receiving program:
  * the URL and HTTP method (POST multipart assumed),
  * the auth scheme (Bearer token assumed),
  * the field names for the file and metadata,
  * what a success response looks like (any 2xx assumed).
Adjust `build_request` below; nothing else needs to change.
"""

import logging

from .. import config

log = logging.getLogger(__name__)


class CustomApiError(RuntimeError):
    pass


def build_request(mp3_path, title, description, language_code):
    """Return (url, headers, form_fields). Edit this to match the endpoint."""
    headers = {}
    if config.CUSTOM_API_TOKEN:
        headers["Authorization"] = "Bearer %s" % config.CUSTOM_API_TOKEN  # TODO confirm auth scheme
    fields = {
        "title": title,
        "description": description,
        "language": config.language_iso(language_code),
    }
    return config.CUSTOM_API_URL, headers, fields


def upload_mp3(mp3_path, title, description, language_code):
    url, headers, fields = build_request(mp3_path, title, description, language_code)
    if config.DRY_RUN_UPLOADS:
        log.info("[dry run] MP3 upload %s -> %s fields=%r", mp3_path, url or "<no URL>", fields)
        return {"dry_run": True}
    if not config.CUSTOM_API_ENABLED:
        log.info("Custom MP3 upload disabled (CUSTOM_API_ENABLED=false)")
        return None
    if not url:
        raise CustomApiError("CUSTOM_API_URL is not set (see .env.example)")

    try:
        import requests
    except ImportError as exc:
        raise CustomApiError("The 'requests' package is missing in Resolve's Python") from exc

    with open(str(mp3_path), "rb") as fh:
        files = {config.CUSTOM_API_FILE_FIELD: (mp3_path.name, fh, "audio/mpeg")}
        try:
            response = requests.post(url, headers=headers, data=fields, files=files,
                                     timeout=config.CUSTOM_API_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            raise CustomApiError("MP3 upload failed: %s" % exc) from exc

    if not 200 <= response.status_code < 300:
        raise CustomApiError("MP3 upload returned HTTP %d: %s"
                             % (response.status_code, response.text[:500]))
    log.info("MP3 uploaded to custom endpoint (HTTP %d)", response.status_code)
    try:
        return response.json()
    except ValueError:
        return {"status_code": response.status_code, "text": response.text[:500]}
