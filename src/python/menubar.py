#!/usr/bin/env python3
"""ai-leverage/src/python/menubar.py

The menu bar at the top of manage.sh's menu, drawn by the menu itself. The
terminal's own menus (File, Edit, View) belong to the terminal, differ from
one terminal to the next, and over ssh there may be none, so ai-leverage
brings its own.

Each menu has a letter, underlined in its title: Alt and that letter opens
it from anywhere (Alt+S opens Stack). So does a click on its title, and F10
opens the first one. The bar also takes the focus like the other areas,
with Tab, shift+Tab or ↑ from the top of the list: ← → choose a menu, its
letter or Enter or ↓ opens it, and Esc goes back to the list.

In the menus, a letter does what it stands for at once, as in a desktop
app's menus; that's the standard everywhere in the menu (tui.py). Each
entry has a letter of its own, bold and underlined in it, unique in that
menu only: typing it does the entry, so Alt+S, u opens Updates, and the
letter of an entry with ▸ goes into the menu beside it: Alt+M, d, h opens
huggingface. ↑↓ and the mouse only move, and Enter or a click does the
highlighted entry; ← → go to the menu next to it, and the mouse on another
title opens that one. An entry with ▸ shows its menu beside it as soon as
it's highlighted, as in Norton Commander: → or Enter goes into it, ← back
out. Esc goes one step back: out of a menu beside, or the menu closes; so
does a click beside it. The line at the bottom says what the highlighted
entry does, and its letter.

(The main list is the one exception: a number there only moves, since
that's how you look at an entry's log; Enter opens it.)

The right end of the bar says what needs attention (the updates the last
check found) and which ai-leverage this is.

Not run on its own: menu.py uses it, and says what the menus hold.
"""

from dataclasses import dataclass

from textual.binding import Binding
from textual.containers import Vertical
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static

from tui import MUTED, MenuList

OPEN = "bold reverse $text-accent"  # the title of the open menu
HOVER = "on $primary 30%"            # what the mouse is on
CURSOR = "bold on $primary 38%"      # the chosen title while the bar has the focus, like the list's highlight
MORE = "▸"                           # an entry that opens a menu of its own (one cell wide in every terminal)


@dataclass
class Entry:
    """One entry of a menu: what it says, what it does (an id for the app's
    run_tool), and what that is, for the line at the bottom. An entry with
    children opens a menu of its own: a list of entries, or the name of a
    group of folders the app fills in (menu_children)."""

    label: str
    action: str = ""
    about: str = ""
    children: object = None
    key: str = ""  # its letter in its menu; worked out from the label when empty


def letters_for(labels, taken=()):
    """A letter for each label, unique among them: the label's first letter
    that's still free; "" when none is"""
    used, found = set(taken), []
    for label in labels:
        letter = next((c for c in label.lower() if "a" <= c <= "z" and c not in used), "")
        used.add(letter)
        found.append(letter)
    return found


def keyed(entries):
    """(letter, entry) for each entry of a menu: its own key, or else the
    first free letter of its label"""
    given = {entry.key for entry in entries if entry.key}
    letters = iter(letters_for([entry.label for entry in entries if not entry.key], given))
    return [(entry.key or next(letters), entry) for entry in entries]


def mnemonics(menus):
    """{menu id: the letter that opens it with Alt}: each title's first free letter"""
    return dict(zip([menu_id for menu_id, _, _ in menus], letters_for([title for _, title, _ in menus])))


def underlined(title, letter, style):
    """A title with its letter in bold and underlined, as menus show the key that opens them"""
    at = title.lower().find(letter) if letter else -1
    if at < 0:
        return Content.styled(title, style)
    return Content.assemble((title[:at], style), (title[at], f"{style} bold underline"), (title[at + 1:], style))


class MenuBar(Static):
    """The menus' titles in one line, and a status at the right end.
    menus is [(id, title, entries)], entries being Entry."""

    can_focus = True
    # A click opens a menu but leaves the focus where it was, as on a desktop app's menu bar
    FOCUS_ON_CLICK = False
    BINDINGS = [
        Binding("left", "move(-1)", show=False),
        Binding("right", "move(1)", show=False),
        Binding("down", "open", show=False),
        Binding("enter", "enter", show=False),
        Binding("escape", "leave", show=False),
    ]

    def __init__(self, menus, **kwargs):
        super().__init__(**kwargs)
        self.menus = menus
        self.keys = mnemonics(menus)
        self.spans = []  # (first column, past the last, menu id or "status")
        self.hover = None
        self.cursor = menus[0][0]  # the title ← → choose while the bar has the focus
        self.last = (None, None, "")

    def menu_for(self, letter):
        return next((menu_id for menu_id, key in self.keys.items() if key == letter), None)

    def draw(self, open_menu=None, status=None, version=""):
        self.last = (open_menu, status, version)
        width = self.size.width or 100
        # The first title's word lines up with the text in the panels under it
        line, self.spans, column = [], [], 0
        for menu_id, title, _ in self.menus:
            if menu_id == open_menu:
                style = OPEN
            elif self.app.focused is self and menu_id == self.cursor:
                style = CURSOR
            else:
                style = "bold " + (HOVER if menu_id == self.hover else "")
            piece = Content.assemble((" ", style), underlined(title, self.keys.get(menu_id), style), (" ", style))
            line += [piece, Content(" ")]
            self.spans.append((column, column + piece.cell_length, menu_id))
            column += piece.cell_length + 1
        # At the right: the status, then the version, as long as there's room;
        # the last word ends where the text in the panels under it ends
        right = []
        if status and status.cell_length:
            right.append(("status", status))
        if version and column + (status.cell_length + 3 if status else 0) + len(version) + 2 <= width:
            right.append(("", Content.styled(version, MUTED)))
        room = width - column - sum(piece.cell_length for _, piece in right) - 2 * (len(right) - 1) - 1
        if right and room >= 1:
            line.append(Content(" " * room))
            column += room
            for n, (name, piece) in enumerate(right):
                if n:
                    line.append(Content("  "))
                    column += 2
                if name:
                    self.spans.append((column, column + piece.cell_length, name))
                    if name == self.hover:
                        piece = piece.stylize(HOVER)
                line.append(piece)
                column += piece.cell_length
        self.update(Content.assemble(*line))

    def at(self, x):
        """What's at a column: a menu's id, "status", or None"""
        return next((name for start, end, name in self.spans if start <= x < end), None)

    def start_of(self, menu_id):
        """The screen column a menu's title starts at"""
        return self.content_region.x + next((start for start, _, name in self.spans if name == menu_id), 0)

    def at_screen(self, x, y):
        """What's at a place on the screen, if it's on the bar's line"""
        content = self.content_region
        return self.at(x - content.x) if y == content.y else None

    def below(self):
        """The screen row a menu opens on: over the bar's bottom edge, so it hangs from the bar"""
        return self.region.y + self.region.height - 1

    def on_resize(self, event):
        self.app.draw_menubar()

    def on_mouse_move(self, event):
        name = self.at_screen(event.screen_x, event.screen_y)
        if name != self.hover:
            self.hover = name
            self.draw(*self.last)

    def on_leave(self, event):
        if self.hover:
            self.hover = None
            self.draw(*self.last)

    def on_click(self, event):
        name = self.at_screen(event.screen_x, event.screen_y)
        if name == "status":
            self.app.run_tool("updates")
        elif name:
            self.app.open_menu(name)

    # --- The keys, while the bar has the focus ---

    def enter(self, first=True):
        """The list's ↑ past its top entry comes here"""
        self.focus()

    def on_focus(self, event):
        self.app.draw_menubar()

    def on_blur(self, event):
        self.app.draw_menubar()

    def action_move(self, step):
        ids = [menu_id for menu_id, _, _ in self.menus]
        self.cursor = ids[(ids.index(self.cursor) + step) % len(ids)]
        self.app.draw_menubar()

    def action_open(self):
        self.app.open_menu(self.cursor)

    def action_enter(self):
        self.action_open()

    def action_leave(self):
        self.app.leave_menubar()

    def on_key(self, event):
        character = event.character
        if event.key.startswith("alt+") or not character:
            return
        if character.isdigit():
            event.stop()
            self.app.type_in_list(character)
        elif self.menu_for(character.lower()):
            # On the bar, a menu's letter opens it without Alt, as in a desktop app's menu bar
            event.stop()
            self.app.open_menu(self.menu_for(character.lower()))


class DropList(MenuList):
    """A menu's entries. ← and → go out of a menu beside, into one, or to
    the menu next to it in the bar, depending on where you are."""

    BINDINGS = [Binding("left", "screen.arrow('left')", show=False),
                Binding("right", "screen.arrow('right')", show=False)]

    def act(self):
        # A letter does its entry at once, as in every box; one with ▸ goes into its menu beside
        self.screen.lettered(self)


class MenuDropdown(ModalScreen):
    """An open menu, under its title in the bar, and the menu of the
    highlighted entry beside it when it has one. Dismisses with the action
    of the entry to do, or None."""

    BINDINGS = [Binding("escape", "close", show=False)]

    def __init__(self, bar, menu_id, highlight=None):
        super().__init__()
        self.bar, self.menu_id, self.highlight = bar, menu_id, highlight
        self.entries = []     # the open menu's entries
        self.inner = []       # the entries of the menu beside it, while one shows
        self.beside = None    # the index of the entry whose menu shows beside it
        self.place = (0, 0, 0)  # where the open menu's box goes: left, top, width

    def compose(self):
        with Vertical(id="dropdown", classes="menu-box"):
            yield DropList(id="dropdown-list")
        with Vertical(id="submenu", classes="menu-box"):
            yield DropList(id="submenu-list")

    def on_mount(self):
        self.show(self.menu_id, self.highlight)

    # --- What it shows ---

    def fill(self, listing, entries):
        """Shows entries in a list, each with its letter at the right and ▸
        when it opens a menu of its own. Returns the width it needs."""
        app = self.app
        rows = [(letter, entry, app.menu_note(entry), app.menu_why(entry)) for letter, entry in keyed(entries)]
        label_width = max((len(entry.label) for _, entry, _, _ in rows), default=4)
        note_width = max((note.cell_length for _, _, note, _ in rows if note), default=0)
        more = any(entry.children for _, entry, _, _ in rows)
        options = []
        for index, (letter, entry, note, why) in enumerate(rows):
            label = underlined(entry.label, letter, MUTED if why else "")
            text = Content(" ") + label.pad_right(label_width - len(entry.label))
            if note_width:
                text += Content("  ") + (note or Content("")).pad_right(note_width - (note.cell_length if note else 0))
            if more:
                text += Content.styled(f"  {MORE if entry.children else ' '}", MUTED)
            text += Content("  ")
            options.append((letter, text, f"e{index}", why))
        listing.fill(options, keep=False)
        return 1 + label_width + (2 + note_width if note_width else 0) + (3 if more else 0) + 2 + 2

    def show(self, menu_id, highlight=None):
        """Shows a menu's entries, under its title"""
        self.menu_id = menu_id
        self.entries = self.app.menu_entries(menu_id)
        listing = self.query_one("#dropdown-list", DropList)
        listing.focus()
        self.hide_beside()
        width = self.fill(listing, self.entries)
        box = self.query_one("#dropdown")
        box.styles.width = width
        left = max(0, min(self.bar.start_of(menu_id), self.size.width - width))
        self.place = (left, self.bar.below(), width)
        box.styles.offset = (left, self.bar.below())
        index = next((i for i, entry in enumerate(self.entries) if highlight and entry.action == highlight), None)
        option = listing.keys.get(keyed(self.entries)[index][0]) if index is not None else None
        listing.highlighted = option if option is not None else listing.first_enabled()
        self.app.menu_opened(menu_id)
        self.show_hint()

    def entry_of(self, listing):
        """The entry a list highlights, or None"""
        option = listing.highlighted_option
        if not option:
            return None
        entries = self.inner if listing.id == "submenu-list" else self.entries
        index = int(option.id[1:])
        return entries[index] if index < len(entries) else None

    def show_beside(self, index):
        """Shows the menu of the entry at index beside this one, without going into it"""
        entry = self.entries[index]
        self.inner = self.app.menu_children(entry)
        self.beside = index
        submenu = self.query_one("#submenu")
        width = self.fill(self.query_one("#submenu-list", DropList), self.inner)
        submenu.styles.width = width
        # Its first entry level with the entry it belongs to. Where show() put
        # the box, not where it was last drawn: after ← or → that's still the
        # menu before, as wide as that one was
        box_left, box_top, box_width = self.place
        left = min(box_left + box_width, self.size.width - width)
        top = box_top + index
        submenu.styles.offset = (max(0, left), max(0, top))
        submenu.display = True
        self.query_one("#submenu-list", DropList).highlighted = None

    def hide_beside(self):
        submenu = self.query_one("#submenu")
        if submenu.display:
            # The focus first, so it isn't lost with the menu that goes
            self.query_one("#dropdown-list", DropList).focus()
            submenu.display = False
        self.beside, self.inner = None, []
        # Its entries go with it, so nothing reads one that isn't there any more
        self.query_one("#submenu-list", DropList).fill([], keep=False)

    def show_hint(self):
        # The menu beside only while it shows: the focus moves a moment after it goes
        listing = self.query_one("#submenu-list" if self.in_beside() else "#dropdown-list", DropList)
        entry = self.entry_of(listing)
        if entry:
            entries = self.inner if listing.id == "submenu-list" else self.entries
            letter = next((key for key, known in keyed(entries) if known is entry), "")
            self.app.menu_hint(entry, letter)

    def refused(self, reason):
        """A letter of an entry that can't be done now: why, in the line at the bottom"""
        self.app.menu_refused(reason)

    # --- Moving around ---

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted):
        listing = event.option_list
        if listing.id == "dropdown-list":
            index = int(event.option_id[1:])
            if self.entries[index].children:
                if self.beside != index:
                    self.show_beside(index)
            elif self.beside is not None:
                self.hide_beside()
        self.show_hint()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        entry = self.entry_of(event.option_list)
        if not entry:
            return
        if entry.children:
            self.go_beside()
        else:
            self.dismiss(entry.action)

    def lettered(self, listing):
        """A letter was typed in a menu: its entry, at once. One with ▸ goes
        into the menu beside it, which becomes the one in use; any other
        does what it stands for."""
        entry = self.entry_of(listing)
        if not entry:
            return
        if entry.children and listing.id == "dropdown-list":
            index = self.entries.index(entry)
            if self.beside != index:
                self.show_beside(index)
            self.go_beside()
        elif entry.action:
            self.dismiss(entry.action)

    def go_beside(self):
        """Into the menu beside"""
        listing = self.query_one("#submenu-list", DropList)
        if self.beside is None or not self.query_one("#submenu").display:
            return
        listing.focus()
        if listing.highlighted is None:
            listing.highlighted = listing.first_enabled()
        self.show_hint()

    def come_back(self):
        """Out of the menu beside, back to the entry it belongs to"""
        self.query_one("#submenu-list", DropList).highlighted = None
        self.query_one("#dropdown-list", DropList).focus()
        self.show_hint()

    def in_beside(self):
        """Whether the menu beside is the one in use: it shows, and has the focus"""
        return self.beside is not None and self.focused is not None and self.focused.id == "submenu-list"

    def action_arrow(self, direction):
        if direction == "left":
            if self.in_beside():
                self.come_back()
            else:
                self.action_step(-1)
        else:
            entry = self.entry_of(self.query_one("#dropdown-list", DropList))
            if not self.in_beside() and entry and entry.children:
                self.go_beside()
            else:
                self.action_step(1)

    def action_step(self, offset):
        ids = [menu_id for menu_id, _, _ in self.bar.menus]
        self.show(ids[(ids.index(self.menu_id) + offset) % len(ids)])

    def step_back(self):
        if self.in_beside():
            self.come_back()
        else:
            self.dismiss(None)

    def action_close(self):
        # Esc: out of the menu beside first, then the menu closes
        self.step_back()

    def on_key(self, event):
        """What the lists left alone: a number closes the menu and goes to
        that entry of the list"""
        character = event.character
        if event.key.startswith("alt+") or not character or len(character) != 1:
            return
        if character.isdigit():
            event.stop()
            self.dismiss(None)
            self.app.call_later(self.app.type_in_list, character)

    # --- The mouse ---

    def on_mouse_move(self, event):
        # Along the bar, the mouse on another title opens that menu
        name = self.bar.at_screen(event.screen_x, event.screen_y)
        if name and name != "status" and name != self.menu_id:
            self.show(name)

    def on_click(self, event):
        # A click inside a menu is its entries' business; only one beside them counts here
        boxes = [self.query_one("#dropdown")] + ([self.query_one("#submenu")] if self.beside is not None else [])
        if event.widget is not self or any(box.region.contains(event.screen_x, event.screen_y) for box in boxes):
            return
        name = self.bar.at_screen(event.screen_x, event.screen_y)
        if name == "status":
            self.dismiss("updates")
        elif name and name != self.menu_id:
            self.show(name)
        else:
            # Its own title again, or beside the menu: it closes
            self.dismiss(None)
