#!/usr/bin/env python3
"""ai-leverage/stack/engines/vllm/chat_format.py

Works out how a model writes its tool calls and its thinking, from the chat
template that came with its download, and names vLLM's setting for each.
vLLM needs both named before it accepts chats that offer tools, as Open WebUI's
do, and unlike SGLang it can't work them out itself.

Two uses:
  python3 -I chat_format.py <org/model> [hub folder]
      says what it found (set_model.sh shows it when you pick a model)
  python3 -I chat_format.py --serve <org/model> [vllm serve options...]
      what vLLM's container runs: "vllm serve" with the settings added.
      A setting already among the options, e.g. from VLLM_EXTRA_ARGS in .env,
      is left as it is.
The hub folder defaults to HF_HUB_CACHE, where the container finds the models.
"""

import json
import os
import sys

# How families mark their tool calls in the chat template, each checked against
# real downloads, and vLLM's name for that format. The first match wins, so a
# marker that's part of a longer one comes after it: Qwen 3.5 writes
# <tool_call><function=...>, older Qwens <tool_call>{json}.
TOOL_FORMATS = [
    (["<function="], "qwen3_coder", "Qwen 3.5 / Qwen3-Coder style"),
    (["<|tool_call>"], "gemma4", "Gemma 4 style"),
    (["<|channel|>"], "openai", "gpt-oss style"),
    (["<tool_call>"], "hermes", "Qwen3 / Qwen2.5 / Hermes style"),
]

# The same for thinking. gpt-oss's needs no setting: vLLM splits it off by itself.
THINKING_FORMATS = [
    (["<|channel>"], "gemma4", "Gemma 4 style"),
    (["<|channel|>"], None, "gpt-oss style, which vLLM splits off by itself"),
    (["<think>", "<｜Assistant｜>"], "deepseek_r1", "DeepSeek R1 style"),
    (["<think>"], "qwen3", "in <think> tags"),
]


def snapshot(model, hub):
    """The folder of the download's current version, as the engines load it"""
    folder = os.path.join(hub, "models--" + model.replace("/", "--"))
    try:
        with open(os.path.join(folder, "refs", "main")) as ref:
            return os.path.join(folder, "snapshots", ref.read().strip())
    except OSError:
        return None


def chat_template(snap):
    """All the chat template text a download has, wherever it keeps it"""
    texts = []
    try:
        with open(os.path.join(snap, "chat_template.jinja"), encoding="utf-8") as f:
            texts.append(f.read())
    except OSError:
        pass
    for name in ("chat_template.json", "tokenizer_config.json"):
        try:
            with open(os.path.join(snap, name), encoding="utf-8") as f:
                template = json.load(f).get("chat_template")
        except (OSError, ValueError, AttributeError):
            continue
        # Either one template, or a list of named ones
        if isinstance(template, str):
            texts.append(template)
        elif isinstance(template, list):
            texts.extend(t.get("template", "") for t in template if isinstance(t, dict))
    return "\n".join(texts)


def match(template, formats):
    for markers, setting, description in formats:
        if all(marker in template for marker in markers):
            return setting, description
    return None, None


def detect(model, hub):
    """(tool setting, its description, thinking setting, its description), or
    None when the download has no chat template to read"""
    snap = snapshot(model, hub)
    template = chat_template(snap) if snap else ""
    if not template:
        return None
    return match(template, TOOL_FORMATS) + match(template, THINKING_FORMATS)


def describe(found):
    tool, tool_text, thinking, thinking_text = found
    lines = []
    if tool:
        lines.append(f"Tool calls: {tool_text} ({tool})")
    else:
        lines.append("Tool calls: no format vLLM knows in its chat template, so chats that offer "
                     "tools (Open WebUI's do) fail. Name one in VLLM_EXTRA_ARGS in .env, "
                     "as the model's page says.")
    if thinking:
        lines.append(f"Thinking: {thinking_text} ({thinking}), shown apart from the answer")
    elif thinking_text:
        lines.append(f"Thinking: {thinking_text}")
    else:
        lines.append("Thinking: none marked, so any thinking stays part of the answer")
    return lines


def given(options, name):
    return any(o == name or o.startswith(name + "=") for o in options)


def serve(args):
    model, options = args[0], args[1:]
    hub = os.environ.get("HF_HUB_CACHE", "/models/huggingface/hub")
    found = detect(model, hub)
    added = []
    if found is None:
        print(f"ai-leverage: {model} has no chat template to read, so vLLM starts without "
              "tool calls and thinking.", flush=True)
    else:
        tool, _, thinking, _ = found
        for line in describe(found):
            print(f"ai-leverage: {line}", flush=True)
        if tool and not given(options, "--tool-call-parser"):
            added += ["--enable-auto-tool-choice", "--tool-call-parser", tool]
        if thinking and not given(options, "--reasoning-parser"):
            added += ["--reasoning-parser", thinking]
        if given(options, "--tool-call-parser") or given(options, "--reasoning-parser"):
            print("ai-leverage: VLLM_EXTRA_ARGS names its own, which win over the above.", flush=True)
    os.execvp("vllm", ["vllm", "serve", model, *options, *added])


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--serve":
        serve(sys.argv[2:])
    if len(sys.argv) not in (2, 3) or sys.argv[1].startswith("-"):
        print(__doc__.split("\n\n")[2], file=sys.stderr)
        sys.exit(1)
    hub = sys.argv[2] if len(sys.argv) == 3 else os.environ.get("HF_HUB_CACHE", "")
    found = detect(sys.argv[1], hub)
    if found is None:
        print("No chat template in this download, so vLLM can't chat with it.")
        sys.exit(1)
    print("\n".join(describe(found)))


if __name__ == "__main__":
    main()
