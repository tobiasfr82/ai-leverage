#!/usr/bin/env python3
"""ai-leverage/src/python/model_facts.py

What a downloaded model asks of the PC, read from its files without loading
it: how much room its weights take, how much memory each token of
conversation takes, and how long a conversation it was made for.
model_fit.py turns that into "fits, with about 85k tokens".

It reads the two folders the downloaders fill:
  models/huggingface/hub   .safetensors models: config.json and the headers
                           of the weight files. GGUF models: their headers.
  models/ollama            each model's manifest, then its GGUF file's header
Only the start of each file is read, never the weights themselves, and
nothing goes online. What it read is kept in the repo's cache/ folder, so
each file is read again only when it changes. A model finder could later fill
the same facts from Hugging Face before a download.

Usage: python3 -I model_facts.py [--json | --gguf]
  One line per model with what it found, or all of it as JSON. --gguf is for
  llama.cpp's list_models: a line per GGUF download (name, tab, size, tab,
  "incomplete" or "reads images"), then a line per organization/model:size
  in the downloader's models.txt that isn't downloaded ("not downloaded",
  tab, the line).
"""

import dataclasses
import json
import math
import mmap
import os
import re
import struct
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gguf_names  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HUB_DIR = os.path.join(BASE_DIR, "models", "huggingface", "hub")
OLLAMA_DIR = os.path.join(BASE_DIR, "models", "ollama")
MODELS_LIST = os.path.join(BASE_DIR, "stack", "downloaders", "huggingface", "models.txt")
CACHE_FILE = os.path.join(BASE_DIR, "cache", "model-facts.json")
# Bumped when what's read changes, so older remembered facts are read again
CACHE_VERSION = 3


@dataclass
class Attention:
    """Attention layers alike in size: what they keep per token of
    conversation (keys and values, as numbers), and the window of a
    sliding-window layer, which only keeps the last tokens"""
    layers: int
    elements: int   # per token, all these layers together
    window: int = 0


@dataclass
class Model:
    name: str                # as its engine names it
    source: str              # huggingface or ollama
    format: str              # safetensors or gguf
    quant: str               # how the weights are stored: NVFP4, AWQ 4-bit, Q4_K_M ...
    needs: str = ""          # what the GPU must run natively: fp4, fp8, bf16, int4, or nothing
    weights: int = 0         # bytes the engine loads (for GGUF: the model file, all parts)
    experts: int = 0         # ...of those, MoE experts, which llama.cpp and Ollama can keep in PC memory
    file_id: str = ""        # the weight file itself: two names for one file are one model
    ram_only: int = 0        # ...of those, what llama.cpp and Ollama always keep in PC memory
    vision_file: int = 0     # a separate file for reading images, loaded with the model
    vision: bool = False     # reads images
    vision_dynamic: bool = False  # ...at any resolution (Qwen-VL style), which takes more working memory
    vision_layers: int = 24  # the image reader's layers and width, as SGLang reads them
    vision_width: int = 1024
    params: int = 0          # parameters, all of them
    text_params: int = 0     # ...without the part that reads images or audio
    expert_params: int = 0   # ...of those, in MoE experts
    table_params: int = 0    # ...and in lookup tables, of which each token reads a row or two
    bits: int = 0            # bits per weight, by its quantization: 16, 8, 6, 5, 4, 3, 2
    max_context: int = 0     # the longest conversation it was made for, in tokens
    vocab: int = 0           # words it knows (its tokenizer's vocabulary)
    attention: list = field(default_factory=list)
    ssm_elements: int = 0    # recurrent state per conversation (Mamba, linear attention), all layers
    conv_elements: int = 0   # ...and the short convolution state that goes with it
    ssm_bytes: int = 4       # bytes per number of that state the model asks for (float32: 4)
    experts_total: int = 0   # MoE: experts per layer...
    experts_used: int = 0    # ...and how many of them work on each token
    kv8_by_makers: bool = False  # its makers ask for 8-bit conversation memory (vLLM follows that)
    quant_method: str = ""   # how it was quantized: modelopt, compressed-tensors, awq ...
    architecture: str = ""
    embedding: bool = False  # an embedding model (for document search), not a chat model
    rough: str = ""          # why the estimate is less certain, if it is
    incomplete: str = ""     # what's missing from the download
    ollama_context: int = 0  # Ollama: the context its settings ask for (num_ctx), 0 when unset
    base: str = ""           # Ollama: the model a spec model is built on


# --- Remembering what was read ---

class Cache:
    """Facts read before, kept with the size and time of every file they came
    from, so a model is read again only when one of its files changed"""

    def __init__(self):
        try:
            with open(CACHE_FILE) as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        self.old = data.get("models", {}) if data.get("version") == CACHE_VERSION else {}
        self.new = {}

    @staticmethod
    def stamp(paths):
        stamps = []
        for path in paths:
            try:
                info = os.stat(path)
                stamps.append([os.path.realpath(path), info.st_size, info.st_mtime_ns])
            except OSError:
                stamps.append([path, -1, 0])
        return stamps

    def models(self, key, paths, read):
        """The models read from these files: remembered, or read now"""
        stamp = self.stamp(paths)
        entry = self.old.get(key)
        if entry and entry.get("files") == stamp:
            try:
                models = [from_dict(m) for m in entry["models"]]
                self.new[key] = entry
                return models
            except (TypeError, KeyError):
                pass
        models = read()
        self.new[key] = {"files": stamp, "models": [dataclasses.asdict(m) for m in models]}
        return models

    def save(self):
        if self.new == self.old:
            return
        try:
            os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
            temporary = CACHE_FILE + ".new"
            with open(temporary, "w") as f:
                json.dump({"version": CACHE_VERSION, "models": self.new}, f)
            os.replace(temporary, CACHE_FILE)
        except OSError:
            pass


def from_dict(data):
    names = {f.name for f in dataclasses.fields(Model)}
    model = Model(**{k: v for k, v in data.items() if k in names})
    model.attention = [Attention(**a) for a in model.attention]
    return model


# --- Hugging Face, .safetensors ---

def snapshot(folder):
    """The version of a download that refs/main points at, as the engines load it"""
    try:
        with open(os.path.join(folder, "refs", "main")) as ref:
            snap = os.path.join(folder, "snapshots", ref.read().strip())
    except OSError:
        return None
    return snap if os.path.isdir(snap) else None


def safetensors_header(path):
    """The tensors a .safetensors file holds, from its header: name ->
    {dtype, shape, data_offsets}"""
    with open(path, "rb") as f:
        length = struct.unpack("<Q", f.read(8))[0]
        if length > 100 * 1024 * 1024:
            raise ValueError("header too big")
        header = json.loads(f.read(length))
    header.pop("__metadata__", None)
    return header


# Tensors that only describe others (quantization scales and such)
NOT_PARAMETERS = ("scale", "zero_point", "zeros", "g_idx", "weight_shape", "input_global_scale")
# Parts of a multimodal model that read images, video or audio
VISION_PARTS = ("visual.", "vision_tower", "vision_model", "audio_tower", "audio_model",
                "embed_vision", "embed_audio", "multi_modal_projector", "mm_projector")


def count_weights(snap, files, bits):
    """(bytes, expert bytes, parameters, parameters that read images or audio,
    expert parameters, lookup-table parameters). A 4-bit weight packs 8 numbers into each 32-bit
    integer (AWQ, GPTQ) or 2 into each byte (FP4), so packed tensors count
    that many times over."""
    total = experts = params = vision = expert_params = tables = 0
    for name in files:
        try:
            header = safetensors_header(os.path.join(snap, name))
        except (OSError, ValueError, struct.error):
            continue
        for tensor, info in header.items():
            start, end = info.get("data_offsets", (0, 0))
            size = end - start
            total += size
            is_expert = ".experts." in tensor and "shared_expert" not in tensor
            if is_expert:
                experts += size
            leaf = tensor.rsplit(".", 1)[-1]
            if any(word in leaf for word in NOT_PARAMETERS):
                continue
            count = math.prod(info.get("shape") or [1])
            if info.get("dtype") == "I32" and leaf in ("qweight", "weight_packed"):
                count *= 32 // (bits or 4)
            elif info.get("dtype") == "U8" and leaf in ("weight_packed", "weight"):
                count *= 2
            params += count
            if any(part in tensor for part in VISION_PARTS):
                vision += count
            elif is_expert:
                expert_params += count
            elif "embed_tokens" in tensor:
                tables += count
    return total, experts, params, vision, expert_params, tables


def quantization(config):
    """(name, what the GPU must run natively, bits, 8-bit memory asked for)"""
    q = config.get("quantization_config") or config.get("text_config", {}).get("quantization_config")
    dtype = str(config.get("torch_dtype") or config.get("dtype")
                or config.get("text_config", {}).get("dtype") or "bfloat16")
    if not q:
        if "bfloat16" in dtype:
            return "BF16", "bf16", 16, False
        if "float32" in dtype:
            return "FP32", "", 32, False
        return "FP16", "", 16, False

    method = str(q.get("quant_method", "")).lower()
    kv = q.get("kv_cache_scheme") or q.get("kv_cache_quant_algo")
    kv8 = (isinstance(kv, dict) and kv.get("num_bits") == 8 and kv.get("type") == "float") \
        or (isinstance(kv, str) and "fp8" in kv.lower())
    # What the weights are: a compressed-tensors model says it per group of
    # layers, and a mixed one (NVFP4 experts, FP8 elsewhere) is named after
    # its smallest
    groups = [g["weights"] for g in (q.get("config_groups") or {}).values()
              if isinstance(g, dict) and isinstance(g.get("weights"), dict)]
    weights = min(groups, key=lambda w: w.get("num_bits") or 16) if groups else {}
    bits = weights.get("num_bits") or q.get("bits") or q.get("w_bit") or 4
    kind = weights.get("type", "")
    algo = str(q.get("quant_algo") or q.get("format") or "").lower()

    if "nvfp4" in algo or (kind == "float" and bits == 4 and weights.get("group_size") == 16):
        return "NVFP4", "fp4", 4, kv8
    if method == "mxfp4" or "mxfp4" in algo:
        return "MXFP4", "fp4", 4, kv8
    if method == "fp8" or "fp8" in algo or (kind == "float" and bits == 8) or "float-quantized" in algo:
        return "FP8", "fp8", 8, kv8
    if method in ("awq", "awq_marlin"):
        return f"AWQ {bits}-bit", "int4", bits, kv8
    if method in ("gptq", "gptq_marlin"):
        return f"GPTQ {bits}-bit", "int4", bits, kv8
    if method == "compressed-tensors":
        return f"INT{bits}", "int4", bits, kv8
    if method == "bitsandbytes":
        return "bitsandbytes 4-bit", "", 4, kv8
    return method or "quantized", "", bits, kv8


def text_config(config):
    for key in ("text_config", "llm_config", "language_config"):
        if isinstance(config.get(key), dict):
            return config[key]
    return config


def layer_kinds(t):
    """What each layer is: full_attention, sliding_attention, or recurrent
    (Mamba or linear attention, which keeps a fixed-size state instead)"""
    n = int(t.get("num_hidden_layers") or 0)
    kinds = t.get("layer_types")
    if isinstance(kinds, list) and len(kinds) >= n:
        out = []
        for kind in kinds[:n]:
            kind = str(kind)
            if "sliding" in kind or kind in ("local", "chunked_attention"):
                out.append("sliding_attention")
            elif "linear" in kind or "mamba" in kind or kind in ("conv", "recurrent"):
                out.append("recurrent")
            else:
                out.append("full_attention")
        return out
    pattern = t.get("hybrid_override_pattern")
    if isinstance(pattern, str) and len(pattern) >= n:
        # Nemotron-H: M is a Mamba layer, * an attention layer, - only a feed-forward
        return ["recurrent" if c == "M" else "full_attention" if c == "*" else "none"
                for c in pattern[:n]]
    interval = t.get("full_attention_interval")
    if interval:
        return ["full_attention" if (i + 1) % interval == 0 else "recurrent" for i in range(n)]
    every = t.get("sliding_window_pattern")
    if t.get("sliding_window") and isinstance(every, int) and every > 1:
        return ["full_attention" if (i + 1) % every == 0 else "sliding_attention" for i in range(n)]
    if t.get("sliding_window") and t.get("use_sliding_window") is True:
        return ["sliding_attention"] * n
    return ["full_attention"] * n


def config_layout(model, config):
    """Fills in conversation memory and recurrent state from config.json"""
    t = text_config(config)
    model.architecture = str(t.get("model_type") or config.get("model_type") or "")
    model.max_context = int(t.get("max_position_embeddings") or config.get("max_position_embeddings") or 0)
    model.vocab = int(t.get("vocab_size") or config.get("vocab_size") or 0)
    heads = int(t.get("num_attention_heads") or 1)
    kv_heads = int(t.get("num_key_value_heads") or heads)
    head_dim = int(t.get("head_dim") or (int(t.get("hidden_size") or 0) // heads))
    global_kv_heads = int(t.get("num_global_key_value_heads") or kv_heads)
    global_head_dim = int(t.get("global_head_dim") or head_dim)
    window = int(t.get("sliding_window") or 0)

    kinds = layer_kinds(t)
    shared = int(t.get("num_kv_shared_layers") or 0)
    if shared:
        # The last layers reuse earlier layers' memory and keep none of their own
        kinds = kinds[: len(kinds) - shared]

    if t.get("kv_lora_rank"):
        # DeepSeek-style compressed attention: one small vector per token and layer
        per_layer = int(t["kv_lora_rank"]) + int(t.get("qk_rope_head_dim") or 0)
        full = kinds.count("full_attention") + kinds.count("sliding_attention")
        model.attention.append(Attention(full, full * per_layer))
    else:
        full = kinds.count("full_attention")
        if full:
            model.attention.append(Attention(full, full * 2 * global_kv_heads * global_head_dim))
        sliding = kinds.count("sliding_attention")
        if sliding:
            model.attention.append(Attention(sliding, sliding * 2 * kv_heads * head_dim, window or 4096))

    recurrent = kinds.count("recurrent")
    if recurrent:
        if t.get("linear_num_value_heads"):
            # Gated DeltaNet (Qwen 3.5 family, Qwen3-Next)
            v_heads, k_heads = int(t["linear_num_value_heads"]), int(t.get("linear_num_key_heads") or 0)
            k_dim, v_dim = int(t.get("linear_key_head_dim") or 128), int(t.get("linear_value_head_dim") or 128)
            kernel = int(t.get("linear_conv_kernel_dim") or 4)
            model.ssm_elements = recurrent * v_heads * k_dim * v_dim
            model.conv_elements = recurrent * (2 * k_heads * k_dim + v_heads * v_dim) * (kernel - 1)
        elif t.get("mamba_num_heads") or t.get("mamba_n_heads"):
            # Mamba 2 (Nemotron-H, Granite 4)
            m_heads = int(t.get("mamba_num_heads") or t.get("mamba_n_heads"))
            m_dim = int(t.get("mamba_head_dim") or t.get("mamba_d_head") or 64)
            state = int(t.get("ssm_state_size") or t.get("mamba_d_state") or 128)
            groups = int(t.get("n_groups") or t.get("mamba_n_groups") or 1)
            kernel = int(t.get("conv_kernel") or t.get("mamba_d_conv") or 4)
            model.ssm_elements = recurrent * m_heads * m_dim * state
            model.conv_elements = recurrent * (m_heads * m_dim + 2 * groups * state) * (kernel - 1)
        else:
            model.rough = "a layer design the calculator doesn't know"
        ssm_dtype = str(t.get("mamba_ssm_dtype") or "float32")
        model.ssm_bytes = 2 if "16" in ssm_dtype else 4

    model.experts_total = int(t.get("num_experts") or t.get("num_local_experts") or t.get("n_routed_experts") or 0)
    model.experts_used = int(t.get("num_experts_per_tok") or t.get("top_k_experts") or 0)


def huggingface_safetensors(repo, snap, files):
    try:
        with open(os.path.join(snap, "config.json")) as f:
            config = json.load(f)
    except (OSError, ValueError):
        return Model(repo, "huggingface", "safetensors", "unknown", incomplete="config.json")
    quant, needs, bits, kv8 = quantization(config)
    model = Model(repo, "huggingface", "safetensors", quant, needs, kv8_by_makers=kv8, bits=bits)
    (model.weights, model.experts, model.params, vision,
     model.expert_params, model.table_params) = count_weights(snap, files, bits)
    model.text_params = model.params - vision
    model.file_id = snap
    vision = config.get("vision_config")
    model.vision = isinstance(vision, dict) or isinstance(config.get("vision_tower"), dict)
    if isinstance(vision, dict):
        model.vision_dynamic = "spatial_merge_size" in vision
        model.vision_layers = int(vision.get("num_hidden_layers") or 24)
        model.vision_width = int(vision.get("hidden_size") or 1024)
    q = config.get("quantization_config") or text_config(config).get("quantization_config") or {}
    model.quant_method = str(q.get("quant_method") or "")
    config_layout(model, config)
    names = " ".join(config.get("architectures") or []).lower()
    if any(word in names for word in ("embedding", "forsequenceclassification", "reward")):
        model.embedding = True
    return model


# --- GGUF ---

GGUF_SCALARS = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}


class GGUFReader:
    """Reads a GGUF file's header: its settings and the list of its tensors,
    without the tensors themselves. The file is mapped into memory rather
    than read, so skipping its long lists (the tokenizer's vocabulary) is quick."""

    def __init__(self, path):
        with open(path, "rb") as f:
            self.size = os.fstat(f.fileno()).st_size
            self.data = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        self.at = 0
        self.lengths = {}

    def read(self, fmt):
        value = struct.unpack_from("<" + fmt, self.data, self.at)[0]
        self.at += struct.calcsize(fmt)
        return value

    def string(self):
        length = struct.unpack_from("<Q", self.data, self.at)[0]
        self.at += 8 + length
        return self.data[self.at - length: self.at].decode("utf-8", "replace")

    def skip_strings(self, count):
        data, at, unpack = self.data, self.at, struct.unpack_from
        for _ in range(count):
            at += 8 + unpack("<Q", data, at)[0]
        self.at = at

    def value(self, kind, key=""):
        if kind == 8:
            return self.string()
        if kind == 9:
            item, count = self.read("I"), self.read("Q")
            self.lengths[key] = count
            if item == 8:
                # Long string lists are the tokenizer's vocabulary: skipped
                if count > 1024:
                    self.skip_strings(count)
                    return None
                return [self.string() for _ in range(count)]
            if count > 4096:
                self.at += struct.calcsize(GGUF_SCALARS[item]) * count
                return None
            return [self.value(item) for _ in range(count)]
        return self.read(GGUF_SCALARS[kind])

    def header(self):
        """(settings, [(name, number of elements, bytes)])"""
        try:
            if self.data[:4] != b"GGUF":
                raise ValueError("not a GGUF file")
            self.at = 4
            self.read("I")
            n_tensors, n_settings = self.read("Q"), self.read("Q")
            settings = {}
            for _ in range(n_settings):
                key = self.string()
                settings[key] = self.value(self.read("I"), key)
            settings["lengths"] = self.lengths
            infos = []
            for _ in range(n_tensors):
                name = self.string()
                dims = [self.read("Q") for _ in range(self.read("I"))]
                self.read("I")
                infos.append((self.read("Q"), name, math.prod(dims)))
        finally:
            self.data.close()
        align = int(settings.get("general.alignment") or 32)
        start = (self.at + align - 1) // align * align
        infos.sort()
        tensors = []
        for i, (offset, name, count) in enumerate(infos):
            end = infos[i + 1][0] if i + 1 < len(infos) else self.size - start
            tensors.append((name, count, end - offset))
        return settings, tensors


# Which layers slide, for architectures whose GGUF files don't say it because
# llama.cpp has it built in: every Nth layer keeps the whole conversation
BUILT_IN_SLIDING = {"gemma2": 2, "gemma3": 6, "gpt-oss": 2, "gptoss": 2, "cohere2": 4}
LAYER = re.compile(r"blk\.(\d+)\.([a-z_]+)")


def gguf_facts(model, paths):
    """Fills in a GGUF model's facts from the headers of all its parts"""
    settings, tensors = {}, []
    for path in paths:
        try:
            s, t = GGUFReader(path).header()
        except (OSError, ValueError, struct.error, KeyError):
            model.incomplete = "unreadable file"
            return
        settings = settings or s
        tensors += t
    arch = str(settings.get("general.architecture") or "")
    model.architecture = arch

    def get(key, default=None):
        value = settings.get(f"{arch}.{key}")
        return default if value is None else value

    output = any(name == "output.weight" for name, _, _ in tensors)
    for name, count, size in tensors:
        model.weights += size
        model.params += count
        if name.startswith(("v.", "mm.", "a.")):
            continue
        model.text_params += count
        if "_exps" in name:
            model.experts += size
            model.expert_params += count
        # The input lookup tables stay in PC memory. Without its own output
        # table, a model also uses the input one on the GPU, as a copy.
        if name == "per_layer_token_embd.weight" or (name == "token_embd.weight" and output):
            model.ram_only += size
        if name in ("per_layer_token_embd.weight", "token_embd.weight"):
            model.table_params += count
    model.vision = model.vision or any(name.startswith("v.") for name, _, _ in tensors)
    model.max_context = int(get("context_length", 0) or 0)
    model.vocab = int(get("vocab_size", 0) or settings.get("lengths", {}).get("tokenizer.ggml.tokens", 0))
    model.embedding = get("pooling_type") is not None

    n = int(get("block_count", 0) or 0) - int(get("nextn_predict_layers", 0) or 0)
    heads = get("attention.head_count", 1)
    kv_heads = get("attention.head_count_kv", heads)
    width = int(get("embedding_length", 0) or 0)
    first_heads = heads[0] if isinstance(heads, list) else heads
    k_len = int(get("attention.key_length", width // max(1, first_heads or 1)))
    v_len = int(get("attention.value_length", k_len))
    k_swa = int(get("attention.key_length_swa", k_len))
    v_swa = int(get("attention.value_length_swa", v_len))
    window = int(get("attention.sliding_window", 0) or 0)
    pattern = get("attention.sliding_window_pattern")
    interval = get("full_attention_interval")
    shared = int(get("attention.shared_kv_layers", 0) or 0)
    compress = get("attention.compress_ratios")
    has_ssm = get("ssm.state_size") is not None
    lora = get("attention.kv_lora_rank")

    if pattern is None and window:
        pattern = BUILT_IN_SLIDING.get(arch)

    # What each layer holds: a recurrent layer has ssm_ tensors (some name
    # their projections attn_qkv too), an attention layer attn_k, attn_kv or
    # attn_qkv, and a layer with neither is only a feed-forward one
    holds = {}
    for name, _, _ in tensors:
        if match := LAYER.match(name):
            holds.setdefault(int(match[1]), set()).add(match[2])

    full = sliding = recurrent = 0
    full_elements = sliding_elements = 0
    for i in range(max(0, n - shared)):
        layer_kv = kv_heads[i] if isinstance(kv_heads, list) and i < len(kv_heads) else kv_heads
        parts = holds.get(i, set())
        is_recurrent = any(p.startswith("ssm_") for p in parts)
        if parts:
            is_attention = any(p.startswith(("attn_k", "attn_kv")) for p in parts) \
                or ("attn_qkv" in parts and not is_recurrent)
        elif interval:
            is_attention = (i + 1) % int(interval) == 0
            is_recurrent = not is_attention and has_ssm
        else:
            is_attention, is_recurrent = True, False
        if is_recurrent:
            recurrent += 1
        if not is_attention or not layer_kv:
            continue
        if isinstance(pattern, list):
            is_sliding = bool(pattern[i]) if i < len(pattern) else False
        elif isinstance(pattern, int) and pattern > 1:
            is_sliding = i % pattern < pattern - 1
        else:
            is_sliding = False
        is_sliding = is_sliding and window > 0
        if lora:
            elements = int(lora) + int(get("rope.dimension_count", 64))
        elif is_sliding:
            elements = int(layer_kv) * (k_swa + v_swa)
        else:
            elements = int(layer_kv) * (k_len + v_len)
        if isinstance(compress, list) and i < len(compress) and compress[i]:
            elements //= int(compress[i])
        if is_sliding:
            sliding += 1
            sliding_elements += elements
        else:
            full += 1
            full_elements += elements
    if full:
        model.attention.append(Attention(full, full_elements))
    if sliding:
        model.attention.append(Attention(sliding, sliding_elements, window))
    if recurrent and has_ssm:
        inner, state = int(get("ssm.inner_size", 0)), int(get("ssm.state_size", 0))
        groups, kernel = int(get("ssm.group_count", 1) or 1), int(get("ssm.conv_kernel", 4))
        model.ssm_elements = recurrent * inner * state
        model.conv_elements = recurrent * (inner + 2 * groups * state) * (kernel - 1)

    model.experts_total = int(get("expert_count", 0) or 0)
    model.experts_used = int(get("expert_used_count", 0) or 0)
    model.file_id = os.path.realpath(paths[0]) if paths else ""
    model.bits = gguf_bits(model.quant, model.weights, model.params)
    if compress or get("attention.indexer.head_count") or get("hyper_connection.count"):
        model.rough = "a new design, so its memory per token is a rough estimate"
    elif recurrent and not has_ssm:
        model.rough = "a layer design the calculator doesn't know"


def gguf_bits(quant, size, params):
    """Bits per weight by a GGUF quantization's name: Q4_K_M and IQ4_XS are
    4, Q8_0 is 8, F16 is 16. Others by the file's size per parameter."""
    name = quant.upper()
    if name in ("F16", "BF16"):
        return 16
    if name == "F32":
        return 32
    if "FP4" in name:
        return 4
    if digit := re.search(r"(?:^|[^A-Z])I?Q(\d)", name):
        return int(digit[1])
    return max(1, round(size * 8 / params)) if params else 0


def gguf_files(snap):
    """The .gguf files in a download, relative to it, in order"""
    files = []
    for root, _, names in os.walk(snap, followlinks=True):
        files += [os.path.relpath(os.path.join(root, f), snap) for f in names if f.endswith(".gguf")]
    return sorted(files)


def huggingface_gguf(repo, snap, files):
    """One model per size in a GGUF download, named like llama.cpp names them:
    organization/model:size, e.g. unsloth/Qwen3.8-Flash-Next-GGUF:IQ4_XS
    (gguf_names.py has the rules)"""
    models = []
    for size, (parts, count) in sorted(gguf_names.by_size(files).items()):
        model = Model(f"{repo}:{size}", "huggingface", "gguf", size)
        if len(parts) < count:
            model.incomplete = "some parts"
        gguf_facts(model, [os.path.join(snap, p) for p in parts])
        if image := gguf_names.image_file(files, parts[0]):
            model.vision = True
            model.vision_file = os.path.getsize(os.path.join(snap, image))
        models.append(model)
    return models


def huggingface(hub=HUB_DIR, cache=None):
    models = []
    try:
        folders = sorted(f for f in os.listdir(hub) if f.startswith("models--"))
    except OSError:
        return models
    cache = cache or Cache()
    for folder in folders:
        snap = snapshot(os.path.join(hub, folder))
        if not snap:
            continue
        repo = folder[len("models--"):].replace("--", "/")
        top = sorted(f for f in os.listdir(snap) if f.endswith(".safetensors"))
        if top:
            paths = [os.path.join(snap, f) for f in ["config.json"] + top]
            models += cache.models(f"huggingface:{repo}", paths,
                                   lambda: [huggingface_safetensors(repo, snap, top)])
        ggufs = gguf_files(snap)
        if ggufs:
            models += cache.models(f"huggingface:{repo}:gguf", [os.path.join(snap, f) for f in ggufs],
                                   lambda: huggingface_gguf(repo, snap, ggufs))
    return models


def gguf_not_downloaded(hub=HUB_DIR, models_list=MODELS_LIST):
    """The organization/model:size lines in the downloader's models.txt whose
    size isn't downloaded. A size counts as there when a model file in its
    download names it, which is how llama.cpp finds it too."""
    missing = []
    try:
        with open(models_list) as f:
            lines = f.read().splitlines()
    except OSError:
        return missing
    for line in lines:
        # As sync_models.sh reads it: no comment or spaces, without GATED|
        line = "".join(line.split("#", 1)[0].split()).rsplit("|", 1)[-1]
        if ":" not in line:
            continue
        repo, size = line.split(":", 1)
        snap = snapshot(os.path.join(hub, "models--" + repo.replace("/", "--")))
        valid = re.fullmatch(r"[A-Za-z0-9_-]+", size)
        if not (valid and snap and gguf_names.first_part(gguf_files(snap), size)):
            missing.append(line)
    return missing


# --- Ollama ---

def ollama_name(relative):
    """registry.ollama.ai/library/qwen3.6/35b -> qwen3.6:35b, and
    registry.ollama.ai/agent/qwen3.6/35b -> agent/qwen3.6:35b"""
    parts = relative.split("/")
    if len(parts) < 3:
        return relative
    host, *path, tag = parts
    if host == "registry.ollama.ai":
        if path and path[0] == "library":
            path = path[1:]
        return "/".join(path) + ":" + tag
    return host + "/" + "/".join(path) + ":" + tag


def ollama(folder=OLLAMA_DIR, cache=None):
    models = []
    cache = cache or Cache()
    manifests = os.path.join(folder, "manifests")
    for root, _, files in os.walk(manifests):
        for file_name in sorted(files):
            path = os.path.join(root, file_name)
            name = ollama_name(os.path.relpath(path, manifests))
            # A manifest names its files by their contents, so it changes
            # whenever any of them does
            models += cache.models(f"ollama:{name}", [path],
                                   lambda: ollama_model(folder, path, name))
    models.sort(key=lambda m: m.name)
    return models


def ollama_model(folder, path, name):
    """[the model a manifest describes], or [] when it can't be read"""
    try:
        with open(path) as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        return []
    def blob(digest):
        return os.path.join(folder, "blobs", digest.replace(":", "-"))

    config = {}
    if manifest.get("config", {}).get("digest"):
        try:
            with open(blob(manifest["config"]["digest"])) as f:
                config = json.load(f)
        except (OSError, ValueError):
            pass
    model = Model(name, "ollama", "gguf", str(config.get("file_type") or "GGUF"))
    weights = None
    for layer in manifest.get("layers", []):
        kind = layer.get("mediaType", "").rsplit(".", 1)[-1]
        if kind == "model":
            weights = blob(layer["digest"])
            model.base = layer.get("from", "")
        elif kind == "projector":
            model.vision = True
            model.vision_file += int(layer.get("size") or 0)
        elif kind == "params":
            try:
                with open(blob(layer["digest"])) as f:
                    model.ollama_context = int(json.load(f).get("num_ctx") or 0)
            except (OSError, ValueError, AttributeError):
                pass
    if not weights or not os.path.exists(weights):
        model.incomplete = "its model file"
    else:
        gguf_facts(model, [weights])
    if model.quant == "unknown":
        model.quant = "GGUF"
    return [model]


# --- Which files are the same model ---

# Words in a model's name that say how the file is stored, not which model it
# is: unsloth/Qwen3.6-35B-A3B-NVFP4 and Ollama's qwen3.6:35b are one model
FORMAT_WORDS = {"gguf", "nvfp4", "mxfp4", "fp4", "fp8", "fp16", "bf16", "f16", "awq", "gptq", "int4",
                "int8", "w4a16", "w8a8", "exl2", "exl3", "mlx", "it", "instruct", "latest", "ud"}
GGUF_SIZE_WORD = re.compile(r"(ud-)?i?q\d(_[a-z0-9]+)*|f32|tq\d_\d")
ACTIVE_WORD = re.compile(r"a\d+(\.\d+)?b")


def name_words(model):
    """The words of a model's own name, without its publisher or namespace"""
    name = model.name
    if name.startswith("hf.co/"):
        name = name.split("/", 2)[-1]
    elif "/" in name:
        name = name.split("/", 1)[1]
    return [w for w in re.split(r"[-:\s]+", name) if w]


def same_model_key(model):
    """The same for every file of one model, in any format or size:
    "qwen3.6 35b" for both unsloth/Qwen3.6-35B-A3B-NVFP4 and qwen3.6:35b.
    A lone version number joins the word before it (gemma-4 is gemma4)."""
    words = []
    for word in name_words(model):
        word = word.lower()
        if word in FORMAT_WORDS or GGUF_SIZE_WORD.fullmatch(word) or ACTIVE_WORD.fullmatch(word):
            continue
        for part in word.split("_"):
            if words and re.fullmatch(r"\d+(\.\d+)?", part) and words[-1].isalpha():
                words[-1] += part
            elif part:
                words.append(part)
    return " ".join(words)


def display_name(model):
    """A model's name for people: the Hugging Face name without its publisher
    and format words (Qwen3.6-35B-A3B), or Ollama's own name (qwen3.6:35b),
    the one Open WebUI lists"""
    if model.source == "ollama":
        return model.name
    words = [w for w in name_words(model)
             if w.lower() not in FORMAT_WORDS and not GGUF_SIZE_WORD.fullmatch(w.lower())]
    return "-".join(words) or model.name


def named_size(model):
    """The parameters a model's name gives, in billions: 35 for
    Qwen3.6-35B-A3B and for qwen3.6:35b, or 0 when it gives none"""
    for word in same_model_key(model).split():
        if match := re.fullmatch(r"(\d+(?:\.\d+)?)b", word):
            return float(match[1])
    return 0


def all_models(sources=("huggingface", "ollama")):
    cache = Cache()
    models = []
    if "huggingface" in sources:
        models += huggingface(cache=cache)
    if "ollama" in sources:
        models += ollama(cache=cache)
    cache.save()
    return models


# --- Showing it ---

def describe(model):
    gib = 1024 ** 3
    per_token = sum(a.elements for a in model.attention if not a.window) * 2
    sliding = sum(a.elements for a in model.attention if a.window) * 2
    text = (f"{model.name}  [{model.source} {model.format} {model.quant}]  "
            f"{model.weights / gib:.1f} GB, {model.text_params / 1e9:.1f}B params, "
            f"max {model.max_context // 1024}k, {per_token // 1024} KB/token")
    if sliding:
        text += f" + {sliding // 1024} KB/token in a {model.attention[-1].window}-token window"
    if model.ssm_elements:
        state = model.ssm_elements * model.ssm_bytes + model.conv_elements * 2
        text += f" + {state / 1024 ** 2:.0f} MB state per conversation"
    if model.experts_total:
        text += f", MoE {model.experts_used}/{model.experts_total} experts ({model.experts / gib:.1f} GB)"
    if model.ram_only:
        text += f", {model.ram_only / gib:.1f} GB lookup tables"
    for flag, label in ((model.vision, "reads images"), (model.kv8_by_makers, "8-bit memory by its makers"),
                        (model.embedding, "embedding model"), (model.rough, model.rough),
                        (model.incomplete, f"missing: {model.incomplete}"),
                        (model.ollama_context, f"num_ctx {model.ollama_context}")):
        if flag:
            text += f", {label}"
    return text


def gguf_lines():
    """For llama.cpp's list_models: its GGUF downloads, then the models.txt
    lines that aren't downloaded"""
    lines = []
    for model in all_models(("huggingface",)):
        if model.format == "gguf":
            note = "incomplete" if model.incomplete else "reads images" if model.vision else ""
            lines.append(f"{model.name}\t{model.weights / 1024 ** 3:.1f} GB\t{note}")
    lines += [f"not downloaded\t{line}" for line in gguf_not_downloaded()]
    return lines


def main():
    if sys.argv[1:] == ["--gguf"]:
        print("\n".join(gguf_lines()))
        return
    models = all_models()
    if sys.argv[1:] == ["--json"]:
        print(json.dumps([dataclasses.asdict(m) for m in models], indent=2))
    elif sys.argv[1:]:
        print(__doc__.split("\n\n")[3], file=sys.stderr)
        sys.exit(1)
    else:
        for model in models:
            print(describe(model))


if __name__ == "__main__":
    main()
