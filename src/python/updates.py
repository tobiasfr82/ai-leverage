#!/usr/bin/env python3
"""ai-leverage/src/python/updates.py

The update overview in manage.sh's menu (Stack › Updates): every engine,
service and app with its version on this PC and its newest stable release,
in a box over the menu, and under them the tools ai-leverage relies on, for
information (they're updated another way).

It shows what the last check found at once, and checks online again as it
opens, with src/bash/check-updates.sh --print, which looks without
downloading anything. Each row changes as its answer comes in. Nothing goes
online on its own: only opening the box and c check.

Enter on a row shows what you can do about it: Update, Revert, Hold or
Release it. Update all updates every one with an update, one after another.
Each gets its notification, as Start does, and the box closes so you see
them there. The menu asks first, in a dialog of its own, and
then runs service.sh or app.sh with --yes (menu.py). Not run on its own:
menu.py uses it.
"""

import os
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static

import stack
from console import descendants, environment
from stack import show_version
from tui import MUTED, MenuList, fit, listed

CHECK = os.path.join(stack.SCRIPT_DIR, "check-updates.sh")
SERVICE = os.path.join(stack.SCRIPT_DIR, "service.sh")
APP = os.path.join(stack.SCRIPT_DIR, "app.sh")

# What the box offers for one row, out of everything an entry can do
UPDATE_ACTIONS = ("update", "revert", "hold", "release")

# Widths of the rows' columns, as in the menu's list
NAME_WIDTH = 14
STATUS_WIDTH = 15


def tool_for(item):
    """The script that updates an item: service.sh for an engine or service, app.sh for an app"""
    return SERVICE if item.kind == "service" else APP


def where(path):
    """A folder as the check names it, so the same folder always matches"""
    return os.path.realpath(path)


def stop_process(proc):
    """Ends a command and everything it started, such as the checks a script runs side by side"""
    if proc and proc.poll() is None:
        for pid in [proc.pid] + descendants(proc.pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass


class Check:
    """One run of check-updates.sh --print, in a thread of its own, and what
    it found so far. on_row(folder, found) and on_end() are called in the
    menu, as the answers come."""

    def __init__(self):
        self.rows = {}        # a folder → (result, installed, newest, note), as each one comes
        self.tools = []       # (name, version, newest, note), once it's done
        self.running = True
        self.failed = False
        self.ended = None     # when it was done, as time.time()
        self.proc = None

    def start(self, app, on_row, on_end):
        def ui(function, *args):
            try:
                app.call_from_thread(function, *args)
            except Exception:  # the menu has quit
                pass

        def work():
            tools = []
            try:
                self.proc = subprocess.Popen([CHECK, "--print"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                             stderr=subprocess.DEVNULL, text=True, env=environment())
                for line in self.proc.stdout:
                    kind, _, rest = line.rstrip("\n").partition("|")
                    fields = rest.split("|") + [""] * 5
                    if kind == "row" and fields[0]:
                        ui(on_row, where(fields[0]), tuple(fields[1:5]))
                    elif kind == "tool" and fields[0]:
                        tools.append(tuple(fields[:4]))
                self.failed = self.proc.wait() != 0
            except OSError:
                self.failed = True
            ui(self.done, tools, on_end)

        threading.Thread(target=work, daemon=True, name="update-check").start()

    def done(self, tools, on_end):
        self.tools = tools or stack.last_tools()
        self.running = False
        self.ended = time.time()
        on_end()

    def stop(self):
        stop_process(self.proc)


def check_one(app, item, on_row):
    """Looks online again for one item, after something changed it, as the
    overview in the terminal does: service.sh or app.sh <folder> check"""
    def work():
        try:
            done = subprocess.run([tool_for(item), item.path, "check"], stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=120, env=environment())
            line = done.stdout.splitlines()[0] if done.stdout.strip() else "failed|||"
        except (OSError, subprocess.SubprocessError):
            line = "failed|||"
        try:
            app.call_from_thread(on_row, where(item.path), tuple((line.split("|") + [""] * 4)[:4]))
        except Exception:
            pass

    threading.Thread(target=work, daemon=True, name=f"check-{item.name}").start()


def read_data(app, items, then):
    """What Update would back up for each engine or service, from service.sh
    <folder> data, side by side in a thread: then({path: (what it holds,
    size)}) in the menu, without the ones that keep no data of their own"""
    def one(item):
        try:
            done = subprocess.run([SERVICE, item.path, "data"], stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, timeout=60, env=environment())
        except (OSError, subprocess.SubprocessError):
            return item.path, None
        about, _, size = done.stdout.strip().partition("|")
        return item.path, (about, size) if about else None

    def work():
        services = [item for item in items if item.kind == "service"]
        found = {}
        if services:
            with ThreadPoolExecutor(max_workers=len(services)) as pool:
                found = {path: data for path, data in pool.map(one, services) if data}
        try:
            app.call_from_thread(then, found)
        except Exception:
            pass

    threading.Thread(target=work, daemon=True, name="update-data").start()


def finding(item, found, pending):
    """What the check found about an item, in words, as (text, style)"""
    if pending:
        return "checking…", MUTED
    if not found:
        return "not checked yet", MUTED
    result, installed, newest, note = found
    if result == "current":
        return "up to date", "$success"
    if result == "newer":
        return "update available" + (f" ({note})" if note else ""), "$warning"
    if result == "held":
        return ("held: Update all skips it" if newest and newest != installed else "held"), "$text-secondary"
    if result == "missing":
        return ("not downloaded yet: Start downloads it" if item.kind == "service" else "not installed"), MUTED
    if result == "other":
        return f"installed another way, at {installed}", MUTED
    return "couldn't check online", "$error"


def newest_of(found):
    """The newer version a check found, as the menus show it, or "" """
    if not found or found[0] not in ("newer", "held") or not found[2]:
        return ""
    if found[2] == found[1]:
        # The same version: a new build of it, unless it's only held there
        return "new build" if found[0] == "newer" else ""
    return show_version(found[2])


class UpdatesMenu(ModalScreen):
    """The update overview, in a box over the menu. A row's number (or Enter
    on it) shows its Update, Revert and Hold; a updates all, after a
    question, c checks again, and Esc, ← or a click beside the box closes
    it: keys do their entry at once, as everywhere in the menu."""

    BINDINGS = [Binding("escape", "close", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="updates"):
            yield Static(id="updates-head")
            yield MenuList(id="updates-list")
            yield Static(id="updates-hint")

    def on_mount(self):
        box = self.query_one("#updates")
        box.border_title = "Updates"
        box.border_subtitle = "a row's number: Update, Revert or Hold it · Esc closes"
        self.fill()
        rows = self.query_one("#updates-list", MenuList)
        # On the first one with an update, else the first one
        menu = self.app
        first = next((n for n, item in enumerate(menu.items, 1) if (menu.found_for(item) or ("",))[0] == "newer"), None)
        index = rows.keys.get(str(first)) if first else None
        rows.highlighted = index if index is not None else rows.first_enabled()
        rows.focus()

    # --- What it shows ---

    def items(self):
        """The groups with something to update, as (group, items)"""
        groups = []
        for group, _, members in self.app.groups:
            found = [item for item in members if item.kind in ("service", "app")]
            if found:
                groups.append((group, found))
        return groups

    def number_of(self, item):
        return next(n for n, known in enumerate(self.app.items, 1) if known is item)

    def fill(self):
        """Draws the rows again, such as when an answer came in"""
        menu = self.app
        rows = self.query_one("#updates-list", MenuList)
        width = rows.width()
        groups = self.items()
        versions = [v for _, items in groups for item in items
                    for v in (self.installed_of(item), newest_of(menu.found_for(item)))]
        versions += [v for tool in self.tools() for v in tool[1:3]]
        version_width = max(7, min(13, max((len(v) for v in versions), default=7)))
        entries = []
        for group, items in groups:
            if entries:
                entries.append((None, Content(" "), None, ""))
            entries.append((None, Content.styled(group.upper(), "bold $text-primary"), None, ""))
            for item in items:
                number = self.number_of(item)
                entries.append((str(number), self.row_line(number, item, width, version_width), f"row-{number}", ""))
        tools = self.tools()
        if tools:
            entries.append((None, Content(" "), None, ""))
            entries.append((None, Content.assemble(("TOOLS", "bold $text-primary"),
                                                   ("  updated another way", MUTED)), None, ""))
            for tool in tools:
                entries.append((None, self.tool_line(tool, width, version_width), None, ""))
        entries.append((None, Content(" "), None, ""))
        todo = menu.updates_to_do()
        checking = bool(menu.check and menu.check.running)
        if todo:
            note = f"{len(todo)} update{'s' if len(todo) != 1 else ''}, one after another; held ones stay as they are"
        else:
            note = "nothing to update"
        why_all = ("It's still looking online: wait for it." if checking else
                   "" if todo else "Nothing to update: every one is up to date, held, or not checked.")
        entries.append(("a", self.action_line("a", "Update all", note, "$warning", why_all), "all", why_all))
        entries.append(("c", self.action_line("c", "Check again", "looks online; nothing is downloaded", "$primary",
                                              "It's checking now." if checking else ""), "check",
                        "It's checking now." if checking else ""))
        rows.fill(entries)
        self.show_head()
        self.show_hint()
        self.fit_height()

    def tools(self):
        check = self.app.check
        return check.tools if check and check.tools else stack.last_tools()

    def installed_of(self, item):
        found = self.app.found_for(item)
        if found and found[0] == "other":
            return ""
        if item.version:
            return item.version
        return show_version(found[1]) if found and found[1] else ""

    def row_line(self, number, item, width, version_width):
        menu = self.app
        found = menu.found_for(item)
        pending = bool(menu.check and menu.check.running and where(item.path) not in menu.check.rows)
        symbol, word, style = menu.state_of(item)
        installed, newest = self.installed_of(item), newest_of(found)
        text, text_style = finding(item, found, pending)
        parts = [(f"{number:>2}  ", MUTED), (fit(item.name, NAME_WIDTH), "bold"), " ",
                 (fit(f"{symbol} {word}" if word else "", STATUS_WIDTH), style), " ",
                 (fit(installed, version_width), MUTED), " ",
                 ("→ " if newest else "  ", "$warning"), (fit(newest, version_width), "bold $warning"), "  ",
                 (text, text_style)]
        return Content.assemble(*parts).truncate(width, ellipsis=True)

    def tool_line(self, tool, width, version_width):
        """A tool's row, its note wrapped under itself when it's long"""
        name, version, newest, note = tool
        parts = ["    ", (fit(name, NAME_WIDTH), "bold $foreground"), " ", " " * STATUS_WIDTH, " ",
                 (fit(version, version_width), MUTED), " ",
                 ("→ " if newest else "  ", "$warning"), (fit(newest, version_width), "bold $warning"), "  "]
        start = Content.assemble(*parts)
        room = width - start.cell_length
        if room < 20:
            return (start + Content.styled(note, MUTED)).truncate(width, ellipsis=True)
        lines = Content.styled(note, MUTED).wrap(room) or [Content("")]
        return Content("\n").join([start + lines[0]] + [Content(" " * start.cell_length) + line for line in lines[1:]])

    def action_line(self, key, label, note, style, why):
        return Content.assemble((f"{key:>2}  ", MUTED), (label, MUTED if why else style),
                                (f"  {note}", MUTED))

    def show_head(self):
        menu = self.app
        check = menu.check
        lines = [Content.styled("Each one's version on this PC and its newest stable release.", MUTED)]
        if check and check.running:
            total = sum(len(items) for _, items in self.items())
            lines.append(Content.styled(f"Looking online… {len(check.rows)} of {total} answered", "$warning"))
        elif check and check.failed and not check.rows:
            lines.append(Content.styled("The check couldn't run. c tries again; src/bash/check-updates.sh in a "
                                        "terminal shows why.", "$error"))
        else:
            last = stack.last_check()
            if check and check.ended:
                when = f"Checked online at {time.strftime('%H:%M', time.localtime(check.ended))}"
            elif last:
                when = f"Checked online {stack.age_text(last[0])}"
            else:
                when = "Not checked online yet: c checks"
            count = len(menu.updates_to_do())
            lines.append(Content.assemble((when, ""), (f" · {count} update{'s' if count != 1 else ''}"
                                                       if count else " · nothing to update", MUTED)))
        self.query_one("#updates-head", Static).update(Content("\n").join(lines))

    def show_hint(self):
        rows = self.query_one("#updates-list", MenuList)
        option = rows.highlighted_option
        # Why a key was refused stays until the highlight moves, through the redraws as answers come in
        refusal = getattr(self, "refusal", None)
        if refusal and option and refusal[1] == option.id:
            self.query_one("#updates-hint", Static).update(Content.styled(refusal[0], "$warning"))
            return
        self.refusal = None
        text = self.hint_for(option.id) if option else ""
        self.query_one("#updates-hint", Static).update(Content.styled(text, MUTED))

    def hint_for(self, option_id):
        menu = self.app
        if option_id == "all":
            todo = menu.updates_to_do()
            names = listed(item.name for item in todo) or "nothing"
            return (f"Updates {names}, one after another, each with its notification. Held ones stay "
                    "as they are. It asks first.")
        if option_id == "check":
            return "Looks online for the newest stable release of each one, without downloading anything."
        item = menu.item_for(f"item-{option_id[4:]}") if option_id and option_id.startswith("row-") else None
        if not item:
            return ""
        found = menu.found_for(item)
        newest = newest_of(found)
        if found and found[0] == "newer":
            return (f"{item.name} {self.installed_of(item)} → {newest} is available. Its number or Enter: Update it, "
                    "or Hold it where it is.")
        if item.held:
            return f"{item.name} is held at {item.version or 'its version'}. Its number or Enter: release the hold, or Revert."
        return f"Its number or Enter: Update, Revert or Hold {item.name}."

    def fit_height(self):
        """The list gets the room the screen has, and scrolls past that"""
        rows = self.query_one("#updates-list", MenuList)
        head = self.query_one("#updates-head").outer_size.height or 3
        hint = self.query_one("#updates-hint").outer_size.height or 3
        rows.styles.max_height = max(5, int(self.size.height * 0.92) - head - hint - 2)

    def on_resize(self, event):
        self.fill()

    # --- Doing things ---

    @on(OptionList.OptionHighlighted, "#updates-list")
    def highlighted(self, event):
        self.show_hint()

    @on(OptionList.OptionSelected, "#updates-list")
    def chosen(self, event):
        menu = self.app
        option_id = event.option_id
        if option_id == "check":
            menu.check_updates()
        elif option_id == "all":
            menu.update_all(began=self.began)
        elif option_id and option_id.startswith("row-"):
            item = menu.item_for(f"item-{option_id[4:]}")
            if item:
                menu.open_actions(item, only=UPDATE_ACTIONS, began=self.began)

    def began(self, item=None):
        """Something chosen here runs now: the box closes, so its notification
        shows how it goes, and the list shows its entry"""
        if self.app.screen is self:
            self.dismiss()
        if item:
            self.app.show_entry(item)

    def refused(self, reason):
        """The key of a row or an action that can't be done now: why, where the hint is"""
        option = self.query_one("#updates-list", MenuList).highlighted_option
        self.refusal = (reason, option.id if option else None)
        self.show_hint()

    def key_hints(self):
        return [("↑↓", "move"), ("Enter or a row's number", "Update, Revert or Hold it"), ("a", "update all"),
                ("c", "check again"), ("Esc", "closes")]

    def action_close(self):
        self.dismiss()

    def action_noop(self):
        pass

    def on_click(self, event):
        # A click beside the box closes it, as beside a menu
        if event.widget is self:
            self.dismiss()
