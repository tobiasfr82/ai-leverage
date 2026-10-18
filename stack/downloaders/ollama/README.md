# Ollama models

Downloads the Ollama engine's models into the shared `models/ollama` folder and builds the
custom ones in `specs/`. The engine itself is in [stack/engines/ollama](../../engines/ollama).

## How it downloads

Ollama can only download its models through Ollama itself. So **Models › Downloaders › Ollama → Sync models** starts a temporary Ollama of its own, just for downloading:

- **It gets no GPU and no open port,** so it never takes memory from an engine that runs,
  for example vLLM while Hermes works with it.
- **It saves into `models/ollama`,** the folder the engine runs its models from. The engine
  sees each finished model straight away, and if it was stopped, it stays stopped.
- **It is removed when the sync ends.**

Ollama checks every file it downloads (`verifying sha256 digest` in the output) and then
records the finished model (`writing manifest`). The temporary Ollama does all of that
itself, so nothing is left for the engine to do.

Sync models runs as a notification in the menu, with its progress there. A model that's
downloaded but no longer in `models.txt`: before downloading anything, the sync asks
whether to delete it. Its notification turns blue and waits; open it (a click, or Enter)
and answer under its log. Run in a terminal (`./sync_models.sh`), it asks there.
**Models › Downloaders › Ollama → Remove unlisted models** asks the same and downloads
nothing. Where nobody can answer, the sync keeps such models and names them at the end.

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
  **Models › Downloaders › Ollama → Sync models** builds every spec after the downloads, and
  fetches a spec's base model even if `models.txt` doesn't list it.
- **Don't list spec models in `models.txt`.** Sync models knows them from `specs/`, and
  neither it nor Remove unlisted models ever offers to delete them or the models they are
  built on.

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

The sizes in `specs/` fit a 32 GB RTX 5090 with `OLLAMA_KV_CACHE_TYPE=q8_0` (see the
engine's [.env.template](../../engines/ollama/.env.template)). On a smaller card, lower
`PARAMETER num_ctx` in the spec.

## Scripts

| Script                | What it does                                                          |
| --------------------- | --------------------------------------------------------------------- |
| `sync_models.sh`      | Makes `models/ollama` match `models.txt`, then builds everything in `specs/` |
| `build_specs.sh`      | Builds only the specs (`--dry-run` to preview)                        |
| `temporary_ollama.sh` | The temporary Ollama both scripts download with. Not a menu entry      |
