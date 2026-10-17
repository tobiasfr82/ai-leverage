#!/usr/bin/env python3
"""ai-leverage/src/python/console.py

The two panes on the menu's right side. Both are about the entry the list
highlights, so moving through the list is how you switch between them:

- LogPane, at the top: the entry's own log, from src/bash/service.sh logs.
  While its container runs, what it printed since it started and then as it
  comes; once stopped, its last run, which Docker keeps until the container
  is deleted. An entry without a log (a downloader, an app, an engine with
  no container yet) shows what it is instead.
- ActionPane, under it: what was done to the entry since the menu opened:
  Start, Stop, Restart, Rebuild, and the folders' scripts that only print,
  each with the command it ran, what that printed and how it ended. Several
  entries can have something running at once; the list says which.

Each pane works like a window. At the right end of its frame, save writes
what it shows to a text file in logs/, and ▢ gives it the whole area under
the hardware panel (❐ puts it back). A double click on its frame does that
too, as on a title bar, and Esc restores. Keys, as everywhere in the menu: a
letter does it at once. m maximizes or restores (so does Enter), s saves and
b goes back to the list. ctrl+c stops what runs, and everything it started,
as in a terminal; stopping an Update, Revert or Rebuild halfway asks first.

What runs finds src/bash/console first on its PATH, so sudo never waits
there for a password nobody can type (see the sudo in that folder). A line a
command redraws in place (\\r), such as a progress bar, shows as it changes.
The panes show output and can't be typed into, so what asks you something
still runs in the plain terminal (tui.step_aside). Not run on its own:
menu.py uses it.
"""

import codecs
import os
import re
import shlex
import signal
import subprocess
import threading
import time
from collections import deque

from rich.text import Text
from textual.binding import Binding
from textual.content import Content
from textual.geometry import Size
from textual.widgets import RichLog

import stack
from tui import MUTED

LOGS_DIR = os.path.join(stack.BASE_DIR, "logs")
SUDO_DIR = os.path.join(stack.BASE_DIR, "src", "bash", "console")
SERVICE = os.path.join(stack.SCRIPT_DIR, "service.sh")
KEEP_LINES = 5_000    # per run; older lines drop off the top, and out of a saved file
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][A-Za-z0-9]")

# The letters that do something in a pane, at once, and what that is
LETTERS = {"m": "max", "s": "save", "b": "back"}


# What's run in the pane of what was done whose stopping halfway can leave things half done
RISKY = {"Update", "Revert", "Rebuild"}


def elapsed(seconds):
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds < 3600 else f"{seconds // 3600}:{seconds // 60 % 60:02d} h"


def took(seconds):
    """How long something took, as said: 3 s, 2 min 41 s"""
    seconds = int(seconds)
    return f"{seconds} s" if seconds < 60 else f"{seconds // 60} min {seconds % 60} s"


def descendants(pid):
    """The processes a process started, and the ones they started, by their
    parents in /proc"""
    children = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat") as f:
                stat = f.read()
            parent = int(stat[stat.rindex(")") + 2:].split()[1])
        except (OSError, ValueError):
            continue
        children.setdefault(parent, []).append(int(entry))
    found, todo = [], [pid]
    while todo:
        for child in children.get(todo.pop(), []):
            found.append(child)
            todo.append(child)
    return found


def environment(columns=None):
    """The environment what the menu runs gets: src/bash/console first on
    PATH, so sudo never waits for a password, and the width it may use"""
    env = dict(os.environ)
    env["PATH"] = SUDO_DIR + os.pathsep + env.get("PATH", "")
    if columns:
        env["COLUMNS"] = str(columns)
    return env


def newest(line):
    """The newest version of a line a command redrew in place with \\r, such
    as a download's progress bar"""
    parts = [part for part in line.split("\r") if part]
    return parts[-1] if parts else ""


# --- Running commands ---

class Run:
    """Commands run one after another for an entry, what they printed, and
    how it went"""

    def __init__(self, path, title, steps, on_done=None, keep_going=False, kind="action"):
        self.path, self.title, self.kind = path, title, kind
        self.steps = steps            # (command, folder or None, line to say first, "" for the command, None for nothing)
        self.on_done = on_done        # called with the exit code once it's done
        self.keep_going = keep_going  # run every step, even after one failed
        self.lines = deque(maxlen=KEEP_LINES)  # what it printed, without colours, for saving
        self.shown = deque(maxlen=KEEP_LINES)  # the same as shown, (text, style), to lay out again
        self.pending = deque()        # lines the worker read and the pane doesn't show yet
        self.live = None              # the line a command is still writing, such as a progress bar
        self.columns = 100            # the width a command is told its terminal has
        self.busy = True
        self.code = None
        self.started = time.monotonic()
        self.wall = time.time()
        self.proc = None
        self.stopping = False


def launch(app, run, on_output, on_end):
    """Runs a Run's steps in a thread of their own. on_output(run) is called
    in the menu when there's more to show, on_end(run) once it's done."""

    def ui(function, *args):
        # Calls into the menu from the run's thread; nothing once the menu has quit
        try:
            app.call_from_thread(function, *args)
        except Exception:
            pass

    def say(text, style):
        run.pending.append((text, style))
        ui(on_output, run)

    def execute(command, folder):
        """One command, its output into the run as it comes"""
        env = environment(run.columns)
        try:
            # In the menu's own process group, the way its status reads run
            # sudo, which keeps sudo's remembered password working
            proc = subprocess.Popen(command, cwd=folder, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, env=env)
        except OSError as error:
            say(f"Couldn't run {command[0]}: {error.strerror}", "$error")
            return 127
        run.proc = proc
        if run.stopping:
            # Told to stop while it was starting
            send(run, signal.SIGTERM)
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        text, shown = "", 0.0
        while True:
            chunk = proc.stdout.read1(65536)
            text += decoder.decode(chunk, final=not chunk)
            *lines, text = text.split("\n")
            for line in lines:
                run.pending.append((newest(line), None))
            if "\r" in text:
                # Redrawn in place: only its newest version counts
                text = "\r" + newest(text)
            run.live = newest(text) or None
            if not chunk:
                break
            if time.monotonic() - shown > 0.05:
                ui(on_output, run)
                shown = time.monotonic()
        if run.live:
            run.pending.append((run.live, None))
            run.live = None
        proc.wait()
        run.proc = None
        ui(on_output, run)
        return proc.returncode

    def work():
        code = failed = 0
        for command, folder, line in run.steps:
            if run.stopping:
                break
            if line is not None:
                shown = [os.path.relpath(word, stack.BASE_DIR) if word.startswith(stack.BASE_DIR) else word
                         for word in command]
                say(line or "$ " + shlex.join(shown), "bold $text-accent")
            code = execute(command, folder)
            failed = failed or code
            if code and not run.keep_going:
                break
        run.code = failed
        ui(on_end, run)

    threading.Thread(target=work, daemon=True, name=run.title).start()


def send(run, number):
    """Sends a signal to what a run runs and to everything it started, as
    ctrl+c in a terminal reaches them all: a script alone would wait for the
    command it runs. sudo passes it on to its command, which runs as root
    and can't be signalled directly."""
    proc = run.proc
    if not proc or proc.poll() is not None:
        return
    for pid in [proc.pid] + descendants(proc.pid):
        try:
            os.kill(pid, number)
        except (ProcessLookupError, PermissionError):
            pass


def stop(app, run):
    """Stops a run as ctrl+c would, and ends it if it's still there after 3 seconds"""
    if not run.proc:
        return
    run.stopping = True
    send(run, signal.SIGINT)
    app.set_timer(3, lambda: send(run, signal.SIGTERM))


# --- The panes ---

class Pane(RichLog):
    """A pane of text on the right, scrolled with the arrows, Page Up/Down and
    the mouse, framed like a window: its title on the left of the frame, save
    and ▢ (maximize) or ❐ (restore) on the right"""

    BINDINGS = [
        Binding("enter", "enter", show=False),
        Binding("escape", "restore", show=False),
        Binding("left", "app.pane_back", show=False),
        Binding("ctrl+c", "stop", show=False),
    ]

    def __init__(self, **kwargs):
        super().__init__(wrap=True, min_width=20, max_lines=KEEP_LINES * 2, markup=False, **kwargs)
        self.live = 0                # how many of its lines show the line a command is still writing
        self.live_text = None
        self.title_main = Content("")
        self.title_note = Content("")
        self.laid_out_at = None

    # --- What it shows ---

    def source(self):
        """What to show: [(text or Content, style)], and the line still being written or None"""
        return [], None

    def slug(self):
        return "pane"

    def redraw(self):
        """Lays everything out again, for a new entry or a new width"""
        self.clear()
        self.live, self.live_text = 0, None
        lines, live = self.source()
        for text, style in lines:
            self.put(text, style)
        self.show_live(live)

    def parts(self, text, style):
        """A line as what to write, and the width to wrap it at: the pane's.
        A pane out of sight (behind a maximized one) has no width, so its
        lines wrap at the width it had when last in sight."""
        width = self.scrollable_content_region.width
        if width:
            self.wrap_width = width
        else:
            width = getattr(self, "wrap_width", None)
        if isinstance(text, Content):
            return (text.wrap(width) if width else [text]), width
        if not style:
            return [Text.from_ansi(text)], width
        content = Content.styled(text, style)
        return (content.wrap(width) if width else [content]), width

    def put(self, text, style):
        parts, width = self.parts(text, style)
        for part in parts:
            self.write(part, width=width)

    def show_live(self, text):
        """Shows the line a command is still writing in place of the version
        shown before, as a terminal redraws a progress bar"""
        if text == self.live_text:
            return
        self.drop_live()
        if text and self._size_known:
            before = len(self.lines)
            self.put(text, None)
            self.live, self.live_text = len(self.lines) - before, text

    def drop_live(self):
        if self.live:
            del self.lines[-self.live:]
            self._line_cache.clear()
            self.virtual_size = Size(self._widest_line_width, len(self.lines))
            self.refresh()
        self.live, self.live_text = 0, None

    def on_resize(self, event):
        super().on_resize(event)
        if event.size.width and event.size.width != self.laid_out_at:
            self.laid_out_at = event.size.width
            self.redraw()
        self.draw_frame()

    # --- The frame: its title, and the controls at the right ---

    def maximized(self):
        return self.has_class("-max")

    def controls(self):
        """(name, text, what it does) for each control at the right of the frame"""
        if self.maximized():
            size = ("max", "❐", "Restore: back next to the list   m, Enter or Esc")
        else:
            size = ("max", "▢", "Maximize: the whole area under the hardware panel   m, Enter, or a double click on the "
                                "frame")
        return [("save", "save", "Save what this shows as a text file in logs/   s"), size]

    def set_title(self, main, note=None):
        self.title_main = main if isinstance(main, Content) else Content.styled(main, "bold")
        self.title_note = note if isinstance(note, Content) else Content.styled(note or "", MUTED)
        self.draw_frame()

    def draw_frame(self):
        """The title on the left of the top frame, the controls on the right,
        and the frame's own line between them"""
        width = self.outer_size.width
        if width < 16:
            return
        controls = Content.assemble(*[
            Content.styled(f" {text} ", f"bold {MUTED}")
            .stylize(f"@click=app.pane_do({self.id!r}, {name!r})") for name, text, _ in self.controls()])
        title = self.title_main + (Content("  ") + self.title_note if self.title_note.cell_length else Content(""))
        # The frame keeps "╭─ " and " ─╮" at its ends; a space each side of the line
        room = width - 6 - controls.cell_length - 2
        title = title.truncate(max(1, room - 1), ellipsis=True)
        line = "$border" if self.has_focus else "$foreground 20%"
        self.border_title = Content.assemble(title, " ", ("─" * max(1, room - title.cell_length), line), " ", controls)

    def on_focus(self, event):
        self.draw_frame()

    def on_blur(self, event):
        self.draw_frame()

    def on_mouse_move(self, event):
        # The mouse on a control says what it does
        tip = None
        if event.y == 0:
            right = self.outer_size.width - 3
            for name, text, about in reversed(self.controls()):
                if right - len(text) - 2 <= event.x < right:
                    tip = about
                    break
                right -= len(text) + 2
        if tip != self.tooltip:
            self.tooltip = tip

    def on_leave(self, event):
        self.tooltip = None

    def on_click(self, event):
        # A double click on the frame's top, as on a window's title bar
        if event.chain == 2 and event.y == 0:
            self.app.pane_maximize(self)

    # --- Keys ---

    def on_key(self, event):
        character = event.character
        if character and character.lower() in LETTERS and not event.key.startswith("alt+"):
            event.stop()
            self.do(LETTERS[character.lower()])

    def action_enter(self):
        self.do("max")

    def action_restore(self):
        # As for anything maximized in a Textual app, Esc puts it back
        if self.maximized():
            self.app.pane_maximize(self, False)

    def do(self, name):
        if name == "max":
            self.app.pane_maximize(self)
        elif name == "save":
            self.save()
        elif name == "back":
            self.app.pane_back()

    def action_stop(self):
        # As in a terminal: with text selected, ctrl+c copies it; otherwise it stops what runs
        if self.screen.get_selected_text():
            self.screen.action_copy_text()
        else:
            self.stop()

    def stop(self):
        pass

    def save(self):
        """Writes what the pane shows to a file in logs/, which git ignores"""
        lines, live = self.source()
        text = [ANSI.sub("", line.plain if isinstance(line, Content) else line) for line, _ in lines]
        if live:
            text.append(ANSI.sub("", live))
        os.makedirs(LOGS_DIR, exist_ok=True)
        path = os.path.join(LOGS_DIR, f"{self.slug()}_{time.strftime('%Y-%m-%d_%H-%M-%S')}.log")
        try:
            with open(path, "w") as f:
                f.write(f"# {self.title_main.plain} {self.title_note.plain}, from ai-leverage's menu, "
                        f"saved {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("\n".join(text) + "\n")
        except OSError as error:
            self.app.notify(f"Couldn't save it: {error.strerror}", severity="error")
            return
        self.app.notify(f"Saved to {os.path.relpath(path, stack.BASE_DIR)}")


class LogPane(Pane):
    """The highlighted entry's log: live while its container runs, its last
    run once stopped. One reader at a time, for the entry in view."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.item = None
        self.key = None       # what it shows now: (path, state, when it started), to know when that changed
        self.reader = None    # the Run that reads the log
        self.about = []       # what it shows instead of a log: lines of Content

    def slug(self):
        return f"{self.item.name}_log" if self.item else "log"

    def show(self, item, about, has_log, force=False):
        """Shows an entry: its log when has_log, else the lines in about.
        Reads the log again only when the entry or its container changed."""
        key = (item.path, item.docker, item.started, has_log)
        if key == self.key and not force:
            if not has_log:
                self.about = about
                self.redraw()
            return
        self.key, self.item = key, item
        self.end_reader()
        self.border_subtitle = ""
        if has_log:
            running = item.docker in ("running", "restarting")
            run = Run(item.path, f"{item.name} log", [([SERVICE, item.path, "logs"], None, None)], kind="log")
            run.columns = max(40, (self.scrollable_content_region.width or 100))
            self.reader = run
            self.about = []
            self.set_title(item.name + "'s log", "live" if running else "last run")
            self.border_subtitle = Content.styled(f"src/bash/service.sh {os.path.relpath(item.path, stack.BASE_DIR)} logs",
                                                  MUTED)
            launch(self.app, run, self.output, self.ended)
        else:
            self.reader = None
            self.about = about
            self.set_title(item.name, item.crumb)
        self.redraw()

    def end_reader(self):
        if self.reader:
            self.reader.stopping = True
            send(self.reader, signal.SIGTERM)
            self.reader = None

    def source(self):
        if self.reader:
            return list(self.reader.shown), self.reader.live
        return [(line, None) for line in self.about], None

    def output(self, run):
        if run is not self.reader:
            run.pending.clear()
            return
        if run.stopping and run.proc is None and not run.pending:
            return
        self.drop_live()
        while run.pending:
            text, style = run.pending.popleft()
            run.lines.append(ANSI.sub("", text))
            run.shown.append((text, style))
            self.put(text, style)
        self.show_live(run.live)

    def ended(self, run):
        run.busy = False
        if run is not self.reader:
            return
        if not run.stopping and self.item and self.item.docker in ("running", "restarting"):
            # The log ended by itself: the container stopped or crashed
            self.put(f"── {self.item.name} stopped ──", MUTED)
            self.app.log_ended(self.item)

    def stop(self):
        """ctrl+c: stops following the log, and keeps what it shows"""
        run = self.reader
        if run and run.busy and not run.stopping:
            run.stopping = True
            send(run, signal.SIGTERM)
            self.set_title(self.title_main, "not following")
            run.pending.append(("── not following any more; it does again when you come back to this entry ──", MUTED))
            self.output(run)


class ActionPane(Pane):
    """What was done to the highlighted entry since the menu opened, one run
    after the other: its title and when, the commands and what they printed,
    and how it ended"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.runs = {}     # an entry's path → its Runs, oldest first
        self.item = None
        self.hint = ""     # where to find what you can do with the entry, for when nothing was done yet

    def slug(self):
        return f"{self.item.name}_actions" if self.item else "actions"

    def show(self, item, hint=""):
        self.item, self.hint = item, hint
        self.retitle()
        self.redraw()

    def retitle(self):
        if not self.item:
            return
        run = self.latest(self.item.path)
        if run and run.busy:
            note = Content.styled(f"◐ {run.title}  {elapsed(time.monotonic() - run.started)}", "$warning")
        elif run:
            note = Content.styled(f"✗ {run.title} failed" if run.code else f"✓ {run.title}",
                                  "$error" if run.code else MUTED)
        else:
            note = None
        self.set_title(f"What was done to {self.item.name}", note)

    def latest(self, path):
        runs = self.runs.get(path)
        return runs[-1] if runs else None

    def busy(self, path):
        run = self.latest(path)
        return bool(run and run.busy)

    def source(self):
        if not self.item:
            return [], None
        runs = self.runs.get(self.item.path, [])
        if not runs:
            return [(Content.styled(f"Nothing done to {self.item.name} since the menu opened."
                                    + (f" {self.hint}" if self.hint else ""), MUTED), None)], None
        lines = []
        for n, run in enumerate(runs):
            if n:
                lines.append(("", None))
            lines += list(run.shown)
        latest = runs[-1]
        return lines, latest.live if latest.busy else None

    def start(self, item, title, steps, on_done=None, keep_going=False):
        """Runs steps for an entry, shown here while it's the one in view.
        Returns the Run."""
        run = Run(item.path, title, steps, on_done, keep_going)
        run.columns = max(40, (self.scrollable_content_region.width or 100))
        run.pending.append((f"── {title} · {time.strftime('%H:%M:%S')} ──", f"bold {MUTED}"))
        self.runs.setdefault(item.path, []).append(run)
        if self.item and self.item.path == item.path:
            self.redraw()
        self.retitle()
        launch(self.app, run, self.output, self.ended)
        return run

    def shows(self, run):
        return self.item is not None and run.path == self.item.path

    def output(self, run):
        if self.shows(run):
            self.drop_live()
        while run.pending:
            text, style = run.pending.popleft()
            run.lines.append(ANSI.sub("", text))
            run.shown.append((text, style))
            if self.shows(run):
                self.put(text, style)
        if self.shows(run) and run is self.latest(run.path):
            self.show_live(run.live)

    def ended(self, run):
        seconds = took(time.monotonic() - run.started)
        if run.stopping and run.code:
            run.pending.append(("── stopped ──", MUTED))
        elif run.code:
            run.pending.append((f"── failed after {seconds} (exit code {run.code}) ✗ ──", "$error"))
        else:
            run.pending.append((f"── done in {seconds} ✓ ──", "$success"))
        self.output(run)
        run.busy = False
        self.retitle()
        if run.on_done:
            run.on_done(run.code)

    def note(self, path, text, style="$success"):
        """A line of the menu's own under an entry's latest run, such as when
        its engine is ready"""
        run = self.latest(path)
        if run:
            run.pending.append((text, style))
            self.output(run)

    def stop(self):
        run = self.latest(self.item.path) if self.item else None
        if run and run.busy:
            # Stopping these halfway can leave things half done: ask first
            self.app.stop_run(run, self.item, risky=run.title in RISKY)

    def stop_all(self):
        """Ends everything still running, so the menu can quit"""
        for runs in self.runs.values():
            for run in runs:
                run.stopping = True
                send(run, signal.SIGTERM)

    def tick(self):
        # The time in the title while something runs, and what a quiet command wrote since the last look
        if self.item and self.busy(self.item.path):
            self.retitle()
            self.output(self.latest(self.item.path))
