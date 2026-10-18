#!/usr/bin/env python3
"""ai-leverage/src/python/fit_screen.py

The model fit (Models › Tuning › Fit in the menu): which downloaded models
fit on this PC for what you need, biggest first, and for each one, every way
to run it, where the memory goes, and what to do to use it.

What you need is chosen at the top: how much context, whether the PC's
memory may help (bigger models, slower), how many conversations run at once,
and the order. A click on a choice or its key changes it. The list under it
answers for that goal, and the panel under the list shows the model the list
highlights: → or Enter goes into it, to look at each way to run it, and Esc
goes back. The calculation is model_fit.py's; this draws it, and keeps your
choices in config/model-fit.conf, where the engines' model lists find them
too.

The menu opens it full screen. Typed in a terminal, it shows the same screen
on its own, and Esc leaves it. It's drawn with Textual, from the menu's
Python environment (src/python/.venv, which manage.sh sets up); started with
another Python, such as python3, it switches to that one by itself.

Usage: python3 -I fit_screen.py [--print]
  Full screen in a terminal. --print, or output that isn't a terminal,
  prints the list for the saved goal once.
"""

import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(HERE, ".venv")


def use_menu_python():
    """Starts this again with the menu's Python environment, which has
    Textual, when another Python started it. The environment is set up
    first, as manage.sh does, when it isn't there yet."""
    try:
        import textual  # noqa: F401
        return
    except ImportError:
        pass
    python = os.path.join(VENV, "bin", "python")
    if os.path.realpath(sys.prefix) == os.path.realpath(VENV):
        sys.exit("The menu's Python environment lacks Textual. ./manage.sh sets it up again.")
    if not os.path.exists(python):
        if not shutil.which("uv"):
            sys.exit("This screen is drawn with Textual, which uv sets up. Run ./bootstrap.sh first.")
        print("Setting up the menu's Python environment: uv downloads Textual, which draws this "
              "(about 13 MB, once)...", file=sys.stderr)
        if subprocess.call(["uv", "sync", "--project", HERE, "--locked", "--quiet"]) != 0:
            sys.exit("Couldn't set up the menu's Python environment. See the messages above.")
    os.execv(python, [python, "-I", os.path.abspath(__file__), *sys.argv[1:]])


# Before Textual is imported: typed in a terminal, this may be the wrong Python
if __name__ == "__main__":
    use_menu_python()

sys.path.insert(0, HERE)

from textual import on, work  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.containers import Vertical, VerticalScroll  # noqa: E402
from textual.content import Content  # noqa: E402
from textual.screen import ModalScreen, Screen  # noqa: E402
from textual.widgets import Input, OptionList, Static  # noqa: E402

import hardware  # noqa: E402
import model_facts  # noqa: E402
import model_fit as fit  # noqa: E402
import tui  # noqa: E402
from tui import MUTED, JumpList, keys_line  # noqa: E402

K = fit.K

# --- Colours: the theme's, so they mean what they mean in the rest of the menu ---

GREEN, YELLOW = "$success", "$warning"
MAGENTA = "#B762D0"                     # with the PC's memory: no theme colour is magenta in every theme
HEAD = "bold $text-primary"             # a section's name, as the groups in the update overview
CHOSEN = "bold reverse $text-primary"   # the choice that's made, and the context you need on the scale
KEY = "bold $text-accent"               # a key, as in the line at the bottom

# The parts of the memory bars: their colour, character and name
PARTS = {
    "model": ("$primary", "█", "model"),
    "working": ("$secondary", "█", "working"),
    "conversation": (GREEN, "█", "conversation"),
    "room": (GREEN, "░", "room for more"),
    "kept": (MUTED, "▒", "kept free"),
    "others": (MUTED, "▓", "others"),
    "free": (MUTED, "░", "free"),
    "tables": (MAGENTA, "▒", "lookup tables"),
    "moved": (MAGENTA, "█", "from the GPU"),
}


def runs(cells):
    """(character, style) cells as text, one piece per run of a style"""
    pieces = []
    for char, style in cells:
        if pieces and pieces[-1][1] == style:
            pieces[-1][0] += char
        else:
            pieces.append([char, style])
    return Content.assemble(*[(text, style) for text, style in pieces])


def rule(width, label):
    return Content.styled(f"── {label} " + "─" * max(0, width - len(label) - 4), MUTED)


def first_fitting(versions, width):
    """The first of several versions of a text that fits the width, else the last"""
    for version in versions:
        if version.cell_length <= width:
            return version
    return versions[-1]


def shorten(text, width):
    """Shortens a long name in the middle, so the columns line up"""
    if len(text) <= width:
        return text
    keep = width - 1
    return text[: keep // 2] + "…" + text[len(text) - (keep - keep // 2):]


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
    ends = [(column(plan.reach[fit.AS_SET], width), GREEN),
            (column(plan.reach[fit.EIGHT_BIT], width), YELLOW)]
    if pc_memory:
        ends.append((column(max(plan.reach[fit.PC_MEMORY], plan.reach[fit.BOTH]), width), MAGENTA))
    top = column(plan.model.max_context or HIGH, width)
    mark = column(need, width) if need else -1
    cells = []
    for i in range(width):
        style = next((s for end, s in ends if i < end), None)
        if style:
            cells.append(("█", f"{style} 40%" if dim else style))
        elif i == mark - 1:
            cells.append(("│", MUTED if dim else "bold $text-primary"))
        elif i < top:
            cells.append(("·", MUTED))
        else:
            cells.append((" ", ""))
    return runs(cells)


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
        style = CHOSEN if tokens == need else MUTED
        for i, char in enumerate(label):
            if start + i < width:
                cells[start + i] = (char, style)
                taken.add(start + i)
    return runs(cells)


def memory_bar(parts, total, width, over=0):
    """A bar of where a GPU's (or the PC's) memory goes, part by part"""
    pieces, used, drawn = [], 0, 0
    for name, size in parts:
        style, char, _ = PARTS[name]
        start, used = round(used / total * width), used + size
        count = max(0, min(width, round(used / total * width)) - start)
        if count:
            pieces.append((char * count, style))
            drawn += count
    pieces.append(" " * max(0, width - drawn))
    if over:
        pieces.append((f" +{hardware.gb(over)} too much", "bold $error"))
    return Content.assemble(*pieces)


def parts_key(parts, width):
    """What each colour of a memory bar is, and how big, in GB: as many
    lines as it takes at this width, never breaking one apart"""
    lines, line = [], Content("")
    for name, size in parts:
        if size < 0.05 * hardware.GiB:
            continue
        style, char, label = PARTS[name]
        part = Content.assemble((char, style), f" {label} {size / hardware.GiB:.1f}")
        if line.cell_length and line.cell_length + 2 + part.cell_length + 3 > width:
            lines.append(line)
            line = Content("")
        line += Content("  " if line.cell_length else "") + part
    return lines + [line + Content.styled(" GB", MUTED)]


def legend(width):
    """What the colours of the context bars mean"""
    words = [" fits as set   ", " with 8-bit conversation memory   ", " with PC memory, slower   ",
             " beyond this PC, within the model's limit"]
    short = [" as set  ", " 8-bit memory  ", " PC memory, slower  ", " beyond this PC"]
    versions = [Content.assemble(("█", GREEN), w[0], ("█", YELLOW), w[1], ("█", MAGENTA), w[2], ("·", MUTED), w[3])
                for w in (words, short)]
    return first_fitting(versions, width)


def parse_size(text):
    """A context size typed in, such as 200k, 1M or 204800: (tokens, "") or
    (0, why it isn't one)"""
    text = text.strip().lower().replace(",", "")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(k|m)?", text)
    if not match:
        return 0, "That isn't a size: try 200k or 204800."
    tokens = int(float(match[1]) * {"k": K, "m": K * K}.get(match[2], 1))
    if tokens < 1024:
        return 0, "That's less than 1k tokens."
    return tokens, ""


# --- What it shows ---

PLACES = {False: "on the GPU alone", True: "with the PC's memory helping"}
CONVERSATIONS = [1, 2, 3, 4, 6, 8]


class Fit:
    """What the screen shows: the PC, the goal, and every downloaded model
    for that goal, worked out by model_fit. Reading the models' files takes
    a moment the first time; after that, a change of the goal is quick."""

    def __init__(self):
        self.goal = fit.Goal()
        self.found = hardware.detect()
        self.engines = fit.engines_for(self.found)
        self.models = model_facts.all_models()
        self.gpu = self.found["gpus"][0] if self.found["gpus"] else None
        self.build()

    def build(self):
        """Works out every model's ways to run it, for this many conversations"""
        self.groups = fit.groups(self.models, self.engines, self.goal.conversations)
        self.rank()

    def rank(self):
        self.meets, self.misses = fit.ranked(self.groups, self.goal)
        self.rows = self.meets + self.misses

    def index_of(self, group):
        """Where a model is in the list now, also after its ways were worked out again"""
        return next((i for i, (g, _, _) in enumerate(self.rows) if g is group or g.files == group.files), None)

    # --- The goal ---

    def pc_text(self):
        """What the PC has, for the frame at the top"""
        if not self.gpu:
            return "no NVIDIA GPU found"
        name = self.gpu["name"].replace("NVIDIA GeForce ", "").replace("NVIDIA ", "")
        free, total = self.found["ram_available"], self.found["ram_total"]
        return f"{name} · VRAM {hardware.gb(self.gpu['total'])} · RAM {hardware.gb(free)} free / {hardware.gb(total)}"

    def sentence(self):
        if not self.gpu:
            return "No NVIDIA GPU found. The stack's engines are set up for one, so none of these run here."
        goal, n = self.goal, len(self.meets)
        each = f" each, for {goal.conversations} conversations at once" if goal.conversations > 1 else ""
        order = "Longest context first." if goal.by_context else "Biggest first, a rough guide to quality."
        if not goal.context:
            return f"The longest context each model gets {PLACES[goal.pc_memory]}{each}. {order}"
        models = "1 model holds" if n == 1 else f"{n} models hold"
        return f"{models} {fit.tokens_text(goal.context)}{each} {PLACES[goal.pc_memory]}. {order}"

    def goal_text(self):
        """The goal in one line, for the printed list"""
        goal = self.goal
        context = fit.tokens_text(goal.context) if goal.context else "the longest"
        place = "GPU and PC memory" if goal.pc_memory else "GPU only"
        n = goal.conversations
        return (f"Context you need: {context} · may run on: {place} · "
                f"{n} conversation{'s' if n > 1 else ''} at once")

    # --- The list ---

    def widths(self, width):
        """Name and bar widths for the list, leaving the last column room to
        say how a model runs"""
        name = max(16, min(32, (width - 4) // 4))
        bar = max(14, min(40, width - 4 - name - 10 - 9 - 36))
        return name, bar

    def list_head(self, width):
        name_width, bar_width = self.widths(width)
        return Content.assemble(("    " + "MODEL".ljust(name_width) + "SIZE".ljust(10), MUTED),
                                scale(bar_width, self.goal.context), ("         HOW IT RUNS", MUTED))

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
        return Content.assemble(route.engine.label + quant, (" + 8-bit memory", YELLOW) if eight else "",
                                (ram + speed, MAGENTA) if ram else "")

    def why_not(self, group, route):
        """Why a model doesn't meet the goal, in a few words"""
        goal = self.goal
        if group.max_context and goal.context and group.max_context < goal.context:
            return Content.styled(f"made for {fit.tokens_text(group.max_context)}", MUTED)
        if route and not goal.pc_memory and route.plan.most(True) >= max(goal.context, 4 * K):
            return Content.assemble(("only with PC memory: ", MUTED), ("p", KEY))
        size, way = fit.better_size(group, goal, self.engines)
        if size:
            return Content.styled(f"as a {size.file.quant} it would: not downloaded", MUTED)
        if route and route.plan.most(goal.pc_memory):
            return Content.styled(f"{route.engine.label} gets {fit.tokens_text(route.plan.most(goal.pc_memory))} "
                                  "at most", MUTED)
        why = route.plan.why if route else ""
        return Content.styled(why or "doesn't run here", MUTED)

    def row(self, index, width, name_width, bar_width):
        group, route, way = self.rows[index]
        meets = index < len(self.meets)
        pieces = [(f"{index + 1:>2}  " if meets else "    ", MUTED),
                  (f"{shorten(group.name, name_width - 1):<{name_width}}", "" if meets else MUTED),
                  (f"{group.size_text():<10}", "" if meets else MUTED)]
        if route:
            pieces.append(context_bar(route.plan, self.goal.pc_memory, bar_width, self.goal.context, dim=not meets))
            most = route.plan.most(self.goal.pc_memory)
            pieces.append((f" {fit.tokens_text(most) if most else '–':>6}  ", "bold" if meets else MUTED))
        else:
            pieces.append(" " * (bar_width + 9))
        room = width - (4 + name_width + 10 + bar_width + 9)
        pieces.append(self.how(route, way, room) if meets else self.why_not(group, route))
        return Content.assemble(*pieces).truncate(width, ellipsis=True)

    def list_entries(self, width):
        """The list's rows for a JumpList: the models that meet the goal with
        their number, then a line, then the ones that don't"""
        name_width, bar_width = self.widths(width)
        entries = []
        for index in range(len(self.rows)):
            if index == len(self.meets) and self.misses:
                n = len(self.misses)
                label = ("1 doesn't" if n == 1 else f"{n} don't") + \
                    (f" hold {fit.tokens_text(self.goal.context)}" if self.goal.context else " run here")
                entries.append((None, rule(width, label), None, ""))
            key = str(index + 1) if index < len(self.meets) else None
            entries.append((key, self.row(index, width, name_width, bar_width), f"m{index}", ""))
        return entries

    # --- One model in detail ---

    def about(self, group):
        """What a model is, for its panel's frame"""
        size = group.size_text().replace(" MoE", "")
        about = [f"{size} parameters, about {group.active / 1e9:.0f}B at work per token (MoE)" if group.moe
                 else f"{size} parameters · dense"]
        if group.vision:
            about.append("reads images")
        if group.max_context:
            about.append(f"made for up to {fit.tokens_text(group.max_context)}")
        return " · ".join(about)

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

    def way_widths(self, width):
        bar = max(18, min(34, (width - 60) // 2))
        return bar, max(24, width - 11 - bar - 9 - 28)

    def ways_head(self, width):
        bar_width, what_width = self.way_widths(width)
        return Content.assemble(("WAYS TO RUN IT HERE".ljust(11 + what_width), HEAD),
                                scale(bar_width, self.goal.context))

    def way_row(self, route, width):
        bar_width, what_width = self.way_widths(width)
        plan = route.plan
        way = plan.way(self.goal.context or 4 * K, self.goal.pc_memory)
        size = hardware.gb(route.file.weights + route.file.vision_file)
        if route.downloaded:
            what = f"{shorten(route.file.name, what_width - len(size) - 4)} · {size}"
        else:
            what = shorten(f"{route.file.quant} GGUF, not downloaded · ~{size}", what_width - 1)
        most = plan.most(self.goal.pc_memory)
        return Content.assemble(
            f"{route.engine.label:<11}", (f"{what:<{what_width}}", "" if route.downloaded else MUTED),
            context_bar(plan, self.goal.pc_memory, bar_width, self.goal.context, dim=not route.downloaded),
            (f" {fit.tokens_text(most) if most else '–':>6}  ", "bold" if way is not None else MUTED),
            self.verdict(route, way)).truncate(width, ellipsis=True)

    def verdict(self, route, way):
        """Whether a way meets the goal, and what it takes"""
        if way is None:
            plan = route.plan
            if not self.goal.pc_memory and plan.most(True) >= max(self.goal.context, 4 * K):
                return Content.assemble(("only with PC memory: ", MUTED), ("p", KEY))
            if not plan.most(self.goal.pc_memory):
                why = plan.why or "doesn't run here"
                short = ("too big for " + route.engine.label if why.startswith("too big") else
                         "won't start, see below" if why.startswith("won't start") else
                         "can't run it natively" if "natively" in why else why)
                return Content.styled(short, MUTED)
            return Content.styled(f"falls short of {fit.tokens_text(self.goal.context)}", MUTED)
        words = {fit.AS_SET: ("meets it as set", GREEN), fit.EIGHT_BIT: ("with 8-bit memory", YELLOW),
                 fit.PC_MEMORY: ("with PC memory", MAGENTA), fit.BOTH: ("8-bit and PC memory", MAGENTA)}
        text, style = words[way]
        if not self.goal.context and way == fit.AS_SET:
            text = "as set"
        if not route.downloaded:
            text = "would: " + text.replace("meets it ", "")
        return Content.styled(text, style)

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
        lines = [Content.assemble(("WHERE THE MEMORY GOES", HEAD), (f"   {route.engine.label} {at}", MUTED))]
        bar_width = max(30, min(72, width - 20))
        indent = " " * 15
        if self.gpu:
            lines.append(Content.assemble((f"GPU {hardware.gb(self.gpu['total']):>9}  ", "bold"),
                                          memory_bar(layout.gpu, self.gpu["total"], bar_width, layout.over)))
            lines += [Content(indent) + part for part in parts_key(layout.gpu, width - len(indent))]
        if layout.ram:
            total = self.found["ram_total"]
            lines.append(Content.assemble((f"RAM {hardware.gb(total):>9}  ", "bold"),
                                          memory_bar(layout.ram, total, bar_width)))
            lines += [Content(indent) + part for part in parts_key(layout.ram, width - len(indent))]
        if not layout.fits:
            if not self.goal.pc_memory and plan.most(True) and layout.over:
                why = Content.assemble((f"It needs {hardware.gb(layout.over)} more than the GPU has. "
                                        "With PC memory it runs: ", YELLOW), ("p", KEY))
            else:
                why = Content.styled(layout.why, YELLOW)
            lines.append(Content.assemble(indent, why))
        return lines

    def how_to_use(self, group, route):
        """What to do to run it this way, in a few short paragraphs"""
        plan, engine, f = route.plan, route.engine, route.file
        need = self.goal.context
        way = plan.way(need or 4 * K, self.goal.pc_memory)
        text = []
        if not route.downloaded:
            where = ("stack/downloaders/ollama/models.txt, with the tag its page on ollama.com gives"
                     if engine.name == "ollama" else
                     "stack/downloaders/huggingface/models.txt as organization/model-GGUF:" + f.quant)
            text.append(f"This size isn't downloaded, and it only exists if someone publishes it. If you find a "
                        f"{f.quant} of {group.name}, add it to {where}, then run Sync models in its downloader "
                        "(Models › Downloaders).")
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
                            "stack/downloaders/ollama/specs, then run Sync models in the ollama downloader.")
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
            text.append(f"Its download is missing {route.file.incomplete}: run Sync models in its downloader.")
        if group.rough:
            text.append(f"This model is {group.rough}.")
        return text

    def way_text(self, group, route, width):
        """Under the ways: where the memory goes, and what to do to use it"""
        lines = self.memory(route, width) + [Content(""), Content.styled("TO USE IT", HEAD)]
        lines += [Content(paragraph) for paragraph in self.how_to_use(group, route)]
        return Content("\n").join(lines)

    # --- Changing the goal; each change is saved at once ---

    def set_context(self, tokens):
        self.goal.context = tokens
        self.goal.save()
        self.rank()

    def step_context(self, step):
        steps = self.goal.steps()
        index = steps.index(self.goal.context) if self.goal.context in steps else 3
        self.set_context(steps[max(0, min(len(steps) - 1, index + step))])

    def own_size(self, tokens):
        self.goal.extra = tokens
        self.set_context(tokens)

    def set_place(self, pc_memory):
        self.goal.pc_memory = pc_memory
        self.goal.save()
        self.rank()

    def set_conversations(self, n):
        self.goal.conversations = n
        self.goal.save()
        self.build()

    def next_conversations(self):
        self.set_conversations(next((c for c in CONVERSATIONS if c > self.goal.conversations), 1))

    def set_sort(self, by_context):
        self.goal.by_context = by_context
        self.goal.save()
        self.rank()

    # --- Printed once ---

    def printed(self, width):
        """The list for the saved goal, as lines to print"""
        lines = [Content.assemble(("Model fit", "bold"), (f"   {self.pc_text()}", MUTED)),
                 Content.styled(self.goal_text(), MUTED), Content(""), Content.styled(self.sentence(), "bold"),
                 Content(""), self.list_head(width)]
        lines += [text for _, text, _, _ in self.list_entries(width)]
        if not self.rows:
            lines.append(Content.styled("    No models downloaded yet. Models › Downloaders gets them.", MUTED))
        return lines + [Content(""), legend(width)]


# --- The screen ---

class FitList(JumpList):
    """A list on the fit screen. A click only highlights, since what's
    highlighted shows in the panel under it, and ← → move between the list
    and that panel, as in the menu."""

    BINDINGS = [Binding("left", "screen.side_left", show=False),
                Binding("right", "screen.side_right", show=False)]

    async def _on_click(self, event):
        event.prevent_default()  # OptionList's own click would choose it too
        index = event.style.meta.get("option")
        if index is not None and not self.options[index].disabled:
            self.highlighted = index
        self.focus()


class WaysList(FitList):
    """The ways to run a model, in the panel under the list: PgUp and PgDn
    scroll that panel, for what's under them on a short screen"""

    BINDINGS = [Binding("pageup", "screen.scroll_detail(-1)", show=False),
                Binding("pagedown", "screen.scroll_detail(1)", show=False)]


class Detail(VerticalScroll, can_focus=False):
    """The panel under the list, which the mouse scrolls when it's long"""


class FitScreen(Screen):
    """The fit, full screen: the goal at the top, the models for it under
    it, and the highlighted model in the panel at the bottom. Esc goes back,
    from that panel to the list, and from the list out of the fit (leaving
    says where to)."""

    BINDINGS = [
        Binding("escape", "back", show=False),
        Binding("minus", "step_context(-1)", show=False),
        Binding("plus,equals_sign", "step_context(1)", show=False),
        Binding("p", "toggle_place", show=False),
        Binding("c", "next_conversations", show=False),
        Binding("s", "toggle_sort", show=False),
        Binding("o", "own_size", show=False),
    ]

    def __init__(self, leaving="back to the menu"):
        super().__init__()
        self.leaving = leaving
        self.fit = None
        self.routes = []     # the ways to run the model the panel shows
        self.shown = None    # that model

    def compose(self) -> ComposeResult:
        yield Static(id="fit-goal", classes="panel")
        with Vertical(id="fit-models", classes="panel"):
            yield Static(id="fit-head")
            yield FitList(id="fit-list")
        with Detail(id="fit-detail", classes="panel"):
            yield Static(id="fit-ways-head")
            yield WaysList(id="fit-ways")
            yield Static(id="fit-more")
        yield Static(id="fit-keys")

    def on_mount(self):
        self.query_one("#fit-goal").border_title = "Models › Tuning › Fit"
        self.query_one("#fit-models").border_title = "Working out what fits…"
        self.query_one("#fit-detail").display = False
        self.query_one("#fit-list", FitList).focus()
        self.show_keys()
        self.load()

    @work(thread=True, exclusive=True)
    def load(self):
        """Reads the PC and the models' files, which takes a moment the first time"""
        try:
            found = Fit()
        except Exception as error:  # shown where the list would be, rather than ending the menu
            self.app.call_from_thread(self.failed, error)
            return
        self.app.call_from_thread(self.loaded, found)

    def failed(self, error):
        self.query_one("#fit-models").border_title = "Couldn't work out what fits"
        self.query_one("#fit-head", Static).update(Content.styled(f"{type(error).__name__}: {error}", "$error"))

    def loaded(self, found):
        self.fit = found
        # Once the panels have their size, which the rows are cut to
        self.call_after_refresh(self.draw)

    # --- Drawing ---

    def list_width(self):
        """Room for a row of the list: inside its padding, and the scrollbar's column kept"""
        return max(60, self.query_one("#fit-list").size.width - 3)

    def draw(self, keep=None):
        """Everything again for the goal as it is now. The list keeps its
        model (keep, or the highlighted one), wherever the new order puts it."""
        if not self.fit:
            return
        fit_now = self.fit
        models = self.query_one("#fit-list", FitList)
        if keep is None:
            keep = self.highlighted_group()
        self.draw_goal()
        width = self.list_width()
        panel = self.query_one("#fit-models")
        panel.border_title = fit_now.sentence()
        panel.border_subtitle = legend(width - 4)
        self.query_one("#fit-head", Static).update(Content(" ").append(fit_now.list_head(width)))
        if not fit_now.rows:
            models.fill([(None, Content.styled("No models downloaded yet. Models › Downloaders gets them.", MUTED),
                          None, "")])
            self.query_one("#fit-detail").display = False
            return
        at = fit_now.index_of(keep) if keep else None
        models.fill(fit_now.list_entries(width), keep=False, prefer=f"m{at if at is not None else 0}")
        self.show_detail(force=True)

    def draw_goal(self):
        """The choices at the top: a click on one, or its key, changes it"""
        goal = self.fit.goal
        panel = self.query_one("#fit-goal", Static)
        width = max(60, panel.size.width - 2)
        wide = width >= 110
        steps = []
        for tokens in goal.steps():
            label = fit.tokens_text(tokens).lstrip("~") if tokens else "longest"
            steps.append((label, f"set_context({tokens})", tokens == goal.context))
        own = Content.assemble(" ", ("O", "bold underline"), "wn size… ")
        places = ((False, "GPU only, fast"), (True, "GPU and PC memory: bigger models, slower")) if wide else \
            ((False, "GPU only"), (True, "GPU + PC memory (slower)"))
        counts = sorted(set(CONVERSATIONS + [goal.conversations]))
        orders = ((False, "Biggest first"), (True, "Longest context first"))
        rows = [
            ("Context you need" if wide else "Context", steps + [(own, "own_size", False)], "- +"),
            ("May run on" if wide else "Runs on",
             [(label, f"set_place({value})", value == goal.pc_memory) for value, label in places], "p"),
            ("Conversations at once" if wide else "At once",
             [(str(n), f"set_conversations({n})", n == goal.conversations) for n in counts], "c"),
            ("Order", [(label, f"set_sort({value})", value == goal.by_context) for value, label in orders], "s"),
        ]
        label_width = 23 if wide else 9
        lines = []
        for label, chips, key in rows:
            line = Content.styled(f"{label:<{label_width}}", "bold")
            for text, action, chosen in chips:
                chip = text if isinstance(text, Content) else Content(f" {text} ")
                line += chip.stylize_before(f"{CHOSEN if chosen else ''} @click=screen.{action}".strip()) + " "
            line += Content(" " * max(1, width - line.cell_length - len(key)))
            lines.append(line + Content.styled(key, KEY))
        panel.update(Content("\n").join(lines))
        panel.border_subtitle = self.fit.pc_text()

    def highlighted_group(self):
        models = self.query_one("#fit-list", FitList)
        option = models.highlighted_option
        if not self.fit or not option or not option.id:
            return None
        index = int(option.id[1:])
        return self.fit.rows[index][0] if index < len(self.fit.rows) else None

    def show_detail(self, force=False):
        """The panel under the list, for the model it highlights: its ways to
        run it, and for the way highlighted there, where the memory goes and
        what to do to use it"""
        group = self.highlighted_group()
        detail = self.query_one("#fit-detail", Detail)
        if not group:
            detail.display = False
            return
        if group is self.shown and not force:
            return
        ways = self.query_one("#fit-ways", FitList)
        same = group is self.shown or (self.shown is not None and group.files == self.shown.files)
        kept = ways.highlighted if same else 0
        self.shown = group
        detail.display = True
        width = self.list_width()
        detail.border_title = f"{group.name} · {self.fit.about(group)}"
        detail.border_subtitle = "estimates, not measurements"
        self.query_one("#fit-ways-head", Static).update(Content(" ").append(self.fit.ways_head(width)))
        self.routes = self.fit.detail_routes(group)
        ways.fill([(None, self.fit.way_row(route, width), f"w{i}", "") for i, route in enumerate(self.routes)],
                  keep=False, prefer=f"w{min(kept or 0, len(self.routes) - 1)}")
        if not same:
            detail.scroll_home(animate=False)
        self.show_way()

    def show_way(self):
        ways = self.query_one("#fit-ways", FitList)
        option = ways.highlighted_option
        more = self.query_one("#fit-more", Static)
        if not option or not self.shown:
            more.update("")
            return
        route = self.routes[int(option.id[1:])]
        more.update(self.fit.way_text(self.shown, route, self.list_width()))
        # Whether PgUp PgDn have more to show, once it's laid out
        self.call_after_refresh(self.show_keys)

    def show_keys(self):
        """The line at the bottom: the keys of the list or of the panel under it"""
        in_ways = self.focused is not None and self.focused.id == "fit-ways"
        if in_ways:
            moves = [("↑↓", "the ways to run it"), ("← or Esc", "back to the list")]
            if self.query_one("#fit-detail").max_scroll_y:
                moves.insert(1, ("PgUp PgDn", "scroll"))
        else:
            moves = [("↑↓", "move"), ("its number", "jumps to it"), ("→ or Enter", "its ways to run it")]
        goal = [("- +", "context"), ("o", "own size"), ("p", "PC memory"), ("c", "conversations"), ("s", "order")]
        leave = [] if in_ways else [("Esc", self.leaving)]
        width = self.size.width - 2
        short = [(key, what.split()[0]) for key, what in moves[:1]] + moves[1:2] + \
            [(key, what) for key, what in goal if key in ("- +", "p")] + leave
        line = first_fitting([keys_line(*moves, *goal, *leave), keys_line(*moves[:2], *goal, *leave),
                              keys_line(*short)], width)
        self.query_one("#fit-keys", Static).update(line)

    def on_resize(self, event):
        self.draw()
        self.show_keys()

    # --- Moving around ---

    @on(OptionList.OptionHighlighted, "#fit-list")
    def model_highlighted(self, event):
        self.show_detail()

    @on(OptionList.OptionHighlighted, "#fit-ways")
    def way_highlighted(self, event):
        self.show_way()

    @on(OptionList.OptionSelected, "#fit-list")
    def model_chosen(self, event):
        self.action_side_right()

    def on_descendant_focus(self, event):
        self.show_keys()

    def action_side_right(self):
        """From the list into the panel under it"""
        ways = self.query_one("#fit-ways", FitList)
        if self.focused is self.query_one("#fit-list") and self.shown and ways.option_count:
            ways.focus()

    def action_side_left(self):
        if self.focused is self.query_one("#fit-ways"):
            self.query_one("#fit-list", FitList).focus()

    def action_scroll_detail(self, direction):
        detail = self.query_one("#fit-detail", Detail)
        detail.scroll_to(y=detail.scroll_y + direction * max(1, detail.size.height - 2), animate=False)

    def action_back(self):
        if self.focused is self.query_one("#fit-ways"):
            self.query_one("#fit-list", FitList).focus()
        else:
            self.dismiss()

    def on_key(self, event):
        # A number typed in the panel goes to that model in the list
        if event.character and event.character.isdigit() and self.focused is self.query_one("#fit-ways"):
            models = self.query_one("#fit-list", FitList)
            models.focus()
            models.type_key(event.character)
            event.stop()

    # --- Changing the goal ---

    def change(self, what, *args):
        if self.fit:
            keep = self.highlighted_group()
            getattr(self.fit, what)(*args)
            self.draw(keep)

    def action_set_context(self, tokens):
        self.change("set_context", tokens)

    def action_step_context(self, step):
        self.change("step_context", step)

    def action_set_place(self, pc_memory):
        self.change("set_place", pc_memory)

    def action_toggle_place(self):
        if self.fit:
            self.change("set_place", not self.fit.goal.pc_memory)

    def action_set_conversations(self, n):
        self.change("set_conversations", n)

    def action_next_conversations(self):
        self.change("next_conversations")

    def action_set_sort(self, by_context):
        self.change("set_sort", by_context)

    def action_toggle_sort(self):
        if self.fit:
            self.change("set_sort", not self.fit.goal.by_context)

    def action_own_size(self):
        if not self.fit:
            return

        def given(tokens):
            self.show_keys()
            if tokens:
                self.change("own_size", tokens)

        self.query_one("#fit-keys", Static).update(keys_line(*SizeBox.HINTS))
        self.app.push_screen(SizeBox(), given)


class SizeBox(ModalScreen):
    """Asks for a context size of your own, such as 200k, in a box over the
    fit. Enter adds it to the sizes at the top and picks it; Esc closes the
    box and changes nothing."""

    BINDINGS = [Binding("escape", "close", show=False)]
    HINTS = [("Enter", "adds it"), ("Esc", "closes")]
    NOTE = "It joins the sizes at the top, and stays there until you add another."


    def compose(self) -> ComposeResult:
        with Vertical(id="sizebox") as box:
            box.border_title = "Context size of your own"
            box.border_subtitle = "Enter adds it · Esc closes"
            yield Static("How much context do you need, in tokens? Such as 200k, 1M or 204800.", id="sizebox-text")
            yield Input(placeholder="200k", restrict=r"[0-9kKmM.,]*", id="sizebox-input")
            yield Static(Content.styled(self.NOTE, MUTED), id="sizebox-why")

    def on_mount(self):
        self.query_one(Input).focus()

    def key_hints(self):
        return self.HINTS

    @on(Input.Submitted)
    def submitted(self, event):
        tokens, why = parse_size(event.value)
        if why:
            self.query_one("#sizebox-why", Static).update(Content.styled(why, "$warning"))
        else:
            self.dismiss(tokens)

    def action_close(self):
        self.dismiss(None)

    def on_click(self, event):
        if event.widget is self:
            self.dismiss(None)


# --- On its own, typed in a terminal ---

class FitApp(App):
    """The fit on its own: the same screen as in the menu, in the menu's
    look and the theme picked there. Esc or ctrl+c leaves it."""

    CSS_PATH = "menu.tcss"
    TITLE = "AI Leverage › Fit"
    BINDINGS = [Binding("ctrl+c", "quit", show=False, priority=True)]

    def on_mount(self):
        theme = tui.saved_theme()
        self.theme = theme if theme in self.available_themes else tui.DEFAULT_THEME
        self.theme_changed_signal.subscribe(self, lambda changed: tui.save_theme(changed.name))
        self.push_screen(FitScreen(leaving="quit"), lambda _: self.exit())


def print_once():
    """The list for the saved goal, once: plain for output that isn't a
    terminal, in the theme's colours for one that is"""
    width = shutil.get_terminal_size((120, 50)).columns
    lines = Fit().printed(width)
    if not sys.stdout.isatty():
        print("\n".join(line.plain.rstrip() for line in lines))
        return
    from rich.console import Console
    from rich.style import Style as RichStyle
    from rich.text import Text
    from textual.style import Style
    from textual.theme import BUILTIN_THEMES

    theme = BUILTIN_THEMES.get(tui.saved_theme()) or BUILTIN_THEMES[tui.DEFAULT_THEME]
    variables = theme.to_color_system().generate()

    def parse(style):
        return Style.parse(style, variables)

    def terminal_style(style):
        # The terminal's own background is under it, so see-through colours are dimmed instead
        faint = style.foreground is not None and style.foreground.a < 1
        return style.rich_style + RichStyle(dim=True) if faint else style.rich_style

    console = Console(highlight=False, soft_wrap=True)
    for line in lines:
        console.print(Text.assemble(*[(text, terminal_style(style))
                                      for text, style in line.render(Style.null(), "", parse)]))


def main():
    args = sys.argv[1:]
    if args and args != ["--print"]:
        print(__doc__[__doc__.index("Usage:"):].rstrip(), file=sys.stderr)
        sys.exit(1)
    if args or not (sys.stdin.isatty() and sys.stdout.isatty()):
        try:
            print_once()
            sys.stdout.flush()
        except BrokenPipeError:
            # Output cut short, as by head: nothing more to say
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return
    FitApp().run()


if __name__ == "__main__":
    main()
