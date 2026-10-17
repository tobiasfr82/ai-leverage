#!/usr/bin/env python3
"""ai-leverage/src/python/menu.py

The menu manage.sh opens. At the top, a menu bar (menubar.py) with what
isn't about one entry, such as Updates and Stop all, and under it what the
PC has to spare, updated every 2 seconds. On the left,
everything in stack/ and apps/ in the order the parts build on each other.
On the right, two panes about the entry the list highlights: its log at the
top, and what was done to it under that (console.py). So moving through the
list is how you look at things.

Typing an entry's number moves the list to it, which shows its log; Enter
or a click opens what you can do with it, in a box over the menu, where its
number does it at once and b or Esc closes the box: 4 Enter 1 starts the 4th
entry. Alt and a menu's letter opens that menu (menubar.py), where a letter
does its entry at once: Alt+S, u opens the update overview (updates.py).
Whatever can't be undone asks first, in a yes/no box.

The menu shows things and runs scripts; what they do is in the scripts, so
each one works the same typed in a terminal. Start, Stop, Restart, Rebuild,
Update, Revert, Hold and the logs run src/bash/service.sh (an app's,
src/bash/app.sh), and so do the folders' scripts that only print (a "# menu:
console" line at their top), in the pane under the log, while the menu stays
usable. What a script would ask first, the menu asks in a dialog of its own,
and then runs it with --yes. An engine that runs but doesn't answer yet,
such as one still loading its model, says ◐ LOADING until it does. What
asks you more, such as Install or a script that asks questions, runs in the
plain terminal, exactly as from a shell, with the menu out of the way; it
comes back when it's done.

The facts come from stack.py and system.py, which need nothing but Python.
Textual draws them, from src/python's own environment, which manage.sh sets
up with uv.

Usage: python -I menu.py    (manage.sh starts it)
"""

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import textual  # noqa: E402
from textual import on, work  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.command import DiscoveryHit, Hit, Provider  # noqa: E402
from textual.containers import Horizontal, Vertical  # noqa: E402
from textual.content import Content  # noqa: E402
from textual.markup import escape  # noqa: E402
from textual.screen import ModalScreen  # noqa: E402
from textual.widgets import OptionList, Static  # noqa: E402

import stack  # noqa: E402
import system  # noqa: E402
import tui  # noqa: E402
import console  # noqa: E402
import updates  # noqa: E402
from console import SERVICE, ActionPane, LogPane, Pane, elapsed  # noqa: E402
from tui import MUTED, JumpList, MenuList, fit, listed, pill  # noqa: E402
from menubar import Entry, MenuBar, MenuDropdown, mnemonics  # noqa: E402
from updates import UpdatesMenu, newest_of  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT_DIR = stack.SCRIPT_DIR
GiB = system.GiB

# How the list shows an engine's or service's state in Docker, and an app's:
# a symbol, the word the menus have always used, and its colour
DOCKER_STATES = {
    "running": ("●", "UP", "$success"),
    "restarting": ("●", "RESTARTING", "$error"),
    "stopped": ("○", "STOPPED", MUTED),
    "": ("○", "DOWN", MUTED),
    "?": ("?", "UNKNOWN", MUTED),
}
APP_STATES = {
    "installed": ("●", "INSTALLED", "$success"),
    "held": ("●", "HELD", "$warning"),
    "other": ("◐", "OTHER INSTALL", "$warning"),
    "missing": ("○", "NOT INSTALLED", MUTED),
}
WAITING = ("·", "…", MUTED)

# What an entry's row says while something runs for it
BUSY_WORDS = {"start": "STARTING", "restart": "STARTING", "stop": "STOPPING", "rebuild": "REBUILDING",
              "script": "RUNNING", "update": "UPDATING", "revert": "REVERTING", "hold": "HOLDING",
              "release": "RELEASING", "queued": "QUEUED"}

# What the pane of what was done calls each update step
STEP_TITLES = {"update": "Update", "revert": "Revert", "hold": "Hold", "release": "Release the hold"}

# What each state means, for the facts about an entry
STATE_MEANS = {
    "running": "It runs.",
    "loading": "It runs, but doesn't answer yet: it's still loading. Its log shows how far it got.",
    "restarting": "It keeps crashing and starting again.",
    "stopped": "It's stopped. Start brings it back as it was.",
    "": "It has no container yet: Start creates one.",
    "?": "Docker's state wasn't read: Stack › Refresh asks for your password.",
}

# Widths of the list's columns
NAME_WIDTH = 14
STATUS_WIDTH = 15
VERSION_WIDTH = 11
LABEL_WIDTH = 13

# The menu bar's menus: (id, title, entries). Each menu's letter (Alt and it
# opens the menu) and each entry's letter (unique in its menu) are worked out
# from the words, in menubar.py, so a new entry or menu needs no letter of its own.
MENUS = [
    ("app", "AI Leverage", [
        Entry("About AI Leverage", "about", "What this is, which version runs, and where it keeps things."),
        Entry("Theme…", "theme", "Picks the menu's colours. It remembers them in config/menu.conf."),
        Entry("Quit", "quit", "Leaves the menu (ctrl+q does too). Engines and services keep running, and "
                              "./manage.sh brings it back."),
    ]),
    ("stack", "Stack", [
        Entry("Updates…", "updates",
              "Looks online for newer versions of every engine, service and app, and lists them next to what's "
              "installed. From there: Update all of them, or Update, Revert or Hold one. It asks before it changes "
              "anything."),
        Entry("Refresh", "refresh",
              "Reads the status of everything again: what runs, the versions, and what the last update check found."),
        Entry("Stop all", "stop",
              "Stops every engine and service that runs, the services first. It asks first. Settings and data stay."),
    ]),
    ("models", "Models", [
        Entry("Downloaders", about="Get models onto this PC: each downloader in stack/downloaders, with the "
                                   "models its models.txt lists.", children="downloaders"),
        Entry("Tuning", about="Tune models to this PC: which of them fit for the context you need, and how to run "
                              "each.", children=[
            Entry("Fit…", "fit",
                  "Which of your downloaded models fit on this PC for the context you need, biggest first, and every "
                  "way to run each one."),
        ]),
    ]),
    ("system", "System", [
        Entry("Monitor", "monitor",
              "The GPU's load, memory, power and temperature, which engine uses how much of it, and the CPU, RAM, "
              "disk and network, live, in a window of its own."),
        Entry("Ports", "ports", "Which ports the containers publish on this PC, in a window of its own."),
    ]),
    ("help", "Help", [
        Entry("Keys and mouse", "keys", "How to move around and do things, with the keys and with the mouse."),
        Entry("Find any action…", "palette", "Finds anything the menu can do by a few letters of it, such as "
                                             "\"start vllm\" or \"update hermes\" (ctrl+p does too)."),
        Entry("README", "readme", "Shows ai-leverage's README: what it is, how to start, and how it's laid out."),
    ]),
]
MENU_KEYS = mnemonics(MENUS)

# The groups in stack/ that live in a menu instead of the list, since they're
# used now and then, not every day: a menu entry whose children are the
# group's name lists its folders, in alphabetical order (menu_children).
MENU_GROUPS = {"downloaders"}


def menu_label(name):
    """A folder's name as a menu entry: with a capital, like every entry, so its
    first letter can be its key (huggingface is Huggingface)"""
    return name[:1].upper() + name[1:]


def menu_actions(entries):
    """Every entry that does something, in menus and the menus beside them"""
    for entry in entries:
        if isinstance(entry.children, list):
            yield from menu_actions(entry.children)
        elif entry.action:
            yield entry


LIT = "bold reverse $text-accent"


class StackCommands(Provider):
    """Everything the menu can do, for the command palette (ctrl+p): every
    entry's actions and the tools, found by typing a few letters of them,
    such as "start vllm" or "update hermes". Enter does it, as in the menu."""

    def commands(self):
        app = self.app
        for item in app.all_items:
            for _, _, action, why in app.item_actions(item, 60):
                if not why and action != "back":
                    yield app.command_text(item, action), partial(app.perform, item, action), \
                        app.what_it_does(item, action)
        for _, _, entries in MENUS:
            for entry in menu_actions(entries):
                if entry.action != "palette":
                    yield entry.label.rstrip("…"), partial(app.run_tool, entry.action), entry.about

    async def search(self, query):
        # Each word may match anywhere, so "update hermes" finds "Update hermes to v0.23"
        whole = self.matcher(query)
        words = [self.matcher(word) for word in query.split()]
        for text, command, help_text in self.commands():
            scores = [word.match(text) for word in words]
            if scores and all(scores):
                shown = whole.highlight(text) if whole.match(text) else text
                yield Hit(sum(scores) / len(scores), shown, command, text=text, help=help_text)

    async def discover(self):
        for text, command, help_text in self.commands():
            yield DiscoveryHit(text, command, text=text, help=help_text)


def spoken(seconds):
    """A time it took, as said: 41 s, 2 min 41 s, 1 h 3 min"""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min {seconds % 60} s"
    return f"{seconds // 3600} h {seconds // 60 % 60} min"


def link(url):
    """An address you can click to open in the browser"""
    return Content.from_markup(f"[@click=app.open_link({url!r})]{escape(url)}[/]")


class ActionsMenu(ModalScreen):
    """What you can do with an entry, in a box over the menu: what it is and
    how it's doing at the top, the actions under that, and what the
    highlighted one does at the bottom. Enter or a click does it and closes
    the box; Esc, or b and Enter, closes it without doing anything. Dismisses
    with the action's id, or None."""

    BINDINGS = [Binding("escape", "close", show=False)]

    def __init__(self, item, only=None):
        super().__init__()
        self.item = item
        self.only = only  # the actions to offer, or None for all of them

    def compose(self) -> ComposeResult:
        with Vertical(id="popup"):
            yield Static(id="popup-head")
            yield Static(Content.styled("WHAT YOU CAN DO", f"bold {MUTED}"), id="popup-title")
            yield MenuList(id="popup-actions")
            yield Static(id="popup-hint")

    def on_mount(self):
        popup = self.query_one("#popup")
        popup.border_title = self.item.crumb
        popup.border_subtitle = "its number or letter does it · Esc or b closes"
        self.fill()
        actions = self.query_one("#popup-actions", MenuList)
        actions.highlighted = actions.first_enabled()
        actions.focus()

    def fill(self):
        """Draws what it shows again, such as after the entry's status changed"""
        menu = self.app
        room = self.query_one("#popup").scrollable_content_region.width or 70
        self.query_one("#popup-head", Static).update(menu.item_head(self.item, room))
        actions = menu.item_actions(self.item, room)
        if self.only:
            actions = [entry for entry in actions if entry[2] in self.only or entry[2] == "back"]
        self.query_one("#popup-actions", MenuList).fill(actions)
        self.show_hint()

    def on_resize(self, event):
        self.fill()

    def show_hint(self):
        actions = self.query_one("#popup-actions", MenuList)
        option = actions.highlighted_option
        text = self.app.what_it_does(self.item, option.id) if option else ""
        self.query_one("#popup-hint", Static).update(Content.styled(text, MUTED))

    @on(OptionList.OptionHighlighted, "#popup-actions")
    def highlighted(self, event):
        self.show_hint()

    @on(OptionList.OptionSelected, "#popup-actions")
    def chosen(self, event):
        self.dismiss(None if event.option_id == "back" else event.option_id)

    def action_close(self):
        self.dismiss(None)

    def action_noop(self):
        pass

    def on_click(self, event):
        # A click beside the box closes it, as beside a menu
        if event.widget is self:
            self.dismiss(None)


class Menu(App):
    CSS_PATH = "menu.tcss"
    TITLE = "AI Leverage"
    COMMANDS = App.COMMANDS | {StackCommands}
    # F10 opens the menu bar, and Alt with a menu's letter opens that menu, as in most desktop apps
    # (some terminals keep F10 for their own menus). Before any list or pane sees the letter.
    BINDINGS = [Binding("f10", "menu_key", show=False, priority=True)] + [
        Binding(f"alt+{letter}", f"open_menu({menu_id!r})", show=False, priority=True)
        for menu_id, letter in MENU_KEYS.items() if letter]
    # Under 100 columns, the panes go under the list instead of beside it.
    # Under 36 rows, the pane of what was done gets smaller.
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (100, "-wide"), (128, "-very-wide")]
    VERTICAL_BREAKPOINTS = [(0, "-short"), (36, "-tall")]

    def __init__(self):
        super().__init__()
        self.groups = []
        self.items = []          # the list's entries, in order, so entry n is items[n - 1]
        self.menu_items = {}     # a group in MENU_GROUPS → its items, which live in a menu
        self.all_items = []      # both
        self.intros = {}         # an item's path → the first paragraph of its README
        self.docker_ok = None    # None until read, then whether sudo let us ask Docker
        self.reading = False
        self.status_at = ""
        self.models_bytes = None
        self.models_at = 0.0
        self.readings = None
        self.shown = None        # the item the panes show
        self.busy = {}           # an item's path → what its row says while something runs for it
        self.answered = {}       # an item's path → when its container started, once it answered since then
        self.watching = set()    # the paths of items a thread asks until they're ready
        self.announce = {}       # an item's path → "started" and the like, to say once it's clear whether it answers
        self.open_menu_id = None  # the menu bar's menu that's open, if any
        self.log_timer = None
        self.check = None        # the update check (updates.Check) since the menu opened, if any
        self.version = stack.stack_version()

    def compose(self) -> ComposeResult:
        yield MenuBar(MENUS, id="menubar", classes="panel")
        yield Static(id="system", classes="panel")
        with Horizontal(id="main"):
            yield JumpList(id="stack", classes="panel")
            yield LogPane(id="log", classes="panel")
            yield ActionPane(id="actions", classes="panel")
        yield Static(id="keys")

    # --- Starting ---

    def on_mount(self):
        theme = tui.saved_theme()
        self.theme = theme if theme in self.available_themes else tui.DEFAULT_THEME
        self.theme_changed_signal.subscribe(self, self.theme_changed)
        self.query_one("#system").border_title = "This PC"
        stack_list = self.query_one("#stack", JumpList)
        stack_list.border_title = "Stack"
        stack_list.resized = self.fill_stack
        # ↑ past the list's top entry goes to the menu bar
        stack_list.above = self.query_one(MenuBar)
        self.discover()
        stack_list.focus()
        self.read_system()
        self.set_interval(2, self.read_system)
        self.set_interval(1, self.tick)
        self.read_status()

    def theme_changed(self, theme):
        if theme.name != tui.saved_theme():
            tui.save_theme(theme.name)

    def discover(self):
        found = stack.discover()
        self.groups = [group for group in found if group[0] not in MENU_GROUPS]
        self.menu_items = {}
        for group, _, members in found:
            if group in MENU_GROUPS:
                self.menu_items[group] = sorted(members, key=lambda item: item.name.lower())
        self.items = [item for _, _, members in self.groups for item in members]
        self.all_items = self.items + [item for members in self.menu_items.values() for item in members]
        self.intros = {item.path: stack.readme_intro(item.path) for item in self.all_items}
        self.fill_stack()
        self.draw_menubar()

    # --- The top: the menu bar, and what the PC has to spare ---

    @work(thread=True, exclusive=True, group="system", exit_on_error=False)
    def read_system(self):
        if time.monotonic() - self.models_at > 30:
            self.models_bytes, self.models_at = system.models_size(), time.monotonic()
        readings = (system.disk(), self.models_bytes, system.memory(), system.gpus())
        self.call_from_thread(self.show_system, readings)

    def show_system(self, readings=None):
        self.readings = readings or self.readings
        if not self.readings:
            return
        disk, models, memory, gpus = self.readings
        panel = self.query_one("#system", Static)
        width = max(40, panel.scrollable_content_region.width or self.size.width - 4)
        meter = max(10, min(32, width // 5))
        lines = []

        def row(label, share, style, *rest):
            parts = [(f"{label:<6}", "bold"), tui.bar(share, meter, style), "  "]
            parts += [p for p in rest if p]
            lines.append(Content.assemble(*parts))

        if disk:
            free, total = disk
            style = ("", "$warning", "$error")[system.disk_level(free)]
            row("Disk", 1 - free / total if total else 0, style or "$primary",
                (f"{system.human(free)} free / {system.human(total)}", style),
                (f" · models use {system.human(models)}", MUTED) if models else None)
        if memory:
            total, available, swapped = memory
            style = ("", "$warning", "$error")[system.ram_level(available)]
            row("RAM", 1 - available / total if total else 0, style or "$primary",
                (f"{system.human(available)} free / {system.human(total)}", style),
                (f" · {system.human(swapped)} swapped", "$warning") if swapped > system.SWAP_WARNING else None)
        if gpus is None:
            lines.append(Content.assemble(("GPU   ", "bold"), ("no NVIDIA GPU found (nvidia-smi is missing)", MUTED)))
        elif not gpus:
            lines.append(Content.assemble(("GPU   ", "bold"), ("the NVIDIA driver doesn't answer", "$error")))
        for gpu in gpus or []:
            label = "GPU" if len(gpus) == 1 else f"GPU {gpu['index']}"
            used, total = gpu["used"] or 0, gpu["total"] or 0
            temp_style = ("", "$warning", "$error")[system.temp_level(gpu["temp"])]
            row(label, used / total if total else 0, "$accent",
                f"VRAM {used / GiB:.1f} GB used / {total / GiB:.1f} GB",
                (f" · {gpu['load']:.0f}% busy", MUTED) if gpu["load"] is not None else None,
                (f" · {gpu['watts']:.0f} W", MUTED) if gpu["watts"] is not None else None,
                (" · ", MUTED) if gpu["temp"] is not None else None,
                (f"{gpu['temp']:.0f}°C", temp_style or MUTED) if gpu["temp"] is not None else None,
                (f"  {gpu['name'].replace('NVIDIA ', '').replace('GeForce ', '')}", MUTED) if width > 110 else None)
        panel.update(Content("\n").join(lines))

    def base(self):
        """The menu's own screen, under any box that's open"""
        return self.screen_stack[0]

    def draw_menubar(self):
        """The menu bar, with the updates the last check found at its right end"""
        count = len(self.updates_to_do())
        status = Content.styled(f"{count} update{'s' if count != 1 else ''}", "bold $warning") if count else None
        self.base().query_one(MenuBar).draw(self.open_menu_id, status, self.version)

    def action_open_menu(self, menu_id, highlight=None):
        """Opens a menu of the menu bar under its title. With a menu open, it
        switches to this one, or closes it when it's the one open, as a click
        on an open menu's title does."""
        if isinstance(self.screen, MenuDropdown):
            if self.screen.menu_id == menu_id:
                self.screen.dismiss(None)
            else:
                self.screen.show(menu_id, highlight)
            return
        if self.screen is not self.base():
            return

        def chosen(action):
            self.menu_opened(None)
            if action:
                self.run_tool(action)

        self.push_screen(MenuDropdown(self.base().query_one(MenuBar), menu_id, highlight), chosen)

    def open_menu(self, menu_id, highlight=None):
        self.action_open_menu(menu_id, highlight)

    def action_menu_key(self):
        """F10: opens the first menu, or closes the one open"""
        if isinstance(self.screen, MenuDropdown):
            self.screen.dismiss(None)
        elif self.screen is self.base():
            self.open_menu(MENUS[0][0])

    def menu_opened(self, menu_id):
        """Lights the open menu's title, or none"""
        self.open_menu_id = menu_id
        if menu_id:
            self.base().query_one(MenuBar).cursor = menu_id
        self.draw_menubar()
        if menu_id is None:
            self.show_keys(self.focus_name())

    def menu_hint(self, entry):
        """What the highlighted entry of an open menu does, in the line at the bottom"""
        keys = self.base().query_one("#keys", Static)
        about = entry.about + (" → or Enter opens it." if entry.children else "")
        text = Content.assemble(("Enter", LIT), (f" {entry.label.rstrip('…')}: ", "bold"),
                                tui.inline_markdown(about, MUTED))
        keys.update(text.truncate(max(20, self.size.width - 2), ellipsis=True))

    def menu_entries(self, menu_id):
        """A menu's entries"""
        return next(entries for found, _, entries in MENUS if found == menu_id)

    def menu_children(self, entry):
        """The entries of the menu beside an entry: its own, or one for each
        folder of the group it names, in alphabetical order"""
        if isinstance(entry.children, list):
            return entry.children
        return [Entry(menu_label(item.name), f"open:{item.path}", self.intros.get(item.path) or f"Opens {item.name}.")
                for item in self.menu_items.get(entry.children, [])]

    def menu_place(self, item):
        """Where an item that isn't in the list lives: "Models › Downloaders › huggingface", or "" """
        if item in self.items or item.group not in MENU_GROUPS:
            return ""
        for _, title, entries in MENUS:
            for entry in entries:
                if entry.children == item.group:
                    return f"{title} › {entry.label} › {menu_label(item.name)}"
        return ""

    def show_off_list(self, item):
        """Shows an item that lives in a menu on the right, as if the list had
        it: the list's highlight steps aside until the next ↑ or ↓"""
        self.base().query_one("#stack", JumpList).park()
        self.show(item)

    def leave_menubar(self):
        self.base().query_one("#stack", JumpList).focus()

    def menu_note(self, entry):
        """A word next to a menu entry, such as how many updates the last
        check found, or what a downloader runs now"""
        pane = self.base().query_one(ActionPane)
        if isinstance(entry.children, str):
            running = sum(pane.busy(item.path) for item in self.menu_items.get(entry.children, []))
            return Content.styled(f"◐ {running} running", "$warning") if running else None
        action = entry.action
        if action.startswith("open:"):
            run = pane.latest(action[5:])
            if run and run.busy:
                return Content.styled(f"◐ {run.title}", "$warning")
            return None
        if action == "updates":
            count = len(self.updates_to_do())
            return Content.styled(f"{count} found", "$warning") if count else None
        return None

    def menu_why(self, entry):
        """Why a menu entry can't be done now, or "" """
        if entry.action == "stop" and self.docker_ok and not any(
                item.kind == "service" and item.docker in ("running", "restarting") for item in self.items):
            return "Nothing is running."
        return ""

    def type_in_list(self, character):
        """A number typed in an open menu: it closes, and the list jumps"""
        stack_list = self.base().query_one("#stack", JumpList)
        stack_list.focus()
        stack_list.type_key(character)

    # --- The left: the stack and the apps ---

    def state_of(self, item):
        """(symbol, word, colour) for an item's status in the list"""
        if item.path in self.busy:
            word = self.busy[item.path]
            return ("·", word, MUTED) if word == BUSY_WORDS["queued"] else ("◐", word, "$warning")
        if item.kind == "service":
            if self.docker_ok is None:
                return WAITING
            if self.loading(item):
                took = f" {elapsed(max(0, time.time() - item.started))}" if item.started else ""
                return ("◐", "LOADING" + took, "$warning")
            return DOCKER_STATES.get(item.docker, DOCKER_STATES["?"])
        if item.kind == "app":
            if not item.loaded:
                return WAITING
            if item.app_state == "installed" and item.held:
                return APP_STATES["held"]
            return APP_STATES.get(item.app_state, APP_STATES["missing"])
        return ("", "", "")

    def found_for(self, item):
        """What the update check found about an item: (result, installed,
        newest, note), from the check that runs or ran since the menu opened,
        else from the last one (cache/updates), or None"""
        found = self.check.rows.get(updates.where(item.path)) if self.check else None
        return found or stack.update_found(item)

    def newer(self, item):
        """The newer version the last update check found, e.g. "v0.40.5", or "" """
        found = self.found_for(item)
        return newest_of(found) if found and found[0] == "newer" else ""

    def updates_to_do(self):
        """The items Update all updates: the check found a newer version, and they aren't held"""
        return [item for item in self.items if item.kind in ("service", "app")
                and (self.found_for(item) or ("",))[0] == "newer" and not item.held]

    def item_line(self, number, item, width):
        symbol, word, style = self.state_of(item)
        parts = [(f"{number:>2}  ", MUTED), (fit(item.name, NAME_WIDTH), "bold"), " ",
                 (fit(f"{symbol} {word}" if word else "", STATUS_WIDTH), style)]
        room = width - 4 - NAME_WIDTH - 1 - STATUS_WIDTH
        newer = self.newer(item)
        hint = f"↑ {newer}" if newer else ""
        # The version, then a newer one when the last check found it; short of
        # room, the newer one takes the version's place
        if room >= 1 + VERSION_WIDTH + (len(hint) + 1 if hint else 0):
            parts.append((" " + fit(item.version, VERSION_WIDTH), MUTED))
        if hint and room >= len(hint) + 1:
            parts.append((" " + hint, "$warning"))
        line = Content.assemble(*parts)
        if item.kind == "service" and item.docker == "running" and item.info:
            line += Content.assemble("\n", (fit(f"    └ {item.info}", width).rstrip(), MUTED))
        return line

    def fill_stack(self):
        stack_list = self.query_one("#stack", JumpList)
        width = stack_list.width()
        entries, number = [], 0
        for index, (group, about, members) in enumerate(self.groups):
            if index:
                entries.append((None, Content(" "), None, ""))
            entries.append((None, Content.assemble((f"{group.upper():<13}", "bold $text-primary"),
                                                   (about, MUTED)), None, ""))
            for item in members:
                number += 1
                entries.append((str(number), self.item_line(number, item, width), f"item-{number}", ""))
        if not entries:
            entries.append((None, Content.styled(f"Nothing found in {stack.STACK_DIR}", "$error"), None, ""))
        shown = next((n for n, item in enumerate(self.items, 1) if item is self.shown), None)
        stack_list.fill(entries, prefer=f"item-{shown}" if shown else None)

    def redraw_item(self, item):
        """Draws an entry's row again, and what shows it: the panes, and the
        box of its actions when it's open"""
        number = next((n for n, known in enumerate(self.items, 1) if known is item), None)
        stack_list = self.base().query_one("#stack", JumpList)
        index = stack_list.keys.get(str(number)) if number else None
        if index is not None:
            stack_list.refill(index, self.item_line(number, item, stack_list.width()))
        if self.shown is item:
            self.show_log(item)
        if isinstance(self.screen, ActionsMenu) and self.screen.item is item:
            self.screen.fill()
        self.refill_updates()

    def refill_updates(self):
        """Draws the update overview again, when it's open"""
        for screen in self.screen_stack:
            if isinstance(screen, UpdatesMenu):
                screen.fill()
    def item_for(self, option_id):
        """The item a stack entry stands for"""
        if option_id and option_id.startswith("item-"):
            return self.items[int(option_id[5:]) - 1]
        return None

    # --- Reading the status ---

    @work(thread=True, exclusive=True, group="status", exit_on_error=False)
    def read_status(self):
        self.reading = True
        self.call_from_thread(self.show_status_time)
        try:
            ready = stack.sudo_ready()
            states = stack.docker_states() if ready else None
            answered = self.ask_ready(states) if states else {}
            self.call_from_thread(self.got_docker, states, ready, answered)
            items = [item for item in self.items if item.kind == "app" or (ready and item.kind == "service")]
            stack.load_statuses(items, each=lambda item: self.call_from_thread(self.redraw_item, item))
        finally:
            self.reading = False
            self.call_from_thread(self.status_read)

    def got_docker(self, states, ready, answered):
        self.docker_ok = ready and states is not None
        self.answered.update(answered)
        stack.apply_docker(self.items, states)
        for item in self.items:
            if self.loading(item):
                self.watch(item)
        self.tell_started()
        self.fill_stack()
        self.show_stack_title()
        if self.shown:
            self.show_log(self.shown)

    def status_read(self):
        self.status_at = time.strftime("%H:%M:%S")
        self.show_status_time()
        self.draw_menubar()

    def show_stack_title(self):
        """The list's title, with how many run, how many still load and how
        many keep crashing"""
        services = [item for item in self.items if item.kind == "service"]
        loading = sum(self.loading(item) for item in services)
        up = sum(item.docker == "running" for item in services) - loading
        crashing = sum(item.docker == "restarting" for item in services)
        title = Content.styled("Stack", "bold")
        if self.docker_ok:
            title += Content.styled(f"  {up} of {len(services)} up", MUTED)
            if loading:
                title += Content.styled(f" · {loading} loading", "$warning")
            if crashing:
                title += Content.styled(f" · {crashing} restarting", "$error")
        self.query_one("#stack").border_title = title

    def show_status_time(self):
        stack_list = self.query_one("#stack", JumpList)
        if self.reading:
            stack_list.border_subtitle = "reading status…"
        elif self.docker_ok is False:
            stack_list.border_subtitle = Content.styled("Docker not read · Stack › Refresh asks for your password", "$warning")
        else:
            stack_list.border_subtitle = f"status as of {self.status_at}"

    # --- Whether what runs is ready ---

    def loading(self, item):
        """Whether an engine or service runs but doesn't answer yet, such as
        an engine still loading its model: its container is up, and the
        address its ai-leverage.ready label names hasn't answered since the
        container started. Without that label, running counts as ready."""
        return (item.kind == "service" and item.docker == "running" and bool(item.ready_url)
                and self.answered.get(item.path) != item.started)

    def ask_ready(self, states):
        """Asks each engine and service that runs whether it's ready, all at
        once, in the status read's thread: {path: when its container started}
        for those that answer. One that answered since its container started
        isn't asked again."""
        asks = []
        for item in self.items:
            found = states.get(item.project) if item.kind == "service" else None
            if found and found.state == "running" and found.ready and self.answered.get(item.path) != found.started:
                asks.append((item.path, found))
        if not asks:
            return {}
        with ThreadPoolExecutor(max_workers=len(asks)) as pool:
            results = list(pool.map(lambda ask: stack.answers(ask[1].ready, timeout=1.5), asks))
        return {path: found.started for (path, found), ok in zip(asks, results) if ok}

    def watch(self, item):
        """Asks an engine or service that's still loading whether it's ready,
        every 2 seconds, in a thread of its own, until it answers or stops
        running. It asks the engine itself, on this PC, so it needs no sudo
        (Docker is still only read after an action and on r)."""
        if item.path in self.watching:
            return
        self.watching.add(item.path)
        started, url = item.started, item.ready_url

        def ask():
            try:
                while item.started == started and self.loading(item):
                    asked = time.monotonic()
                    # An engine may keep the question waiting until it's loaded
                    if stack.answers(url, timeout=30):
                        self.call_from_thread(self.became_ready, item, started)
                        return
                    time.sleep(max(0.0, 2 - (time.monotonic() - asked)))
            except RuntimeError:  # the menu has quit
                pass
            finally:
                self.watching.discard(item.path)

        threading.Thread(target=ask, daemon=True, name=f"ready-{item.name}").start()

    def became_ready(self, item, started):
        if item.started != started or item.docker != "running":
            return
        self.answered[item.path] = started
        took = spoken(time.time() - started) if started else ""
        verb = self.announce.pop(item.path, None)
        if verb:
            self.notify(f"{item.name} {verb}.")
        else:
            self.notify(f"{item.name} is ready" + (f", {took} after it started." if took else "."), timeout=8)
        self.query_one(ActionPane).note(item.path, f"── {item.name} is ready: it answers now"
                                        + (f", {took} after its container started" if took else "") + " ──")
        self.redraw_item(item)
        self.show_stack_title()

    def tell_started(self):
        """Says how Start, Restart or Rebuild went, once the status read after
        it shows whether it runs and answers"""
        for path, verb in list(self.announce.items()):
            item = next((known for known in self.items if known.path == path), None)
            if item and self.loading(item):
                # A moment first, so what loads in a second or two gets one message, not two
                self.set_timer(4, partial(self.tell_loading, item))
                continue
            self.announce.pop(path)
            if not item:
                continue
            if item.docker in ("running", "?"):
                self.notify(f"{item.name} {verb}.")
            else:
                self.notify(f"{item.name} {verb}, but doesn't run now: its log says why.",
                            severity="warning", timeout=8)

    def tell_loading(self, item):
        verb = self.announce.pop(item.path, None) if self.loading(item) else None
        if verb:
            self.notify(f"{item.name} {verb} and is still loading. The list says ◐ LOADING until it answers, "
                        "then ● UP.", timeout=8)

    def tick(self):
        """Moves the clock on the entries that are still loading, and the one
        in the title of what runs"""
        stack_list = self.query_one("#stack", JumpList)
        for number, item in enumerate(self.items, 1):
            if self.loading(item) and item.path not in self.busy:
                index = stack_list.keys.get(str(number))
                if index is not None:
                    stack_list.refill(index, self.item_line(number, item, stack_list.width()))
        self.query_one(ActionPane).tick()

    # --- What an entry is, and what you can do with it ---

    def has_log(self, item):
        """Whether an entry has a log to show: an engine or service with a container"""
        return item.kind == "service" and bool(self.docker_ok) and item.docker in ("running", "restarting", "stopped")

    def item_head(self, item, room):
        """What an entry is and how it's doing: its name, status and version,
        the first paragraph of its README, and its facts"""
        symbol, word, style = self.state_of(item)
        title = Content.assemble((item.name, "bold"), "  ")
        if word and word != "…":
            title += pill(word, style)
        if item.version:
            title += Content.styled(f"  {item.version}", MUTED)
        if item.held:
            title += Content.styled("  held", "$warning")
        about = item.about if item.kind == "app" else self.intros.get(item.path, "")
        text = title
        if about:
            text += Content("\n") + tui.inline_markdown(about, MUTED)
        facts = self.item_facts(item, room)
        if facts.cell_length:
            text += Content("\n\n") + facts
        return text

    def about_lines(self, item):
        """What the log pane shows for an entry without a log"""
        pane = self.query_one(LogPane)
        room = (pane.scrollable_content_region.width or 60)
        lines = self.item_head(item, room).split("\n", allow_blank=True)
        place = self.menu_place(item)
        hint = Content.assemble(("Enter", "bold $text-accent"), (" or a click on it in the list: what you can do", MUTED)) \
            if not place else Content.assemble((place, "bold $text-accent"), (": what you can do with it", MUTED))
        if item.kind == "service" and item.docker == "":
            hint = Content.styled(f"{item.name} has no container yet, so no log. Start creates it, and its log "
                                  "shows here.", MUTED) + Content("\n") + hint
        elif item.kind == "service" and not self.docker_ok:
            hint = Content.styled("Docker wasn't read, so its log can't be: Stack › Refresh asks for your password.",
                                  "$warning") + Content("\n") + hint
        return lines + [Content("")] + hint.split("\n", allow_blank=True)

    def item_facts(self, item, room):
        rows = []
        if item.kind == "service":
            if self.loading(item):
                rows.append(("Status", Content.styled(STATE_MEANS["loading"], "$warning"), ""))
            elif item.docker != "running":
                rows.append(("Status", Content.styled(STATE_MEANS.get(item.docker, ""),
                                                      "$error" if item.docker == "restarting" else ""), ""))
            if item.docker == "running" and item.info:
                key, colon, value = item.info.partition(": ")
                rows.append((key.capitalize() if colon else "Runs", value if colon else item.info, ""))
            if item.docker == "running" and item.url:
                rows.append(("Address", link(item.url), item.url_note))
            connect, note = item.connect()
            if connect:
                rows.append(("Services use", connect, note))
        if item.kind == "app" and item.loaded:
            if item.app_state == "other":
                rows.append(("Installed", f"another way: {item.version}", ""))
            elif item.source:
                rows.append(("Source", item.source, ""))
        if item.kind in ("service", "app") and item.loaded and item.app_state != "other":
            if item.kind == "service" and not item.downloaded:
                rows.append(("Version", Content.styled("not downloaded yet: Start downloads it", MUTED), ""))
            found = self.found_for(item)
            checked = stack.last_check()
            age = f"checked {stack.age_text(checked[0])}" if checked else ""
            if not found:
                rows.append(("Update", Content.styled("not checked yet: Stack › Updates checks", MUTED), ""))
            elif found[0] == "newer":
                rows.append(("Update", Content.assemble((f"{self.newer(item)} available", "$warning"),
                                                       (f" · {age}", MUTED)), ""))
            elif found[0] == "current":
                rows.append(("Update", Content.styled(f"up to date · {age}", MUTED), ""))
            elif found[0] == "failed":
                rows.append(("Update", Content.styled("the last check couldn't tell", "$error"), ""))
            if item.held:
                rows.append(("Held", Content.styled(f"at {item.version or 'its version'}: Update skips it", "$warning"), ""))
            if item.previous:
                rows.append(("Revert", f"goes back to {item.previous}", ""))
        return self.fact_lines(rows, room)

    def fact_lines(self, rows, room):
        """Rows of (label, value, note) as lines: the label in a column of its
        own and the value next to it, wrapped under itself. A short note goes
        after the value, a long one on lines of its own under it."""
        room = max(24, room - LABEL_WIDTH)
        lines = []
        for label, value, note in rows:
            value = value if isinstance(value, Content) else Content(value)
            if note and value.cell_length + 2 + len(note) <= room:
                value += Content.styled(f"  {note}", MUTED)
                note = ""
            for n, part in enumerate(value.wrap(room) or [Content("")]):
                lines.append(Content.assemble((f"{label if n == 0 else '':<{LABEL_WIDTH}}", MUTED), part))
            for part in Content.styled(note, MUTED).wrap(room) if note else []:
                lines.append(Content.assemble(" " * LABEL_WIDTH, part))
        return Content("\n").join(lines)

    def item_actions(self, item, room):
        """(key, text, id, why it can't be done now) for each thing to do with
        an item, numbered as in the menus before: the service's or app's own
        actions first, then the folder's scripts"""
        entries = []

        def add(key, label, action, note="", why="", style=""):
            # One line each: a note too long for it ends in …; the line under
            # the list says it in full
            text = Content.assemble((f"{key:>2}  ", MUTED), (label, MUTED if why else style))
            if note:
                text += Content.styled(f"  {note}", MUTED)
            entries.append((key, text.truncate(max(20, room - 2), ellipsis=True), action, why))

        first = 1
        held = f"{item.name} is held at {item.version or 'its version'}: release the hold first." if item.held else ""
        if item.kind == "service":
            missing = "" if item.downloaded else f"{item.name} isn't downloaded yet: Start downloads it."
            newer = self.newer(item)
            add("1", "Start", "start", "also applies changes in its .env", style="$success")
            add("2", "Stop", "stop", style="$error")
            add("3", "Restart", "restart", style="$primary")
            add("4", "Update", "update", f"to {newer}" if newer else "to its newest stable release",
                why=missing or held, style="$warning")
            add("5", "Revert", "revert", f"to {item.previous}" if item.previous else "none saved yet",
                why=missing or ("" if item.previous else
                                f"No earlier version of {item.name} is saved yet: Revert works after an Update from this menu."),
                style="$secondary")
            if item.held:
                add("6", "Release the hold", "release", f"so Update updates {item.name} again", why=missing, style="bold")
            else:
                add("6", "Hold", "hold", f"at {item.version}" if item.version else "at its version",
                    why=missing, style="bold")
            add("7", "Rebuild", "rebuild", "its container from the images on this PC", style="bold")
            first = 8
        elif item.kind == "app":
            missing = "" if item.app_state != "missing" else f"{item.app_name or item.name} isn't installed."
            newer = self.newer(item)
            add("1", "Install", "install", f"from {item.source}" if item.source else "", style="$success")
            add("2", "Update", "update", f"to {newer}" if newer else "to its newest stable release",
                why=missing or held, style="$warning")
            add("3", "Revert", "revert", f"to {item.previous}" if item.previous else "none saved yet",
                why=missing or ("" if item.previous else
                                f"No earlier version of {item.name} is saved yet: Revert works after an Update from this menu."),
                style="$secondary")
            if item.held:
                add("4", "Release the hold", "release", f"so Update updates {item.name} again", why=missing, style="bold")
            else:
                add("4", "Hold", "hold", f"at {item.version}" if item.version else "at its version",
                    why=missing, style="bold")
            add("5", "Uninstall", "uninstall", "your own files and settings stay", why=missing, style="$error")
            first = 6
        for offset, script in enumerate(item.scripts):
            add(str(first + offset), script[:-3], f"script-{offset}",
                "" if script in item.console else "in the terminal", style="bold")
        if item.readme():
            add("i", f"Read about {item.name}", "readme", "its README")
        if item.kind == "service" and item.docker == "running" and item.url and "API" not in item.url_note:
            add("o", "Open in your browser", "open", item.url,
                why=f"{item.name} is still loading: it opens once it answers." if self.loading(item) else "")
        add("b", "Go back", "back", "Esc", style=MUTED)
        return entries

    def what_it_does(self, item, action):
        """What an action does, in a sentence or two"""
        name = item.name
        if action.startswith("script-"):
            script = item.scripts[int(action[7:])]
            about = stack.script_intro(os.path.join(item.path, script)) or f"Runs {script} in its folder."
            return about + ("" if script in item.console else " It runs in the plain terminal, because it asks things.")
        newer = self.newer(item)
        hints = {
            "start": f"Starts {name}, or creates its container first, and applies changes in its .env. "
                     "Its log shows on the right, and the list says when it's ready.",
            "stop": f"Stops {name}. Its settings and data stay, and Start brings it back.",
            "restart": f"Stops and starts {name} again as it is. Changes in its .env need Start.",
            "update": f"Updates {name} to its newest stable release"
                      + (f" ({newer}, found by the last check)" if newer else "")
                      + ". It says what that changes and asks first, and saves the version it replaces, for Revert.",
            "revert": f"Goes back to {item.previous}, the version before the last update, and holds {name} there "
                      "so Update skips it. It asks first.",
            "hold": f"Keeps {name} at {item.version or 'its version'}: Update and Update all skip it until you release it.",
            "release": f"Ends the hold, so Update updates {name} again.",
            "rebuild": f"Deletes {name}'s container and creates it again from the images already on this PC. "
                       "Its settings and data stay. Update is what gets a newer version. Asks first.",
            "install": f"Installs {item.app_name or name}" + (f" from {item.source}" if item.source else "")
                       + ". Nothing happens if it's there already. It runs in the plain terminal, because it can "
                       "ask things.",
            "uninstall": f"Removes {item.app_name or name}. Your own files and settings stay. Asks first, in the "
                         "plain terminal.",
            "readme": f"Shows {name}'s README: what it is, how to use it, and its settings.",
            "open": f"Opens {item.url} in your browser.",
            "back": "Closes this box. Esc does the same.",
        }
        return hints.get(action, "")

    def command_text(self, item, action):
        """An action as a command, for the command palette: "Start vllm" """
        name = item.name
        if action.startswith("script-"):
            return f"{item.scripts[int(action[7:])][:-3]} ({name})"
        newer = self.newer(item)
        return {
            "start": f"Start {name}", "stop": f"Stop {name}", "restart": f"Restart {name}",
            "update": f"Update {name}" + (f" to {newer}" if newer else ""),
            "revert": f"Revert {name} to {item.previous}", "hold": f"Hold {name} at {item.version or 'its version'}",
            "release": f"Release the hold on {name}", "rebuild": f"Rebuild {name}'s container",
            "install": f"Install {name}", "uninstall": f"Uninstall {name}",
            "readme": f"Read about {name}", "open": f"Open {name} in your browser",
        }.get(action, f"{action} {name}")

    # --- The right: the panes about the highlighted entry ---

    def show(self, item):
        """The panes switch to an entry: what was done to it at once, its log
        once the highlight rests on it for a moment, so moving through the
        list doesn't start a reader for every entry on the way"""
        self.shown = item
        place = self.menu_place(item)
        self.query_one(ActionPane).show(item, f"{place} shows what you can do." if place else
                                        "Enter, or a click on it in the list, shows what you can do.")
        if self.log_timer:
            self.log_timer.stop()
        self.log_timer = self.set_timer(0.25, partial(self.show_log, item))

    def show_log(self, item):
        if item is self.shown:
            self.query_one(LogPane).show(item, self.about_lines(item), self.has_log(item))

    def pane_maximize(self, pane, on=None):
        """Gives a pane the whole area under the hardware panel, or puts it back"""
        on = not pane.maximized() if on is None else on
        if on == pane.maximized():
            return
        other = self.query_one(ActionPane if isinstance(pane, LogPane) else LogPane)
        if on:
            other.remove_class("-max")
            # First, so the list isn't focused as it goes out of sight
            if not pane.has_focus:
                self.screen.set_focus(pane)
        pane.set_class(on, "-max")
        self.screen.set_class(on, "-maximized")
        pane.draw_frame()
        self.show_keys(self.focus_name())

    def pane_back(self):
        """From a pane back to the list"""
        for pane in self.query(Pane):
            if pane.maximized():
                self.pane_maximize(pane, False)
        self.query_one("#stack", JumpList).focus()

    def action_pane_back(self):
        self.pane_back()

    def action_pane_do(self, pane_id, name):
        """A click on a control in a pane's frame"""
        self.query_one(f"#{pane_id}", Pane).do(name)

    def log_ended(self, item):
        """A log the pane followed ended by itself: its container stopped or
        crashed. Reading the status again shows it in the list."""
        self.after_step()

    def on_resize(self, event):
        """A new terminal size: the meters at the top and the list's columns
        are worked out for the width, so draw them again once it's laid out"""
        self.call_after_refresh(self.relayout)

    def relayout(self):
        self.show_system()
        self.draw_menubar()
        self.fill_stack()
        self.show_keys(self.focus_name())

    # --- Moving around ---

    def focus_name(self):
        """What has the focus, as show_keys knows it: stack, log or actions"""
        return self.focused.id if self.focused and self.focused.id in ("stack", "log", "actions", "menubar") else "stack"

    @on(OptionList.OptionHighlighted, "#stack")
    def stack_highlighted(self, event):
        item = self.item_for(event.option_id)
        # The list drawn again (a status read) keeps its entry: that's no move
        if item and item is not self.shown:
            self.show(item)

    def on_descendant_focus(self, event):
        if event.widget.screen is not self.screen_stack[0]:
            return
        if event.widget.id == "stack" and self.screen.has_class("-maximized"):
            # Back in the list: a maximized pane goes back next to it
            for pane in self.query(Pane):
                self.pane_maximize(pane, False)
        self.show_keys(self.focus_name())

    def show_keys(self, focused):
        wide = self.size.width >= 120
        if focused in ("log", "actions"):
            pane = self.query_one(f"#{focused}", Pane)
            pairs = [("↑↓ PgUp PgDn", "scroll")] if wide else [("↑↓", "scroll")]
            if pane.maximized():
                pairs.append(("m, Enter or Esc", "restore"))
            else:
                pairs.append(("m or Enter", "maximize"))
            pairs += [("s", "save"), ("b or ←", "back"),
                      ("ctrl+c", "stop following" if focused == "log" else "stop")]
            self.base().query_one("#keys", Static).update(tui.keys_line(*pairs))
            return
        if self.open_menu_id:
            return  # the open menu says what its entry does
        if focused == "menubar":
            pairs = [("← →", "choose a menu"), ("its letter, Enter or ↓", "opens it"),
                     ("Esc or b", "back to the list"), ("Tab", "next area")]
            self.base().query_one("#keys", Static).update(tui.keys_line(*pairs))
            return
        pairs = [("↑↓", "move"), ("Enter", "what you can do"), ("its number", "jumps to it" if wide else "jumps"),
                 ("→", "its log"), ("Alt+letter", "a menu" if wide else "menus")]
        if wide:
            pairs.append(("F10", "the first menu"))
        pairs.append(("ctrl+p", "find any action" if wide else "more"))
        self.base().query_one("#keys", Static).update(tui.keys_line(*pairs))

    def on_key(self, event):
        if self.focused is None and self.screen is self.screen_stack[0]:
            # Nothing has the focus: the list takes it back
            self.query_one("#stack", JumpList).focus()

    def action_side_right(self):
        if self.focused and self.focused.id == "stack":
            self.query_one(LogPane).focus()

    def action_side_left(self):
        pass

    @on(OptionList.OptionSelected, "#stack")
    def stack_selected(self, event):
        item = self.item_for(event.option_id)
        if item:
            self.open_actions(item)

    def open_actions(self, item, only=None, began=None):
        """The box of what you can do with an entry. began() is called once
        the action chosen there runs, after its question if it has one."""
        def chosen(action):
            if action:
                self.perform(item, action, began)

        self.push_screen(ActionsMenu(item, only), chosen)

    def show_entry(self, item):
        """Moves the list's highlight to an entry, so the panes show it"""
        number = next((n for n, known in enumerate(self.items, 1) if known is item), None)
        stack_list = self.query_one("#stack", JumpList)
        index = stack_list.keys.get(str(number)) if number else None
        if index is not None:
            stack_list.highlighted = index

    # --- Doing things ---

    def step(self, title, steps, pause=True, report=False, keep_going=False):
        code = tui.step_aside(self, title, steps, pause, report, keep_going)
        self.after_step()
        return code

    def after_step(self):
        self.read_status()
        self.draw_menubar()

    def run_tool(self, tool):
        python = [sys.executable, "-I"]
        if tool == "updates":
            self.open_updates()
        elif tool == "fit":
            self.step("AI LEVERAGE › model fit", [([*python, os.path.join(HERE, "fit_screen.py")], None, "")],
                      pause=False)
        elif tool in ("monitor", "ports"):
            script = os.path.join(SCRIPT_DIR, "monitor-system.sh" if tool == "monitor" else "docker-list-ports.sh")
            if tui.open_window([script]):
                self.notify(f"{'The monitor' if tool == 'monitor' else 'The ports'} opened in a window of its own.")
            else:
                self.step(f"AI LEVERAGE › {tool}", [([script], None, "")])
        elif tool == "stop":
            self.stop_all()
        elif tool == "refresh":
            self.refresh_status()
        elif tool == "quit":
            self.exit()
        elif tool == "about":
            self.push_screen(tui.InfoBox("About AI Leverage", self.about_text()))
        elif tool == "theme":
            self.action_change_theme()
        elif tool == "keys":
            self.push_screen(tui.InfoBox("Keys and mouse", self.keys_text()))
        elif tool == "palette":
            self.action_command_palette()
        elif tool == "readme":
            self.push_screen(tui.Reader(os.path.join(stack.BASE_DIR, "README.md"), "AI Leverage"))
        elif tool.startswith("open:"):
            # An item that lives in a menu, such as a downloader: shown on the right, and its box
            item = next((known for known in self.all_items if known.path == tool[5:]), None)
            if item:
                self.show_off_list(item)
                self.open_actions(item)

    def about_text(self):
        """What ai-leverage is, which version runs, and where it keeps things"""
        intro = stack.readme_intro(stack.BASE_DIR)
        remote, _ = stack.run(["git", "-C", stack.BASE_DIR, "remote", "get-url", "origin"], timeout=5)
        remote = remote.strip()
        if remote.startswith("git@github.com:"):
            remote = "https://github.com/" + remote[len("git@github.com:"):]
        remote = remote.removesuffix(".git")
        drawn = f"Textual {getattr(textual, '__version__', '?')}, Python {sys.version.split()[0]}"
        rows = [("Version", self.version or "not a git copy", ""),
                ("Folder", stack.BASE_DIR.replace(os.path.expanduser("~"), "~", 1), ""),
                ("Settings", "config/", "menu.conf, model-fit.conf"),
                ("Drawn with", drawn, "")]
        if remote:
            rows.append(("Source", link(remote) if remote.startswith("http") else remote, ""))
        return Content.assemble(
            ("AI Leverage", "bold"), "\n", tui.inline_markdown(intro, MUTED), "\n\n",
            ("It's a terminal program on purpose: it works the same over ssh, in tmux and on a PC without a "
             "desktop, and sudo asks where you type.", MUTED), "\n\n",
            self.fact_lines(rows, 78))

    def keys_text(self):
        """How to move around and do things, for Help › Keys and mouse"""
        menus = " · ".join(f"Alt+{letter.upper()} {title}" for (_, title, _), letter in zip(MENUS, MENU_KEYS.values()))
        rows = [
            ("The rule", "In the menus and the boxes, an entry's number or letter does it at once, as in a desktop "
                         "app; ↑↓ and the mouse only move, and Enter or a click does the highlighted one. b goes back. "
                         "Whatever can't be undone asks first: y says yes, n, b or Esc no.", ""),
            ("The list", "↑↓ move · an entry's number moves to it, to look at its log · Enter or a click: what you "
                         "can do with it · → its log", ""),
            ("Menus", f"{menus} (the underlined letter) · F10 the first one · a click on a title", ""),
            ("In a menu", "an entry's underlined letter does it at once (Alt+S u opens Updates; Alt+M d h opens "
                          "huggingface) · ↑↓ move, Enter does it · ← → the next menu · ▸ shows a menu beside: → or "
                          "Enter goes in, ← or Esc back out · b one step back", ""),
            ("The bar", "Tab, shift+Tab or ↑ from the list's top · ← → choose a menu · its letter, Enter or ↓ opens "
                        "it · Esc or b back to the list", ""),
            ("Areas", "Tab and shift+Tab go from the bar to the list, the log and the pane of what was done", ""),
            ("Boxes", "an entry's number or letter does it at once (4 Enter 1 starts the 4th entry) · Esc, b, ← or "
                      "a click beside one closes it", ""),
            ("Panes", "↑↓ PgUp PgDn scroll · m, Enter or ▢ maximizes · Esc restores · s saves to logs/ · "
                      "ctrl+c stops what runs (an Update, Revert or Rebuild asks first) · b or ← back to the list", ""),
            ("Anywhere", "ctrl+p finds any action by a few letters of it · ctrl+q quits", ""),
        ]
        return self.fact_lines(rows, 78)

    def exit(self, *args, **kwargs):
        """Ends what still runs, such as the log the pane follows, then quits"""
        self.query_one(ActionPane).stop_all()
        self.query_one(LogPane).end_reader()
        if self.check:
            self.check.stop()
        super().exit(*args, **kwargs)

    def refresh_status(self):
        """Reads the status again. When sudo's time ran out, it asks for the
        password first, in the plain terminal."""
        if not stack.sudo_ready():
            with self.suspend():
                print("\033[H\033[2J\033[1mAI LEVERAGE\033[0m\n")
                print("The menu reads what runs from Docker, which needs sudo.")
                os.system("sudo -v")
        self.query_one(LogPane).key = None  # read the log again too
        self.after_step()

    def sudo_or_ask(self, why="Docker needs sudo", refused="Nothing was started: sudo needs your password."):
        """Whether sudo works without a password now. When its time ran out,
        it asks for the password in the plain terminal first, because the
        panes can't be typed into."""
        if stack.sudo_ready():
            return True
        with self.suspend():
            print("\033[H\033[2J\033[1mAI LEVERAGE\033[0m\n")
            print(f"{why}, and its time ran out.")
            ok = os.system("sudo -v") == 0
        if not ok:
            self.notify(refused, severity="warning")
        return ok

    def still_running(self, item):
        """Whether something still runs for an entry, which another action has to wait for"""
        run = self.query_one(ActionPane).latest(item.path)
        if run and run.busy:
            self.notify(f"{run.title} of {item.name} still runs. Wait for it, or ctrl+c in the pane of what "
                        "was done stops it.", timeout=6)
            return True
        return False

    def stop_all(self):
        if self.docker_ok is False:
            self.notify("Docker's state wasn't read, so the menu doesn't know what runs. "
                        "Stack › Refresh asks for your password.", severity="warning", timeout=6)
            return
        running = [item for item in reversed(self.items)
                   if item.kind == "service" and item.docker in ("running", "restarting")]
        if not running:
            self.notify("Nothing is running.")
            return
        names = ", ".join(item.name for item in running)

        def answered(yes):
            if not yes or not self.sudo_or_ask():
                return
            queue = [item for item in running if not self.still_running(item)]
            failed = []
            for item in queue:
                self.busy[item.path] = BUSY_WORDS["stop"]
                self.redraw_item(item)

            def next_one():
                # One after another, the services first, each in its own entry's pane
                if not queue:
                    self.notify("Stopped them all." if not failed else
                                f"{', '.join(failed)} didn't stop: the pane of what was done to it says why.",
                                severity="error" if failed else "information")
                    self.after_step()
                    return
                item = queue.pop(0)

                def done(code):
                    self.busy.pop(item.path, None)
                    if code:
                        failed.append(item.name)
                    self.redraw_item(item)
                    next_one()

                self.query_one(ActionPane).start(item, "Stop", [([SERVICE, item.path, "stop"], None, "")],
                                                 on_done=done)

            next_one()

        self.push_screen(tui.Confirm("Stop all?", Content.assemble(
            "These run now and stop in this order, the services first:\n", (names, "bold")),
            "Stop them", "Keep them running"), answered)

    def action_run(self, item, action):
        """Start, Stop, Restart or Rebuild, with what it prints in the pane of
        what was done. Its log shows above that once its container runs."""
        if self.still_running(item) or not self.sudo_or_ask():
            return
        # Rebuild asked in the menu's own dialog already
        steps = [([SERVICE, item.path, action] + (["--yes"] if action == "rebuild" else []), None, "")]
        self.busy[item.path] = BUSY_WORDS[action]
        self.redraw_item(item)
        verb = {"start": "started", "restart": "restarted", "stop": "stopped", "rebuild": "rebuilt"}[action]

        def done(code):
            self.busy.pop(item.path, None)
            if code:
                self.notify(f"{action.capitalize()} of {item.name} failed: the pane of what was done to it says why.",
                            severity="error")
            elif action == "stop":
                self.notify(f"{item.name} stopped.")
            else:
                # Said once the status read shows whether it answers (tell_started)
                self.announce[item.path] = verb
            self.after_step()

        self.query_one(ActionPane).start(item, action.capitalize(), steps, on_done=done)

    def action_script(self, item, script):
        """A folder's script that only prints, in the pane of what was done.
        It runs in its folder, as from a terminal there."""
        if self.still_running(item):
            return
        if stack.uses_sudo(os.path.join(item.path, script)) and not self.sudo_or_ask(f"{script} uses sudo"):
            return
        name = script[:-3]
        self.busy[item.path] = BUSY_WORDS["script"]
        self.redraw_item(item)

        def done(code):
            self.busy.pop(item.path, None)
            self.notify(f"{name} ({item.name}) failed: the pane of what was done to it says why." if code else
                        f"{name} ({item.name}) is done.", severity="error" if code else "information")
            self.after_step()

        self.query_one(ActionPane).start(item, name, [([f"./{script}"], item.path,
                                                       f"$ cd {os.path.relpath(item.path, stack.BASE_DIR)} && ./{script}")],
                                         on_done=done)

    # --- Updates ---

    def open_updates(self):
        """The update overview, in a box over the menu. It shows what the last
        check found, and looks online again as it opens."""
        self.check_updates()
        self.push_screen(UpdatesMenu())

    def check_updates(self):
        """Looks online for newer versions of everything, unless that runs
        already (check-updates.sh --print, in a thread). The list, the bar
        and the overview change as each answer comes in."""
        if self.check and self.check.running:
            return
        if not self.sudo_or_ask("Looking for updates reads Docker's images, which needs sudo",
                                refused="Not checked online: sudo needs your password."):
            self.refill_updates()
            return
        self.check = updates.Check()
        self.check.start(self, self.check_row, self.check_ended)
        self.refill_updates()

    def check_row(self, path, found):
        """One answer of the update check, for the item in that folder"""
        if self.check:
            self.check.rows[path] = found
        item = next((known for known in self.items if updates.where(known.path) == path), None)
        if item:
            self.redraw_item(item)
        self.draw_menubar()

    def check_ended(self):
        self.draw_menubar()
        self.refill_updates()
        if not any(isinstance(screen, UpdatesMenu) for screen in self.screen_stack):
            count = len(self.updates_to_do())
            self.notify(f"The update check found {count} update{'s' if count != 1 else ''}: Stack › Updates shows them."
                        if count else "The update check is done: everything is up to date.")

    def sudo_for(self, item):
        """sudo for an update step: Docker needs it, and so does apt"""
        if item.kind == "service":
            return self.sudo_or_ask()
        if item.method == "apt":
            return self.sudo_or_ask(f"{item.app_name or item.name} comes from apt, which needs sudo")
        return True

    def ask_update(self, item, action, began=None):
        """Update or Revert one entry: the menu asks what the script would
        ask, with what it would say first, then runs it with --yes"""
        if self.still_running(item) or not self.sudo_for(item):
            return

        def gathered(data):
            title, body, yes = self.update_question(item, action, data.get(item.path))

            def answered(ok):
                if ok:
                    self.run_update(item, action, began)

            self.push_screen(tui.Confirm(title, body, yes, "Keep it as it is"), answered)

        if item.kind == "service":
            updates.read_data(self, [item], gathered)
        else:
            gathered({})

    def update_question(self, item, action, data):
        """What Update or Revert would change, as (title, text, yes): the
        versions, a restart, and the data it backs up or puts back"""
        name = item.name if item.kind == "service" else item.app_name or item.name
        version = item.version or "its version"
        running = item.kind == "service" and item.docker in ("running", "restarting")
        verb = "updating" if action == "update" else "reverting"
        if action == "update":
            newer = self.newer(item)
            first = Content.assemble((name, "bold"), f" {version} → ",
                                     (newer, "bold $warning") if newer else "its newest stable release, if there's a newer one")
            first += Content.styled(f"\nIt looks online once more first, and keeps {version}, so Revert can go back to it.",
                                    MUTED)
        else:
            first = Content.assemble((name, "bold"), f" goes back from {version} to ", (item.previous, "bold"),
                                     ", and is held there so Update skips it.")
        blocks = [first]
        if running:
            blocks.append(Content.styled(f"{name} is running, so {verb} restarts it: open chats are cut off"
                                         + (", and it loads its model again." if item.group == "engines" else "."),
                                         "$warning"))
        if data:
            about, size = data
            if action == "update":
                blocks.append(Content.styled(f"It backs up {about} first ({size}): a new version may convert that "
                                             "data when it first starts, and Revert can put the backup back.", "$warning"))
            elif item.backup:
                blocks.append(Content.styled(f"It also puts back the copy of {about} made before the update "
                                             f"({item.backup}), after backing up what's there now, so nothing is lost.",
                                             "$warning"))
            else:
                blocks.append(Content.styled(f"There's no copy of {about} from before the update. If the newer version "
                                             "converted it, the older one may not be able to read it.", "$warning"))
        title = f"{'Update' if action == 'update' else 'Revert'} {name}?"
        return title, Content("\n\n").join(blocks), "Update it" if action == "update" else "Revert it"

    def run_update(self, item, action, began=None):
        """Update, Revert, Hold or Release the hold, with what it prints in
        the pane of what was done. Update and Revert were asked already."""
        if self.still_running(item) or not self.sudo_for(item):
            return
        steps = [([updates.tool_for(item), item.path, action] + (["--yes"] if action in ("update", "revert") else []),
                  None, "")]
        title = STEP_TITLES[action]
        self.busy[item.path] = BUSY_WORDS[action]
        self.redraw_item(item)
        if began:
            began(item)

        def done(code):
            self.busy.pop(item.path, None)
            if code:
                self.notify(f"{title} of {item.name} failed: the pane of what was done to it says why.",
                            severity="error")
            else:
                self.notify(f"{title} of {item.name} is done.")
            self.after_step()
            # What it is now, for the list and the overview
            updates.check_one(self, item, self.check_row)

        self.query_one(ActionPane).start(item, title, steps, on_done=done)

    def update_all(self, began=None):
        """Updates every item the check found an update for, one after
        another, each in its own entry's pane, after one question for all"""
        if self.check and self.check.running:
            self.notify("The check still looks online: wait for it.")
            return
        pane = self.query_one(ActionPane)
        todo = [item for item in self.updates_to_do() if not pane.busy(item.path)]
        if not todo:
            self.notify("Nothing to update.")
            return
        if any(item.kind == "service" or item.method == "apt" for item in todo) and not self.sudo_or_ask():
            return

        def answered(yes):
            if not yes:
                return
            queue = [item for item in todo if not pane.busy(item.path)]
            if not queue:
                return
            for item in queue:
                self.busy[item.path] = BUSY_WORDS["queued"]
                self.redraw_item(item)
            if began:
                began(queue[0])
            done_ok, failed = [], []

            def next_one():
                if not queue:
                    if failed:
                        self.notify(f"{listed(failed)} didn't update: the pane of what was done to it says why."
                                    + (f" Updated: {listed(done_ok)}." if done_ok else ""), severity="error",
                                    timeout=10)
                    else:
                        self.notify(f"Updated {listed(done_ok)}.")
                    return
                item = queue.pop(0)
                self.busy[item.path] = BUSY_WORDS["update"]
                self.redraw_item(item)

                def done(code):
                    self.busy.pop(item.path, None)
                    (failed if code else done_ok).append(item.name)
                    self.redraw_item(item)
                    self.after_step()
                    updates.check_one(self, item, self.check_row)
                    next_one()

                pane.start(item, "Update", [([updates.tool_for(item), item.path, "update", "--yes"], None, "")],
                           on_done=done)

            next_one()

        def gathered(data):
            lines = []
            for item in todo:
                notes = []
                if item.kind == "service" and item.docker in ("running", "restarting"):
                    notes.append("running: restarts it")
                if item.path in data:
                    notes.append(f"backs up {data[item.path][0]} first, {data[item.path][1]}")
                lines.append(Content.assemble("  ", (fit(item.name, 14), "bold"), f" {item.version} → ",
                                              (self.newer(item), "$warning"),
                                              (f"  ({'; '.join(notes)})", MUTED) if notes else ""))
            body = Content("These update one after another, each in its own pane under the log:\n")
            body += Content("\n").join(lines)
            if any(item.kind == "service" and item.docker in ("running", "restarting") for item in todo):
                body += Content.styled("\n\nThe running ones restart: open chats are cut off, and an engine loads "
                                       "its model again.", "$warning")
            if data:
                body += Content.styled("\n\nA new version may convert the data it finds, so the old version can't "
                                       "read it after a Revert. The backups let Revert put it back.", "$warning")
            many = len(todo) > 1
            self.push_screen(tui.Confirm("Update all?" if many else f"Update {todo[0].name}?", body,
                                         "Update them" if many else "Update it",
                                         "Keep them as they are" if many else "Keep it as it is"), answered)

        updates.read_data(self, todo, gathered)

    def stop_run(self, run, item, risky=False):
        """ctrl+c in the pane of what was done: stops what runs there, as in a
        terminal. An Update, Revert or Rebuild asks first, since stopping it
        halfway can leave things half done."""
        if not risky:
            console.stop(self, run)
            return

        def answered(yes):
            if yes and run.busy:
                console.stop(self, run)

        self.push_screen(tui.Confirm(f"Stop the {run.title.lower()} of {item.name}?", Content.assemble(
            f"The {run.title.lower()} of ", (item.name, "bold"), " still runs. Stopping it halfway can leave ",
            (item.name, "bold"), " half done: a download cut off, or a backup or its data half copied.\n\n",
            ("Letting it finish is safer; Revert can go back afterwards.", MUTED)),
            "stop it now", "let it finish"), answered)

    def perform(self, item, action, began=None):
        """Does an action chosen for an entry. began() is called once it runs,
        after its question if it has one."""
        title = f"AI LEVERAGE › {item.crumb}"
        app = os.path.join(SCRIPT_DIR, "app.sh")
        if action == "readme":
            self.push_screen(tui.Reader(item.readme(), item.crumb))
        elif action == "open":
            problem = tui.open_browser(item.url)
            self.notify(problem or f"Opening {item.url} in your browser.", severity="warning" if problem else "information")
        elif action.startswith("script-"):
            script = item.scripts[int(action[7:])]
            if script in item.console:
                self.action_script(item, script)
            else:
                self.step(f"{title} › {script[:-3]}", [([f"./{script}"], item.path,
                                                         f"Running {os.path.relpath(item.path, stack.BASE_DIR)}/{script}...")])
        elif action == "start":
            self.action_run(item, action)
        elif action in ("restart", "stop"):
            if item.docker not in ("running", "restarting"):
                self.action_run(item, action)
                return
            loads = " An engine loads its model again, which can take minutes." if item.group == "engines" else ""
            what = ("stops it: open chats are cut off. Its settings and data stay, and Start brings it back."
                    if action == "stop" else f"stops it and starts it again: open chats are cut off.{loads}")
            self.push_screen(tui.Confirm(f"{action.capitalize()} {item.name}?", Content.assemble(
                (item.name, "bold"), f" runs. {action.capitalize()} {what}"),
                f"{action} it", "keep it running"),
                lambda yes: yes and self.action_run(item, action))
        elif action == "rebuild":
            def answered(yes):
                if yes:
                    self.action_run(item, "rebuild")

            self.push_screen(tui.Confirm(f"Rebuild {item.name}?", Content.assemble(
                f"This deletes {item.name}'s container and creates it again from the images already on this PC. "
                "Its settings and data stay.\n\n",
                ("To get a newer version, use Update instead.", MUTED)),
                "Rebuild it", "Keep it as it is"), answered)
        elif action in ("update", "revert"):
            self.ask_update(item, action, began)
        elif action in ("hold", "release"):
            self.run_update(item, action, began)
        elif action in ("install", "uninstall"):
            self.step(f"{title} › {action}", [([app, item.path, action], None, "")])

    def action_open_link(self, url):
        problem = tui.open_browser(url)
        self.notify(problem or f"Opening {url} in your browser.", severity="warning" if problem else "information")


if __name__ == "__main__":
    Menu().run()
