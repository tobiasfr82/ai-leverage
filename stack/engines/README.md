# Engines

Run the models. Each engine reads the models a downloader put in `models/`, and answers the
services over the shared `ai-leverage` network.

| Engine    | Runs models from     | Other containers use     | This PC                     |
| --------- | -------------------- | ------------------------ | --------------------------- |
| `ollama/` | `models/ollama`      | `http://ollama:11434`    | `http://localhost:11434`    |
| `vllm/`   | `models/huggingface` | `http://vllm:8000/v1`    | `http://localhost:8000/v1`  |
| `sglang/` | `models/huggingface` | `http://sglang:30000/v1` | `http://localhost:30000/v1` |

The engines share the GPU. vLLM and SGLang each claim most of its memory when they start,
so run only one of them at a time, and stop it while you use Ollama's larger models; see
[Hardware](../../README.md#-hardware).

## vLLM and SGLang run only what is downloaded

Both read `models/huggingface` read-only and never go online, so they can't change your
downloads and every file in there stays yours. In exchange, a model only runs once
**downloaders → huggingface → sync_models** has fetched all of it. Their **set_model**
shows what to do: it lists models from `models.txt` that aren't downloaded yet, and marks a
download that lacks something, for example `(missing: chat template)`. Run sync_models to
fetch it.
