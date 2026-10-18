#!/usr/bin/env python3
"""ai-leverage/src/python/console.py

What the menu runs, and the pane that shows an entry's log:

- LogPane, right of the list: the highlighted entry's own log, from
  src/bash/service.sh logs. While its container runs, what it printed since
  it started and then as it comes; once stopped, its last run, which Docker
  keeps until the container is deleted. An entry without a log (a
  downloader, an app, an engine with no container yet) shows what it is
  instead.
- Runs: what the menu ran since it opened, such as Start, Stop, Update and
  the folders' scripts that only print, each with the command it ran, what
  that printed and how it ended. Several entries can have something running
  at once. Each one's notification shows how it goes, and its whole log
  (notices.py).

At the right end of the log's frame, save writes what it shows to a text
file in logs/. Keys, as everywhere in the menu: a letter does it at once. s
saves, Esc (or ←) goes back to the list, and a number goes to that entry of
the list. ctrl+c stops following the log.
In a notification's log, ctrl+c stops what runs, and everything it started,
as in a terminal; stopping an Update, Revert or Rebuild halfway asks first.
A script can ask a yes/no question from there too (src/bash/ask.sh): it
writes the question on a channel of its own, AI_LEVERAGE_ASK_FD, apart from
what it prints, and reads the answer back from it. Its card then waits for
you, and the answer is given in its log window.

What runs finds src/bash/console first on its PATH, so sudo never waits
there for a password nobody can type (see the sudo in that folder). What a
command redraws in place, such as a progress bar (with \\r, or by moving the
cursor back up, as Ollama's does), shows as it changes (Redraw). The mouse
selects text in a pane, and ctrl+c copies it.
What's shown can't be typed into, so a script that asks anything else still
runs in the plain terminal (tui.step_aside). Not run on its own: menu.py
uses it.
"""

import codecs
import os
import re
import select
import shlex
import signal
import socket
import subprocess
import threading
import time
from collections import deque

from rich.text import Text
from textual.binding import Binding
from textual.content import Content
from textual.geometry import Size
from textual.strip import Strip
from textual.widgets import RichLog

import stack
from tui import MUTED

LOGS_DIR = os.path.join(stack.BASE_DIR, "logs")
SUDO_DIR = os.path.join(stack.BASE_DIR, "src", "bash", "console")
SERVICE = os.path.join(stack.SCRIPT_DIR, "service.sh")
KEEP_LINES = 5_000    # per run; older lines drop off the top, and out of a saved file
COLUMNS = 118         # the width what runs is told its terminal has: a notification's log window
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][A-Za-z0-9]")

# What a command prints, cut at the terminal's moves: \r, \n, control sequences
# (the cursor up, to a column, clearing a line, colours…), titles and the like
CONTROL = re.compile(r"(\r|\n|\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Za-z0-9]|\x1b[=>78])")
# The start of one of them, at the end of what has come so far: the rest comes next
PARTIAL = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*|\][^\x07\x1b]*|[()])?$")

# Symbols some terminal fonts lack or draw two cells wide, which shifts the rest
# of their row in such a terminal; in what commands print they show as
# look-alikes every font has: check marks as a root sign, crosses as a times
# sign, the warning sign as !, the play triangle as a pointer, framed squares
# as plain ones
SAFE = str.maketrans({"\u2713": "\u221a", "\u2714": "\u221a", "\u2717": "\u00d7", "\u2718": "\u00d7",
                      "\u2715": "\u00d7", "\u2716": "\u00d7", "\u26a0": "!", "\u25b6": "\u25ba",
                      "\u2750": "\u25ab", "\u25a3": "\u25ab", "\u25a2": "\u25a1"})

# The letters that do something in a pane, at once, and what that is
LETTERS = {"s": "save"}


# What's run whose stopping halfway can leave things half done
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


class Redraw:
    """What a command prints, line by line, the way a terminal shows it: \\r
    starts the line over, and a progress display that moves the cursor back
    up redraws the lines under it in place, as Ollama's and tqdm's do. A line
    is done once the cursor is past it for good: REACH lines later, or as
    many as the cursor has gone back up, if that's more. The lines not done
    yet show too, as they are now (live)."""

    REACH = 8  # the last lines kept open, since a progress display may still go back up to them

    def __init__(self):
        self.lines = [""]    # the lines that may still change; the cursor is on one of them
        self.row = 0         # the cursor's line in them; below 0 it's on one that's done
        self.fresh = False   # the next text starts the cursor's line over
        self.reach = self.REACH  # how far back up the cursor may still go
        self.above = ""      # what's written on a line that's done: a line of its own
        self.carry = ""      # the start of a control sequence whose end comes next

    def feed(self, text):
        """More of what it printed. Returns the lines that are done."""
        text, self.carry = self.carry + text, ""
        partial = PARTIAL.search(text)
        if partial:
            text, self.carry = text[:partial.start()], text[partial.start():]
        done = []
        for piece in CONTROL.split(text):
            if not piece:
                continue
            if piece == "\n":
                self.move(1, done)
            elif piece == "\r":
                self.fresh = True
            elif piece.startswith("\x1b["):
                params, final = piece[2:-1], piece[-1]
                count = int(params) if params.isdigit() else 1
                if final == "A":
                    self.move(-count, done)
                elif final == "B":
                    self.move(min(count, len(self.lines) - 1 - self.row), done)
                elif final in "GH":
                    self.fresh = True    # to a column, or the top: what follows starts the line over
                elif final == "K" and (params == "2" or self.fresh) and 0 <= self.row < len(self.lines):
                    self.lines[self.row] = ""
                elif final == "m":
                    self.write(piece)    # colours go with the text
            elif piece[0] != "\x1b":
                self.write(piece)
        cut = min(self.row, len(self.lines) - 1 - self.reach)
        if cut > 0:
            done += self.lines[:cut]
            del self.lines[:cut]
            self.row -= cut
        return done

    def move(self, rows, done):
        """The cursor up (rows below 0) or down, to the start of a line"""
        if self.row < 0 and self.above:
            done.append(self.above)
            self.above = ""
        self.row += rows
        if self.row >= len(self.lines):
            self.lines += [""] * (self.row - len(self.lines) + 1)
        if rows < 0:
            self.reach = max(self.reach, len(self.lines) - 1 - self.row)
        self.fresh = True

    def write(self, text):
        if self.row < 0:
            self.above = text if self.fresh else self.above + text
        elif self.fresh:
            self.lines[self.row] = text
        else:
            self.lines[self.row] += text
        self.fresh = False

    def live(self):
        """The lines that may still change, as they are now"""
        lines = self.lines[:-1] if self.lines[-1] == "" else self.lines
        return "\n".join(lines)

    def close(self):
        """What's left, done: the command has ended"""
        lines = ([self.above] if self.above else []) + (self.lines[:-1] if self.lines[-1] == "" else self.lines)
        self.__init__()
        return lines


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
        self.total = 0                # how many lines it printed in all, older ones dropped or not
        self.pending = deque()        # lines the worker read and the pane doesn't show yet
        self.live = None              # the line a command is still writing, such as a progress bar
        self.columns = 100            # the width a command is told its terminal has
        self.busy = True
        self.code = None
        self.started = time.monotonic()
        self.wall = time.time()
        self.finished = None          # when it was done, as time.monotonic() and as time.time()
        self.finished_wall = None
        self.proc = None
        self.stopping = False
        self.question = None          # what its script asks and waits for: (question, yes, no)
        self.asker = None             # the menu's end of the channel its script asks on


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
        # The channel it can ask on, apart from what it prints: it writes a question there and reads the answer
        mine, theirs = socket.socketpair()
        env["AI_LEVERAGE_ASK_FD"] = str(theirs.fileno())
        try:
            # In the menu's own process group, the way its status reads run
            # sudo, which keeps sudo's remembered password working
            proc = subprocess.Popen(command, cwd=folder, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, env=env, pass_fds=(theirs.fileno(),))
        except OSError as error:
            mine.close()
            say(f"Couldn't run {command[0]}: {error.strerror}", "$error")
            return 127
        finally:
            theirs.close()
        run.proc, run.asker = proc, mine
        if run.stopping:
            # Told to stop while it was starting
            send(run, signal.SIGTERM)
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        screen, shown, ended = Redraw(), 0.0, None
        out, asked, listening = proc.stdout.fileno(), b"", True
        while True:
            ready = select.select([out, mine] if listening else [out], [], [], 0.25)[0]
            if out in ready:
                chunk = os.read(out, 65536)
            elif mine in ready:
                chunk = None
            else:
                # Nothing more for now. Once it has ended, what it left running in the
                # background, still holding its output open, isn't waited for long
                if proc.poll() is None:
                    continue
                ended = ended or time.monotonic()
                if time.monotonic() - ended < 1:
                    continue
                chunk = b""
            if chunk is not None:
                for line in screen.feed(decoder.decode(chunk, final=not chunk)):
                    run.pending.append((line, None))
            if mine in ready:
                # It asks. What it printed before is done: nothing redraws while it waits,
                # and the answer goes under it
                heard = mine.recv(4096)
                listening = bool(heard)
                asked += heard
                while b"\n" in asked:
                    line, asked = asked.split(b"\n", 1)
                    parts = line.decode("utf-8", "replace").split("\t")
                    if parts[0] == "ask" and len(parts) == 4:
                        for done in screen.close():
                            run.pending.append((done, None))
                        run.question = tuple(parts[1:])
                        shown = 0.0
            # The lines it may still redraw, such as a progress bar, show in place
            run.live = screen.live() or None
            if chunk == b"":
                break
            if time.monotonic() - shown > 0.05:
                ui(on_output, run)
                shown = time.monotonic()
        for line in screen.close():
            run.pending.append((line, None))
        run.live = run.question = run.asker = None
        mine.close()
        proc.stdout.close()
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
    """A pane of text, scrolled with the arrows, Page Up/Down and the mouse,
    framed like a window: its title on the left of the frame, its controls,
    such as save, on the right"""

    BINDINGS = [
        Binding("escape", "app.pane_back", show=False),
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
        A pane that has no width at the moment wraps its lines at the width
        it had last."""
        width = self.scrollable_content_region.width
        if width:
            self.wrap_width = width
        else:
            width = getattr(self, "wrap_width", None)
        if isinstance(text, Content):
            return (text.wrap(width) if width else [text]), width
        text = text.translate(SAFE)
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

    # --- Selecting text with the mouse, which ctrl+c copies ---

    def render_line(self, y):
        """A line on screen, with where each part of it is, so the mouse can
        select text, and the selection marked"""
        scroll_x, scroll_y = self.scroll_offset
        index = scroll_y + y
        line = self._render_line(index, scroll_x, self.scrollable_content_region.width)
        selection = self.text_selection
        if selection is not None and index < len(self.lines):
            span = selection.get_span(index)
            if span is not None:
                start, end = span
                end = self.lines[index].cell_length if end == -1 else end
                start, end = max(0, start - scroll_x), min(line.cell_length, end - scroll_x)
                if end > start:
                    before, chosen, after = line.divide([start, end, line.cell_length])
                    marked = chosen.apply_style(self.screen.get_component_rich_style("screen--selection"))
                    line = Strip.join([before, marked, after])
        return line.apply_offsets(scroll_x, index).apply_style(self.rich_style)

    def get_selection(self, selection):
        """The text the mouse selected"""
        return selection.extract("\n".join(line.text for line in self.lines)), "\n"

    def selection_updated(self, selection):
        self._line_cache.clear()
        self.refresh()

    def on_resize(self, event):
        super().on_resize(event)
        if event.size.width and event.size.width != self.laid_out_at:
            self.laid_out_at = event.size.width
            self.redraw()
        self.draw_frame()

    # --- The frame: its title, and the controls at the right ---

    def controls(self):
        """(name, text, what it does) for each control at the right of the frame"""
        return [("save", "save", "Save what this shows as a text file in logs/   s")]

    def click(self, name):
        """The action a click on a control in the frame runs"""
        return f"app.pane_do({self.id!r}, {name!r})"

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
            Content.styled(f" {text} ", f"bold {MUTED}").stylize(f"@click={self.click(name)}")
            for name, text, _ in self.controls()])
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

    # --- Keys ---

    def on_key(self, event):
        character = event.character
        if character and character.lower() in LETTERS and not event.key.startswith("alt+"):
            event.stop()
            self.do(LETTERS[character.lower()])

    def do(self, name):
        if name == "save":
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

    def on_key(self, event):
        # A number goes to that entry of the list, as from the menu bar
        if event.character and event.character.isdigit():
            event.stop()
            self.app.type_in_list(event.character)
            return
        super().on_key(event)

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


class Runs:
    """What the menu runs for its entries, and ran since it opened: each
    entry's Runs, oldest first, with what they printed. changed(run) is
    called in the menu when one printed more or ended, for its notification."""

    def __init__(self, app, changed=None):
        self.app = app
        self.runs = {}     # an entry's path → its Runs, oldest first
        self.changed = changed

    def latest(self, path):
        runs = self.runs.get(path)
        return runs[-1] if runs else None

    def busy(self, path):
        run = self.latest(path)
        return bool(run and run.busy)

    def start(self, item, title, steps, on_done=None, keep_going=False):
        """Runs steps for an entry, in a thread. Returns the Run."""
        run = Run(item.path, title, steps, on_done, keep_going)
        run.columns = COLUMNS
        run.pending.append((f"── {title} · {time.strftime('%H:%M:%S')} ──", f"bold {MUTED}"))
        self.runs.setdefault(item.path, []).append(run)
        launch(self.app, run, self.output, self.ended)
        return run

    def output(self, run):
        """What a run's thread read, into what it printed"""
        while run.pending:
            text, style = run.pending.popleft()
            run.lines.append(ANSI.sub("", text))
            run.shown.append((text, style))
            run.total += 1
        if self.changed:
            self.changed(run)

    def ended(self, run):
        run.finished, run.finished_wall = time.monotonic(), time.time()
        seconds = took(run.finished - run.started)
        if run.stopping and run.code:
            run.pending.append(("── stopped ──", MUTED))
        elif run.code:
            run.pending.append((f"── failed after {seconds} (exit code {run.code}) × ──", "$error"))
        else:
            run.pending.append((f"── done in {seconds} √ ──", "$success"))
        run.busy = False
        self.output(run)
        if run.on_done:
            run.on_done(run.code)
        if self.changed:
            self.changed(run)

    def answer(self, run, yes):
        """Your answer to what a run's script asks: into its log, under the
        question, and back to the script, which goes on"""
        if not run.question or not run.asker:
            return
        question, said = run.question, "Yes, " + run.question[1] if yes else "No, " + run.question[2]
        run.question = None
        run.pending.append((f"? {question[0]}  {said}", "bold $primary"))
        try:
            run.asker.sendall(b"y\n" if yes else b"n\n")
        except OSError:
            pass
        self.output(run)

    def note(self, path, text, style="$success"):
        """A line of the menu's own under an entry's latest run, such as when
        its engine is ready"""
        run = self.latest(path)
        if run:
            run.pending.append((text, style))
            self.output(run)

    def stop_all(self):
        """Ends everything still running, so the menu can quit"""
        for runs in self.runs.values():
            for run in runs:
                run.stopping = True
                send(run, signal.SIGTERM)

    def tick(self):
        # What a quiet command wrote since the last look
        for runs in self.runs.values():
            if runs and runs[-1].busy:
                self.output(runs[-1])
