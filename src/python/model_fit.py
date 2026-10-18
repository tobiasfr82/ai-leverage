#!/usr/bin/env python3
"""ai-leverage/src/python/model_fit.py

Works out which downloaded models fit on this PC, on which engine, and with
how much context: the length of conversation a model can hold, in tokens.

A model needs room on the GPU for three things: its weights, the engine's
working memory, and its conversation memory, which grows with every token.
What's left after the first two, divided by the memory each token takes, is
the context. llama.cpp and Ollama can also keep part of a model in the PC's
memory, which is slower but lets bigger models and longer conversations run.

Everything here is an estimate ("about 85k tokens"). Each engine's numbers
below are calibrated on real starts on an RTX 5090, and its log says what it
really got.

What it plans for is the goal: how much context you need, whether the PC's
memory may help, and how many conversations run at once. fit_screen.py
(Models › Tuning › Fit in the menu) sets it, and it's kept in config/model-fit.conf.

What each engine is set to comes from its folder, the most specific first:
an option in its *_EXTRA_ARGS, then its .env, then the default its
compose.yaml gives (${CONTEXT_SIZE:-65536}), and else the engine's own.

Usage: python3 -I model_fit.py --engine <vllm|sglang|llamacpp|ollama>
  One line per model the engine runs, for set_model and list_models: the
  model's name, a tab, how much context it gets. Lines starting with # are
  notes for under the list.
"""

import copy
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hardware  # noqa: E402
import model_facts  # noqa: E402

GiB = 1024 ** 3
MiB = 1024 ** 2
K = 1024

BASE_DIR = model_facts.BASE_DIR
ENGINES_DIR = os.path.join(BASE_DIR, "stack", "engines")
CONFIG_FILE = os.path.join(BASE_DIR, "config", "model-fit.conf")

# The context sizes the goal can be set to; 0 is "the longest it gets"
CONTEXT_STEPS = [8 * K, 16 * K, 32 * K, 64 * K, 128 * K, 256 * K]
LONGEST = 0

# CUDA sees a little less of the GPU than nvidia-smi reports: 31.36 of 31.84 GB
# on an RTX 5090 (vLLM's log)
CUDA_SHARE = 0.985

# PC memory llama.cpp and Ollama leave free for the desktop and other programs
RAM_MARGIN = 4 * GiB

# Bytes per number of conversation memory: normal (16-bit) and 8-bit. llama.cpp
# and Ollama's q8_0 keeps a scale per 32 numbers, so it's 8.5 bits.
KV_BYTES = {"vllm": (2, 1), "sglang": (2, 1), "llamacpp": (2, 34 / 32), "ollama": (2, 34 / 32)}

# GGUF sizes a model could be downloaded in, best first: their bits per weight
# on average, and the bits they're named after
GGUF_SIZES = [("Q8_0", 8.5, 8), ("Q6_K", 6.6, 6), ("Q5_K_M", 5.7, 5), ("Q4_K_M", 4.85, 4), ("IQ4_XS", 4.3, 4)]

# Ways of running a model, from the least to the most it asks of you: as the
# engine is set, with 8-bit conversation memory (a setting), with part of the
# model in PC memory (slower), or both
AS_SET, EIGHT_BIT, PC_MEMORY, BOTH = range(4)


# --- Settings ---

def read_settings(path):
    """KEY=value lines of a .env or .conf file, without quotes and comments"""
    values = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    except OSError:
        pass
    return values


def write_settings(path, template, values):
    """Sets KEY=value lines in a settings file, which starts as a copy of its
    template, so every setting stays documented. A commented-out line for a
    key is replaced in place; a key that isn't there is added at the end."""
    try:
        with open(path) as f:
            lines = f.read().splitlines()
    except OSError:
        try:
            with open(template) as f:
                lines = f.read().splitlines()
        except OSError:
            lines = []
    for key, value in values.items():
        for i, line in enumerate(lines):
            if line.startswith(key + "=") or line.startswith("#" + key + "="):
                lines[i] = f"{key}={value}"
                break
        else:
            lines.append(f"{key}={value}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def compose_defaults(path):
    """The defaults a compose.yaml gives its settings, ${KEY:-value}: what
    the engine gets when its .env doesn't set KEY. The first one counts."""
    defaults = {}
    try:
        with open(path) as f:
            text = f.read()
    except OSError:
        return defaults
    for key, value in re.findall(r"\$\{(\w+):-([^}]*)\}", text):
        defaults.setdefault(key, value)
    return defaults


def option(args, *names):
    """The value after an option in an EXTRA_ARGS line, e.g. --kv-cache-dtype fp8"""
    words = args.split()
    for i, word in enumerate(words):
        for name in names:
            if word == name and i + 1 < len(words):
                return words[i + 1]
            if word.startswith(name + "="):
                return word.split("=", 1)[1]
    return None


def number(text, default=None, kind=float):
    try:
        return kind(text)
    except (TypeError, ValueError):
        return default


class Goal:
    """What the fit plans for: how much context you need (0 for the longest
    each model gets), whether the PC's memory may help, how many
    conversations run at once, and how the list is sorted"""

    def __init__(self):
        env = read_settings(CONFIG_FILE)
        self.context = max(0, number(env.get("FIT_CONTEXT"), 64 * K, int))
        self.pc_memory = env.get("FIT_PLACE", "gpu") == "gpu+ram"
        self.conversations = min(16, max(1, number(env.get("FIT_CONVERSATIONS"), 1, int)))
        self.by_context = env.get("FIT_SORT", "size") == "context"
        self.extra = number(env.get("FIT_EXTRA_CONTEXT"), 0, int) or 0

    def steps(self):
        """The context sizes to choose from, your own one included, then "longest" """
        sizes = sorted(set(CONTEXT_STEPS + ([self.extra] if self.extra else [])))
        return sizes + [LONGEST]

    def save(self):
        write_settings(CONFIG_FILE, CONFIG_FILE + ".template", {
            "FIT_CONTEXT": self.context,
            "FIT_PLACE": "gpu+ram" if self.pc_memory else "gpu",
            "FIT_CONVERSATIONS": self.conversations,
            "FIT_SORT": "context" if self.by_context else "size",
            "FIT_EXTRA_CONTEXT": self.extra or "",
        })


# --- What each part needs ---

def per_token(model, kv_bytes):
    """Bytes of conversation memory per token in the layers that keep it all"""
    return sum(a.elements for a in model.attention if not a.window) * kv_bytes


def window_bytes(model, kv_bytes, tokens, copies=1, extra=0):
    """Bytes the sliding-window layers keep for this many tokens: never more
    than their window (once per conversation the engine keeps one for), plus
    what the engine keeps beyond it"""
    return sum(a.elements * min(tokens, a.window * copies + extra)
               for a in model.attention if a.window) * kv_bytes


def state(model, ssm_bytes, conv_bytes):
    """Bytes of recurrent state one conversation keeps, whatever its length"""
    return model.ssm_elements * ssm_bytes + model.conv_elements * conv_bytes


def longest(fits, cap):
    """The most tokens for which fits(tokens) holds, up to cap, in steps of 256"""
    if cap <= 0 or not fits(256):
        return 0
    if fits(cap):
        return cap
    low, high = 256, cap
    while high - low > 256:
        middle = (low + high) // 2
        if fits(middle):
            low = middle
        else:
            high = middle
    return low


class Layout:
    """Where a model goes when an engine runs it with a context size: the
    parts on the GPU and in PC memory, in bytes, and whether it fits.
    The parts' names: model, working (the engine's working memory, or what
    it holds back for it), conversation, room (what the engine keeps for
    more conversation), kept (kept free on purpose), others (the desktop,
    other programs and what CUDA doesn't show) and free; in PC memory:
    tables (lookup tables that always stay there) and moved (what didn't
    fit on the GPU)."""

    def __init__(self, fits, why="", slower=""):
        self.fits = fits
        self.why = why        # why it doesn't fit, or won't start
        self.slower = slower  # "a bit slower" or "much slower" when part is in PC memory
        self.gpu = []
        self.ram = []
        self.over = 0         # how much it needs beyond what it may use

    def part(self, place, name, size):
        if size > 0:
            (self.gpu if place == "gpu" else self.ram).append((name, size))
        return self

    def on(self, place):
        return sum(size for _, size in (self.gpu if place == "gpu" else self.ram))


# --- The engines ---

class Engine:
    name = ""
    label = ""
    format = ""
    gguf = False
    # How to switch on 8-bit conversation memory today
    eight_bit = ""
    # The .env setting with options of your own for it
    extra_args = ""

    def __init__(self, gpu, ram_available):
        self.gpu = gpu
        self.ram = ram_available
        folder = os.path.join(ENGINES_DIR, self.name)
        self.env = read_settings(os.path.join(folder, ".env"))
        self.defaults = compose_defaults(os.path.join(folder, "compose.yaml"))
        self.args = (self.setting(self.extra_args) or "") if self.extra_args else ""
        self.total = gpu["total"] if gpu else 0
        self.cuda_total = self.total * CUDA_SHARE
        self.others = gpu["others"] if gpu else 0
        self.free = self.cuda_total - self.others

    def setting(self, key, *options):
        """What the engine gets for a setting, the most specific first: one of
        these options in its EXTRA_ARGS, its .env, the default its compose.yaml
        gives; None leaves it to the engine. Settings per model will go first.
        Empty counts as not set, as it does for Compose."""
        for value in (option(self.args, *options) if options else None, self.env.get(key), self.defaults.get(key)):
            if value not in (None, ""):
                return value
        return None

    def installed(self):
        return os.path.isdir(os.path.join(ENGINES_DIR, self.name))

    def runs(self, model):
        return model.format == self.format and (self.name == "ollama") == (model.source == "ollama")

    def cap(self, model):
        """The longest context this engine can give the model"""
        return model.max_context or 256 * K

    def kv8_as_set(self, model):
        return False

    def layout(self, model, tokens, conversations, kv8, allow_ram=False):
        raise NotImplementedError

    def check(self, model, tokens, conversations, kv8, allow_ram=False):
        if not self.gpu:
            return Layout(False, why="no NVIDIA GPU found")
        if model.needs and model.needs not in self.gpu["native"]:
            return Layout(False, why=f"needs {model.needs.upper()}, which this GPU doesn't run natively")
        return self.layout(model, tokens, conversations, kv8, allow_ram)


class VLLM(Engine):
    """vLLM takes VRAM_LIMIT of the GPU (its compose.yaml gives the default)
    for everything, and without it 0.9, its own default. The
    working memory comes from its startup log with Ornith 9B: the weights plus
    0.67 GB (17.66 GB weights + CUDA, 18.2 in all), and a test run's peak of
    2.27 GB. That peak grows with the vocabulary (256 conversations' worth of
    word scores) and with an image reader: 1.4 GB for one that reads any
    resolution (Qwen), 0.85 GB for a fixed one (Gemma, calibrated on its
    2,672 tokens). Sliding-window layers keep their window plus 4,096 tokens in
    flight (2 steps of 2,048 on cards under 70 GB). Recurrent state counts
    twice per conversation, to keep a copy for reuse. What's left over it
    keeps for more conversation."""
    name, label, format = "vllm", "vLLM", "safetensors"
    eight_bit = 'VLLM_EXTRA_ARGS="--kv-cache-dtype fp8" in stack/engines/vllm/.env'
    extra_args = "VLLM_EXTRA_ARGS"

    def settings(self):
        args = self.args
        limit = number(self.setting("VRAM_LIMIT", "--gpu-memory-utilization"), 0.9)
        # "auto" or none: as long as the model was made for, if it fits
        context = number(self.setting("CONTEXT_SIZE", "--max-model-len"), 0, int)
        kv = option(args, "--kv-cache-dtype")
        seqs = number(option(args, "--max-num-seqs"), 256, int)
        batch = number(option(args, "--max-num-batched-tokens"), 8192 if self.cuda_total >= 70 * GiB else 2048, int)
        return limit, context, kv, seqs, batch

    def cap(self, model):
        _, context, _, _, _ = self.settings()
        return min(model.max_context or 256 * K, context or 10 ** 9)

    def kv8_as_set(self, model):
        kv = self.settings()[2]
        return kv.startswith("fp8") if kv else model.kv8_by_makers

    def working(self, model):
        _, _, _, seqs, _ = self.settings()
        memory = 0.67 * GiB + 0.3 * GiB + seqs * (model.vocab or 150000) * 10
        if model.vision:
            memory += 1.4 * GiB if model.vision_dynamic else 0.85 * GiB
        return memory

    def layout(self, model, tokens, conversations, kv8, allow_ram=False):
        limit, _, _, _, batch = self.settings()
        budget = limit * self.cuda_total
        if budget > self.free:
            return Layout(False, why=f"won't start: VRAM_LIMIT {limit} asks for {gb(budget)} "
                                     f"and {gb(self.free)} is free")
        working = self.working(model)
        kv_bytes = KV_BYTES["vllm"][1 if kv8 else 0]
        one = (tokens * per_token(model, kv_bytes) + window_bytes(model, kv_bytes, tokens, extra=2 * batch)
               + 2 * state(model, model.ssm_bytes, 2))
        conversation = conversations * one
        need = model.weights + working + conversation
        result = Layout(need <= budget)
        if not result.fits:
            result.over = need - budget
            if model.weights + working > budget:
                result.why = (f"too big: needs {gb(model.weights + working)}, "
                              f"vLLM may use {gb(budget)} (VRAM_LIMIT {limit})")
            else:
                result.why = "not enough room for that much conversation"
        result.part("gpu", "model", model.weights).part("gpu", "working", working)
        result.part("gpu", "conversation", min(conversation, budget - model.weights - working))
        result.part("gpu", "room", budget - need)
        return result.part("gpu", "others", self.total - budget)


class SGLang(Engine):
    """SGLang keeps a share of the GPU (VRAM_LIMIT, or its own default) for the
    weights and the conversation memory, minus what this PC's other programs
    and its own CUDA setup use (0.5 GB). Its default is in its memory_hook.py
    (0.5.21): it holds back 0.5 GB, 1.5 MB per token of a prefill chunk (4,096
    on 20-35 GB cards), and room for CUDA graphs, then takes 5% to 20% less
    for a model that reads images. Models with recurrent state (Qwen 3.5
    family) give 0.9 / 1.9 of that memory to state, 5 slots per conversation
    and a spare, and sliding-window layers get 0.8 times as many tokens as the
    full ones. Calibrated on its Qwen3.8 AWQ start: 14,262 tokens."""
    name, label, format = "sglang", "SGLang", "safetensors"
    eight_bit = "--kv-cache-dtype fp8_e4m3 in SGLANG_EXTRA_ARGS in stack/engines/sglang/.env"
    extra_args = "SGLANG_EXTRA_ARGS"

    def settings(self):
        args = self.args
        return {
            "fraction": number(self.setting("VRAM_LIMIT", "--mem-fraction-static")),
            "context": number(self.setting("CONTEXT_SIZE", "--context-length"), 0, int),
            "kv": option(args, "--kv-cache-dtype"),
            "ssm": option(args, "--mamba-ssm-dtype"),
            "slots": number(option(args, "--max-mamba-cache-size"), 0, int),
            "ratio": number(option(args, "--mamba-full-memory-ratio"), 0.9),
            "swa": number(option(args, "--swa-full-tokens-ratio"), 0.8),
            "chunk": number(option(args, "--chunked-prefill-size"), 0, int),
        }

    def default_fraction(self, model, s):
        gpu_mb = self.cuda_total / MiB
        if gpu_mb < 20 * 1024:
            chunk, max_bs = 2048, 8
        elif gpu_mb < 35 * 1024:
            chunk, max_bs = 4096, 48
        elif gpu_mb < 60 * 1024:
            chunk, max_bs = 4096, 32
        elif gpu_mb < 160 * 1024:
            chunk, max_bs = 8192, 256
        else:
            chunk, max_bs = 16384, 512
        chunk = s["chunk"] or chunk
        graph_sizes = {2048: 42, 4096: 50, 8192: 66, 16384: 82}.get(chunk, 50)
        reserved = 512 + max(chunk, 2048) * 1.5 + 128 + max_bs * 2 + graph_sizes * 8
        if gpu_mb > 60 * 1024:
            reserved = max(reserved, 10 * 1024)
        fraction = round((gpu_mb - reserved) / gpu_mb, 3)
        if model.vision:
            ratio = model.vision_layers * model.vision_width ** 2 / (24 * 1024 ** 2)
            fraction *= 0.95 * max(0.8, min(1.05, 1 - 0.1 * (ratio - 1)))
        return fraction

    def fraction(self, model):
        s = self.settings()
        return s["fraction"] or self.default_fraction(model, s)

    def cap(self, model):
        context = self.settings()["context"]
        return min(model.max_context or 256 * K, context or 10 ** 9)

    def kv8_as_set(self, model):
        kv = self.settings()["kv"]
        if kv:
            return kv.startswith("fp8")
        return model.kv8_by_makers and model.quant_method.startswith("modelopt")

    def layout(self, model, tokens, conversations, kv8, allow_ram=False):
        s = self.settings()
        budget = self.fraction(model) * self.cuda_total
        held = self.cuda_total - budget
        pool = budget - self.others - 0.5 * GiB - model.weights
        result = Layout(True)
        if pool <= 0:
            result = Layout(False, why=f"too big: needs {gb(model.weights)}, SGLang keeps "
                                       f"{gb(budget - self.others - 0.5 * GiB)} for the model and conversation")
            result.over = -pool
            pool = 0
        kv_bytes = KV_BYTES["sglang"][1 if kv8 else 0]
        state_memory = 0
        if model.ssm_elements and result.fits:
            # Plus one spare slot, as SGLang keeps (kv_cache_configurator.py)
            slot = state(model, 2 if s["ssm"] in ("bfloat16", "float16") else model.ssm_bytes, 2)
            slots = s["slots"] or int(pool * s["ratio"] / (1 + s["ratio"]) // slot) - 1
            if slots // 5 < 1:
                fix = " Add --mamba-ssm-dtype bfloat16 to SGLANG_EXTRA_ARGS." if not s["ssm"] else ""
                result = Layout(False, why="won't start: too little room for the state each conversation "
                                           "keeps (\"state cache is too small\")." + fix)
            elif slots // 5 < conversations:
                result = Layout(False, why=f"room for the state of {slots // 5} conversation(s) at once")
            state_memory = (slots + 1) * slot
        full = per_token(model, kv_bytes)
        sliding = sum(a.elements for a in model.attention if a.window) * kv_bytes
        conversation = conversations * tokens * (full + s["swa"] * sliding)
        if result.fits and state_memory + conversation > pool:
            result = Layout(False, why="not enough room for that much conversation")
            result.over = state_memory + conversation - pool
        result.part("gpu", "model", model.weights).part("gpu", "working", held)
        used = min(pool, state_memory + conversation)
        result.part("gpu", "conversation", used).part("gpu", "room", pool - used)
        return result.part("gpu", "others", self.total - self.cuda_total + self.others + 0.5 * GiB)


class GGUFEngine(Engine):
    """What llama.cpp and Ollama share: GGUF files, part of a model in PC
    memory when the GPU is full, and lookup tables that always stay there"""
    format = "gguf"
    gguf = True
    keep_free = 0
    slots = 1
    window_extra = 512

    def working(self, model):
        """The compute buffer: the word scores for a batch of 512 tokens, plus a little"""
        return 0.3 * GiB + 512 * (model.vocab or 150000) * 4

    def layout(self, model, tokens, conversations, kv8, allow_ram=False):
        kv_bytes = KV_BYTES[self.name][1 if kv8 else 0]
        copies = max(self.slots, conversations)
        total_tokens = tokens * conversations
        kv = (total_tokens * per_token(model, kv_bytes)
              + window_bytes(model, kv_bytes, total_tokens, copies, self.window_extra)
              + copies * state(model, 4, 4))
        weights = model.weights - model.ram_only + model.vision_file
        working = self.working(model)
        budget = self.free - self.keep_free - 0.3 * GiB
        ram_room = self.ram - RAM_MARGIN - model.ram_only
        need = weights + working + kv
        overflow = max(0, need - budget)
        if model.ram_only > self.ram - RAM_MARGIN:
            result = Layout(False, why=f"its lookup tables need {gb(model.ram_only)} of PC memory, "
                                       f"{gb(max(0, self.ram - RAM_MARGIN))} is free")
        elif not overflow:
            result = Layout(True)
        elif not allow_ram:
            result = Layout(False, why="doesn't fit on the GPU alone")
        # What can move to PC memory: MoE experts first, which costs little
        # speed, then whole layers with their conversation memory, which
        # costs a lot. The working memory stays.
        elif overflow > weights + kv:
            result = Layout(False, why="doesn't fit, even with most of it in PC memory")
        elif overflow > ram_room:
            result = Layout(False, why=f"needs {gb(overflow + model.ram_only)} of PC memory, "
                                       f"{gb(max(0, self.ram - RAM_MARGIN))} is free")
        else:
            moved_experts = model.experts and overflow <= model.experts
            result = Layout(True, slower="a bit slower" if moved_experts else "much slower")
        moved = overflow if result.fits else 0
        if not result.fits and overflow:
            result.over = overflow
        result.part("gpu", "model", weights - min(moved, weights)).part("gpu", "working", working)
        result.part("gpu", "conversation", kv - max(0, moved - weights))
        result.part("gpu", "kept", self.keep_free)
        result.part("gpu", "others", self.total - self.cuda_total + self.others + 0.3 * GiB)
        result.part("gpu", "free", self.total - result.on("gpu"))
        result.part("ram", "tables", model.ram_only).part("ram", "moved", moved)
        return result


class LlamaCpp(GGUFEngine):
    """llama.cpp fits each model to the GPU's free memory minus VRAM_KEEP_FREE
    (its compose.yaml gives the default; 1 GB is llama.cpp's own) and keeps
    the rest in PC memory, MoE experts first. Every model gets CONTEXT_SIZE
    tokens (the default in its compose.yaml; without one, the fit plans for as
    long as the model was made for), one pool shared by 4 conversation slots
    (its default), each with its own recurrent state, in 32-bit.
    Sliding-window layers keep their window per slot plus a batch."""
    name, label = "llamacpp", "llama.cpp"
    eight_bit = ('LLAMACPP_EXTRA_ARGS="--cache-type-k q8_0 --cache-type-v q8_0" '
                 'in stack/engines/llamacpp/.env')
    extra_args = "LLAMACPP_EXTRA_ARGS"

    def __init__(self, gpu, ram_available):
        super().__init__(gpu, ram_available)
        self.keep_free = number(self.setting("VRAM_KEEP_FREE", "--fit-target"), 1024, int) * MiB
        self.slots = number(option(self.args, "-np", "--parallel"), 4, int)
        if self.slots < 1:
            self.slots = 4

    def as_set(self, model):
        context = number(self.setting("CONTEXT_SIZE", "-c", "--ctx-size"), 0, int) or model.max_context or 256 * K
        return min(context, model.max_context or context)

    def kv8_as_set(self, model):
        kv = option(self.args, "-ctk", "--cache-type-k")
        return bool(kv) and kv.startswith("q8")


class Ollama(GGUFEngine):
    """Ollama sizes its context to the GPU unless told (4k under 24 GB, 32k to
    48 GB, 256k above), or a model's own num_ctx says otherwise. Each of
    OLLAMA_NUM_PARALLEL conversations (1 by default) gets the whole context.
    OLLAMA_KV_CACHE_TYPE q8_0 stores it at 8 bits, for every model. Layers that
    don't fit on the GPU run on the CPU, so it gets slower."""
    name, label = "ollama", "Ollama"
    eight_bit = "OLLAMA_KV_CACHE_TYPE=q8_0 in stack/engines/ollama/.env (for every model)"

    def __init__(self, gpu, ram_available):
        super().__init__(gpu, ram_available)
        self.keep_free = 0.5 * GiB
        self.slots = max(1, number(self.setting("OLLAMA_NUM_PARALLEL"), 1, int))

    def as_set(self, model):
        if model.ollama_context:
            context = model.ollama_context
        else:
            context = number(self.setting("OLLAMA_CONTEXT_LENGTH"), 0, int)
            if not context:
                context = 4 * K if self.total < 24 * GiB else 32 * K if self.total < 48 * GiB else 256 * K
        return min(context, model.max_context or context)

    def kv8_as_set(self, model):
        return (self.setting("OLLAMA_KV_CACHE_TYPE") or "f16").startswith("q8")

    def layout(self, model, tokens, conversations, kv8, allow_ram=False):
        # Ollama spreads layers, not experts, so a MoE model slows down as much
        result = super().layout(model, tokens, conversations, kv8, allow_ram)
        if result.slower:
            result.slower = "slower"
        return result


ENGINES = [VLLM, SGLang, LlamaCpp, Ollama]


def engines_for(found):
    gpu = found["gpus"][0] if found["gpus"] else None
    return {e.name: e for e in (cls(gpu, found["ram_available"]) for cls in ENGINES) if e.installed()}


# --- One file on one engine ---

def gb(size):
    return hardware.gb(size)


def tokens_text(tokens):
    """262144 -> 256k, 199056 -> ~194k, 2672 -> ~2.6k"""
    if tokens >= 1000 * K:
        return f"{tokens / K / K:.1f}M".replace(".0M", "M")
    if tokens % K == 0:
        return f"{tokens // K}k"
    if tokens < 10 * K:
        return f"~{tokens / K:.1f}k"
    return f"~{tokens // K}k"


class Plan:
    """One file on one engine: the longest context it gets as the engine is
    set, with 8-bit conversation memory, and with part in PC memory"""

    def __init__(self, engine, model, conversations):
        self.engine, self.model, self.conversations = engine, model, conversations
        n = conversations
        self.cap = engine.cap(model)
        self.kv8_set = engine.kv8_as_set(model)
        self.reach = [0, 0, 0, 0]
        self.reach[AS_SET] = longest(lambda t: engine.check(model, t, n, self.kv8_set).fits, self.cap)
        self.reach[EIGHT_BIT] = self.reach[AS_SET] if self.kv8_set else \
            longest(lambda t: engine.check(model, t, n, True).fits, self.cap)
        if engine.gguf:
            self.reach[PC_MEMORY] = longest(lambda t: engine.check(model, t, n, self.kv8_set, True).fits, self.cap)
            self.reach[BOTH] = self.reach[PC_MEMORY] if self.kv8_set else \
                longest(lambda t: engine.check(model, t, n, True, True).fits, self.cap)
        self.why = "" if max(self.reach) else engine.check(model, 256, n, True, engine.gguf).why

    def most(self, pc_memory):
        """The longest context it gets, with the PC's memory or without"""
        return max(self.reach) if pc_memory else max(self.reach[AS_SET], self.reach[EIGHT_BIT])

    def way(self, tokens, pc_memory):
        """The least it asks of you to hold this many tokens: AS_SET,
        EIGHT_BIT, PC_MEMORY or BOTH, or None when it can't"""
        for way in (AS_SET, EIGHT_BIT, PC_MEMORY, BOTH):
            if (pc_memory or way < PC_MEMORY) and self.reach[way] >= tokens and self.reach[way]:
                return way
        return None

    def layout(self, tokens, way):
        kv8 = self.kv8_set or way in (EIGHT_BIT, BOTH)
        return self.engine.check(self.model, tokens, self.conversations, kv8, way in (PC_MEMORY, BOTH))

    def summary(self, goal_context=0):
        """"~194k · 8-bit 256k (its max)", or why it won't run: for the model lists"""
        if not max(self.reach):
            return self.why
        parts = []
        if self.reach[AS_SET]:
            parts.append(tokens_text(self.reach[AS_SET]))
        if self.reach[EIGHT_BIT] > self.reach[AS_SET]:
            parts.append(f"8-bit {tokens_text(self.reach[EIGHT_BIT])}")
        if self.reach[PC_MEMORY] > max(self.reach[:2]):
            parts.append(f"with PC memory {tokens_text(self.reach[PC_MEMORY])}")
        if self.reach[BOTH] > max(self.reach[:3]):
            parts.append(f"8-bit with PC memory {tokens_text(self.reach[BOTH])}")
        text = " · ".join(parts)
        if self.model.max_context and max(self.reach) >= self.model.max_context:
            text += " (its max)"
        if goal_context and max(self.reach) < goal_context:
            text += f"  ! under your {tokens_text(goal_context)}"
        return text


# --- Models: the files of one model, and the ways to run it ---

class Route:
    """One way to run a model: one of its files on an engine. Not downloaded
    when it's the same model in another size, worked out from its parameters."""

    def __init__(self, plan, downloaded=True):
        self.plan = plan
        self.downloaded = downloaded
        self.file = plan.model
        self.engine = plan.engine
        self.presets = []   # Ollama: models with saved settings on top of this one

    def bits(self):
        return self.file.bits or 0


ENGINE_ORDER = {"vllm": 0, "sglang": 1, "llamacpp": 2, "ollama": 3}


class Group:
    """All files of one model, whatever their format or size"""

    def __init__(self, files):
        self.files = files
        hf = [f for f in files if f.source == "huggingface"]
        # Ollama's own name for it, not one with saved settings (agent/...)
        named = sorted(hf or files, key=lambda f: (f.format != "safetensors", "/" in f.name, f.name))
        self.name = model_facts.display_name(named[0])
        main = max(files, key=lambda f: f.text_params)
        self.params = main.text_params
        # The size its name gives, which people know it by, when that's close
        named_size = model_facts.named_size(named[0]) * 1e9
        self.named = named_size if named_size and abs(named_size - self.params) < 0.25 * self.params else 0
        self.moe = bool(main.experts_total)
        # What works on each token: all but the experts that sit out, and
        # the lookup tables, of which it reads only a row or two
        self.active = self.params - main.table_params
        if self.moe and main.experts_used:
            self.active -= main.expert_params * (1 - main.experts_used / main.experts_total)
        self.vision = any(f.vision for f in files)
        self.max_context = max(f.max_context for f in files)
        self.embedding = any(f.embedding for f in files)
        self.rough = next((f.rough for f in files if f.rough), "")
        self.routes = []
        self.other_sizes = None

    def best(self, goal):
        """(Route, way) that meets the goal asking the least of you, or
        (None, None). Of routes that ask as little, the better quality wins,
        then the longer context."""
        best = None
        for route in self.routes:
            plan = route.plan
            way = plan.way(goal.context or 4 * K, goal.pc_memory)
            if way is None:
                continue
            if not goal.context:
                way = plan.way(plan.most(goal.pc_memory), goal.pc_memory)
            rank = (way, -route.bits(), -plan.most(goal.pc_memory), ENGINE_ORDER[route.engine.name])
            if best is None or rank < best[0]:
                best = (rank, route, way)
        return (best[1], best[2]) if best else (None, None)

    def closest(self, goal):
        """The route that gets furthest, for a model that doesn't meet the goal"""
        return max(self.routes, key=lambda r: (r.plan.most(goal.pc_memory), -ENGINE_ORDER[r.engine.name]),
                   default=None)

    def size_text(self):
        """"35B MoE", "27B", "7.5B": by its name when that gives a size"""
        params = self.named or self.params
        size = f"{params / 1e9:.0f}B" if params >= 9.5e9 else f"{params / 1e9:.1f}B".replace(".0B", "B")
        return size + (" MoE" if self.moe else "")


def same_shape(a, b):
    """Two files whose names say they're one model, checked by their size"""
    big = max(a.text_params, b.text_params) or 1
    return abs(a.text_params - b.text_params) / big < 0.1


def groups(models, engines, conversations):
    """The models, each with its files and the ways to run them"""
    found = {}
    for model in models:
        key = model_facts.same_model_key(model)
        for candidate in found.setdefault(key, []):
            if same_shape(candidate[0], model):
                candidate.append(model)
                break
        else:
            found[key].append([model])
    result = []
    for lists in found.values():
        for files in lists:
            group = Group(files)
            # Ollama models with saved settings share their base model's file:
            # one route, run as the base, with the others as its presets
            ollama = {}
            for f in files:
                if f.source == "ollama":
                    ollama.setdefault(f.file_id, []).append(f)
            for f in files:
                if f.source == "ollama" and ollama[f.file_id][0] is not f:
                    continue
                if f.source == "ollama":
                    named = sorted(ollama[f.file_id], key=lambda m: ("/" in m.name, m.name))
                    f, presets = named[0], named[1:]
                else:
                    presets = []
                for engine in engines.values():
                    if engine.runs(f):
                        route = Route(Plan(engine, f, conversations))
                        route.presets = presets
                        group.routes.append(route)
            result.append(group)
    return result


def other_sizes(group, engines, conversations):
    """Routes for the same model in GGUF sizes that aren't downloaded, worked
    out from its parameters: on Ollama when you have it there, else on
    llama.cpp. Sizes it has already are left out."""
    if group.other_sizes is not None:
        return group.other_sizes
    group.other_sizes = []
    main = max(group.files, key=lambda f: (f.format == "safetensors", f.text_params))
    in_ollama = any(f.source == "ollama" for f in group.files)
    engine = engines.get("ollama" if in_ollama else "llamacpp")
    if not engine or not main.text_params or group.embedding:
        return group.other_sizes
    have = {f.quant.upper() for f in group.files}
    for size, bpw, bits in GGUF_SIZES:
        if size in have:
            continue
        other = copy.deepcopy(main)
        other.format, other.quant, other.bits, other.needs = "gguf", size, bits, ""
        other.weights = int(main.text_params * bpw / 8)
        share = main.expert_params / main.text_params if main.text_params else 0
        other.experts = int(other.weights * share)
        other.ram_only = 0
        other.vision_file = int((main.params - main.text_params) * 2) if main.vision else main.vision_file
        other.ssm_bytes = 4
        other.name = f"{group.name} as {size}"
        group.other_sizes.append(Route(Plan(engine, other, conversations), downloaded=False))
    return group.other_sizes


def better_size(group, goal, engines):
    """A size that isn't downloaded and meets the goal when no download does,
    or meets it in better quality than the best download: (Route, way).
    Of those, the one that asks the least of you, then the best quality."""
    have, _ = group.best(goal)
    best = None
    for route in other_sizes(group, engines, goal.conversations):
        way = route.plan.way(goal.context or 4 * K, goal.pc_memory)
        if way is None or (have and route.bits() <= have.bits()):
            continue
        if best is None or (way, -route.bits()) < (best[1], -best[0].bits()):
            best = (route, way)
    return best or (None, None)


def ranked(all_groups, goal):
    """(models that meet the goal, models that don't) as (Group, Route, way),
    each in the goal's order: biggest first, or longest context first"""
    meets, misses = [], []
    for group in all_groups:
        if group.embedding:
            continue
        route, way = group.best(goal)
        if route:
            meets.append((group, route, way))
        else:
            misses.append((group, group.closest(goal), None))

    def order(item):
        group, route, _ = item
        most = route.plan.most(goal.pc_memory) if route else 0
        if goal.by_context:
            return (-most, -group.params)
        return (-group.params, -(route.bits() if route else 0), -most)

    return sorted(meets, key=order), sorted(misses, key=order)


# --- set_model and list_models ---

def engine_lines(name, found, models, goal):
    """Model name, a tab, what it gets; then lines starting with # for notes
    to show under the list"""
    engine = engines_for(found).get(name)
    if not engine:
        return []
    lines, eight = [], False
    for model in models:
        if not engine.runs(model) or model.embedding:
            continue
        plan = Plan(engine, model, goal.conversations)
        text = plan.summary(goal.context)
        eight = eight or "8-bit" in text
        if engine.gguf:
            context = engine.as_set(model)
            way = plan.way(context, True)
            if way in (AS_SET, EIGHT_BIT):
                done = "fits" if way == AS_SET else "fits with 8-bit memory"
            elif way is not None:
                layout = plan.layout(context, way)
                done = f"{gb(layout.on('ram'))} in PC memory, {layout.slower}"
            else:
                done = "doesn't fit"
            text = f"set to {tokens_text(context)}: {done} · most: {text}"
        lines.append(f"{model.name}\t{text}")
    if eight:
        lines.append("#\t8-bit: conversation memory at half the size, a little less precise. "
                     f"To use it: {engine.eight_bit}")
    return lines


def main():
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "--engine" and args[1] in [c.name for c in ENGINES]:
        found = hardware.detect()
        models = model_facts.all_models(("ollama",) if args[1] == "ollama" else ("huggingface",))
        print("\n".join(engine_lines(args[1], found, models, Goal())))
    else:
        print(__doc__.split("\n\n")[5], file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
