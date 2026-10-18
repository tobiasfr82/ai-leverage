# Hugging Face

Downloads the models vLLM, SGLang and llama.cpp run into the shared `models/huggingface`
folder. All three engines read that same folder, and each one only picks out the kind of
model it can run:

- **vLLM and SGLang** run models in `.safetensors` format. A model downloaded for them
  shows up in their `set_model.sh` (menu: **vllm → Set model** and **sglang → Set model**).
- **llama.cpp** runs models in GGUF format. A model downloaded for it shows up in Open WebUI
  and in **llamacpp → List models**, after a Restart of llama.cpp.

| Script             | What it does                                                   |
| ------------------ | -------------------------------------------------------------- |
| `sync_models.sh`   | Downloads every model in `models.txt`. Re-runs skip what is already there. |
| `check_health.sh`  | Lists the downloaded models and their size.                    |

Both run through [uv](https://docs.astral.sh/uv/), which `bootstrap.sh` installs. uv sets
up the right Python version and the `hf` tool on first use. `gguf_files.py` is a helper
that `sync_models.sh` uses, not a menu entry.

## models.txt

One model per line, from its huggingface.co address. There are two kinds of lines:

```text
cyankiwi/Qwen3.8-27B-AWQ-INT4            # the .safetensors model, for vLLM and SGLang
unsloth/gpt-oss-120b-GGUF:Q4_K_M         # one size of a GGUF model, for llama.cpp
GATED|meta-llama/Llama-3.1-8B-Instruct   # a model that needs an access token
```

**Why GGUF lines name a size:** a `.safetensors` model's page holds one version of the
model; other versions have pages of their own. A GGUF model's page holds a dozen sizes of
the same model instead: `unsloth/gpt-oss-120b-GGUF` has 15, about 1,010 GB in all, while
the `Q4_K_M` one is 63 GB. The size is the last part of the file names, and it is also the
name llama.cpp and Open WebUI show, e.g. `unsloth/gpt-oss-120b-GGUF:Q4_K_M`. `Q4_K_M` is
the usual choice; `Q8_0` is better and nearly twice as big. A size that doesn't exist fails
with a list of the ones that do:

```text
unsloth/gpt-oss-120b-GGUF has no size Q4_K_Z. Its sizes: Q2_K, Q2_K_L, Q3_K_M, ...
```

A GGUF model listed without a size gets a note in the same way, because vLLM and SGLang
can't run it.

The `.safetensors` models in the repo's list fit a 32 GB GPU. Trim the list to what your GPU
can hold before the first sync: such a model roughly needs its download size in VRAM, plus
room for the conversation. GGUF models can be bigger than the GPU, because llama.cpp keeps
what doesn't fit in the PC's memory; see
[the llama.cpp README](../../engines/llamacpp/README.md).

## What gets downloaded

For a line without a size, a whitelist decides which of a model's files are downloaded, and
everything else is skipped. By default that is the weights in `.safetensors` format plus the
small files an engine needs: the model's settings (`config.json`), its tokenizer and its chat
template. Skipped are older weight formats that can run code when they are opened (`.bin`,
`.pth`), the model's own Python code, GGUF files, READMEs and images. `HF_INCLUDE` in `.env`
replaces the whitelist; see `.env.template`.

For a line with a size, only the files of that size are downloaded, picked the way llama.cpp
picks them: every part of a model that is split into several files, plus the file that lets
the model read images, if it has one. A GGUF file carries the model's tokenizer and chat
template inside, so nothing else is needed.

## Gated models

Some models need you to accept their terms on huggingface.co first. Then create an access
token and put it in a local `.env`:

```bash
cp .env.template .env    # then set HF_TOKEN=... in .env
```

Without a token, `sync_models.sh` skips gated models and says so at the end.
