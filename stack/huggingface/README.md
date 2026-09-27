# Hugging Face

Downloads the models vLLM serves into the shared `models/huggingface` folder at the top
of the repo. vLLM reads that same folder, so a model downloaded here shows up in
`stack/vllm/set_model.sh`.

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
Qwen/Qwen3.6-27B-FP8
GATED|google/gemma-4-31B-it
```

The list in the repo fits a 32 GB GPU. Trim it to what your GPU can hold before the first
sync: a model roughly needs its download size in VRAM, plus room for the conversation.

## Gated models

Some models need you to accept their terms on huggingface.co first. Then create an access
token and put it in a local `.env`:

```bash
cp .env.template .env    # then set HF_TOKEN=... in .env
```

Without a token, `sync_models.sh` skips gated models and says so at the end.
