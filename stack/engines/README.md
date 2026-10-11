# Engines

Run the models. Each engine reads the models a downloader put in `models/`, and answers the
services over the shared `ai-leverage` network.

| Engine    | Runs models from     | Other containers use  | This PC                    |
| --------- | -------------------- | --------------------- | -------------------------- |
| `ollama/` | `models/ollama`      | `http://ollama:11434` | `http://localhost:11434`   |
| `vllm/`   | `models/huggingface` | `http://vllm:8000/v1` | `http://localhost:8000/v1` |

The engines share the GPU. vLLM claims most of its memory when it starts, so stop it while
you use Ollama's larger models; see [Hardware](../../README.md#-hardware).
