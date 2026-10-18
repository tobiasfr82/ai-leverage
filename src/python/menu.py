#!/usr/bin/env python3
"""ai-leverage/src/python/menu.py

The menu manage.sh opens. At the top, a menu bar (menubar.py) with what
isn't about one entry, such as Updates and Stop all, and under it what the
PC has to spare, updated every 2 seconds. Under that, three columns: on the
left, everything in stack/ and apps/ in the order the parts build on each
other; in the middle, the log of the entry the list highlights (console.py),
so moving through the list is how you look at things; on the right, the
notifications (notices.py): a card for each thing the menu runs, the newest
at the top, yellow while it runs, green once it's done, red when it failed,
blue while it asks you something. A click on one shows its whole log, and
the question under it. In a terminal narrower than 160 columns,
the list and the log stay side by side and the notifications run along the
bottom, the full width, their cards side by side.

Typing an entry's number moves the list to it, which shows its log; Enter
or a click opens what you can do with it, in a box over the menu, where its
number does it at once and Esc closes the box: 4 Enter 1 starts the 4th
entry. Alt and a menu's letter opens that menu (menubar.py), where a letter
does its entry at once: Alt+S, u opens the update overview (updates.py).
Whatever can't be undone asks first, in a yes/no box.

The menu shows things and runs scripts; what they do is in the scripts, so
each one works the same typed in a terminal. Start, Stop, Restart, Rebuild,
Update, Revert, Hold and the logs run src/bash/service.sh (an app's,
src/bash/app.sh), and so do the folders' scripts that only print (a "# menu:
console" line at their top), each with its notification, while the menu stays
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
from console import SERVICE, LogPane, Pane, Runs, elapsed  # noqa: E402
from tui import MUTED, JumpList, MenuList, fit, pill  # noqa: E402
from menubar import Entry, MenuBar, MenuDropdown, mnemonics  # noqa: E402
from updates import UpdatesMenu, newest_of  # noqa: E402
from notices import KEEP, KEEP_CHOICES, Notice, NoticeColumn, RunWindow  # noqa: E402
from fit_screen import FitScreen  # noqa: E402

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

# What a notification calls each update step
STEP_TITLES = {"update": "Update", "revert": "Revert", "hold": "Hold", "release": "Release the hold"}

# What each state means, for the facts about an entry
STATE_MEANS = {
    "running": "It runs.",
    "loading": "It runs, but doesn't answer yet: it's still loading. Its log shows how far it got.",
    "restarting": "It keeps crashing and starting again.",
    "stopped": "It's stopped. Start brings it back as it was.",
    "": "It has no container yet: Start creates one.",
    "?": "Docker's state wasn't read: Stack › Refresh status asks for your password.",
}

# From this many columns, three columns side by side; narrower, the notifications run along the bottom
WIDE_FROM = 160

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
        Entry("About AI Leverage", "about", "Shows what this is, which version runs, and where it keeps its files."),
        Entry("Theme…", "theme", "Picks the menu's colours. Saved in config/menu.conf."),
        Entry("Notifications…", "notices",
              "Sets how many notifications to keep; the oldest finished one closes first. Saved in config/menu.conf."),
        Entry("Quit", "quit", "Leaves the menu (ctrl+q too). Engines and services keep running."),
    ]),
    ("stack", "Stack", [
        Entry("Updates…", "updates",
              "Looks online for newer versions; update, revert or hold each one from there. Asks first."),
        Entry("Refresh status", "refresh", "Reads again what runs, the versions, and what the last update check found."),
        Entry("Stop all engines and services", "stop",
              "Stops everything that runs, the services first. Settings and data stay. Asks first."),
    ]),
    ("models", "Models", [
        Entry("Downloaders", about="Gets models onto this PC: one downloader per folder in stack/downloaders.",
              children="downloaders"),
        Entry("Tuning", about="Shows which models fit this PC for the context you need, and how to run them.",
              children=[
                  Entry("Fit…", "fit",
                        "Shows which downloaded models fit this PC for the context you need, biggest first."),
              ]),
    ]),
    ("system", "System", [
        Entry("Monitor", "monitor", "Shows GPU, CPU, RAM, disk and network use live, in a window of its own."),
        Entry("Container ports", "ports", "Shows which ports the containers use on this PC, in a window of its own."),
    ]),
    ("help", "Help", [
        Entry("Keys and mouse", "keys", "Shows how to move around and do things with the keys and the mouse."),
        Entry("Find any action…", "palette", "Finds any action by a few letters of it, such as \"start vllm\" "
                                             "(ctrl+p too)."),
        Entry("README", "readme", "Shows ai-leverage's README: what it is, how to start, how it's laid out."),
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
                if not why:
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


def script_label(script):
    """A folder's script as an action's label: check_health.sh is "Check health" """
    words = script[:-3].replace("_", " ").replace("-", " ").strip()
    return words[:1].upper() + words[1:]


def link(url):
    """An address you can click to open in the browser"""
    return Content.from_markup(f"[@click=app.open_link({url!r})]{escape(url)}[/]")


class ActionsMenu(ModalScreen):
    """What you can do with an entry, in a box over the menu: what it is and
    how it's doing at the top, the actions under that, and what the
    highlighted one does at the bottom, as many lines as the longest of them
    takes, so the box keeps its size. Its number or letter, Enter or a click
    does it and closes the box; Esc, ← or a click beside it closes it without
    doing anything. Dismisses with the action's id, or None."""

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
        popup.border_subtitle = "its number or letter does it · Esc closes"
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
            actions = [entry for entry in actions if entry[2] in self.only]
        self.query_one("#popup-actions", MenuList).fill(actions)
        # The hint gets the lines its longest text needs (a reason why one can't be done included),
        # wrapped rather than cut, and keeps them while the highlight moves
        width = max(20, room)
        texts = [menu.what_it_does(self.item, action) for _, _, action, _ in actions]
        texts += [why for _, _, _, why in actions if why]
        lines = max([len(Content(text).wrap(width)) for text in texts if text] or [1])
        self.query_one("#popup-hint").styles.height = max(2, lines) + 1  # and its rule on top
        self.show_hint()

    def on_resize(self, event):
        self.fill()

    def show_hint(self):
        actions = self.query_one("#popup-actions", MenuList)
        option = actions.highlighted_option
        # Why a key was refused stays until the highlight moves, through a redraw as the status changes
        refusal = getattr(self, "refusal", None)
        if refusal and option and refusal[1] == option.id:
            self.query_one("#popup-hint", Static).update(Content.styled(refusal[0], "$warning"))
            return
        self.refusal = None
        text = self.app.what_it_does(self.item, option.id) if option else ""
        self.query_one("#popup-hint", Static).update(Content.styled(text, MUTED))

    @on(OptionList.OptionHighlighted, "#popup-actions")
    def highlighted(self, event):
        self.show_hint()

    def refused(self, reason):
        """The number or letter of an action that can't be done now: why, where the hint is"""
        option = self.query_one("#popup-actions", MenuList).highlighted_option
        self.refusal = (reason, option.id if option else None)
        self.show_hint()

    def key_hints(self):
        return [("↑↓", "move"), ("Enter or its number", "does it"), ("Esc", "closes")]

    @on(OptionList.OptionSelected, "#popup-actions")
    def chosen(self, event):
        self.dismiss(event.option_id)

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
    # From WIDE_FROM columns, the list, the log and the notifications side by side; narrower,
    # the list and the log, and the notifications in a row along the bottom (menu.tcss)
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (WIDE_FROM, "-wide")]

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
        self.shown = None        # the item the log shows
        self.busy = {}           # an item's path → what its row says while something runs for it
        self.answered = {}       # an item's path → when its container started, once it answered since then
        self.watching = set()    # the paths of items a thread asks until they're ready
        self.open_menu_id = None  # the menu bar's menu that's open, if any
        self.log_timer = None
        self.check = None        # the update check (updates.Check) since the menu opened, if any
        self.check_notice = None  # its card in the notifications
        self.start_notices = {}  # an item's path → the card of its last Start, Restart or Rebuild, until it's clear
        self.runs = Runs(self, changed=self.run_changed)  # what the menu runs, and ran since it opened
        self.version = stack.stack_version()

    def compose(self) -> ComposeResult:
        yield MenuBar(MENUS, id="menubar", classes="panel")
        yield Static(id="system", classes="panel")
        with Horizontal(id="main"):
            yield JumpList(id="stack", classes="panel")
            yield LogPane(id="log", classes="panel")
            yield NoticeColumn(id="notices", classes="panel")
        yield Static(id="keys")

    # --- Starting ---

    def on_mount(self):
        theme = tui.saved_theme()
        self.theme = theme if theme in self.available_themes else tui.DEFAULT_THEME
        self.theme_changed_signal.subscribe(self, self.theme_changed)
        self.screen_change_signal.subscribe(self, self.screen_changed)
        self.query_one("#system").border_title = "This PC"
        stack_list = self.query_one("#stack", JumpList)
        stack_list.border_title = "Stack"
        stack_list.resized = self.fill_stack
        # ↑ past the list's top entry goes to the menu bar
        stack_list.above = self.query_one(MenuBar)
        self.query_one(NoticeColumn).keep = self.saved_keep()
        self.discover()
        stack_list.focus()
        self.read_system()
        self.set_interval(2, self.read_system)
        self.set_interval(1, self.tick)
        self.read_status()

    def screen_changed(self, screen):
        """The line at the bottom says the keys of what's in front: a box's
        own (its key_hints), or the menu's for the area in use"""
        if isinstance(screen, MenuDropdown):
            return  # an open menu says what its highlighted entry does
        if screen is self.base():
            self.show_keys(self.focus_name())
        elif hasattr(screen, "key_hints"):
            self.base().query_one("#keys", Static).update(tui.keys_line(*screen.key_hints()))

    def refresh_keys(self):
        """The line at the bottom again, such as when what a box offers changed"""
        self.screen_changed(self.screen)

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

    def menu_hint(self, entry, letter=""):
        """What the highlighted entry of an open menu does, and the keys that
        do it, in the line at the bottom: "u or Enter  Updates: Looks online…" """
        keys = self.base().query_one("#keys", Static)
        does = (f"{letter}, → or Enter" if entry.children else f"{letter} or Enter") if letter else "Enter"
        text = Content.assemble((does, LIT), (f" {entry.label.rstrip('…')}: ", "bold"),
                                tui.inline_markdown(entry.about, MUTED))
        keys.update(text.truncate(max(20, self.size.width - 2), ellipsis=True))

    def menu_refused(self, reason):
        """Why the entry whose letter was typed can't be done now, in the line at the bottom"""
        self.base().query_one("#keys", Static).update(
            Content.styled(reason, "$warning").truncate(max(20, self.size.width - 2), ellipsis=True))

    def menu_entries(self, menu_id):
        """A menu's entries"""
        return next(entries for found, _, entries in MENUS if found == menu_id)

    def menu_children(self, entry):
        """The entries of the menu beside an entry: its own, or one for each
        folder of the group it names, in alphabetical order"""
        if isinstance(entry.children, list):
            return entry.children
        # The first sentence of each folder's README: the line at the bottom has room for one
        return [Entry(menu_label(item.name), f"open:{item.path}",
                      stack.first_sentence(self.intros.get(item.path, "")) or f"Opens {item.name}.")
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
        runs = self.runs
        if isinstance(entry.children, str):
            running = sum(runs.busy(item.path) for item in self.menu_items.get(entry.children, []))
            return Content.styled(f"◐ {running} running", "$warning") if running else None
        action = entry.action
        if action.startswith("open:"):
            run = runs.latest(action[5:])
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
            # One line, cut to fit a narrow list
            entries.append((None, Content.assemble((f"{group.upper():<13}", "bold $text-primary"),
                                                   (about, MUTED)).truncate(width, ellipsis=True), None, ""))
            for item in members:
                number += 1
                entries.append((str(number), self.item_line(number, item, width), f"item-{number}", ""))
        if not entries:
            entries.append((None, Content.styled(f"Nothing found in {stack.STACK_DIR}", "$error"), None, ""))
        shown = next((n for n, item in enumerate(self.items, 1) if item is self.shown), None)
        stack_list.fill(entries, prefer=f"item-{shown}" if shown else None)

    def redraw_item(self, item):
        """Draws an entry's row again, and what shows it: the log, and the
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
            stack_list.border_subtitle = Content.styled("Docker not read · Stack › Refresh status asks for your password",
                                                        "$warning")
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
        if not self.notice_phase(item, "ready", f"ready, {took} after its container started" if took else
                                 "ready: it answers now"):
            # Not started from the menu, or started before it opened: a card of its own
            self.notices().add(Notice(f"{item.name} is ready", item=item, state="done",
                                      text=f"{took} after its container started" if took else "it answers now",
                                      opens=partial(self.show_entry, item)))
        self.runs.note(item.path, f"── {item.name} is ready: it answers now"
                       + (f", {took} after its container started" if took else "") + " ──")
        self.redraw_item(item)
        self.show_stack_title()

    def tell_started(self):
        """What became of a Start, Restart or Rebuild, once the status read
        after it shows whether it runs and answers: its card stays yellow
        while the engine loads, turns green once it answers, and red when it
        doesn't run"""
        for notice in list(self.start_notices.values()):
            item = notice.item
            if self.loading(item):
                if notice.phase != "loading":
                    self.notice_phase(item, "loading", "loading; green once it answers", since=item.started)
            elif notice.phase == "checking" and item.docker in ("running", "?"):
                self.notice_phase(item, "ready", "")
            elif notice.phase == "loading" and item.docker == "running":
                self.notice_phase(item, "ready", "ready: it answers now")
            else:
                self.notice_phase(item, "broken", "it doesn't run now: its log says why" if notice.phase == "checking"
                                  else "it stopped while it loaded: its log says why")

    def tick(self):
        """Moves the clock on the entries that are still loading, and on
        the notifications that run"""
        found = self.query("#stack")
        if not found:
            return  # the menu is quitting: its widgets are gone already
        stack_list = found.first(JumpList)
        for number, item in enumerate(self.items, 1):
            if self.loading(item) and item.path not in self.busy:
                index = stack_list.keys.get(str(number))
                if index is not None:
                    stack_list.refill(index, self.item_line(number, item, stack_list.width()))
        self.runs.tick()
        self.notices().tick()
        if isinstance(self.screen, RunWindow):
            self.screen.more()

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
            hint = Content.styled("Docker wasn't read, so its log can't be: Stack › Refresh status asks for your "
                                  "password.",
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

    def fact_lines(self, rows, room, label_width=LABEL_WIDTH):
        """Rows of (label, value, note) as lines: the label in a column of its
        own and the value next to it, wrapped under itself. A short note goes
        after the value, a long one on lines of its own under it."""
        room = max(24, room - label_width)
        lines = []
        for label, value, note in rows:
            value = value if isinstance(value, Content) else Content(value)
            if note and value.cell_length + 2 + len(note) <= room:
                value += Content.styled(f"  {note}", MUTED)
                note = ""
            for n, part in enumerate(value.wrap(room) or [Content("")]):
                lines.append(Content.assemble((f"{label if n == 0 else '':<{label_width}}", MUTED), part))
            for part in Content.styled(note, MUTED).wrap(room) if note else []:
                lines.append(Content.assemble(" " * label_width, part))
        return Content("\n").join(lines)

    def item_actions(self, item, room):
        """(key, text, id, why it can't be done now) for each thing to do with
        an item, numbered as in the menus before: the service's or app's own
        actions first, then the folder's scripts. A note after a label only
        finishes it (to which version, from where, in the terminal); what an
        action does is in the hint under the list."""
        entries = []

        def add(key, label, action, note="", why="", style=""):
            # One line each: a note too long for it ends in …
            text = Content.assemble((f"{key:>2}  ", MUTED), (label, MUTED if why else style))
            if note:
                text += Content.styled(f"  {note}", MUTED)
            entries.append((key, text.truncate(max(20, room - 2), ellipsis=True), action, why))

        first = 1
        held = f"{item.name} is held at {item.version or 'its version'}: release the hold first." if item.held else ""
        no_earlier = "Nothing to go back to yet: Revert works after an Update from this menu."
        if item.kind == "service":
            missing = "" if item.downloaded else f"{item.name} isn't downloaded yet: Start downloads it."
            newer = self.newer(item)
            add("1", "Start", "start", style="$success")
            add("2", "Stop", "stop", style="$error")
            add("3", "Restart", "restart", style="$primary")
            add("4", "Update", "update", f"to {newer}" if newer else "to its newest stable release",
                why=missing or held, style="$warning")
            add("5", "Revert", "revert", f"to {item.previous}" if item.previous else "",
                why=missing or ("" if item.previous else no_earlier), style="$secondary")
            if item.held:
                add("6", "Release the hold", "release", why=missing, style="bold")
            else:
                add("6", "Hold", "hold", f"at {item.version}" if item.version else "at its version",
                    why=missing, style="bold")
            add("7", "Rebuild", "rebuild", "its container", style="bold")
            first = 8
        elif item.kind == "app":
            missing = "" if item.app_state != "missing" else f"{item.app_name or item.name} isn't installed."
            newer = self.newer(item)
            add("1", "Install", "install", f"from {item.source}" if item.source else "", style="$success")
            add("2", "Update", "update", f"to {newer}" if newer else "to its newest stable release",
                why=missing or held, style="$warning")
            add("3", "Revert", "revert", f"to {item.previous}" if item.previous else "",
                why=missing or ("" if item.previous else no_earlier), style="$secondary")
            if item.held:
                add("4", "Release the hold", "release", why=missing, style="bold")
            else:
                add("4", "Hold", "hold", f"at {item.version}" if item.version else "at its version",
                    why=missing, style="bold")
            add("5", "Uninstall", "uninstall", why=missing, style="$error")
            first = 6
        for offset, script in enumerate(item.scripts):
            add(str(first + offset), script_label(script), f"script-{offset}",
                "" if script in item.console else "in the terminal", style="bold")
        if item.readme():
            add("i", f"Read about {item.name}", "readme")
        if item.kind == "service" and item.docker == "running" and item.url and "API" not in item.url_note:
            add("o", "Open in your browser", "open", item.url,
                why=f"{item.name} is still loading: it opens once it answers." if self.loading(item) else "")
        return entries

    def what_it_does(self, item, action):
        """What an action does, in a sentence or two"""
        name = item.name
        if action.startswith("script-"):
            script = item.scripts[int(action[7:])]
            about = stack.script_intro(os.path.join(item.path, script))
            runs = f"Runs {script}." if script in item.console else \
                f"Runs {script} in the plain terminal, since it asks things."
            return f"{about} {runs}" if about else runs
        newer = self.newer(item)
        asks = " It asks first." if item.kind == "service" and item.docker in ("running", "restarting") else ""
        hints = {
            "start": f"Starts {name} with the settings in its .env, creating its container if it has none. Its "
                     "notification turns green once it's ready.",
            "stop": f"Stops {name}; its settings and data stay, and Start brings it back." + asks,
            "restart": f"Stops and starts {name} as it is; changes in its .env need Start." + asks,
            "update": f"Updates {name} to {newer or 'its newest stable release'} and keeps the version it replaces, "
                      "for Revert. It asks first.",
            "revert": f"Goes back to {item.previous}, the version before the last update, and holds it there. "
                      "It asks first.",
            "hold": f"Keeps {name} at {item.version or 'its version'}: Update and Update all skip it until you "
                    "release the hold.",
            "release": f"Ends the hold, so Update updates {name} again.",
            "rebuild": f"Creates {name}'s container again from the images on this PC; its settings and data stay. "
                       "Update is what gets a newer version. It asks first.",
            "install": f"Installs {item.app_name or name}" + (f" from {item.source}" if item.source else "")
                       + ", in the plain terminal, since it may ask things. Nothing changes if it's there already.",
            "uninstall": f"Removes {item.app_name or name}; your own files and settings stay. It asks first, in the "
                         "plain terminal.",
            "readme": f"Shows {name}'s README: what it is, how to use it, and its settings.",
            "open": f"Opens {item.url} in your browser.",
        }
        return hints.get(action, "")

    def command_text(self, item, action):
        """An action as a command, for the command palette: "Start vllm" """
        name = item.name
        if action.startswith("script-"):
            return f"{script_label(item.scripts[int(action[7:])])} ({name})"
        newer = self.newer(item)
        return {
            "start": f"Start {name}", "stop": f"Stop {name}", "restart": f"Restart {name}",
            "update": f"Update {name}" + (f" to {newer}" if newer else ""),
            "revert": f"Revert {name} to {item.previous}", "hold": f"Hold {name} at {item.version or 'its version'}",
            "release": f"Release the hold on {name}", "rebuild": f"Rebuild {name}'s container",
            "install": f"Install {name}", "uninstall": f"Uninstall {name}",
            "readme": f"Read about {name}", "open": f"Open {name} in your browser",
        }.get(action, f"{action} {name}")

    # --- The middle: the highlighted entry's log ---

    def show(self, item):
        """The log switches to an entry once the highlight rests on it for a
        moment, so moving through the list doesn't start a reader for every
        entry on the way"""
        self.shown = item
        if self.log_timer:
            self.log_timer.stop()
        self.log_timer = self.set_timer(0.25, partial(self.show_log, item))

    def show_log(self, item):
        if item is self.shown:
            self.query_one(LogPane).show(item, self.about_lines(item), self.has_log(item))

    def pane_back(self):
        """From the log or the notifications back to the list"""
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
        """What has the focus, as show_keys knows it: stack, log, menubar or notices"""
        return self.focused.id if self.focused and self.focused.id in ("stack", "log", "menubar", "notices") else "stack"

    @on(OptionList.OptionHighlighted, "#stack")
    def stack_highlighted(self, event):
        item = self.item_for(event.option_id)
        # The list drawn again (a status read) keeps its entry: that's no move
        if item and item is not self.shown:
            self.show(item)

    def on_descendant_focus(self, event):
        if event.widget.screen is not self.screen_stack[0]:
            return
        self.show_keys(self.focus_name())

    def show_keys(self, focused):
        wide = self.size.width >= 120
        if focused == "log":
            pairs = [("↑↓ PgUp PgDn", "scroll")] if wide else [("↑↓", "scroll")]
            pairs += [("s", "save"), ("ctrl+c", "stop following"), ("Esc", "back to the list")]
            self.base().query_one("#keys", Static).update(tui.keys_line(*pairs))
            return
        if focused == "notices":
            across = self.notices().across()
            pairs = [("← →" if across else "↑↓", "move"), ("Enter or a click", "its whole log"),
                     ("x or ×", "close it"), ("c", "close the finished ones"), ("Esc", "back to the list")]
            self.base().query_one("#keys", Static).update(tui.keys_line(*pairs))
            return
        if self.open_menu_id:
            return  # the open menu says what its entry does
        if focused == "menubar":
            pairs = [("← →", "choose a menu"), ("its letter, Enter or ↓", "opens it"), ("Esc", "back to the list")]
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
        """Moves the list's highlight to an entry, so the log shows it"""
        number = next((n for n, known in enumerate(self.items, 1) if known is item), None)
        stack_list = self.query_one("#stack", JumpList)
        index = stack_list.keys.get(str(number)) if number else None
        if index is not None:
            stack_list.highlighted = index

    # --- Notifications ---

    def notices(self):
        return self.query_one(NoticeColumn)

    def notify(self, message, *, title="", severity="information", timeout=None, markup=True):
        """A message, such as why something can't be done now: a card in the
        notifications that closes by itself. While a box is open over the
        menu, it pops up at the bottom right instead, where it can be seen."""
        if self.screen is self.base() and threading.current_thread() is threading.main_thread():
            timeout = timeout or self.NOTIFICATION_TIMEOUT
            state = {"warning": "warning", "error": "failed"}.get(severity, "info")
            self.notices().add(Notice(str(message), state=state,
                                      timeout=max(timeout, 8) if state != "info" else timeout))
        else:
            super().notify(message, title=title, severity=severity, timeout=timeout, markup=markup)

    def start_run(self, item, title, steps, on_done=None, label=None):
        """Runs steps for an entry, with a card in the notifications that
        shows how it goes and opens its whole log. Returns the card."""
        run = self.runs.start(item, title, steps, on_done=on_done)
        return self.notices().add(Notice(label or f"{title} {item.name}", item=item, run=run))

    def run_changed(self, run):
        """What runs printed more or ended: its card, and its window when that's open"""
        column = self.notices()
        notice = column.for_run(run)
        if notice:
            column.changed(notice)
        if isinstance(self.screen, RunWindow) and self.screen.notice.run is run:
            self.screen.more()

    def notice_phase(self, item, phase, text, since=None):
        """What became of a Start, Restart or Rebuild once the status read
        shows whether it runs and answers: "loading" keeps its card yellow,
        "ready" turns it green, "broken" red"""
        notice = self.start_notices.get(item.path)
        if not notice:
            return None
        notice.phase, notice.text = phase, text
        if since:
            notice.since = since
        if phase != "loading":
            notice.ended = time.time()
            self.start_notices.pop(item.path, None)
        self.notices().changed(notice)
        return notice

    def take_over(self, item, action):
        """A new action for an entry whose Start still waits to load: that
        card stops waiting, since its script did its part"""
        earlier = self.start_notices.pop(item.path, None)
        if earlier:
            earlier.phase, earlier.text, earlier.ended = None, f"done; then {action.lower()}", time.time()
            self.notices().changed(earlier)

    def close_notice(self, notice):
        """× or x on a card: closes it. One whose action hasn't finished asks
        first, since closing it stops that action; a finished one just closes."""
        column = self.notices()
        if not notice.going:
            column.close(notice)
            return
        run, item = notice.run, notice.item
        if run is not None and run.busy:
            what = run.title.lower()
            doing = "is waiting for your answer" if run.question else "is still running"
            body = Content.assemble((notice.title, "bold"), f" {doing}. Closing its notification stops it.")
            if run.title in console.RISKY:
                body += Content.styled(f"\n\nStopping it halfway can leave {item.name} half done, such as a download "
                                       "cut off or its data half copied. Letting it finish is safer.", "$warning")
            title = f"Stop the {what} of {item.name}?"

            def stop():
                if run.busy:
                    console.stop(self, run)
        elif item is not None and notice.phase in ("checking", "loading"):
            body = Content.assemble((item.name, "bold"), " is still "
                                    + ("loading its model" if item.group == "engines" else "starting")
                                    + f". Closing its notification stops {item.name}.")
            title = f"Stop {item.name}?"

            def stop():
                self.start_notices.pop(item.path, None)
                self.action_run(item, "stop")
        elif notice is self.check_notice and self.check and self.check.running:
            body = Content("The update check is still looking online. Closing its notification stops it; what it "
                           "found so far stays.")
            title = "Stop the update check?"

            def stop():
                if self.check and self.check.running:
                    self.check.stop()
        else:
            column.close(notice)
            return

        def answered(yes):
            if yes:
                column.close(notice)
                stop()

        self.push_screen(tui.Confirm(title, body, "stop it and close this", "keep it running"), answered)

    def action_notices_clear(self):
        self.notices().close_finished()

    def saved_keep(self):
        """How many notifications the column keeps, from config/menu.conf"""
        try:
            return max(1, int(tui.setting("MENU_NOTIFICATIONS", KEEP)))
        except ValueError:
            return KEEP

    def choose_keep(self):
        """AI Leverage › Notifications: how many the column keeps"""
        column = self.notices()

        def chosen(keep):
            if keep:
                column.set_keep(int(keep))
                tui.save_setting("MENU_NOTIFICATIONS", keep)

        self.push_screen(tui.Choose("Notifications", Content(
            "How many notifications the menu keeps. With one more, the oldest finished one closes; one whose action "
            "still runs stays until it's done."),
            [(str(n), f"Keep the last {keep}", str(keep)) for n, keep in enumerate(KEEP_CHOICES, 1)],
            current=str(column.keep)), chosen)

    # --- Doing things ---

    def step(self, title, steps, pause=True, report=False, keep_going=False):
        code = tui.step_aside(self, title, steps, pause, report, keep_going)
        self.after_step()
        return code

    def after_step(self):
        self.read_status()
        self.draw_menubar()

    def run_tool(self, tool):
        if tool == "updates":
            self.open_updates()
        elif tool == "fit":
            self.push_screen(FitScreen())
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
        elif tool == "notices":
            self.choose_keep()
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
            ("The rule", "In menus and boxes, an entry's number or letter does it at once; ↑↓ and the mouse only "
                         "move, and Enter or a click does the highlighted one. Esc goes back. What can't be undone "
                         "asks first: y yes, n or Esc no.", ""),
            ("The list", "↑↓ move · its number moves to it, to see its log · Enter or a click: what you can do with "
                         "it · → its log", ""),
            ("Menus", f"{menus} · F10 the first one · a click on a title", ""),
            ("In a menu", "its underlined letter does it at once (Alt+S u opens Updates; Alt+M d h opens "
                          "huggingface) · ↑↓ move, Enter does it · ▸ shows a menu beside: its letter, → or Enter goes "
                          "in, ← back out · ← → the next menu · Esc one step back", ""),
            ("Areas", "Tab and shift+Tab go through the menu bar, the list, the log and the notifications · Esc goes "
                      "back to the list · a number goes to that entry of the list from anywhere but a box", ""),
            ("Boxes", "its number or letter does it at once (4 Enter 1 starts entry 4) · Esc, ← or a click beside "
                      "it closes it", ""),
            ("The log", "↑↓ PgUp PgDn scroll · s saves to logs/ · ctrl+c stops following · a drag of the mouse "
                        "selects text, which ctrl+c then copies (in a notification's log too)", ""),
            ("Notifications", "the newest first: yellow runs, green done, red failed, blue asks you · ↑↓ move (← → "
                              "in the bottom row) · Enter or a click: its whole log, where ctrl+c stops it and y or n "
                              "answers · x or × closes one (one running or asking asks first) · c closes the finished "
                              "ones", ""),
            ("Anywhere", "ctrl+p finds any action by a few letters of it · ctrl+q quits", ""),
        ]
        return self.fact_lines(rows, 78, label_width=15)

    def exit(self, *args, **kwargs):
        """Ends what still runs, such as the log the pane follows, then quits"""
        self.runs.stop_all()
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
        run = self.runs.latest(item.path)
        if run and run.busy:
            self.notify(f"{run.title} of {item.name} is still running. Wait for it, or stop it with × on its "
                        "notification.", timeout=6)
            return True
        return False

    def stop_all(self):
        if self.docker_ok is False:
            self.notify("Docker's state wasn't read, so the menu doesn't know what runs. "
                        "Stack › Refresh status asks for your password.", severity="warning", timeout=6)
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
            for item in queue:
                self.take_over(item, "stop")
                self.busy[item.path] = BUSY_WORDS["stop"]
                self.redraw_item(item)

            def next_one():
                # One after another, the services first, each with its notification
                if not queue:
                    self.after_step()
                    return
                item = queue.pop(0)

                def done(code):
                    self.busy.pop(item.path, None)
                    self.redraw_item(item)
                    next_one()

                self.start_run(item, "Stop", [([SERVICE, item.path, "stop"], None, "")], on_done=done)

            next_one()

        self.push_screen(tui.Confirm("Stop all engines and services?", Content.assemble(
            "These stop one after another, the services first:\n", (names, "bold")),
            "Stop them", "Keep them running"), answered)

    def action_run(self, item, action):
        """Start, Stop, Restart or Rebuild, with its notification. The log
        shows its container's own log once it runs."""
        if self.still_running(item) or not self.sudo_or_ask():
            return
        # Rebuild asked in the menu's own dialog already
        steps = [([SERVICE, item.path, action] + (["--yes"] if action == "rebuild" else []), None, "")]
        self.take_over(item, action)
        self.busy[item.path] = BUSY_WORDS[action]
        self.redraw_item(item)

        def done(code):
            self.busy.pop(item.path, None)
            if not code and action != "stop":
                # Its card stays yellow until the status read shows whether it runs and answers (tell_started)
                notice.phase, notice.text = "checking", "done: checking that it runs…"
                self.start_notices[item.path] = notice
            self.after_step()

        notice = self.start_run(item, action.capitalize(), steps, on_done=done)

    def action_script(self, item, script):
        """A folder's script that only prints, with its notification. It runs
        in its folder, as from a terminal there."""
        if self.still_running(item):
            return
        if stack.uses_sudo(os.path.join(item.path, script)) and not self.sudo_or_ask(f"{script} uses sudo"):
            return
        label = script_label(script)
        self.busy[item.path] = BUSY_WORDS["script"]
        self.redraw_item(item)

        def done(code):
            self.busy.pop(item.path, None)
            self.after_step()

        self.start_run(item, label, [([f"./{script}"], item.path,
                                      f"$ cd {os.path.relpath(item.path, stack.BASE_DIR)} && ./{script}")],
                       on_done=done, label=f"{label} ({item.name})")

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
        # One card for the latest check: a new one takes the place of the one before
        column = self.notices()
        if self.check_notice:
            column.close(self.check_notice)
        self.check_notice = column.add(Notice("Update check", state="running", text="looking online…",
                                              opens=lambda: self.push_screen(UpdatesMenu())))
        self.refill_updates()

    def check_row(self, path, found):
        """One answer of the update check, for the item in that folder"""
        if self.check:
            self.check.rows[path] = found
            if self.check.running and self.check_notice:
                self.check_notice.text = f"looking online… {len(self.check.rows)} answered"
                self.notices().changed(self.check_notice)
        item = next((known for known in self.items if updates.where(known.path) == path), None)
        if item:
            self.redraw_item(item)
        self.draw_menubar()

    def check_ended(self):
        self.draw_menubar()
        self.refill_updates()
        count = len(self.updates_to_do())
        found = f"found {count} update{'s' if count != 1 else ''}" if count else "everything is up to date"
        if self.check_notice:
            notice = self.check_notice
            notice.status = "failed" if self.check and self.check.failed else "done"
            notice.text = ("couldn't look online for everything: Stack › Updates shows what it found"
                           if notice.status == "failed" else found + (": Stack › Updates shows them" if count else ""))
            notice.ended = time.time()
            self.notices().changed(notice)

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
                                     (newer, "bold $warning") if newer else "its newest stable release")
            first += Content.styled(f"\nIt keeps {version}, so Revert can go back to it.", MUTED)
        else:
            first = Content.assemble((name, "bold"), f" goes back from {version} to ", (item.previous, "bold"),
                                     " and stays there: Update skips it.")
        blocks = [first]
        if running:
            blocks.append(Content.styled(f"{name} is running: {verb} restarts it and cuts off open chats"
                                         + (", and it loads its model again." if item.group == "engines" else "."),
                                         "$warning"))
        if data:
            about, size = data
            if action == "update":
                blocks.append(Content.styled(f"It backs up {about} first ({size}), since a new version may convert "
                                             "it; Revert can put the backup back.", "$warning"))
            elif item.backup:
                blocks.append(Content.styled(f"It puts back the copy of {about} from before the update ({item.backup}), "
                                             "after backing up what's there now.", "$warning"))
            else:
                blocks.append(Content.styled(f"There's no copy of {about} from before the update: if the newer version "
                                             "converted it, the older one may not read it.", "$warning"))
        title = f"{'Update' if action == 'update' else 'Revert'} {name}?"
        return title, Content("\n\n").join(blocks), "Update it" if action == "update" else "Revert it"

    def run_update(self, item, action, began=None):
        """Update, Revert, Hold or Release the hold, with its notification.
        Update and Revert were asked already."""
        if self.still_running(item) or not self.sudo_for(item):
            return
        steps = [([updates.tool_for(item), item.path, action] + (["--yes"] if action in ("update", "revert") else []),
                  None, "")]
        title = STEP_TITLES[action]
        self.take_over(item, title)
        self.busy[item.path] = BUSY_WORDS[action]
        self.redraw_item(item)
        if began:
            began(item)

        def done(code):
            self.busy.pop(item.path, None)
            self.after_step()
            # What it is now, for the list and the overview
            updates.check_one(self, item, self.check_row)

        self.start_run(item, title, steps, on_done=done,
                       label=f"Release the hold on {item.name}" if action == "release" else None)

    def update_all(self, began=None):
        """Updates every item the check found an update for, one after
        another, each in its own entry's pane, after one question for all"""
        if self.check and self.check.running:
            self.notify("The update check is still looking online: wait for it.")
            return
        todo = [item for item in self.updates_to_do() if not self.runs.busy(item.path)]
        if not todo:
            self.notify("Nothing to update.")
            return
        if any(item.kind == "service" or item.method == "apt" for item in todo) and not self.sudo_or_ask():
            return

        def answered(yes):
            if not yes:
                return
            queue = [item for item in todo if not self.runs.busy(item.path)]
            if not queue:
                return
            for item in queue:
                self.busy[item.path] = BUSY_WORDS["queued"]
                self.redraw_item(item)
            if began:
                began(queue[0])

            def next_one():
                # One after another, each with its notification
                if not queue:
                    return
                item = queue.pop(0)
                self.take_over(item, "update")
                self.busy[item.path] = BUSY_WORDS["update"]
                self.redraw_item(item)

                def done(code):
                    self.busy.pop(item.path, None)
                    self.redraw_item(item)
                    self.after_step()
                    updates.check_one(self, item, self.check_row)
                    next_one()

                self.start_run(item, "Update", [([updates.tool_for(item), item.path, "update", "--yes"], None, "")],
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
            body = Content("These update one after another:\n")
            body += Content("\n").join(lines)
            if any(item.kind == "service" and item.docker in ("running", "restarting") for item in todo):
                body += Content.styled("\n\nThe running ones restart, which cuts off open chats; an engine loads its "
                                       "model again.", "$warning")
            if data:
                body += Content.styled("\n\nA new version may convert the data it finds; the backups let Revert put "
                                       "it back.", "$warning")
            many = len(todo) > 1
            self.push_screen(tui.Confirm("Update all?" if many else f"Update {todo[0].name}?", body,
                                         "Update them" if many else "Update it",
                                         "Keep them as they are" if many else "Keep it as it is"), answered)

        updates.read_data(self, todo, gathered)

    def stop_run(self, run, item, risky=False):
        """ctrl+c in a notification's log: stops what runs there, as in a
        terminal. An Update, Revert or Rebuild asks first, since stopping it
        halfway can leave things half done."""
        if not risky:
            console.stop(self, run)
            return

        def answered(yes):
            if yes and run.busy:
                console.stop(self, run)

        self.push_screen(tui.Confirm(f"Stop the {run.title.lower()} of {item.name}?", Content.assemble(
            f"The {run.title.lower()} of ", (item.name, "bold"), " is still running. Stopping it halfway can leave ",
            (item.name, "bold"), " half done, such as a download cut off or its data half copied.\n\n",
            ("Letting it finish is safer.", MUTED)),
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
            if action == "stop":
                what = "Stopping it cuts off open chats. Its settings and data stay, and Start brings it back."
            else:
                what = "Restarting it cuts off open chats" + (
                    ", and it loads its model again, which can take minutes." if item.group == "engines" else ".")
            self.push_screen(tui.Confirm(f"{action.capitalize()} {item.name}?", Content.assemble(
                (item.name, "bold"), f" is running. {what}"),
                f"{action} it", "keep it running"),
                lambda yes: yes and self.action_run(item, action))
        elif action == "rebuild":
            def answered(yes):
                if yes:
                    self.action_run(item, "rebuild")

            self.push_screen(tui.Confirm(f"Rebuild {item.name}?", Content.assemble(
                f"This creates {item.name}'s container again from the images on this PC. Its settings and data "
                "stay.\n\n", ("For a newer version, use Update instead.", MUTED)),
                "Rebuild it", "Keep it as it is"), answered)
        elif action in ("update", "revert"):
            self.ask_update(item, action, began)
        elif action in ("hold", "release"):
            self.run_update(item, action, began)
        elif action in ("install", "uninstall"):
            code = self.step(f"{title} › {action}", [([app, item.path, action], None, "")])
            # It ran in the plain terminal, which showed what it printed: the card says how it ended
            self.notices().add(Notice(f"{action.capitalize()} {item.name}", item=item,
                                      state="failed" if code else "done",
                                      text=f"failed (exit code {code}) in the terminal" if code else
                                      "done, in the terminal", opens=partial(self.show_entry, item)))

    def action_open_link(self, url):
        problem = tui.open_browser(url)
        self.notify(problem or f"Opening {url} in your browser.", severity="warning" if problem else "information")


if __name__ == "__main__":
    Menu().run()
