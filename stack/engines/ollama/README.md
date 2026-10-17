# Ollama

The everyday engine: easy model switching, and several models on one GPU. On this PC it
answers at `http://localhost:11434`; other containers use `http://ollama:11434`.

It runs the models in the shared `models/ollama` folder at the top of the repo. To add or
remove models, edit the list in [stack/downloaders/ollama](../../downloaders/ollama) and run
**Models › Downloaders › ollama → sync_models**. That works whether this engine runs or not,
and a running engine picks up each new model straight away.

## Settings

Everything is optional; see `.env.template`. Without a `.env`, Ollama sizes itself to your
GPU, for example 32k tokens of context on a 32 GB card.

The `agent/...` models have a larger context of their own, set in their specs. Agents reach
Ollama at `http://localhost:11434/v1` and must be told that size: see
[Context](../../downloaders/ollama/README.md#context-how-much-text-a-model-keeps-in-mind).
