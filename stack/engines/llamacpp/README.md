# llama.cpp

The engine for models bigger than the GPU. It runs models in GGUF format, and what doesn't
fit in the GPU's memory stays in the PC's memory. That works best for MoE models, which use
only a few of their parts, their "experts", for each word: gpt-oss 120B, about twice the
size of a 32 GB GPU, still runs at a usable speed.

It picks models the way Ollama does: it lists every GGUF model the Hugging Face downloader
fetched, and loads the one you choose in Open WebUI. On this PC it answers at
`http://localhost:8080`, which is also its own chat page; other containers use
`http://llamacpp:8080/v1`.

## First start

1. Add a GGUF model to `stack/downloaders/huggingface/models.txt`, as
   `organization/model:size`. The list has examples: remove the `#` in front of
   `unsloth/gemma-4-E4B-it-GGUF:Q4_K_M` (6 GB) for a first test. Then run
   **Models › Downloaders › Huggingface → Sync models**.
2. Start **engines → llamacpp**. The very first start downloads llama.cpp itself (about
   2.6 GB) once.
3. In Open WebUI, pick the model, e.g. `unsloth/gemma-4-E4B-it-GGUF:Q4_K_M`, and chat. The
   first message loads the model: seconds for a small one, a minute or two for a big one.
   Follow it in **llamacpp → View logs**.

**llamacpp → List models** shows the models llama.cpp can run, and the GGUF lines in
`models.txt` that aren't downloaded yet. llama.cpp reads its list when it starts, so
**Restart** it after downloading a new model.

## Using it in Open WebUI

An Open WebUI installed after llama.cpp arrived in this repo is already connected. If your
Open WebUI was set up before, it keeps its own list of connections, so add llama.cpp to it
once:

1. Open WebUI → **Admin Panel → Settings → Connections**
2. Next to **OpenAI API**, click **+** (Add Connection)
3. URL: `http://llamacpp:8080/v1`. Leave the key empty: llama.cpp doesn't check it, so if
   Open WebUI insists on one, type anything. Connection type: **Local**. API type: **Chat
   Completions**, the default.
4. Save.

Open WebUI then lists every GGUF model llama.cpp found. Only one is loaded at a time:
picking another one unloads the one before. The connection can stay when llama.cpp is
stopped: Open WebUI then just doesn't list its models.

## How it shares the GPU and the PC's memory

Each time it loads a model, llama.cpp looks at how much GPU memory is free right then, and
fills it in this order:

```text
GPU  [ conversation memory | the parts every word needs | as much of the rest as fits | 4 GB free ]
PC   [ the rest of the model ]
```

What that means for you:

- **A model that fits on the GPU runs entirely there.** A bigger one runs with part of it
  in the PC's memory. That is slower, but much less so for MoE models such as gpt-oss or
  Qwen's "A3B" models, whose experts are what goes to the PC's memory.
- **The conversation length is fixed**, at 65,536 tokens by default (`CONTEXT_SIZE` in
  `.env`). llama.cpp doesn't shorten it to squeeze a model in; it moves more of the model to
  the PC's memory instead. A model whose own maximum is lower gets its maximum. If a model
  can't load at all, lower `CONTEXT_SIZE`.
- **It leaves 4 GB of the GPU free** for Docling and Open WebUI's document search, which use
  the GPU too (`VRAM_KEEP_FREE`).
- **It works with what is free at that moment.** If vLLM, SGLang or a big Ollama model holds
  the GPU, llama.cpp puts more in the PC's memory and runs slower. Stop them first for full
  speed.
- **After 30 minutes without a chat, it unloads the model** and frees the GPU for the other
  engines (`IDLE_UNLOAD_SECONDS`). The next chat loads it again.

To see where a model went, open **llamacpp → View logs** while it loads. The lines with
`llama_params_fit` say how much GPU memory the model needed, how much was free, and how many
of its layers "overflow" to the PC's memory. To decide that yourself, see `--n-cpu-moe` in
`.env.template`.

## Its own chat page

`http://localhost:8080` opens llama.cpp's own chat page: simpler than Open WebUI, and handy to
try a model quickly. Like the rest of llama.cpp it has no login, so only this PC can open it.

## How it is locked down

- **It only runs models you already downloaded.** It never goes online for a model, and it
  sees `models/huggingface` read-only, so it cannot change or delete anything in it, the
  same as vLLM and SGLang. llama.cpp can also download models by itself when asked through
  its API; here that fails, so downloads only come from `models.txt`.
- **Only this PC and the stack's containers can reach it** (port on `127.0.0.1`), like the
  other engines. Web pages from other sites, open in your browser, can't use it either:
  llama.cpp only answers browser requests from pages on this PC (`--cors-origins localhost`).
  Open WebUI talks to it from its own server, so it isn't affected.
- **Its tools for agents stay off.** llama.cpp can let a model read and write files and run
  commands (`--tools`). That is off unless you add it yourself, and it shouldn't be added
  here.
- **It follows the newest build.** llama.cpp publishes a build for almost every change,
  several a day, and adds support for new models that way, so the update check finds a new
  one most days. **Update** when you need one, **Revert** goes back one build, and **Hold**
  keeps the one you have. To stay on one build for good, set `LLAMACPP_IMAGE_TAG` in `.env`
  (see `.env.template`). It's the CUDA 12.8 build; the `server-cuda13` images need a newer
  NVIDIA driver than 580.

## Settings

Everything is optional; see `.env.template` for the conversation length, the GPU memory to
leave free, when to unload an idle model, extra options, the port and the version.
