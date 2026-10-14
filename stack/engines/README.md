# Engines

Run the models. Each engine reads the models a downloader put in `models/`, and answers the
services over the shared `ai-leverage` network.

| Engine      | Runs models from                      | Other containers use      | This PC                     |
| ----------- | ------------------------------------- | ------------------------- | --------------------------- |
| `ollama/`   | `models/ollama`                       | `http://ollama:11434`     | `http://localhost:11434`    |
| `vllm/`     | `models/huggingface` (`.safetensors`) | `http://vllm:8000/v1`     | `http://localhost:8000/v1`  |
| `sglang/`   | `models/huggingface` (`.safetensors`) | `http://sglang:30000/v1`  | `http://localhost:30000/v1` |
| `llamacpp/` | `models/huggingface` (GGUF)           | `http://llamacpp:8080/v1` | `http://localhost:8080`     |

Which one to use:

- **Ollama** for everyday use: easy model switching, many models.
- **vLLM or SGLang** for speed, with one model that fits the GPU. Some models run better on
  one, some on the other.
- **llama.cpp** for models bigger than the GPU: what doesn't fit stays in the PC's memory.
  It switches models like Ollama, from Open WebUI's model list.

The engines share the GPU. vLLM and SGLang each claim most of its memory when they start,
so run only one of them at a time, and stop it while you use Ollama's larger models or
llama.cpp. llama.cpp takes what is free when it loads a model and unloads it after 30
minutes without a chat; see [Hardware](../../README.md#-hardware).

## vLLM, SGLang and llama.cpp run only what is downloaded

All three read `models/huggingface` read-only and never go online, so they can't change
your downloads and every file in there stays yours. In exchange, a model only runs once
**downloaders → huggingface → sync_models** has fetched all of it. Each one picks out the
kind of model it can run, so they share the folder without seeing each other's models.

- vLLM's and SGLang's **set_model** shows what to do: it lists models from `models.txt` that
  aren't downloaded yet, and marks a download that lacks something, for example
  `(missing: chat template)`. Run sync_models to fetch it.
- llama.cpp's **list_models** does the same for GGUF models. Restart llama.cpp after a
  download, because it reads its list of models when it starts.

## Tool calls and thinking

Open WebUI offers every model tools, so an engine has to know how the model writes a tool
call, and how it marks its thinking to show it apart from the answer. Ollama, SGLang and
llama.cpp work this out themselves. vLLM can't, so its container starts through
`vllm/chat_format.py`, which reads the model's chat template and starts vLLM with the
matching settings. Its log says what it found, and **set_model** says it when you pick a
model:

```text
ai-leverage: Tool calls: Qwen 3.5 / Qwen3-Coder style (qwen3_coder)
ai-leverage: Thinking: in <think> tags (qwen3), shown apart from the answer
```

It knows the Qwen 3.5 family (Qwen3.6, Qwen3.8, Ornith), Qwen3 and Qwen2.5, Hermes,
Gemma 4, gpt-oss and DeepSeek R1. These are families, not single models, so their
fine-tunes and quantized versions come along. For a model it doesn't know, it says so, and
`VLLM_EXTRA_ARGS` in `vllm/.env` can name the format the model's page gives, for example
`--enable-auto-tool-choice --tool-call-parser mistral`. Settings named there always win.
A new family is one line in `chat_format.py`.
