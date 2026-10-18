#!/usr/bin/env python3
"""ai-leverage/src/python/notices.py

The menu's notifications, in a column of their own right of the log, as
high as the list. In a terminal narrower than 160 columns they're a row
along the bottom instead, the full width, with the cards side by side.
Each thing the menu runs for an entry (Start, Stop, Update, a folder's
script...) gets a card there as it begins, the newest at the top, so the
column reads like a queue: what came before moves down (in the row: to the
right), and it scrolls once there's more than fits.

A card's colour says how it's doing: yellow while it runs, green once it's
done, red when it failed or was stopped, blue while its script asks you
something and waits for the answer. An engine that loads its model counts
as running until it answers, so its Start turns green once you can use it.
A click on a card, or Enter on it, shows its whole log in a window over the
menu; a question waits under the log there, answered y or n. Its ×, or x, closes the card: one whose action hasn't
finished asks first, since closing it stops that action.
The column keeps the last 10 cards (MENU_NOTIFICATIONS in config/menu.conf,
or AI Leverage › Notifications); with one more, the oldest finished card
closes.

Short messages, such as why something can't be done now, are grey cards,
and close by themselves after a few seconds, as the toasts they replace did.
While a box is open over the menu, they pop up at the bottom right instead,
where they can be seen.

Keys, as everywhere in the menu: ↑↓ move between the cards (← → in the row),
Enter shows the log, x closes the card, c closes every finished one, Esc
goes back to the list (← in the column, ↑ in the row, too), and a number
goes to that entry of the list.

Not run on its own: menu.py uses it.
"""

import re
import time

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Static

from console import ANSI, RISKY, SAFE, Pane, elapsed, took
from tui import MUTED, MenuList, first_key

# How a card shows each state: its symbol and its colour
LOOKS = {
    "running": ("◐", "$warning"),
    "done": ("√", "$success"),
    "failed": ("!", "$error"),
    "asking": ("?", "$primary"),
    "info": ("•", MUTED),
    "warning": ("!", "$warning"),
}

KEEP = 10                     # how many cards the column keeps, unless config/menu.conf says otherwise
ROW_LINES = 3                 # a card's lines in the row along the bottom, in a narrower terminal
KEEP_CHOICES = (5, 10, 20, 50)

EMPTY = ("Nothing yet. What you start, stop or update shows here: yellow while it runs, green when it's done, "
         "red when it failed, blue when it asks you something. A click on one shows its whole log.")
ASKING = "Waiting for answer"


PERCENT = re.compile(r"(\d{1,3})%")


def last_line(run):
    """The last thing a run printed, without the menu's own ── lines, and
    whether it's a line still being redrawn, such as a download's progress.
    Of several redrawn together (Ollama shows a line for each part of a
    model), the one still on its way."""
    if run.live and run.live.strip():
        lines = [line for line in (ANSI.sub("", part).translate(SAFE).strip() for part in run.live.split("\n")) if line]
        going = [line for line in lines if any(int(n) < 100 for n in PERCENT.findall(line))]
        return (going or lines)[-1], True
    for line in reversed(run.lines):
        line = line.strip().translate(SAFE)
        if line and not line.startswith("──"):
            return line, False
    return "", False


class Notice:
    """One notification: something the menu runs or ran for an entry, or a message"""

    def __init__(self, title, item=None, run=None, state="info", text="", timeout=None, opens=None):
        self.title = title
        self.item = item          # the entry it's about, if any
        self.run = run            # the console.Run whose log it shows, if any
        self.status = state       # without a run: running, done, failed, info or warning
        self.text = text          # the line under the title; for a run, what the menu says once it's done
        self.timeout = timeout    # a message closes by itself after so many seconds
        self.opens = opens        # what a click does when there's no log to show
        self.phase = None         # after Start: "checking" or "loading" (still running), "ready" or "broken"
        self.since = None         # when what it waits for began, such as the container's start, as time.time()
        self.created = time.time()
        self.ended = None         # when it was done, as time.time(), when that isn't when its run ended
        self.card = None

    @property
    def state(self):
        run = self.run
        if run is None:
            return self.status
        if run.question:
            return "asking"
        if run.busy or self.phase in ("checking", "loading"):
            return "running"
        if run.code or self.phase == "broken":
            return "failed"
        return "done"

    @property
    def going(self):
        """Whether what it's about hasn't finished: it runs, or waits for your answer"""
        return self.state in ("running", "asking")

    @property
    def transient(self):
        """A message that closes by itself, and doesn't count among the cards kept"""
        return self.timeout is not None

    def corner(self):
        """What the card's top right says: how long it has been running, or when it was done"""
        if self.going:
            since = self.since or (self.run.wall if self.run else self.created)
            return elapsed(max(0, time.time() - since))
        at = self.ended or (self.run.finished_wall if self.run and self.run.finished_wall else self.created)
        return time.strftime("%H:%M", time.localtime(at))

    def detail(self):
        """The line under the title"""
        run = self.run
        if run is None:
            return self.text
        if run.question:
            return ASKING
        if run.busy:
            return last_line(run)[0] or "starting…"
        seconds = took((run.finished or time.monotonic()) - run.started)
        if run.stopping and run.code:
            return f"stopped after {seconds}"
        if run.code:
            last = last_line(run)[0]
            return f"failed after {seconds} (exit code {run.code})" + (f": {last}" if last else "")
        return self.text or f"done in {seconds}"


# --- A card ---

class CardText(Widget):
    """A card's words: its symbol and title with the time at the right, and
    the line under them. A message wraps; an action's line is cut to fit,
    and its log has the rest."""

    def __init__(self, notice):
        super().__init__()
        self.notice = notice

    def lines(self, width):
        notice = self.notice
        width = max(12, width)
        symbol, style = LOOKS[notice.state]
        if notice.transient:
            # A message: its words, wrapped under themselves
            parts = Content(notice.title).wrap(width - 2) or [Content("")]
            return [Content.assemble((f"{symbol} " if n == 0 else "  ", f"bold {style}"), part)
                    for n, part in enumerate(parts)]
        corner = notice.corner()
        title = Content.styled(notice.title, "bold").truncate(max(4, width - 2 - len(corner) - 1), ellipsis=True)
        first = Content.assemble((f"{symbol} ", f"bold {style}"), title)
        first += Content(" " * max(1, width - first.cell_length - len(corner))) + Content.styled(corner, MUTED)
        lines = [first]
        detail = notice.detail()
        if detail and notice.run is not None and notice.run.busy and last_line(notice.run)[1] \
                and len(detail) > width - 2:
            # A progress bar says the most at its end: 45%|#####     | 2.2/4.9G
            return lines + [Content.styled("  …" + detail[-(width - 3):], MUTED)]
        if detail:
            # A failure gets two lines, to say why
            parts = Content.styled(detail, MUTED).wrap(width - 2)
            room = 2 if notice.state == "failed" else 1
            if len(parts) > room:
                parts = parts[:room - 1] + [Content.styled(" ".join(p.plain for p in parts[room - 1:]), MUTED)
                                            .truncate(width - 2, ellipsis=True)]
            lines += [Content("  ") + part for part in parts]
        return lines

    def shown(self, width):
        """Its lines, cut to the three a card has in the row along the bottom"""
        lines = self.lines(width)
        column = self.parent.parent if self.parent else None
        if isinstance(column, NoticeColumn) and column.across() and len(lines) > ROW_LINES:
            last = lines[ROW_LINES - 1]
            lines = lines[:ROW_LINES - 1] + [last.truncate(max(1, width - 1)) + Content.styled("…", MUTED)]
        return lines

    def render(self):
        return Content("\n").join(self.shown(self.size.width))

    def get_content_height(self, container, viewport, width):
        return len(self.shown(width))


class CloseButton(Static):
    """A card's ×: a click closes the card, after asking when its action
    hasn't finished"""


class NoticeCard(Horizontal):
    """One notification in the column, coloured by its state"""

    def __init__(self, notice):
        super().__init__(classes=f"-{notice.state}")
        self.notice = notice
        self.looks = notice.state

    def compose(self) -> ComposeResult:
        yield CardText(self.notice)
        yield CloseButton("×")

    def on_mount(self):
        self.sync()

    def sync(self):
        """Draws it again, in its state's colour"""
        state = self.notice.state
        if state != self.looks:
            self.remove_class(f"-{self.looks}")
            self.add_class(f"-{state}")
            self.looks = state
        # Its parts may not be there: a card closed again before it was drawn, such as by the limit
        for button in self.query(CloseButton):
            button.tooltip = ("Stop it and close this notification: asks first   x" if self.notice.going
                              else "Close this notification   x")
        for text in self.query(CardText):
            text.refresh(layout=True)

    def on_click(self, event):
        event.stop()
        column = self.parent
        if isinstance(event.widget, CloseButton):
            column.ask_close(self.notice)
        else:
            column.set_cursor(self.notice)
            column.open(self.notice)


# --- The column ---

class NoticeColumn(VerticalScroll, can_focus=True):
    """The notifications, the newest at the top. Its frame says how many run
    (◐ 2) and how many wait for your answer (? 1), and "clear" at its right
    closes every finished card; one that waits isn't finished."""

    BINDINGS = [
        Binding("up", "arrow('up')", show=False),
        Binding("down", "arrow('down')", show=False),
        Binding("left", "arrow('left')", show=False),
        Binding("right", "arrow('right')", show=False),
        Binding("home", "move(-1000)", show=False),
        Binding("end", "move(1000)", show=False),
        Binding("enter", "open", show=False),
        Binding("delete", "close", show=False),
        Binding("escape", "app.pane_back", show=False),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.notices = []    # newest first
        self.cursor = None   # the card Enter opens while the column has the focus
        self.keep = KEEP

    def compose(self) -> ComposeResult:
        yield Static(Content.styled(EMPTY, MUTED), id="notices-empty")

    def on_mount(self):
        self.retitle()

    def on_resize(self, event):
        self.retitle()

    # --- Cards in, cards out ---

    def add(self, notice):
        """A new card, at the top"""
        self.notices.insert(0, notice)
        notice.card = NoticeCard(notice)
        self.mount(notice.card, before=0)
        self.query_one("#notices-empty").display = False
        if notice.transient:
            self.set_timer(notice.timeout, lambda: self.close(notice))
        self.prune()
        self.retitle()
        return notice

    def close(self, notice):
        if notice not in self.notices:
            return
        index = self.notices.index(notice)
        self.notices.remove(notice)
        if notice.card:
            notice.card.remove()
            notice.card = None
        if self.cursor is notice:
            self.cursor = None
            if self.notices:
                self.set_cursor(self.notices[min(index, len(self.notices) - 1)])
        self.query_one("#notices-empty").display = not self.notices
        self.retitle()

    def ask_close(self, notice):
        """× or x: the menu closes it, asking first when its action hasn't finished"""
        if hasattr(self.app, "close_notice"):
            self.app.close_notice(notice)
        else:
            self.close(notice)

    def close_finished(self):
        """Closes every card whose action is done, and the messages"""
        for notice in [n for n in self.notices if not n.going]:
            self.close(notice)

    def prune(self):
        """Closes the oldest finished cards while there are more than it keeps.
        A card whose action still runs stays, and closes once it's done."""
        kept = [notice for notice in self.notices if not notice.transient]
        excess = len(kept) - self.keep
        for notice in reversed(kept):
            if excess <= 0:
                break
            if not notice.going:
                self.close(notice)
                excess -= 1

    def set_keep(self, keep):
        self.keep = keep
        self.prune()
        self.retitle()

    def changed(self, notice):
        """A card's action printed more or changed its state"""
        if notice.card:
            was = notice.card.looks
            notice.card.sync()
            if notice.card.looks != was:
                self.prune()
                self.retitle()

    def for_run(self, run):
        return next((notice for notice in self.notices if notice.run is run), None)

    def tick(self):
        """Moves the clocks on the cards that run"""
        for notice in self.notices:
            if notice.card and notice.going:
                notice.card.sync()

    def running(self):
        return sum(notice.state == "running" for notice in self.notices)

    def asking(self):
        return sum(notice.state == "asking" for notice in self.notices)

    # --- Its frame ---

    def retitle(self):
        """The title at the left of the top frame, with how many run, and "clear" at the right"""
        width = self.outer_size.width
        running = self.running()
        title = Content.styled("Notifications", "bold")
        # How many run and how many wait for your answer: a symbol and a number each, in their cards' colours
        if running:
            title += Content.styled(f"  ◐ {running}", "$warning")
        asking = self.asking()
        if asking:
            title += Content.styled(f"  ? {asking}", "$primary")
        finished = any(not notice.going for notice in self.notices)
        controls = Content.styled(" clear ", f"bold {MUTED}").stylize("@click=app.notices_clear") if finished \
            else Content("")
        if width >= 16:
            # The frame keeps "╭─ " and " ─╮" at its ends; a space each side of the line
            room = width - 8 - controls.cell_length
            title = title.truncate(max(1, room - 1), ellipsis=True)
            line = "$border" if self.has_focus else "$foreground 20%"
            if finished:
                self.border_title = Content.assemble(title, " ", ("─" * max(1, room - title.cell_length), line), " ",
                                                     controls)
            else:
                # Without "clear", the line runs on to the frame's corner
                self.border_title = Content.assemble(title, " ", ("─" * max(1, room + 1 - title.cell_length), line))
        kept = sum(not notice.transient for notice in self.notices)
        self.border_subtitle = Content.styled(f"{kept} of the last {self.keep} kept" if kept else
                                              f"keeps the last {self.keep}", MUTED)

    def on_mouse_move(self, event):
        # The mouse on "clear" says what it does
        tip = None
        if event.y == 0 and self.outer_size.width - 10 <= event.x < self.outer_size.width - 3 \
                and any(not notice.going for notice in self.notices):
            tip = "Close every finished notification   c"
        if tip != self.tooltip:
            self.tooltip = tip

    def on_leave(self, event):
        self.tooltip = None

    # --- Moving and keys ---

    def across(self):
        """Whether the cards run side by side: the row along the bottom, in a narrower terminal"""
        return self.styles.layout is not None and self.styles.layout.name == "horizontal"

    def action_arrow(self, direction):
        """The arrows along the cards move between them; the one towards the
        list goes back to it (← in the column, ↑ in the row)"""
        steps = {"left": -1, "right": 1} if self.across() else {"up": -1, "down": 1}
        if direction in steps:
            self.action_move(steps[direction])
        elif direction == ("up" if self.across() else "left"):
            self.app.pane_back()

    def on_mouse_scroll_down(self, event):
        # In the row, the wheel scrolls sideways (it only scrolls up and down by itself)
        if self.across():
            self.scroll_relative(x=10, animate=False)
            event.stop()

    def on_mouse_scroll_up(self, event):
        if self.across():
            self.scroll_relative(x=-10, animate=False)
            event.stop()

    def on_focus(self, event):
        if self.cursor not in self.notices and self.notices:
            self.set_cursor(self.notices[0])
        self.retitle()

    def on_blur(self, event):
        self.retitle()

    def set_cursor(self, notice):
        if self.cursor and self.cursor.card:
            self.cursor.card.remove_class("-cursor")
        self.cursor = notice
        if notice and notice.card:
            notice.card.add_class("-cursor")
            self.scroll_to_widget(notice.card, animate=False)

    def action_move(self, delta):
        if not self.notices:
            return
        index = self.notices.index(self.cursor) if self.cursor in self.notices else 0
        self.set_cursor(self.notices[max(0, min(len(self.notices) - 1, index + delta))])

    def action_open(self):
        if self.cursor in self.notices:
            self.open(self.cursor)

    def action_close(self):
        if self.cursor in self.notices:
            self.ask_close(self.cursor)

    def open(self, notice):
        """Its whole log in a window over the menu, or what it's about"""
        if notice.run is not None:
            self.app.push_screen(RunWindow(notice))
        elif notice.opens:
            notice.opens()

    def on_key(self, event):
        # A letter does it at once, as everywhere in the menu; a number goes to that entry of the list
        character = (event.character or "").lower()
        if event.key.startswith("alt+") or not character:
            return
        if character.isdigit():
            event.stop()
            self.app.type_in_list(character)
        elif character == "x":
            event.stop()
            self.action_close()
        elif character == "c":
            event.stop()
            self.close_finished()


# --- A card's whole log ---

class RunLog(Pane):
    """What a notification's action printed, all of it, live while it runs,
    in a window over the menu"""

    BINDINGS = [Binding("escape", "close", show=False), Binding("left", "close", show=False)]

    def __init__(self, notice, **kwargs):
        super().__init__(**kwargs)
        self.notice = notice
        self.written = 0     # how many of its run's lines it shows

    def source(self):
        run = self.notice.run
        return list(run.shown), (run.live if run.busy else None)

    def redraw(self):
        super().redraw()
        self.written = self.notice.run.total

    def more(self):
        """What its run printed since the last look, and its state in the frame"""
        run = self.notice.run
        new = min(run.total - self.written, len(run.shown))
        if new > 0:
            self.drop_live()
            for text, style in list(run.shown)[-new:]:
                self.put(text, style)
        self.written = run.total
        self.show_live(run.live if run.busy else None)
        self.retitle()

    def retitle(self):
        notice = self.notice
        symbol, style = LOOKS[notice.state]
        if notice.state == "asking":
            note = f"{symbol} waiting for answer  {notice.corner()}"
        elif notice.run.busy:
            note = f"{symbol} running  {notice.corner()}"
        elif notice.state == "running":
            # Its script is done, and it waits for the engine to answer
            note = f"{symbol} {notice.detail()}  {notice.corner()}"
        else:
            note = f"{symbol} {notice.detail()}"
        self.set_title(notice.title, Content.styled(note, style))
        self.border_subtitle = Content.styled(
            "s saves" + (" · ctrl+c stops it" if notice.run.busy else "") + " · Esc closes", MUTED)
        if self.screen is self.app.screen and hasattr(self.app, "refresh_keys"):
            self.app.refresh_keys()

    def on_key(self, event):
        # y or n answers what its script asks, also while the log has the focus
        character = (event.character or "").lower()
        if character in ("y", "n") and self.notice.run.question and not event.key.startswith("alt+"):
            event.stop()
            self.app.runs.answer(self.notice.run, character == "y")
            return
        super().on_key(event)

    def slug(self):
        item = self.notice.item
        return f"{item.name if item else 'menu'}_{self.notice.run.title.lower().replace(' ', '-')}"

    def controls(self):
        return [("save", "save", "Save this log as a text file in logs/   s"), ("close", "×", "Close   Esc")]

    def click(self, name):
        return f"screen.control({name!r})"

    def do(self, name):
        if name == "save":
            self.save()
        elif name in ("close", "back"):
            self.screen.dismiss()

    def action_close(self):
        self.screen.dismiss()

    def stop(self):
        run = self.notice.run
        if run.busy:
            self.app.stop_run(run, self.notice.item, risky=run.title in RISKY)


class RunWindow(ModalScreen):
    """A notification's whole log, over the menu. Esc, ← or a click beside
    it closes it; s saves it; ctrl+c stops what runs. While its script asks
    something, the question waits under the log, answered "Yes, …" or
    "No, …" as the menu's other questions are: No highlighted first, y or n
    at once. Closing the window leaves it waiting."""

    BINDINGS = [Binding("escape", "close", show=False)]

    def __init__(self, notice):
        super().__init__()
        self.notice = notice
        self.asked = None    # the question it shows

    def compose(self) -> ComposeResult:
        with Vertical(id="runwindow"):
            yield RunLog(self.notice, id="runlog", classes="panel")
            with Vertical(id="asking") as box:
                box.border_title = Content.styled(f"{LOOKS['asking'][0]} Waiting for answer", "bold")
                box.border_subtitle = Content.styled("y yes · n no · Esc closes, it keeps waiting", MUTED)
                yield Static(id="asking-question")
                yield MenuList(id="asking-answers")

    def on_mount(self):
        log = self.query_one(RunLog)
        log.retitle()
        log.focus()
        self.query_one("#asking").display = False
        self.show_question()

    def more(self):
        self.query_one(RunLog).more()
        self.show_question()

    def show_question(self):
        """The question its script asks now, under the log, or none"""
        question = self.notice.run.question
        if question == self.asked:
            return
        self.asked = question
        box = self.query_one("#asking")
        box.display = question is not None
        if question:
            text, yes, no = question
            self.query_one("#asking-question", Static).update(Content(text))
            answers = self.query_one("#asking-answers", MenuList)
            answers.fill([("y", first_key("Yes") + Content(f", {yes}"), "yes", ""),
                          ("n", first_key("No") + Content(f", {no}"), "no", "")], keep=False)
            answers.highlighted = answers.keys["n"]
            answers.focus()
        elif self.focused is None or self.focused.id == "asking-answers":
            self.query_one(RunLog).focus()
        if hasattr(self.app, "refresh_keys"):
            self.app.refresh_keys()

    def on_option_list_option_selected(self, event):
        if event.option_list.id == "asking-answers":
            event.stop()
            self.app.runs.answer(self.notice.run, event.option_id == "yes")

    def key_hints(self):
        if self.notice.run.question:
            return [("y", "yes"), ("n", "no"), ("Esc", "closes, it keeps waiting")]
        hints = [("↑↓ PgUp PgDn", "scroll"), ("s", "save")]
        if self.notice.run.busy:
            hints.append(("ctrl+c", "stop it"))
        return hints + [("Esc", "closes")]

    def action_control(self, name):
        self.query_one(RunLog).do(name)

    def action_close(self):
        self.dismiss()

    def on_click(self, event):
        if event.widget is self:
            self.dismiss()
