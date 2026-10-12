# Downloaders

Get models onto this PC. Each folder here downloads the models in its `models.txt` into the
shared `models/` folder at the top of the repo, in a subfolder with its own name, and the
engines read them from there.

| Downloader     | Downloads into       | Read by                                            |
| -------------- | -------------------- | -------------------------------------------------- |
| `huggingface/` | `models/huggingface` | vLLM and SGLang (`.safetensors`), llama.cpp (GGUF) |
| `ollama/`      | `models/ollama`      | Ollama                                             |

In `manage.sh`, each one has a **sync_models** entry that downloads what its `models.txt`
lists and skips what is already there. A downloader works on its own: no engine needs to
run while it downloads.
