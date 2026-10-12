# Hugging Face

Downloads the models vLLM and SGLang serve into the shared `models/huggingface` folder at
the top of the repo. Both engines read that same folder, so a model downloaded here shows up
in their `set_model.sh` (menu: **vllm → set_model** and **sglang → set_model**).

| Script             | What it does                                                   |
| ------------------ | -------------------------------------------------------------- |
| `sync_models.sh`   | Downloads every model in `models.txt`. Re-runs skip what is already there. |
| `check_health.sh`  | Lists the downloaded models and their size.                    |

Both run through [uv](https://docs.astral.sh/uv/), which `bootstrap.sh` installs. uv sets
up the right Python version and the `hf` tool on first use.

## models.txt

One model per line, as `organization/model` from its huggingface.co address. Mark models
that need an access token with `GATED|`:

```text
cyankiwi/Qwen3.8-27B-AWQ-INT4
GATED|meta-llama/Llama-3.1-8B-Instruct
```

The list in the repo fits a 32 GB GPU. Trim it to what your GPU can hold before the first
sync: a model roughly needs its download size in VRAM, plus room for the conversation.
GGUF models belong in Ollama's list instead, `stack/downloaders/ollama/models.txt`.

## What gets downloaded

A whitelist decides which of a model's files are downloaded, and everything else is
skipped. By default that is the weights in `.safetensors` format plus the small files an
engine needs: the model's settings (`config.json`), its tokenizer and its chat template.
Skipped are older weight formats that can run code when they are opened (`.bin`, `.pth`),
the model's own Python code, GGUF files, READMEs and images.

`HF_INCLUDE` in `.env` replaces the whitelist; see `.env.template`.

## Gated models

Some models need you to accept their terms on huggingface.co first. Then create an access
token and put it in a local `.env`:

```bash
cp .env.template .env    # then set HF_TOKEN=... in .env
```

Without a token, `sync_models.sh` skips gated models and says so at the end.
