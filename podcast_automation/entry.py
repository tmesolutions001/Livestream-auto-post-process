"""Command-line / Resolve-menu entry point."""

import argparse
import datetime
import logging
import sys

from . import config, pipeline, resolve_env, ui_dialog

log = logging.getLogger("podcast_automation")


def setup_logging(verbose=False):
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logfile = config.LOG_DIR / ("run_%s.log" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    # Resolve reuses one interpreter across script runs: drop handlers from earlier runs.
    for handler in [h for h in root.handlers if getattr(h, "_podcast_automation", False)]:
        root.removeHandler(handler)
        handler.close()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    for handler in (logging.StreamHandler(sys.stdout), logging.FileHandler(str(logfile), encoding="utf-8")):
        handler.setFormatter(fmt)
        handler._podcast_automation = True
        root.addHandler(handler)
    return logfile


def parse_args(argv):
    p = argparse.ArgumentParser(prog="podcast_automation",
                                description="DaVinci Resolve podcast automation")
    p.add_argument("--no-gui", action="store_true",
                   help="skip the Resolve dialog and take the inputs from the flags below")
    p.add_argument("--language", help="English/Spanish/EN/ES")
    p.add_argument("--start", default="", help="trim start timestamp")
    p.add_argument("--end", default="", help="trim end timestamp")
    p.add_argument("--title", default="")
    p.add_argument("--description", default="")
    p.add_argument("--description-file", help="read the description from a text file")
    p.add_argument("--dry-run-uploads", action="store_true",
                   help="log uploads instead of sending them")
    p.add_argument("--youtube-auth", metavar="CODE",
                   help="run the one-time YouTube OAuth flow for EN or ES and exit")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(script_globals=None, argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    logfile = setup_logging(args.verbose)
    log.info("Log file: %s", logfile)

    if args.dry_run_uploads:
        config.DRY_RUN_UPLOADS = True

    if args.youtube_auth:
        from .uploads import youtube
        code = config.language_code(args.youtube_auth)
        youtube.get_credentials(code, interactive=True)
        log.info("YouTube token saved to %s", config.YOUTUBE_TOKEN_FILES[code])
        return 0

    ctx = resolve_env.connect(script_globals)
    ui, dispatcher = (None, None) if args.no_gui else ctx.ui_dispatcher()

    if args.no_gui:
        description = args.description
        if args.description_file:
            with open(args.description_file, encoding="utf-8") as fh:
                description = fh.read()
        request, error = ui_dialog.validate_inputs(
            args.language or "", args.start, args.end, args.title, description)
        if error:
            log.error(error)
            return 2
    else:
        if dispatcher is None:
            log.error("Resolve UIManager is not available (DaVinci Resolve Studio is required "
                      "for the dialog). Use --no-gui with --language/--title/... instead.")
            return 2
        request = ui_dialog.show_dialog(ui, dispatcher)
        if request is None:
            log.info("Cancelled by user")
            return 1

    result = pipeline.run(ctx, request)
    log.info("\n%s", result.summary())
    if dispatcher is not None:
        ui_dialog.show_message(ui, dispatcher, "Podcast Automation",
                               result.summary() + "\n\nLog: %s" % logfile)
    return 0 if result.ok else 3
