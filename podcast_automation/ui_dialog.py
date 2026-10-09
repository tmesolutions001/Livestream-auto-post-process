"""Native Resolve pop-up (UIManager) that collects the run parameters (spec §4)."""

from . import config
from .timecode import TimestampError, parse_timestamp

WINDOW_ID = "PodcastAutomationWin"


class EpisodeRequest(object):
    """Everything the user entered in the dialog."""

    def __init__(self, language_code, start, end, title, description):
        self.language_code = language_code
        self.start = start
        self.end = end
        self.title = title
        self.description = description

    def __repr__(self):
        return ("EpisodeRequest(language=%r, start=%r, end=%r, title=%r)"
                % (self.language_code, self.start, self.end, self.title))


def validate_inputs(language_label, start, end, title, description):
    """Return (EpisodeRequest, None) or (None, error message). No Resolve needed."""
    try:
        code = config.language_code(language_label)
    except ValueError as exc:
        return None, str(exc)

    title = (title or "").strip()
    description = (description or "").strip()
    if not title:
        return None, "YouTube Title is required."
    if len(title) > 100:
        return None, "YouTube Title must be 100 characters or fewer (currently %d)." % len(title)
    if "<" in title or ">" in title:
        return None, "YouTube does not allow '<' or '>' in titles."
    if len(description.encode("utf-8")) > 5000:
        return None, "YouTube Description must be 5000 bytes or fewer."
    if "<" in description or ">" in description:
        return None, "YouTube does not allow '<' or '>' in descriptions."

    # Syntax check at a nominal rate; the real frame math happens once the
    # clip's frame rate is known.
    try:
        s = parse_timestamp(start, 30.0)
        e = parse_timestamp(end, 30.0)
    except TimestampError as exc:
        return None, str(exc)
    if s is not None and e is not None and e <= s:
        return None, "End timestamp must be after the start timestamp."

    missing = [str(p) for p in config.staged_files(code).values() if not p.is_file()]
    if missing:
        return None, "Missing staged file(s):\n" + "\n".join(missing)

    return EpisodeRequest(code, (start or "").strip(), (end or "").strip(), title, description), None


def show_dialog(ui, dispatcher):
    """Show the form and block until the user starts or cancels.

    Returns an EpisodeRequest, or None if cancelled.
    """
    labels = list(config.LANGUAGES.keys())
    label_width = 130

    def row(label, widget):
        return ui.HGroup({"Weight": 0}, [
            ui.Label({"Text": label, "MinimumSize": [label_width, 0],
                      "MaximumSize": [label_width, 1000], "Weight": 0}),
            widget,
        ])

    win = dispatcher.AddWindow(
        {"ID": WINDOW_ID, "WindowTitle": "Podcast Automation",
         "Geometry": [200, 150, 560, 520]},
        ui.VGroup({"Spacing": 8}, [
            ui.Label({"Text": "Staging folder: %s" % config.STAGING_DIR,
                      "Weight": 0, "WordWrap": True}),
            row("Language", ui.ComboBox({"ID": "Language"})),
            row("Start timestamp", ui.LineEdit({"ID": "Start",
                                                "PlaceholderText": "HH:MM:SS  (blank = beginning)"})),
            row("End timestamp", ui.LineEdit({"ID": "End",
                                              "PlaceholderText": "HH:MM:SS  (blank = end of file)"})),
            row("YouTube Title", ui.LineEdit({"ID": "Title", "PlaceholderText": "Episode title"})),
            ui.Label({"Text": "YouTube Description", "Weight": 0}),
            ui.TextEdit({"ID": "Description", "Weight": 1}),
            ui.Label({"ID": "Status", "Text": "", "Weight": 0, "WordWrap": True,
                      "StyleSheet": "color: #ff6b6b;"}),
            ui.HGroup({"Weight": 0}, [
                ui.HGap(0, 1),
                ui.Button({"ID": "CancelBtn", "Text": "Cancel"}),
                ui.Button({"ID": "StartBtn", "Text": "Start Automation"}),
            ]),
        ]),
    )
    items = win.GetItems()
    for label in labels:
        items["Language"].AddItem(label)
    items["Language"].CurrentIndex = 0

    result = {"request": None}

    def on_close(ev):
        dispatcher.ExitLoop()

    def on_start(ev):
        request, error = validate_inputs(
            items["Language"].CurrentText,
            items["Start"].Text,
            items["End"].Text,
            items["Title"].Text,
            items["Description"].PlainText,
        )
        if error:
            items["Status"].Text = error
            return
        result["request"] = request
        dispatcher.ExitLoop()

    getattr(win.On, WINDOW_ID).Close = on_close
    win.On.CancelBtn.Clicked = on_close
    win.On.StartBtn.Clicked = on_start

    win.Show()
    dispatcher.RunLoop()
    win.Hide()
    return result["request"]


def show_message(ui, dispatcher, title, text):
    """Simple modal-ish message box used for the final success/failure report."""
    win_id = "PodcastAutomationMsg"
    win = dispatcher.AddWindow(
        {"ID": win_id, "WindowTitle": title, "Geometry": [250, 200, 520, 260]},
        ui.VGroup([
            ui.TextEdit({"ID": "Body", "Text": text, "ReadOnly": True}),
            ui.HGroup({"Weight": 0}, [ui.HGap(0, 1), ui.Button({"ID": "OkBtn", "Text": "OK"})]),
        ]),
    )

    def close(ev):
        dispatcher.ExitLoop()

    getattr(win.On, win_id).Close = close
    win.On.OkBtn.Clicked = close
    win.Show()
    dispatcher.RunLoop()
    win.Hide()
