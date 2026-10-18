#!/usr/bin/env python3
"""ai-leverage/src/python/tui.py

The pieces manage.sh's menus share, drawn with Textual: lists you move
through by typing an entry's number or letter, running a script in the plain
terminal and coming back, a yes/no question, a README reader, windows of
their own for the live tools, and the theme you picked.

Keys work the same everywhere: in a menu, a box or a pane, typing an
entry's number or letter does it at once, as in a desktop app's menus, and
Esc goes back. The arrows and the mouse only move, and Enter or a click does
the highlighted entry. Whatever can't be undone asks first, in a yes/no box.
The one exception is the main list, where you look at things: a number
there only moves the highlight (which shows that entry's log), and Enter
opens it. A box says its keys in the line at the bottom of the menu (keys()).

Not run on its own: menu.py imports it.
"""

import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import termios
import time
import tty

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.content import Content
from textual.screen import ModalScreen, Screen
from textual.widgets import Markdown, OptionList, Static
from textual.widgets.option_list import Option

import model_fit

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_FILE = os.path.join(BASE_DIR, "config", "menu.conf")
DEFAULT_THEME = "tokyo-night"

# Text that steps back, such as notes and descriptions. Textual's own
# $text-muted shows as full white inside lists, so this one is used instead.
MUTED = "$foreground-muted"


# --- Text ---

INLINE = re.compile(r"`([^`]+)`|\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)]+)\)")


def inline_markdown(text, style=""):
    """A line of Markdown as styled text: `code`, **bold**, and [links] as
    their words"""
    parts, at = [], 0
    for match in INLINE.finditer(text):
        parts.append((text[at:match.start()], style))
        code, bold, link, _ = match.groups()
        if code:
            parts.append((code, f"{style} $text-secondary"))
        elif bold:
            parts.append((bold, f"{style} bold"))
        else:
            parts.append((link, style))
        at = match.end()
    parts.append((text[at:], style))
    return Content.assemble(*[(t, s) for t, s in parts if t])


def listed(names):
    """Names as said: "vllm", "vllm and vscode", "vllm, sglang and vscode" """
    names = list(names)
    return " and ".join(names) if len(names) < 3 else ", ".join(names[:-1]) + " and " + names[-1]


def fit(text, width):
    """Text cut to a width with an ellipsis, or padded to it"""
    if len(text) > width:
        return text[:max(0, width - 1)] + "…"
    return text.ljust(width)


EIGHTHS = " ▏▎▍▌▋▊▉"


def bar(share, width, style="$primary", track="$foreground 12%"):
    """A meter: share (0 to 1) of width cells filled, to the eighth of a cell,
    on a track that shows the whole"""
    share = min(1.0, max(0.0, share))
    cells = share * width
    full = int(cells)
    part = int(round((cells - full) * 8))
    if part == 8:
        full, part = full + 1, 0
    pieces = [("█" * full, style)]
    rest = width - full
    if part and rest:
        pieces.append((EIGHTHS[part], f"{style} on {track}"))
        rest -= 1
    pieces.append((" " * rest, f"on {track}"))
    return Content.assemble(*[(t, s) for t, s in pieces if t])


def pill(text, style):
    """A word in a coloured box, for a status"""
    return Content.styled(f" {text} ", f"bold reverse {style}")


def keys_line(*pairs, lit=None):
    """Key hints for the bottom line: ("↑↓", "move"), ("Enter", "open")...
    The pair whose key is lit stands out, such as the one the next Enter does."""
    parts = []
    for key, what in pairs:
        if parts:
            parts.append(("   ", ""))
        parts.append((key, "bold reverse $text-accent" if key == lit else "bold $text-accent"))
        parts.append((f" {what}", "bold" if key == lit else MUTED))
    return Content.assemble(*parts)


# --- Lists you jump through ---

class JumpList(OptionList):
    """A list whose entries carry a number or a letter. Typing one moves the
    highlight there, and Enter or a click does it; nothing happens by typing
    alone. Two digits typed quickly make one number, so 12 reaches entry 12.
    Headings and blank lines are entries no key reaches and the arrows skip.
    A key whose entry can't be done now says why, and the Enter after it
    does nothing, so 5 Enter never does what was highlighted before.

    below/above: the list the arrows move on to past the last or first entry,
    instead of going round to the other end."""

    TYPING_PAUSE = 0.8

    # Left and right move between the menu's sides (the app decides what that
    # means) instead of scrolling sideways
    BINDINGS = [
        Binding("left", "app.side_left", show=False),
        Binding("right", "app.side_right", show=False),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.keys = {}      # "4" or "u" → its entry's index
        self.reasons = {}   # "5" → why that entry can't be done now
        self.below = None
        self.above = None
        self.resized = None  # called when its width changes
        self.refused = False  # the last key typed was an entry that can't be done now
        self.parked = False   # its highlight is put away while something else is shown (park)
        self._typed = ""
        self._typed_at = 0.0

    def fill(self, entries, keep=True, prefer=None):
        """Shows entries: (key or None, text, id, why it's not possible now or
        ""). An entry without an id is a heading or a blank line; one without a
        key can still be chosen with the arrows or the mouse. The highlight
        stays on the entry with the same id when there is one, or else goes to
        the entry prefer names."""
        # bool(): the options are a list set_options fills, so a list empty until now isn't parked
        parked = self.highlighted is None and (self.parked or (not self.has_focus and bool(self.options)))
        was = self.highlighted_option.id if keep and self.highlighted_option else None
        self.keys, self.reasons, options = {}, {}, []
        for key, text, option_id, why in entries:
            if key:
                self.keys[key] = len(options)
                if why:
                    self.reasons[key] = why
            options.append(Option(text, id=option_id, disabled=not option_id or bool(why)))
        self.set_options(options)
        if parked:
            return
        target = next((i for i, o in enumerate(options) if was and o.id == was and not o.disabled), None)
        if target is None:
            target = next((i for i, o in enumerate(options) if prefer and o.id == prefer), None)
        self.highlighted = target if target is not None else self.first_enabled()

    def refill(self, index, text):
        """Changes one entry's text, keeping everything else"""
        self.replace_option_prompt_at_index(index, text)

    def first_enabled(self):
        return next((i for i, o in enumerate(self.options) if not o.disabled), None)

    def last_enabled(self):
        return next((i for i in range(len(self.options) - 1, -1, -1) if not self.options[i].disabled), None)

    def jump(self, key):
        """Highlights the entry for a key. True when the key is one of this list's."""
        if key not in self.keys:
            return False
        if key in self.reasons:
            self.refuse(self.reasons[key])
            self.refused = True
        else:
            self.highlighted = self.keys[key]
            self.refused = False
            self.parked = False
        return True

    def refuse(self, reason):
        """Why an entry can't be done now: in the hint line of the box the list
        is in, where you're looking, or else as a message"""
        said = getattr(self.screen, "refused", None)
        if said:
            said(reason)
        else:
            self.app.notify(reason, timeout=4)

    def type_key(self, character):
        """A typed number or letter, as a jump. True when it was one of this list's."""
        if character.isdigit():
            now = time.monotonic()
            typed = self._typed + character if now - self._typed_at < self.TYPING_PAUSE else character
            if typed not in self.keys:
                typed = character
            self._typed, self._typed_at = typed, now
            return self.jump(typed)
        return self.jump(character.lower())

    def on_key(self, event):
        if event.character and len(event.character) == 1 and event.character.isprintable() \
                and event.character != " " and self.type_key(event.character):
            event.stop()
            event.prevent_default()
        elif event.key != "enter":
            self.refused = False

    def action_select(self):
        if self.refused:
            # Enter after a key that was refused: nothing, rather than what was highlighted before
            self.refused = False
            return
        super().action_select()

    def action_cursor_down(self):
        if self.parked and self.highlighted is None:
            self.unpark()
        elif self.below and self.highlighted == self.last_enabled():
            self.below.enter(first=True)
        else:
            super().action_cursor_down()

    def action_cursor_up(self):
        if self.parked and self.highlighted is None:
            self.unpark()
        elif self.above and self.highlighted == self.first_enabled():
            self.above.enter(first=False)
        else:
            super().action_cursor_up()

    def on_resize(self, event):
        if self.resized:
            self.resized()

    def width(self):
        """Room for an entry's text, inside the list's padding"""
        return max(20, self.scrollable_content_region.width - 2)

    def park(self):
        """Puts the highlight away while something that isn't in the list is
        shown, to bring it back with the next ↑ or ↓"""
        if self.highlighted is not None:
            self._parked = self.highlighted
            self.highlighted = None
        self.parked = True

    def unpark(self):
        self.parked = False
        if self.highlighted is None:
            parked = getattr(self, "_parked", None)
            self.highlighted = parked if parked is not None else self.first_enabled()

    def enter(self, first=True):
        """Moves the focus here, onto the first or last entry"""
        self.focus()
        self.highlighted = self.first_enabled() if first else self.last_enabled()


class MenuList(JumpList):
    """A list in a box over the menu, such as an entry's actions: as in a
    menu, an entry's key does it at once, the highlight follows the mouse,
    and ← closes the box (its screen's close action). A number that starts
    a longer one, such as 1 when there's a 12, waits a moment for the next
    digit before it does entry 1."""

    BINDINGS = [Binding("left", "screen.close", show=False), Binding("right", "screen.noop", show=False)]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.waiting = None  # the timer that does an entry whose number starts a longer one

    def jump(self, key):
        if self.waiting:
            self.waiting.stop()
            self.waiting = None
        found = super().jump(key)
        if not found or self.refused:
            return found
        if key.isdigit() and any(other != key and other.startswith(key) for other in self.keys):
            index = self.keys[key]
            self.waiting = self.set_timer(self.TYPING_PAUSE, lambda: self.act_if(index))
        else:
            self.act()
        return found

    def act_if(self, index):
        self.waiting = None
        if self.highlighted == index:
            self.act()

    def act(self):
        """Does the highlighted entry, as Enter does"""
        self.action_select()

    def _on_mouse_move(self, event):
        super()._on_mouse_move(event)
        index = event.style.meta.get("option")
        if index is not None and index < len(self.options) and not self.options[index].disabled \
                and index != self.highlighted:
            self.highlighted = index
            self.refused = False


# --- Running things in the plain terminal ---

def _ignore(signum, frame):
    pass


def wait_for_key(prompt="Press any key to return to the menu..."):
    """Waits for one key. Keys typed before the prompt don't count, so the
    Enter that started something can't skip what it printed."""
    print(prompt, end="", flush=True)
    fd = sys.stdin.fileno()
    try:
        before = termios.tcgetattr(fd)
    except termios.error:
        return
    try:
        tty.setraw(fd)
        termios.tcflush(fd, termios.TCIFLUSH)
        os.read(fd, 64)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, before)
        print()


def step_aside(app, title, steps, pause=True, report=False, keep_going=False):
    """Runs commands in the plain terminal, with the menu out of the way, as
    if typed in a shell: sudo asks for your password there, Docker shows its
    download bars, a script asks its questions. steps are (command, folder to
    run it in or None, a line to say before it or ""). It stops at the first
    one that fails, unless keep_going. Ctrl+C stops the command, not the
    menu. report says Complete or Failed at the end. Then it waits for a key
    and gives the screen back to the menu. Returns the last exit code."""
    code = failed = 0
    with app.suspend():
        print("\033[H\033[2J", end="")
        print(f"\033[1m{title}\033[0m", flush=True)
        previous = signal.signal(signal.SIGINT, _ignore)
        try:
            for command, folder, say in steps:
                if say:
                    print(f"\n\033[36m{say}\033[0m", flush=True)
                try:
                    code = subprocess.call(command, cwd=folder)
                except OSError as error:
                    print(f"Couldn't run {command[0]}: {error.strerror}")
                    code = 127
                failed = failed or code
                if code != 0 and not keep_going:
                    break
            if report:
                print("\n\033[32mComplete!\033[0m" if not failed else
                      "\n\033[31mFailed. See the messages above.\033[0m")
            if pause:
                print()
                wait_for_key()
        finally:
            signal.signal(signal.SIGINT, previous)
    return failed


# The terminals a window can open in, with what goes before the command
TERMINALS = [("cosmic-term", ["--"]), ("gnome-terminal", ["--"]), ("ptyxis", ["--"]),
             ("konsole", ["-e"]), ("xfce4-terminal", ["-x"]), ("kitty", []),
             ("alacritty", ["-e"]), ("xterm", ["-e"])]


def has_desktop():
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def open_window(command):
    """Opens a command in a terminal window of its own, so the menu stays
    usable. Ctrl+C there stops the command but keeps the window open, to read
    what it printed. False when there's no desktop (e.g. over SSH) or none of
    the known terminals is installed."""
    if not has_desktop():
        return False
    hold = (f"trap true INT; {shlex.join(command)}; echo; "
            "read -n 1 -s -r -p 'Press any key to close...'")
    for terminal, before in TERMINALS:
        if shutil.which(terminal):
            subprocess.Popen([terminal, *before, "bash", "-c", hold], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
    return False


def open_browser(url):
    """Opens an address in the desktop's browser. Returns what went wrong, or
    "" when it opened."""
    if not has_desktop():
        return f"There's no desktop here. Open {url} in a browser on this PC."
    opener = shutil.which("xdg-open")
    if not opener:
        return f"xdg-open is missing. Open {url} in your browser."
    subprocess.Popen([opener, url], start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return ""


# --- A yes/no question ---

def first_key(text, style=""):
    """Text whose first letter is in bold and underlined: the key that does it"""
    return Content.assemble((text[:1], f"{style} bold underline"), (text[1:], style))


class Confirm(ModalScreen):
    """A question in a box over the menu, before something that can't be
    undone, answered "Yes, …" or "No, …". No is highlighted first, as in the
    (y/N) questions, so Enter alone says no. y says yes at once; n, Esc or ←
    say no, as letters work everywhere in the menu. Dismisses with True for
    yes."""

    BINDINGS = [Binding("escape", "close", show=False)]

    def __init__(self, title, body, yes, no):
        super().__init__()
        self.title_text, self.body, self.yes, self.no = title, body, yes, no

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog") as box:
            box.border_title = self.title_text
            box.border_subtitle = "y yes · n or Esc no"
            yield Static(self.body, id="question")
            yield MenuList(id="answers")

    def on_mount(self):
        def said(answer, rest):
            # "Stop them" reads "Yes, stop them"
            return first_key(answer) + Content(f", {rest[:1].lower()}{rest[1:]}")

        answers = self.query_one("#answers", MenuList)
        answers.fill([
            ("y", said("Yes", self.yes), "yes", ""),
            ("n", said("No", self.no), "no", ""),
        ])
        answers.highlighted = answers.keys["n"]
        answers.focus()

    def key_hints(self):
        return [("y", "yes"), ("n or Esc", "no")]

    @on(OptionList.OptionSelected, "#answers")
    def answered(self, event):
        self.dismiss(event.option_id == "yes")

    def action_close(self):
        self.dismiss(False)

    def action_noop(self):
        pass


# --- A choice ---

class Choose(ModalScreen):
    """A choice in a box over the menu, such as how many notifications to
    keep: what it's about at the top, the choices under it, the current one
    marked and highlighted. A choice's number does it at once, as everywhere;
    Esc or ← close the box without changing anything. Dismisses with the
    choice's id, or None."""

    BINDINGS = [Binding("escape", "close", show=False)]

    def __init__(self, title, body, choices, current=None):
        super().__init__()
        self.title_text, self.body, self.current = title, body, current
        self.choices = choices  # (key, label, id)

    def compose(self) -> ComposeResult:
        with Vertical(id="choose") as box:
            box.border_title = self.title_text
            box.border_subtitle = "its number does it · Esc closes"
            yield Static(self.body, id="choose-text")
            yield MenuList(id="choices")

    def on_mount(self):
        choices = self.query_one("#choices", MenuList)
        entries = []
        for key, label, choice_id in self.choices:
            text = Content.assemble((f"{key:>2}  ", MUTED), (label, "bold" if choice_id == self.current else ""))
            if choice_id == self.current:
                text += Content.styled("  ● now", "$success")
            entries.append((key, text, choice_id, ""))
        choices.fill(entries)
        current = next((i for i, (_, _, choice_id) in enumerate(self.choices) if choice_id == self.current), None)
        choices.highlighted = current if current is not None else choices.first_enabled()
        choices.focus()

    def key_hints(self):
        return [("↑↓", "move"), ("its number or Enter", "picks it"), ("Esc", "closes")]

    @on(OptionList.OptionSelected, "#choices")
    def chosen(self, event):
        self.dismiss(event.option_id)

    def action_close(self):
        self.dismiss(None)

    def action_noop(self):
        pass

    def on_click(self, event):
        if event.widget is self:
            self.dismiss(None)


# --- A box of facts ---

class InfoBox(ModalScreen):
    """Facts in a box over the menu, such as About. Esc, ←, Enter or a click
    anywhere closes it."""

    # ← before the box's own scrolling sideways, which it has no use for
    BINDINGS = [Binding("escape", "close", show=False), Binding("enter", "close", show=False),
                Binding("left", "close", show=False, priority=True)]

    def __init__(self, title, body):
        super().__init__()
        self.title_text, self.body = title, body

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="infobox") as box:
            box.border_title = self.title_text
            box.border_subtitle = "Esc closes"
            yield Static(self.body, id="info")

    def on_mount(self):
        self.query_one("#infobox").focus()

    def key_hints(self):
        return [("↑↓", "scroll"), ("Esc", "closes")]

    def action_close(self):
        self.dismiss()

    def on_click(self, event):
        if not event.style.meta.get("@click"):
            self.dismiss()


# --- A README ---

class BackLine(Static):
    """The keys line at the bottom of a full screen; a click on it goes back"""

    def on_click(self):
        self.screen.dismiss()


class Reader(Screen):
    """A folder's README.md, full screen. The arrows, Page Up/Down and the
    mouse scroll it; Esc goes back, like everywhere else, and so do ← and a
    click on the line at the bottom. Links to other READMEs open them here,
    web links in the browser."""

    # ← before the page's own scrolling sideways, which it has no use for
    BINDINGS = [Binding("escape", "back", show=False), Binding("left", "back", show=False, priority=True)]

    def __init__(self, path, crumb):
        super().__init__()
        self.path, self.crumb = path, crumb

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="page") as page:
            page.border_title = f"{self.crumb} › README"
            page.border_subtitle = os.path.relpath(self.path, BASE_DIR)
            yield Markdown(id="readme", open_links=False)
        yield BackLine(id="reader-keys")

    async def on_mount(self):
        await self.load(self.path)
        self.query_one("#page").focus()
        self.show_keys()

    async def load(self, path):
        try:
            with open(path) as f:
                text = f.read()
        except OSError as error:
            text = f"Couldn't read {path}: {error.strerror}"
        self.path = path
        self.query_one("#page").border_subtitle = os.path.relpath(path, BASE_DIR)
        await self.query_one("#readme", Markdown).update(text)
        self.query_one("#page").scroll_home(animate=False)

    def show_keys(self):
        self.query_one("#reader-keys", BackLine).update(
            keys_line(("↑↓ PgUp PgDn", "scroll"), ("Esc", "back to the menu"), ("click", "links")))

    def action_back(self):
        self.dismiss()

    async def on_markdown_link_clicked(self, event):
        event.stop()
        href = event.href
        if re.match(r"^[a-z]+://", href):
            problem = open_browser(href)
            if problem:
                self.notify(problem, timeout=6)
            return
        target = os.path.normpath(os.path.join(os.path.dirname(self.path), href.split("#")[0]))
        if os.path.isdir(target):
            target = os.path.join(target, "README.md")
        if target.endswith(".md") and os.path.isfile(target):
            await self.load(target)
        else:
            self.notify(f"That link goes to {os.path.relpath(target, BASE_DIR)}, which isn't a page to read here.",
                        timeout=5)


# --- The menu's settings: the theme you picked, how many notifications it keeps ---

def setting(key, default):
    """A setting from config/menu.conf, or its default"""
    return model_fit.read_settings(CONFIG_FILE).get(key, default)


def save_setting(key, value):
    model_fit.write_settings(CONFIG_FILE, CONFIG_FILE + ".template", {key: value})


def saved_theme():
    return setting("MENU_THEME", DEFAULT_THEME)


def save_theme(name):
    save_setting("MENU_THEME", name)
