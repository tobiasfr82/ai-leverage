# Ollama

The everyday engine: easy model switching, and several models on one GPU. On this PC it
answers at `http://localhost:11434`; other containers use `http://ollama:11434`.

## Two kinds of models

```text
models.txt   downloaded from ollama.com or Hugging Face: the model itself
specs/       recipes built on this PC from a downloaded model: settings only

gemma4:31b ──────────┬──► icm-crew/gemma4:31b       ICM system prompt, 32k, low temperature
                     └──► agent/gemma4:31b          128k context, for agents
qwen3-coder:30b ─────┬──► icm-crew/qwen3-coder:30b
                     └──► agent/qwen3-coder:30b     128k context, for agents
qwen3.6:35b ─────────────► agent/qwen3.6:35b        256k context, for long agent tasks
qwen3-embedding:8b ──────► rag/qwen3-embedding:8b   8k context, Open WebUI's document search
```

- **A spec model takes no extra disk space.** It reuses its base model's files and only adds
  settings: context size, temperature, a system prompt.
- **It cannot be downloaded,** because it only exists as a recipe in `specs/`.
  **ollama → sync_models** builds every spec after the downloads, and fetches a spec's base
  model even if `models.txt` doesn't list it.
- **Don't list spec models in `models.txt`.** `sync_models` knows them from `specs/` and
  never offers to delete them or the models they are built on.

### Naming

The file name decides the model name: `namespace_model-size.model` becomes
`namespace/model:size`. The namespace says what the model is for.

| File in `specs/`               | Model in Ollama            |
| ------------------------------ | -------------------------- |
| `agent_qwen3-coder-30b.model`  | `agent/qwen3-coder:30b`    |
| `rag_qwen3-embedding-8b.model` | `rag/qwen3-embedding:8b`   |

`./build_specs.sh --dry-run` shows the names without building anything.

## Context: how much text a model keeps in mind

| Models                      | Context                            | Use for                          |
| --------------------------- | ---------------------------------- | -------------------------------- |
| Everything in `models.txt`  | Chosen by Ollama from your VRAM: 32k on a 32 GB card | Chat, and chats about documents |
| `agent/gemma4:31b`, `agent/qwen3-coder:30b` | 128k               | Hermes Agent, VS Code agent mode |
| `agent/qwen3.6:35b`         | 256k                               | Agent tasks that need more       |

Ollama reserves a model's whole context as soon as it loads it, so a bigger context costs
VRAM even for a short question. That is why only the `agent/` models get a large one, and
why 256k is only on Qwen3.6: its design keeps that memory small. Gemma4 and qwen3-coder
would spill into slower system memory at 256k on a 32 GB card.

Agents reach Ollama at `http://localhost:11434/v1`. That address cannot ask for a context
size, so the size is set in the spec, and **you tell the agent the same number**: 131072
for 128k, 262144 for 256k. Otherwise the agent may assume the model's maximum, overfill
the context, and Ollama silently drops the start of the conversation, including the
agent's own instructions.

The sizes in `specs/` fit a 32 GB RTX 5090 with `OLLAMA_KV_CACHE_TYPE=q8_0`
(see `.env.template`). On a smaller card, lower `PARAMETER num_ctx` in the spec.

## Scripts

| Script           | What it does                                                          |
| ---------------- | --------------------------------------------------------------------- |
| `sync_models.sh` | Makes Ollama match `models.txt`, then builds everything in `specs/`   |
| `build_specs.sh` | Builds only the specs (`--dry-run` to preview)                        |
