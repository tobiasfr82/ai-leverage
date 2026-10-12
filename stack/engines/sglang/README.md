# SGLang

A fast engine for one model at a time, like vLLM. It runs the same models as vLLM, from
the shared `models/huggingface` folder. On this PC it answers at
`http://localhost:30000/v1`; other containers use `http://sglang:30000/v1`.

## First start

1. Download models with **downloaders → huggingface → sync_models**.
2. Run **engines → sglang → set_model** and pick one. It saves your choice in `.env`,
   creates the admin key (see below) and offers to start SGLang.
3. Follow the start in **sglang → View logs**. It is ready when the log says
   `The server is fired up and ready to roll!`

The very first start takes a while: Docker downloads SGLang itself (about 14 GB) once,
and then SGLang loads the model and prepares it for your GPU.

## Using it in Open WebUI

An Open WebUI installed after SGLang arrived in this repo is already connected: it lists
SGLang's model while SGLang runs. If your Open WebUI was set up before, it keeps its own
list of connections, so add SGLang to it once:

1. Open WebUI → **Admin Panel → Settings → Connections**
2. Next to **OpenAI API**, click **+** (Add Connection)
3. URL: `http://sglang:30000/v1`. Leave the key empty: SGLang doesn't check it, so if
   Open WebUI insists on one, type anything. Connection type: **Local**. That only decides
   which tab of the model list it shows under, next to Ollama's models. API type:
   **Chat Completions**, the default.
4. Save.

The connection can stay when SGLang is stopped: Open WebUI then just doesn't list its model.

## vLLM or SGLang?

Both serve one model fast. Both claim most of the GPU's memory when they start, so on one
GPU run only one of them: stop vLLM before you start SGLang, and the other way round. Not
every model runs on both, and one is often faster than the other for a given model, so try
the same model on each.

SGLang also works out by itself how a model marks its thinking and its tool calls, which
agents such as Hermes and OpenCode need. If the log says it "could not detect" them, set
the format in `.env` (see `.env.template`).

## How it is locked down

SGLang's project has had serious security holes this year and publishes its fixes only as
new releases, so this engine gets less freedom than the others:

- **It only runs models you already downloaded.** It never goes online for a model, and it
  sees `models/huggingface` read-only, so it cannot change or delete anything in it. vLLM
  is locked the same way. **set_model** marks a download that lacks files; run
  **huggingface → sync_models** to fetch them.
- **Only this PC and the stack's containers can reach it** (port on `127.0.0.1`), like the
  other engines.
- **Its management functions need the admin key** that `set_model` saved in `.env`: swapping
  the model's weights, loading add-ons, emptying its memory and so on. Chats don't need a
  key, so Open WebUI and agents connect as usual.
- **Models can't run their own code.** SGLang's `--trust-remote-code` stays off unless you
  add it yourself.
- **The version is fixed,** so **Update** downloads the same release again rather than a
  newer one. To move up, check
  [SGLang's releases](https://github.com/sgl-project/sglang/releases), set
  `SGLANG_IMAGE_TAG` in `.env` to the new version (for example `v0.5.22-runtime`), then run
  **Update**.

## Settings

Everything except the model and the admin key is optional; see `.env.template` for
memory, context size, extra options, the port and the version.
