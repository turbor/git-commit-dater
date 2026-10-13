#!/usr/bin/env python3
"""TUI/CLI to create or amend a git commit with a chosen author+committer date.

This file is also meant to be readable by people new to Textual (the TUI
framework). Textual lets you build terminal user interfaces using a model that
feels like building a small web page:

  - An `App` is the whole program.
  - Widgets (Button, Input, DataTable, ...) are the building blocks.
  - `compose()` yields the widgets, describing the UI tree.
  - A CSS string styles and lays out those widgets (sizes, colors, borders).
  - User actions arrive as "messages"; you handle them with `on_*` methods.

Scroll down to `CommitDaterApp` for the UI. The top of the file is plain Python
(date parsing and git helpers) with no Textual involved.
"""

import argparse
import calendar
import os
import subprocess
import sys
from datetime import datetime

# --- Textual imports -------------------------------------------------------
# `App` is the base class for the whole TUI program. `ComposeResult` is just
# the return-type annotation used by `compose()` methods.
from textual.app import App, ComposeResult
# `events` holds event classes such as `events.Resize` (sent when the terminal
# size changes).
from textual import events
# Containers are invisible widgets that arrange their children. `Horizontal`
# lays children left-to-right, `Vertical` top-to-bottom, and `VerticalScroll`
# is a vertical container that adds a scrollbar if its content overflows.
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.coordinate import Coordinate
# The actual on-screen widgets we use.
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Input,
    Label,
    Static,
    TextArea,
)

# Column headers for the calendar table (Monday-first).
WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]

# Date/time formats accepted on the command line (see `parse_date`). strptime
# codes: %Y=year %m=month %d=day %H=hour %M=minute %S=second.
DATE_FORMATS = [
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y",
]

# Pre-rendered, indented list of the formats above, shown in `--help`.
DATE_FORMATS_HELP = "\n".join(f"    {f}" for f in DATE_FORMATS)


# ===========================================================================
# Plain helpers (no Textual here) - date handling and git calls.
# ===========================================================================


def parse_date(text):
    """Parse one of the supported date formats into a tz-aware datetime.

    Missing time parts default to 0. Raises ValueError if no format matches.
    """
    text = text.strip()
    for fmt in DATE_FORMATS:
        try:
            # `.astimezone()` with no argument attaches the local timezone.
            return datetime.strptime(text, fmt).astimezone()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date/time: {text!r}")


def to_git_date(dt):
    # ISO 8601 with timezone offset, e.g. 2024-12-24T18:30:00+0100. git accepts
    # this for both author and committer dates.
    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")


def run_commit(dt, message, amend):
    """Create or amend a commit, setting both author and committer date.

    Returns (ok, output). On success output is the git date string; on failure
    it is git's stderr/stdout so the caller can show the error.
    """
    git_date = to_git_date(dt)
    # git reads the author date from GIT_AUTHOR_DATE and the committer date from
    # GIT_COMMITTER_DATE. We set both so the two dates match. We also pass
    # `--date` because on `--amend` the author date would otherwise keep its old
    # value (the env var alone is ignored for the author date when amending).
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": git_date,
        "GIT_COMMITTER_DATE": git_date,
    }
    args = ["git", "commit"]
    if amend:
        args.append("--amend")
    args += ["--date", git_date, "-m", message]
    proc = subprocess.run(args, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "git commit failed").strip()
    return True, git_date


def git(*args):
    # Thin wrapper to run a git command and capture its output as text.
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
    )


def in_git_repo():
    r = git("rev-parse", "--is-inside-work-tree")
    return r.returncode == 0 and r.stdout.strip() == "true"


def last_commit_message():
    # %B = raw commit body (full message). Empty string if there is no commit.
    r = git("log", "-1", "--pretty=%B")
    return r.stdout.rstrip("\n") if r.returncode == 0 else ""


def last_commit_date():
    # %cd = committer date, formatted by the --date option. %A = weekday name.
    r = git("log", "-1", "--pretty=%cd", "--date=format:%Y-%m-%d %H:%M:%S %A")
    return r.stdout.strip() if r.returncode == 0 else ""


def has_head():
    # True if HEAD resolves to a commit (i.e. the repo has at least one commit).
    return git("rev-parse", "--verify", "HEAD").returncode == 0


# ===========================================================================
# Calendar widget.
#
# A custom widget is just a subclass of an existing widget/container. By
# subclassing `Vertical`, instances of CalendarWidget ARE a vertical container,
# and we fill them in via `compose()`.
# ===========================================================================


class CalendarWidget(Vertical):
    def __init__(self, year, month):
        super().__init__()
        # Plain instance attributes holding which month is shown and which day
        # is selected. These are not Textual-specific.
        self.year = year
        self.month = month
        self.selected_day = None

    def compose(self) -> ComposeResult:
        # `compose` describes this widget's children. `yield` each child in the
        # order it should appear. Using `with <Container>():` nests widgets
        # inside that container.
        with Horizontal(id="cal-header"):
            # `id=` gives a widget a unique name we can target from CSS (with
            # `#id`) and look up with `query_one("#id")`. `compact=True` makes a
            # borderless button so it fits on a single line.
            yield Button("<", id="prev-month", compact=True)
            yield Label("", id="month-label")
            yield Button(">", id="next-month", compact=True)
        # The month grid itself. `cursor_type="cell"` lets the user highlight a
        # single cell (a day) with the keyboard or mouse.
        yield DataTable(id="cal-table", cursor_type="cell")

    def on_mount(self):
        # `on_mount` runs once, after the widget has been added to the screen.
        # It is the right place to populate widgets, because now they exist.
        # `query_one` finds a descendant widget; passing the type (DataTable)
        # both narrows the search and gives correct typing.
        table = self.query_one("#cal-table", DataTable)
        table.add_columns(*WEEKDAYS)
        self.render_month()

    def render_month(self):
        # Rebuild the table for `self.year`/`self.month`.
        table = self.query_one("#cal-table", DataTable)
        table.clear()  # remove existing rows (keeps the columns)
        # `Label.update(text)` changes a label's text at runtime.
        self.query_one("#month-label", Label).update(
            f"{calendar.month_name[self.month]} {self.year}"
        )
        # Python's stdlib `calendar` returns weeks as lists of day numbers,
        # using 0 for "no day" (padding at the start/end of the month).
        weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(
            self.year, self.month
        )
        for week in weeks:
            cells = ["" if d == 0 else str(d) for d in week]
            table.add_row(*cells)
        # Re-highlight the previously selected day, if any.
        if self.selected_day is not None:
            self._move_cursor_to_day(self.selected_day)

    def current_day(self):
        """Day under the cursor, falling back to the stored selected day.

        We read the highlighted cell directly instead of relying only on the
        "cell selected" event, so pressing OK works even if the user navigated
        with arrow keys and never pressed Enter on a day.
        """
        table = self.query_one("#cal-table", DataTable)
        try:
            # `cursor_coordinate` is a (row, column) of the highlight;
            # `get_cell_at` returns that cell's value.
            value = table.get_cell_at(table.cursor_coordinate)
        except Exception:
            value = None
        if value and str(value).strip():
            return int(str(value).strip())
        return self.selected_day

    def _move_cursor_to_day(self, day):
        # Find the (row, column) of `day` and move the table cursor there.
        table = self.query_one("#cal-table", DataTable)
        weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(
            self.year, self.month
        )
        for r, week in enumerate(weeks):
            for c, d in enumerate(week):
                if d == day:
                    table.move_cursor(row=r, column=c)
                    return

    def shift_month(self, delta):
        # Move forward/backward one month, wrapping the year as needed.
        m = self.month + delta
        y = self.year
        if m < 1:
            m = 12
            y -= 1
        elif m > 12:
            m = 1
            y += 1
        self.month, self.year = m, y
        self.selected_day = None
        self.render_month()


# ===========================================================================
# The application.
# ===========================================================================


class CommitDaterApp(App):
    # Textual CSS (TCSS). It looks like web CSS but targets widgets. Selectors:
    #   Screen / Button          -> by widget type
    #   #main                    -> by id
    #   .time-input              -> by class (the `classes=` argument)
    #   #cols.stacked #msg       -> a #msg inside a #cols that has class
    #                               "stacked" (used for the responsive layout)
    # Useful values: `1fr` means "take one share of the remaining space"
    # (like flex-grow); `auto` means "size to content".
    CSS = """
    Screen { align: center top; }
    #main { width: 80; height: 1fr; padding: 0 1; }

    /* ----- compact two-column layout (short terminals) -----
       #cols is a Horizontal container, so #left and #right sit side by side. */
    #cols { height: 9; }
    #left { width: 32; height: 9; }
    #right { width: 1fr; height: 9; padding-left: 1; }
    CalendarWidget { height: 9; }

    #cal-header { height: 1; align: center middle; }
    #month-label { width: 1fr; content-align: center middle; text-style: bold; }
    #prev-month, #next-month {
        width: 3; min-width: 3; height: 1; border: none; padding: 0;
    }
    #cal-table { height: 8; }
    #head-info { height: 1; color: $text-muted; }

    #time-row { height: 1; }
    .time-input { width: 4; height: 1; }
    .field-label { width: auto; padding: 0 1 0 0; }
    #msg { height: 4; border: round $accent; }
    #amend { height: 1; }
    #buttons { height: 3; align: right middle; }
    #status { color: $error; height: 1; }

    /* ----- stacked single-column layout (tall terminals) -----
       Adding the "stacked" class to #cols flips it to a vertical layout and
       lets the message box grow to fill the extra vertical space. */
    #cols.stacked { layout: vertical; height: 1fr; }
    #cols.stacked #left { width: 1fr; height: 9; }
    #cols.stacked #right {
        width: 1fr; height: 1fr; padding-left: 0; padding-top: 1;
    }
    #cols.stacked #msg { height: 1fr; }
    """

    # Keyboard shortcuts: (key, action-name, description). "escape" calls
    # `action_cancel` (Textual maps the action name to an `action_*` method).
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self):
        super().__init__()
        # Capture "now" once so the pickers default to the current date/time.
        now = datetime.now()
        self.now = now
        # Build the calendar widget now; we yield it later in `compose`.
        self.cal = CalendarWidget(now.year, now.month)
        self.cal.selected_day = now.day

    def compose(self) -> ComposeResult:
        # Describe the full UI tree. The outer VerticalScroll means the whole
        # form can scroll if a terminal is too small for everything to fit.
        with VerticalScroll(id="main"):
            with Horizontal(id="cols"):
                with Vertical(id="left"):
                    yield self.cal
                with Vertical(id="right"):
                    with Horizontal(id="time-row"):
                        # Each time field is a short Input. `value=` sets the
                        # starting text, `max_length=2` caps it at two digits,
                        # `compact=True` removes the border so the value shows.
                        yield Label("H:", classes="field-label")
                        yield Input(
                            value=f"{self.now.hour:02d}",
                            id="hour",
                            classes="time-input",
                            max_length=2,
                            compact=True,
                        )
                        yield Label("M:", classes="field-label")
                        yield Input(
                            value=f"{self.now.minute:02d}",
                            id="minute",
                            classes="time-input",
                            max_length=2,
                            compact=True,
                        )
                        yield Label("S:", classes="field-label")
                        yield Input(
                            value=f"{self.now.second:02d}",
                            id="second",
                            classes="time-input",
                            max_length=2,
                            compact=True,
                        )
                    yield Label("Commit message:", classes="field-label")
                    # TextArea is a multi-line editor; we seed it with the last
                    # commit message.
                    yield TextArea(last_commit_message(), id="msg")
                    yield Checkbox(
                        "Amend HEAD",
                        value=has_head(),
                        id="amend",
                        compact=True,
                    )
            # These live outside #cols so they always span the full width and
            # sit below the two columns.
            yield Static("", id="head-info")
            yield Static("", id="status")
            with Horizontal(id="buttons"):
                yield Button("Cancel", variant="default", id="cancel")
                yield Button("OK", variant="primary", id="ok")

    def on_mount(self):
        # Runs once after the UI exists. Fill the info line and set the initial
        # layout based on the current terminal height.
        info = last_commit_date()
        self.query_one("#head-info", Static).update(
            f"Last HEAD commit date: {info}" if info else "No HEAD commit yet."
        )
        if not has_head():
            # No commits yet: amending is impossible, so disable the checkbox.
            cb = self.query_one("#amend", Checkbox)
            cb.value = False
            cb.disabled = True
        self._apply_layout(self.size.height)

    # Terminals at least this tall use the roomy stacked layout.
    STACK_MIN_HEIGHT = 28

    def _apply_layout(self, height):
        # `set_class(condition, "name")` adds the class when condition is True
        # and removes it when False. The CSS rules above react to that class.
        cols = self.query_one("#cols")
        cols.set_class(height >= self.STACK_MIN_HEIGHT, "stacked")

    def on_resize(self, event: events.Resize):
        # Textual sends a Resize event whenever the terminal size changes.
        # `event.size` is the new size; we switch layouts to match.
        self._apply_layout(event.size.height)

    # --- Message handlers --------------------------------------------------
    # Textual delivers UI events as "messages". A method named
    # `on_<widget>_<message>` is called automatically for that message. The
    # argument carries details about what happened.

    def on_data_table_cell_selected(self, event: DataTable.CellSelected):
        # Fired when a calendar cell is clicked or Enter is pressed on it.
        value = event.data_table.get_cell_at(event.coordinate)
        if value and str(value).strip():
            self.cal.selected_day = int(str(value).strip())

    def on_button_pressed(self, event: Button.Pressed):
        # Fired for any Button. `event.button.id` tells us which one.
        bid = event.button.id
        if bid == "prev-month":
            self.cal.shift_month(-1)
        elif bid == "next-month":
            self.cal.shift_month(1)
        elif bid == "cancel":
            self.action_cancel()
        elif bid == "ok":
            self.do_commit()

    def action_cancel(self):
        # `self.exit(value)` stops the app; the value is returned from `run()`.
        # None means "cancelled".
        self.exit(None)

    def set_status(self, text):
        # Show an error/status message in the status line.
        self.query_one("#status", Static).update(text)

    def do_commit(self):
        # Gather the inputs, validate them, then create/amend the commit.
        day = self.cal.current_day()
        if day is None:
            self.set_status("Select a day in the calendar.")
            return
        try:
            # `.value` is the current text of an Input widget.
            hour = int(self.query_one("#hour", Input).value)
            minute = int(self.query_one("#minute", Input).value)
            second = int(self.query_one("#second", Input).value)
        except ValueError:
            self.set_status("Hour, minute and second must be numbers.")
            return
        if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
            self.set_status("Hour 0-23, minute 0-59, second 0-59.")
            return

        dt = datetime(
            self.cal.year,
            self.cal.month,
            day,
            hour,
            minute,
            second,
        ).astimezone()

        # `.text` is the full contents of a TextArea.
        message = self.query_one("#msg", TextArea).text
        if not message.strip():
            self.set_status("Commit message is empty.")
            return

        amend = self.query_one("#amend", Checkbox).value

        ok, out = run_commit(dt, message, amend)
        if not ok:
            # Show git's error and stay open so the user can fix things.
            self.set_status(out)
            return
        # Success: close the app and return the committed date string.
        self.exit(out)


# ===========================================================================
# Command-line interface (used when the TUI is not launched).
# ===========================================================================


def build_parser():
    parser = argparse.ArgumentParser(
        prog="git-commit-dater",
        # RawDescriptionHelpFormatter keeps our newlines/indentation in --help.
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Create or amend a git commit, setting BOTH the author and\n"
            "committer date to a chosen value.\n\n"
            "Run with no arguments to launch the interactive TUI (calendar +\n"
            "hour/minute/second picker). Pass --date to commit directly from\n"
            "the command line without the TUI."
        ),
        epilog=(
            "Supported --date formats (local timezone is assumed):\n"
            f"{DATE_FORMATS_HELP}\n\n"
            "Missing time parts default to 00.\n\n"
            "Examples:\n"
            "    git-commit-dater\n"
            "    git-commit-dater --date '2024-12-24 18:30:00' -m 'xmas'\n"
            "    git-commit-dater --date 24.12.2024 --amend\n"
            "    git-commit-dater --date 2024-12-24T18:30:00 -m msg --no-amend\n"
        ),
    )
    parser.add_argument(
        "-d",
        "--date",
        help="Commit date/time. If given, commit directly without the TUI.",
    )
    parser.add_argument(
        "-m",
        "--message",
        help="Commit message. Required with --date unless --amend reuses it.",
    )
    # --amend and --no-amend are mutually exclusive. default=None lets us tell
    # "not specified" apart from an explicit choice.
    amend_group = parser.add_mutually_exclusive_group()
    amend_group.add_argument(
        "--amend",
        dest="amend",
        action="store_true",
        default=None,
        help="Amend HEAD instead of creating a new commit.",
    )
    amend_group.add_argument(
        "--no-amend",
        dest="amend",
        action="store_false",
        help="Force creating a new commit (default in CLI mode).",
    )
    return parser


def run_cli(args):
    # Non-interactive path: parse the date, resolve the message, commit.
    try:
        dt = parse_date(args.date)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        print("Run with --help to see supported formats.", file=sys.stderr)
        sys.exit(2)

    amend = bool(args.amend)
    message = args.message
    if message is None:
        if amend:
            # Reuse the existing message when amending without -m.
            message = last_commit_message()
        else:
            print("--message is required (or use --amend).", file=sys.stderr)
            sys.exit(2)
    if not message.strip():
        print("Commit message is empty.", file=sys.stderr)
        sys.exit(2)

    ok, out = run_commit(dt, message, amend)
    if not ok:
        print(out, file=sys.stderr)
        sys.exit(1)
    print(f"Commit written with date {out}")


def main():
    # Parse args first so `--help` works even outside a git repository.
    args = build_parser().parse_args()

    if not in_git_repo():
        print("Not inside a git repository. Exiting.", file=sys.stderr)
        sys.exit(1)

    if args.date is not None:
        # A date was given: run headless (no TUI).
        run_cli(args)
        return

    # No date: launch the interactive TUI. `.run()` blocks until the app exits
    # and returns whatever we passed to `self.exit(...)`.
    result = CommitDaterApp().run()
    if result:
        print(f"Commit written with date {result}")
    else:
        print("Cancelled.")


if __name__ == "__main__":
    main()
