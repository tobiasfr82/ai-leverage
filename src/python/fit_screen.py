#!/usr/bin/env python3
"""ai-leverage/src/python/fit_screen.py

The model fit screen (Models › Tuning › Fit in the menu): which downloaded
models fit on this PC for what you need, biggest first, and for each one,
every way to run it, where the memory goes, and what to do to use it. Esc
goes back, as everywhere in the menu.

What you need is two choices at the top: how much context, and whether the
PC's memory may help (bigger models, slower). The list answers for that
goal. The calculation is model_fit.py's; this only draws it, with plain
terminal codes, and keeps your choices in config/model-fit.conf, where the
engines' model lists find them too.

Usage: python3 -I fit_screen.py [--print]
  Full screen in a terminal. --print, or output that isn't a terminal,
  prints the list for the saved goal once.
"""

import os
import re
import select
import shutil
import signal
import sys
import termios
import tty

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hardware  # noqa: E402
import model_facts  # noqa: E402
import model_fit as fit  # noqa: E402

K = fit.K

# --- Drawing ---

STYLES = {"bold": "1", "dim": "2", "rev": "7", "red": "31", "green": "32", "yellow": "33",
          "blue": "34", "magenta": "35", "cyan": "36", "grey": "90"}

# The parts of the memory bars: their colour, character and name
PARTS = {
    "model": ("cyan", "█", "model"),
    "working": ("blue", "█", "working"),
    "conversation": ("green", "█", "conversation"),
    "room": ("green", "░", "room for more"),
    "kept": ("grey", "▒", "kept free"),
    "others": ("grey", "▓", "others"),
    "free": ("grey", "░", "free"),
    "tables": ("magenta", "▒", "lookup tables"),
    "moved": ("magenta", "█", "from the GPU"),
}

USE_COLOUR = True


class Line:
    """A line of text in pieces, each with its own style"""

    def __init__(self, *pieces):
        self.pieces = []
        for piece in pieces:
            self.add(*piece) if isinstance(piece, tuple) else self.add(piece)

    def add(self, text, style=""):
        if text:
            self.pieces.append((text, style))
        return self

    def join(self, other):
        """Adds another line's pieces to this one"""
        self.pieces += other.pieces
        return self

    def pad(self, width):
        """Fills it to this many columns"""
        length = len(self)
        if length < width:
            self.add(" " * (width - length))
        return self

    def __len__(self):
        return sum(len(text) for text, _ in self.pieces)

    def draw(self, width):
        out, left = [], width
        for text, style in self.pieces:
            if left <= 0:
                break
            text = text[:left]
            left -= len(text)
            if style and USE_COLOUR:
                codes = ";".join(STYLES[s] for s in style.split())
                out.append(f"\033[{codes}m{text}\033[0m")
            else:
                out.append(text)
        return "".join(out)


def rule(width, char="─", label=""):
    if label:
        return Line((char * 2 + " ", "grey"), (label, "grey"), (" " + char * max(0, width - len(label) - 4), "grey"))
    return Line((char * width, "grey"))


def first_fitting(versions, width):
    """The first of several versions of a line that fits the width, else the last"""
    for version in versions:
        if len(version) <= width:
            return version
    return versions[-1]


def wrap(text, width):
    """Plain text in lines of at most this width"""
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    return lines + ([line] if line else [])


# --- The context bars: 4k to 256k, each doubling the same width ---

LOW, HIGH = 4 * K, 256 * K


def column(tokens, width):
    """How far along a bar of this width a context of so many tokens is"""
    if tokens <= LOW:
        return 0
    span = (tokens.bit_length() - 1) + (tokens / (1 << (tokens.bit_length() - 1)) - 1)
    low = LOW.bit_length() - 1
    return round(min(1.0, (span - low) / ((HIGH.bit_length() - 1) - low)) * width)


def context_bar(plan, pc_memory, width, need=0, dim=False):
    """A bar of how far a plan gets: green as set, yellow with 8-bit memory,
    magenta with the PC's memory, then dots up to the model's own limit"""
    line = Line()
    ends = [(column(plan.reach[fit.AS_SET], width), "green"),
            (column(plan.reach[fit.EIGHT_BIT], width), "yellow")]
    if pc_memory:
        ends.append((column(max(plan.reach[fit.PC_MEMORY], plan.reach[fit.BOTH]), width), "magenta"))
    top = column(plan.model.max_context or HIGH, width)
    mark = column(need, width) if need else -1
    for i in range(width):
        style = next((s for end, s in ends if i < end), None)
        if style:
            line.add("█", style + (" dim" if dim else ""))
        elif i == mark - 1:
            line.add("│", "yellow" if not dim else "grey")
        elif i < top:
            line.add("·", "grey")
        else:
            line.add(" ")
    return line


def scale(width, need, steps=(8 * K, 16 * K, 32 * K, 64 * K, 128 * K, 256 * K)):
    """Tick labels over the bars, each ending where its size is. The context
    you need stands out; a label with no room next to another is left out."""
    cells = [(" ", "")] * width
    taken = set()
    order = ([need] if need else []) + [256 * K] + sorted(steps, reverse=True)
    for tokens in dict.fromkeys(order):
        label = fit.tokens_text(tokens).lstrip("~")
        end = column(tokens, width)
        start = max(0, end - len(label))
        if any(i in taken for i in range(start - 1, end + 1)):
            continue
        style = "rev bold" if tokens == need else "grey"
        for i, char in enumerate(label):
            if start + i < width:
                cells[start + i] = (char, style)
                taken.add(start + i)
    line = Line()
    for char, style in cells:
        line.add(char, style)
    return line


def memory_bar(parts, total, width, over=0):
    """A bar of where a GPU's (or the PC's) memory goes, part by part"""
    line, used = Line(), 0
    for name, size in parts:
        style, char, _ = PARTS[name]
        start, used = round(used / total * width), used + size
        line.add(char * max(0, min(width, round(used / total * width)) - start), style)
    line.pad(width)
    if over:
        line.add(f" +{hardware.gb(over)} too much", "red bold")
    return line


def parts_key(parts):
    """What each colour of a memory bar is, and how big, in GB"""
    line = Line()
    for name, size in parts:
        if size < 0.05 * hardware.GiB:
            continue
        style, char, label = PARTS[name]
        line.add("  " if len(line) else "").add(char, style).add(f" {label} {size / hardware.GiB:.1f}")
    return line.add(" GB", "grey")


# --- What the screen shows ---

PLACES = {False: "on the GPU alone", True: "with the PC's memory helping"}


class Screen:
    def __init__(self):
        self.goal = fit.Goal()
        self.found = hardware.detect()
        self.engines = fit.engines_for(self.found)
        self.models = model_facts.all_models()
        self.gpu = self.found["gpus"][0] if self.found["gpus"] else None
        self.view = "list"
        self.selected = 0
        self.top = 0
        self.route = 0
        self.message = ""
        self.typing = None   # the context size being typed, after o
        self.hits = []       # (row, first column, last column, action) for the mouse
        self.build()

    def build(self):
        """Works out every model's ways to run it, for this many conversations"""
        self.groups = fit.groups(self.models, self.engines, self.goal.conversations)
        self.rank()

    def rank(self, keep=None):
        meets, misses = fit.ranked(self.groups, self.goal)
        self.meets, self.misses = meets, misses
        self.rows = meets + misses
        if keep is not None:
            index = next((i for i, (g, _, _) in enumerate(self.rows) if g is keep), None)
            self.selected = index if index is not None else min(self.selected, len(self.rows) - 1)
        self.selected = max(0, min(self.selected, len(self.rows) - 1))

    def current(self):
        return self.rows[self.selected][0] if self.rows else None

    # --- The top: the goal ---

    def header(self, width, title, right=()):
        """The title, and on its right the first of the versions that fits"""
        right = first_fitting(list(right) or [""], width - len(title) - 4)
        return [Line((f" {title}", "bold"), (" " * max(1, width - len(title) - len(right) - 2), ""),
                     (right, "grey")),
                rule(width, "═")]

    def hardware_texts(self):
        """What the PC has, long to short"""
        n = self.goal.conversations
        at_once = "1 conversation" if n == 1 else f"{n} conversations at once"
        if not self.gpu:
            return [f"no NVIDIA GPU found  ·  {at_once} "]
        name = self.gpu["name"].replace("NVIDIA GeForce ", "").replace("NVIDIA ", "")
        vram = hardware.gb(self.gpu["total"])
        free, total = self.found["ram_available"], self.found["ram_total"]
        return [f"{name} · {vram}  ·  RAM {hardware.gb(free)} free of {hardware.gb(total)}  ·  {at_once} ",
                f"{name} {vram} · RAM {free / hardware.GiB:.0f}/{total / hardware.GiB:.0f} GB free · "
                f"{at_once.replace(' at once', '')} ",
                f"{name} {vram} "]

    def dials(self, width, row):
        """The two choices that make the goal, as rows of options to pick from"""
        wide = width >= 110
        lines = []
        line = Line(("  CONTEXT YOU NEED   " if wide else "  CONTEXT   ", "bold"))
        for tokens in self.goal.steps():
            label = fit.tokens_text(tokens).lstrip("~") if tokens else "longest"
            start = len(line)
            if tokens == self.goal.context:
                line.add(f" {label} ", "rev bold")
            else:
                line.add(f" {label} ")
            self.hits.append((row, start, len(line), ("context", tokens)))
            line.add(" ")
        hint = first_fitting(["← →   o your own", "← →", ""], width - len(line) - 2)
        line.add(" " * max(1, width - len(line) - len(hint) - 1)).add(hint, "grey")
        lines.append(line)
        line = Line(("  MAY RUN ON         " if wide else "  RUNS ON   ", "bold"))
        places = ((False, "GPU only, fast"), (True, "GPU and PC memory: bigger models, slower")) if wide else \
            ((False, "GPU only"), (True, "GPU + PC memory (slower)"))
        for value, label in places:
            start = len(line)
            line.add(f" {label} ", "rev bold" if self.goal.pc_memory == value else "")
            self.hits.append((row + 1, start, len(line), ("place", value)))
            line.add("  ")
        line.add(" " * max(1, width - len(line) - 2)).add("p", "grey")
        lines.append(line)
        return lines

    def sentence(self):
        if not self.gpu:
            return "No NVIDIA GPU found. The stack's engines are set up for one, so none of these run here."
        goal, n = self.goal, len(self.meets)
        each = f" each, for {goal.conversations} conversations at once" if goal.conversations > 1 else ""
        order = "Longest context first." if goal.by_context else "Biggest first."
        if not goal.context:
            return f"The longest context each model gets {PLACES[goal.pc_memory]}{each}. {order}"
        models = "1 model holds" if n == 1 else f"{n} models hold"
        return f"{models} {fit.tokens_text(goal.context)}{each} {PLACES[goal.pc_memory]}. {order}"

    # --- The list ---

    def widths(self, width):
        """Name and bar widths for the list, leaving the last column room to
        say how a model runs"""
        name = max(16, min(32, (width - 8) // 4))
        bar = max(14, min(40, width - 8 - name - 10 - 9 - 36))
        return name, bar

    def how(self, route, way, room):
        """How the best way runs it, in a few words, coloured by what it asks.
        With little room, the file's format goes first, then the speed."""
        plan = route.plan
        eight = way == fit.EIGHT_BIT or (way == fit.BOTH and not plan.kv8_set)
        ram, slower = "", ""
        if way in (fit.PC_MEMORY, fit.BOTH):
            layout = plan.layout(self.goal.context or plan.most(True), way)
            ram, slower = f" + {layout.on('ram') / hardware.GiB:.0f} GB RAM", f", {layout.slower}"
        for quant, speed in ((f" · {route.file.quant}", slower), ("", slower), ("", "")):
            if len(route.engine.label + quant + (" + 8-bit memory" if eight else "") + ram + speed) <= room:
                break
        line = Line((route.engine.label + quant, ""))
        if eight:
            line.add(" + 8-bit memory", "yellow")
        if ram:
            line.add(ram + speed, "magenta")
        return line

    def why_not(self, group, route):
        """Why a model doesn't meet the goal, in a few words"""
        goal = self.goal
        if group.max_context and goal.context and group.max_context < goal.context:
            return Line((f"made for {fit.tokens_text(group.max_context)}", "grey"))
        if route and not goal.pc_memory and route.plan.most(True) >= max(goal.context, 4 * K):
            return Line(("only with PC memory: ", "grey"), ("p", "bold"))
        size, way = fit.better_size(group, goal, self.engines)
        if size:
            return Line((f"as a {size.file.quant} it would: not downloaded", "grey"))
        if route and route.plan.most(goal.pc_memory):
            return Line((f"{route.engine.label} gets {fit.tokens_text(route.plan.most(goal.pc_memory))} at most",
                         "grey"))
        why = route.plan.why if route else ""
        return Line((why or "doesn't run here", "grey"))

    def row(self, index, width, name_width, bar_width):
        group, route, way = self.rows[index]
        meets = index < len(self.meets)
        chosen = index == self.selected and self.view == "list"
        line = Line(("  ► " if chosen else "    ", "cyan bold"))
        line.add(f"{index + 1:>2}  " if meets else "    ", "grey")
        name = shorten(group.name, name_width - 1)
        line.add(f"{name:<{name_width}}", ("bold" if chosen else "") if meets else "grey")
        line.add(f"{group.size_text():<10}", "" if meets else "grey")
        if route:
            line.join(context_bar(route.plan, self.goal.pc_memory, bar_width, self.goal.context, dim=not meets))
            most = route.plan.most(self.goal.pc_memory)
            line.add(f" {fit.tokens_text(most) if most else '–':>6}  ", "bold" if meets else "grey")
        else:
            line.add(" " * (bar_width + 9))
        room = width - len(line)
        return line.join(self.how(route, way, room) if meets else self.why_not(group, route))

    def list_screen(self, width, height=None):
        """The list, filling the height; all of it, unscrolled, without one"""
        self.hits = []
        lines = self.header(width, "MODEL FIT", self.hardware_texts())
        lines += self.dials(width, len(lines) + 1)
        lines.append(rule(width))
        lines += [Line(("  " + text, "bold")) for text in wrap(self.sentence(), width - 3)]
        name_width, bar_width = self.widths(width)
        head = Line(("        " + "MODEL".ljust(name_width) + "SIZE".ljust(10), "grey"))
        head.join(scale(bar_width, self.goal.context)).add("         HOW IT RUNS", "grey")
        lines.append(Line())
        lines.append(head)

        footer = self.footer(width)
        room = max(3, height - len(lines) - len(footer)) if height else 10 ** 6
        body = []
        for index in range(len(self.rows)):
            if index == len(self.meets) and self.misses:
                label = f"{len(self.misses)} don't" + (f" hold {fit.tokens_text(self.goal.context)}"
                                                        if self.goal.context else " run here")
                body.append((None, rule(width, "─", label)))
            body.append((index, self.row(index, width, name_width, bar_width)))
        if not self.rows:
            body.append((None, Line(("    No models downloaded yet. The downloaders in manage.sh fetch them.", "grey"))))
        # Keep the chosen model in view
        at = next((i for i, (index, _) in enumerate(body) if index == self.selected), 0)
        if at < self.top:
            self.top = at
        elif at >= self.top + room:
            self.top = at - room + 1
        self.top = max(0, min(self.top, max(0, len(body) - room)))
        shown = body[self.top: self.top + room]
        for index, line in shown:
            if index is not None:
                self.hits.append((len(lines) + 1, 0, width, ("row", index)))
            lines.append(line)
        if height:
            lines += [Line()] * (room - len(shown))
        above, below = self.top, max(0, len(body) - self.top - room)
        lines += self.with_scroll(footer, above, below, width)
        return lines

    def with_scroll(self, footer, above, below, width):
        if above or below:
            marks = []
            if above:
                marks.append(f"↑ {above} more")
            if below:
                marks.append(f"↓ {below} more")
            footer[0] = rule(width, "═", "  ".join(marks))
        return footer

    def footer(self, width):
        if width >= 120:
            words = (" fits as set   ", " with 8-bit conversation memory   ", " with PC memory, slower   ",
                     " beyond this PC, within the model's limit")
        else:
            words = (" as set  ", " 8-bit memory  ", " PC memory, slower  ", " beyond this PC")
        legend = Line(("  ", ""), ("█", "green"), (words[0], ""), ("█", "yellow"), (words[1], ""),
                      ("█", "magenta"), (words[2], ""), ("·", "grey"), (words[3], ""))
        if self.typing is not None:
            keys = Line(("  Context size in tokens, e.g. 200k: ", "bold"), (self.typing + "▏", "cyan"),
                        ("    Enter to add it, Esc to cancel", "grey"))
        elif self.message:
            keys = Line(("  " + self.message, "yellow"))
        else:
            keys = Line((first_fitting([
                "  ↑↓ move   Enter details   ← → context   p PC memory   c conversations   s sort   "
                "o own size   Esc back to the menu",
                "  ↑↓ move  Enter details  ← → context  p PC memory  c chats  s sort  o own  Esc back",
                "  ↑↓ Enter  ← → context  p PC memory  c chats  s sort  Esc back"], width), "grey"))
        note = Line((first_fitting([
            "  Biggest first is a rough guide: within a family, more parameters mean better answers. "
            "Estimates, not measurements.",
            "  Biggest first is a rough guide, and the numbers are estimates."], width), "grey"))
        return [rule(width, "═"), legend, note, keys]

    # --- One model in detail ---

    def detail_routes(self, group):
        """The downloaded ways to run it, and the size that isn't downloaded
        but would meet the goal in better quality, if there is one"""
        routes = list(group.routes)
        other, _ = fit.better_size(group, self.goal, self.engines)
        if other:
            routes.append(other)

        def order(route):
            way = route.plan.way(self.goal.context or 4 * K, self.goal.pc_memory)
            return (not route.downloaded, way is None, way if way is not None else 9,
                    -route.bits(), -route.plan.most(self.goal.pc_memory))
        return sorted(routes, key=order)

    def detail_screen(self, width, height):
        self.hits = []
        group = self.current()
        about = [group.size_text().replace(" MoE", "") + " parameters"]
        if group.moe:
            about[0] = (f"{group.size_text().replace(' MoE', '')} parameters, "
                        f"about {group.active / 1e9:.0f}B at work per token (MoE)")
        else:
            about.append("dense")
        if group.vision:
            about.append("reads images")
        if group.max_context:
            about.append(f"made for up to {fit.tokens_text(group.max_context)}")
        lines = self.header(width, group.name.upper())
        lines.insert(1, Line(("  " + " · ".join(about), "")))
        lines += self.dials(width, len(lines) + 1)
        lines.append(rule(width))

        routes = self.detail_routes(group)
        self.route = max(0, min(self.route, len(routes) - 1))
        bar_width = max(18, min(34, (width - 60) // 2))
        what_width = max(24, width - 4 - 11 - bar_width - 9 - 28)
        lines.append(Line(("  WAYS TO RUN IT HERE".ljust(4 + 11 + what_width), "bold"))
                     .join(scale(bar_width, self.goal.context)))
        need = self.goal.context or 4 * K
        for index, route in enumerate(routes):
            plan = route.plan
            chosen = index == self.route
            way = plan.way(need, self.goal.pc_memory)
            line = Line(("  ► " if chosen else "    ", "cyan bold"))
            size = hardware.gb(route.file.weights + route.file.vision_file)
            if route.downloaded:
                what = f"{shorten(route.file.name, what_width - len(size) - 4)} · {size}"
            else:
                what = shorten(f"{route.file.quant} GGUF, not downloaded · ~{size}", what_width - 1)
            line.add(f"{route.engine.label:<11}", "bold" if chosen else "")
            line.add(f"{what:<{what_width}}", "" if route.downloaded else "grey")
            line.join(context_bar(plan, self.goal.pc_memory, bar_width, self.goal.context,
                                  dim=not route.downloaded))
            most = plan.most(self.goal.pc_memory)
            line.add(f" {fit.tokens_text(most) if most else '–':>6}  ", "bold" if way is not None else "grey")
            line.join(self.verdict(route, way))
            self.hits.append((len(lines) + 1, 0, width, ("route", index)))
            lines.append(line)

        route = routes[self.route] if routes else None
        if route:
            lines.append(Line())
            lines += self.memory(route, width)
            lines.append(Line())
            lines += self.how_to_use(group, route, width)
        footer = [rule(width, "═"), Line((first_fitting([
            "  ↑↓ move between the ways   ← → context   p PC memory   c conversations   Esc back to the list",
            "  ↑↓ move  ← → context  p PC memory  c chats  Esc back"], width), "grey"))]
        lines = lines[: max(0, height - len(footer))]
        lines += [Line()] * (height - len(footer) - len(lines))
        return lines + footer

    def verdict(self, route, way):
        """Whether a way meets the goal, and what it takes"""
        if way is None:
            plan = route.plan
            if not self.goal.pc_memory and plan.most(True) >= max(self.goal.context, 4 * K):
                return Line(("only with PC memory: ", "grey"), ("p", "bold"))
            if not plan.most(self.goal.pc_memory):
                why = plan.why or "doesn't run here"
                short = ("too big for " + route.engine.label if why.startswith("too big") else
                         "won't start, see below" if why.startswith("won't start") else
                         "can't run it natively" if "natively" in why else why)
                return Line((short, "grey"))
            return Line((f"falls short of {fit.tokens_text(self.goal.context)}", "grey"))
        words = {fit.AS_SET: ("meets it as set", "green"), fit.EIGHT_BIT: ("with 8-bit memory", "yellow"),
                 fit.PC_MEMORY: ("with PC memory", "magenta"), fit.BOTH: ("8-bit and PC memory", "magenta")}
        text, style = words[way]
        if not self.goal.context and way == fit.AS_SET:
            text = "as set"
        if not route.downloaded:
            text = "would: " + text.replace("meets it ", "")
        return Line((text, style))

    def memory(self, route, width):
        """Where the GPU's and the PC's memory goes on this way: at the goal
        when it meets it, at the most it gets when it falls short, and at
        the goal anyway when it doesn't run at all, to show how far off it is"""
        plan = route.plan
        need = self.goal.context
        way = plan.way(need or 4 * K, self.goal.pc_memory)
        most = plan.most(self.goal.pc_memory)
        if way is not None:
            tokens = need or most
            at = f"at {fit.tokens_text(tokens)}"
        elif most:
            tokens, way = most, plan.way(most, self.goal.pc_memory)
            at = f"at {fit.tokens_text(most)}, the most it gets (you need {fit.tokens_text(need)})"
        else:
            tokens, way = need or 4 * K, fit.AS_SET
            at = f"at {fit.tokens_text(tokens)}: it doesn't fit"
        if not tokens:
            tokens = 4 * K
        layout = plan.layout(tokens, way)
        lines = [Line(("  WHERE THE MEMORY GOES", "bold"), (f"   {route.engine.label} {at}", "grey"))]
        bar_width = max(30, min(72, width - 20))
        if self.gpu:
            lines.append(Line((f"  GPU {hardware.gb(self.gpu['total']):>9}  ", "bold"))
                         .join(memory_bar(layout.gpu, self.gpu["total"], bar_width, layout.over)))
            lines.append(Line(("                 ", "")).join(parts_key(layout.gpu)))
        if layout.ram:
            total = self.found["ram_total"]
            lines.append(Line((f"  RAM {hardware.gb(total):>9}  ", "bold"))
                         .join(memory_bar(layout.ram, total, bar_width)))
            lines.append(Line(("                 ", "")).join(parts_key(layout.ram)))
        if not layout.fits:
            why = layout.why
            if not self.goal.pc_memory and plan.most(True):
                why = (f"It needs {hardware.gb(layout.over)} more than the GPU has. With PC memory it runs: p"
                       if layout.over else why)
            lines.append(Line(("                 " + why, "yellow")))
        return lines

    def how_to_use(self, group, route, width):
        plan, engine, f = route.plan, route.engine, route.file
        need = self.goal.context
        way = plan.way(need or 4 * K, self.goal.pc_memory)
        text = []
        if not route.downloaded:
            where = ("stack/downloaders/ollama/models.txt, with the tag its page on ollama.com gives"
                     if engine.name == "ollama" else
                     "stack/downloaders/huggingface/models.txt as organization/model-GGUF:" + f.quant)
            text.append(f"This size isn't downloaded, and it only exists if someone publishes it. If you find a "
                        f"{f.quant} of {group.name}, add it to {where}, then run Sync models.")
        elif engine.name in ("vllm", "sglang"):
            text.append(f"In the menu: {engine.name} → Set model, pick {f.name}, then Start. "
                        f"{engine.label} makes the context as long as fits by itself.")
            if engine.name == "sglang" and not engine.settings()["fraction"]:
                held = engine.cuda_total * (1 - engine.fraction(f))
                text.append(f"By its own default SGLang holds back {hardware.gb(held)} of the GPU for its "
                            "working memory, more for models that read images. A higher VRAM_LIMIT in "
                            "stack/engines/sglang/.env leaves more for conversation; its log shows what it got.")
        elif engine.name == "llamacpp":
            context = engine.as_set(f)
            text.append(f"In Open WebUI, pick {f.name}: llama.cpp loads it when asked.")
            if need and need > context:
                text.append(f"llama.cpp gives every model {fit.tokens_text(context)} now. For {fit.tokens_text(need)}, "
                            f"set CONTEXT_SIZE={need} in stack/engines/llamacpp/.env, then Restart.")
        else:
            context = engine.as_set(f)
            text.append(f"In Open WebUI, pick {f.name}. Ollama gives it {fit.tokens_text(context)} unless an "
                        "app asks for more.")
            if need and need > context:
                text.append(f"For {fit.tokens_text(need)}, save it in a spec: PARAMETER num_ctx {need} in "
                            "stack/downloaders/ollama/specs, then sync_models.")
            if route.presets:
                saved = ", ".join(f"{p.name} ({fit.tokens_text(engine.as_set(p))})" for p in route.presets)
                text.append(f"Saved with settings of its own: {saved}.")
        if way in (fit.EIGHT_BIT, fit.BOTH) and not plan.kv8_set:
            text.append(f"It needs 8-bit conversation memory, half the size and a little less precise: "
                        f"{engine.eight_bit}.")
        if plan.kv8_set and route.file.kv8_by_makers and engine.name in ("vllm", "sglang"):
            text.append("Its makers ask for 8-bit conversation memory, and the engine follows that.")
        if way in (fit.PC_MEMORY, fit.BOTH):
            layout = plan.layout(need or plan.most(True), way)
            text.append(f"{hardware.gb(layout.on('ram'))} of it runs from PC memory: {layout.slower}.")
        if route.file.incomplete:
            text.append(f"Its download is missing {route.file.incomplete}: run sync_models in its downloader.")
        if group.rough:
            text.append(f"This model is {group.rough}.")
        lines = [Line(("  TO USE IT", "bold"))]
        for paragraph in text:
            lines += [Line(("  " + line, "")) for line in wrap(paragraph, width - 4)]
        return lines

    # --- Changing things ---

    def set_context(self, tokens):
        keep = self.current()
        self.goal.context = tokens
        self.goal.save()
        self.rank(keep)

    def step_context(self, step):
        steps = self.goal.steps()
        index = steps.index(self.goal.context) if self.goal.context in steps else 3
        self.set_context(steps[max(0, min(len(steps) - 1, index + step))])

    def set_place(self, pc_memory):
        keep = self.current()
        self.goal.pc_memory = pc_memory
        self.goal.save()
        self.rank(keep)

    def next_conversations(self):
        keep = self.current()
        counts = [1, 2, 3, 4, 6, 8]
        n = self.goal.conversations
        self.goal.conversations = next((c for c in counts if c > n), 1)
        self.goal.save()
        self.build()
        self.rank(next((g for g in self.groups if keep and g.files == keep.files), None))

    def toggle_sort(self):
        keep = self.current()
        self.goal.by_context = not self.goal.by_context
        self.goal.save()
        self.rank(keep)

    def own_size(self, text):
        text = text.strip().lower().replace(",", "")
        match = re.fullmatch(r"(\d+(?:\.\d+)?)(k|m)?", text)
        if not match:
            self.message = "That isn't a size: try 200k or 204800."
            return
        tokens = int(float(match[1]) * {"k": K, "m": K * K}.get(match[2], 1))
        if tokens < 1024:
            self.message = "That's less than 1k tokens."
            return
        self.goal.extra = tokens
        self.set_context(tokens)

    def key(self, key):
        """Does what a key asks; False to leave"""
        self.message = ""
        if self.typing is not None:
            if key == "enter":
                text, self.typing = self.typing, None
                self.own_size(text)
            elif key == "esc":
                self.typing = None
            elif key == "backspace":
                self.typing = self.typing[:-1]
            elif len(key) == 1 and (key.isdigit() or key in "kKmM.,"):
                self.typing += key
            return True
        if key == "esc":
            if self.view == "detail":
                self.view = "list"
                return True
            return False
        if key in ("left", "right"):
            self.step_context(-1 if key == "left" else 1)
        elif key == "p":
            self.set_place(not self.goal.pc_memory)
        elif key == "c":
            self.next_conversations()
        elif key == "o":
            self.typing = ""
        elif self.view == "list":
            self.list_key(key)
        else:
            routes = self.detail_routes(self.current())
            if key == "up":
                self.route = max(0, self.route - 1)
            elif key == "down":
                self.route = min(len(routes) - 1, self.route + 1)
        return True

    def list_key(self, key):
        last = len(self.rows) - 1
        moves = {"up": -1, "down": 1, "pageup": -10, "pagedown": 10}
        if key in moves:
            self.selected = max(0, min(last, self.selected + moves[key]))
        elif key == "home":
            self.selected = 0
        elif key == "end":
            self.selected = last
        elif key == "enter" and self.rows:
            self.view, self.route = "detail", 0
        elif key == "s":
            self.toggle_sort()

    def click(self, row, col, button):
        """A mouse click (button 0) or the wheel (64 up, 65 down)"""
        if button in (64, 65):
            return self.key("up" if button == 64 else "down")
        for hit_row, first, last, (what, value) in self.hits:
            if hit_row == row and first <= col < last:
                if what == "context":
                    self.set_context(value)
                elif what == "place":
                    self.set_place(value)
                elif what == "row":
                    if value == self.selected:
                        self.view, self.route = "detail", 0
                    self.selected = value
                elif what == "route":
                    self.route = value
                return True
        return True

    def frame(self, width, height):
        if width < 80 or height < 20:
            return [Line((" Make the window at least 80 columns wide and 20 lines high.", "yellow"))]
        if not self.rows:
            self.view = "list"
        if self.view == "detail":
            return self.detail_screen(width, height)
        return self.list_screen(width, height)


def shorten(text, width):
    """Shortens a long name in the middle, so the columns line up"""
    if len(text) <= width:
        return text
    keep = width - 1
    return text[: keep // 2] + "…" + text[len(text) - (keep - keep // 2):]


# --- The terminal ---

KEYS = {"[A": "up", "[B": "down", "[C": "right", "[D": "left", "OA": "up", "OB": "down", "OC": "right",
        "OD": "left", "[5~": "pageup", "[6~": "pagedown", "[H": "home", "[F": "end", "[1~": "home",
        "[4~": "end", "OH": "home", "OF": "end"}


def read_key(fd):
    """One key: a letter, or up, down, left, right, enter, backspace, esc,
    pageup, pagedown, home, end; or ("mouse", row, column, button)"""
    data = os.read(fd, 1)
    if data == b"\x1b":
        rest = b""
        while select.select([fd], [], [], 0.03)[0]:
            rest += os.read(fd, 1)
            if rest[-1:].isalpha() or rest[-1:] == b"~" or (rest.startswith(b"[<") and rest[-1:] in b"Mm"):
                break
        text = rest.decode(errors="ignore")
        if text.startswith("[<") and text[-1:] in "Mm":
            try:
                button, col, row = (int(x) for x in text[2:-1].split(";"))
            except ValueError:
                return ""
            return ("mouse", row, col - 1, button) if text[-1] == "M" else ""
        return KEYS.get(text, "esc" if not text else "")
    if data in (b"\r", b"\n"):
        return "enter"
    if data in (b"\x7f", b"\x08"):
        return "backspace"
    if data == b"\x03":
        raise KeyboardInterrupt
    return data.decode(errors="ignore")


def run(screen):
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    resized = [True]
    signal.signal(signal.SIGWINCH, lambda *_: resized.__setitem__(0, True))
    out = sys.stdout
    # The alternate screen, so manage.sh's menu comes back as it was; no
    # cursor; mouse clicks and the wheel reported as keys
    out.write("\033[?1049h\033[?25l\033[?1000h\033[?1006h")
    try:
        tty.setcbreak(fd)
        while True:
            width, height = shutil.get_terminal_size()
            lines = screen.frame(width, height)
            out.write("\033[H" + "".join(line.draw(width) + "\033[K\r\n" for line in lines[:height - 1])
                      + (lines[height - 1].draw(width) if len(lines) >= height else "") + "\033[J")
            out.flush()
            resized[0] = False
            while not select.select([fd], [], [], 0.25)[0]:
                if resized[0]:
                    break
            if resized[0]:
                continue
            key = read_key(fd)
            if isinstance(key, tuple):
                screen.click(key[1], key[2], key[3])
            elif key and not screen.key(key):
                break
    except KeyboardInterrupt:
        pass
    finally:
        out.write("\033[?1000l\033[?1006l\033[?25h\033[?1049l")
        out.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def print_once(screen):
    """The list for the saved goal, once, for output that isn't a terminal"""
    width = shutil.get_terminal_size((120, 50)).columns
    screen.view = "list"
    screen.selected = -1
    lines = screen.list_screen(width)
    print("\n".join(line.draw(width).rstrip() for line in lines).rstrip())


def main():
    global USE_COLOUR
    args = sys.argv[1:]
    if args and args != ["--print"]:
        print(__doc__.split("\n\n")[3], file=sys.stderr)
        sys.exit(1)
    interactive = not args and sys.stdin.isatty() and sys.stdout.isatty()
    USE_COLOUR = sys.stdout.isatty()
    if interactive:
        print("Working out what fits...", flush=True)
    screen = Screen()
    if interactive:
        run(screen)
    else:
        print_once(screen)


if __name__ == "__main__":
    main()
