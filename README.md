# AI-Leverage

A bash & Python-native framework for running large language models locally with Docker.

## Overview
AI-Leverage runs a private AI stack on your own PC: a chat interface, four engines that
run the models, a document reader and an AI agent, all in Docker and all talking to each
other out of the box. One menu (`manage.sh`) starts, stops and updates everything, and plain text lists
decide which models get downloaded.

## 🚀 Quick start
```bash
./bootstrap.sh    # once per machine: installs uv, Docker and NVIDIA's Docker support
./manage.sh       # the menu for everything else
```

The menu lists everything in the order you need it: **downloaders** get models onto this PC,
**engines** run them, and **services** are what you use. At the top it shows what the PC
has to spare, as of when the menu was drawn:

```text
Disk   4.7 TB free / 7.2 TB · models use 969 GB
RAM    67 GB free / 92 GB
GPU    0% busy · VRAM 27.1 GB used / 31.8 GB · 14 W · 34°C
```

**Disk** is the drive `models/` is on. A number turns yellow or red when the disk is nearly
full, RAM runs low, or the GPU gets hot. **r** refreshes these numbers and the services'
status. **m** opens a live monitor that also shows which engine uses how much of the GPU's
memory, the CPU, and how fast a download runs.

1. Run **downloaders → ollama → sync_models** to download the models in
   `stack/downloaders/ollama/models.txt`. That list is large and made for a 32 GB GPU, so
   trim it to what you want first (see [Hardware](#-hardware)).
2. Start **ollama** under engines, then **docling** and **openwebui** under services.
3. Open `http://localhost:3000`. On the first visit you create the admin account;
   everything else is pre-set.

For the AI agent as well, start **hermes** and run **hermes → connect_openwebui** before
you start **openwebui** for the first time, so Open WebUI lists it too. Read
[stack/services/hermes/README.md](stack/services/hermes/README.md) first: it explains which
of your files Hermes can change.

## 🏗️ How it fits together
```text
                     you, in the browser: http://localhost:3000
                                    │
                             ┌──────▼──────┐
                             │ Open WebUI  │  chat interface
                             └─┬───┬───┬──┬┘
       chat + embeddings       │   │   │  │   reading uploaded documents
          ┌────────────────────┘   │   │  └───────────────────────┐
          │            ┌───────────┘   └─────────┐                │
     ┌────▼────┐  ┌────▼────┐            ┌───────▼───────┐   ┌────▼────┐
     │ Ollama  ◄──┤ Hermes  │ the agent  │ vLLM / SGLang │   │ Docling │  (its models ship
     │         │  │         │            │  / llama.cpp  │   │         │   inside the image)
     └────┬────┘  └────┬────┘            └───────┬───────┘   └─────────┘
          │            ▼                         │
          │       your notes                     │
   models/ollama                         models/huggingface
          ▲                                      ▲
 downloaders → ollama                 downloaders → huggingface
 (models.txt + specs/)                (models.txt)
```

- **Ollama** is the everyday engine: easy model switching, many models on one GPU.
- **vLLM** is the fast engine for one model at a time. Pick the model with
  `stack/engines/vllm/set_model.sh` (menu: **vllm → set_model**). It runs only models the
  Hugging Face downloader fetched, and never goes online itself; set_model says when a
  model still needs downloading.
- **SGLang** is another fast engine for one model at a time, for the same models as vLLM,
  and locked down the same way. Some models run better on one, some on the other. Pick the
  model with **sglang → set_model**, and run vLLM or SGLang, not both. See
  [stack/engines/sglang/README.md](stack/engines/sglang/README.md).
- **llama.cpp** runs models bigger than the GPU: what doesn't fit in the GPU's memory stays
  in the PC's memory, which works best for MoE models such as gpt-oss 120B. It runs GGUF
  models from the same Hugging Face downloader, listed with their size, such as
  `unsloth/gpt-oss-120b-GGUF:Q4_K_M`, and switches between them like Ollama: pick one in
  Open WebUI. See [stack/engines/llamacpp/README.md](stack/engines/llamacpp/README.md).
- **Docling** turns uploaded PDFs and Office files into text Open WebUI can search.
- **Hermes** is an AI agent: it thinks with Ollama's models and reads, writes and links the
  files in one folder of yours, such as an Obsidian vault. Chat with it in the terminal
  (**hermes → chat**) or as `hermes-agent` in Open WebUI. See
  [stack/services/hermes/README.md](stack/services/hermes/README.md) for what it can reach.
- Models live in the shared `models/` folder at the top of the repo, never inside a
  container, so updating or rebuilding a service never re-downloads them. The downloaders
  fill it, and the engines read from it.

| Folder                      | What it is                                                      |
| --------------------------- | --------------------------------------------------------------- |
| `stack/downloaders/<name>/` | Downloads the models in its `models.txt` into `models/<name>`   |
| `stack/engines/<name>/`     | Runs the models: `compose.yaml`, settings, and sometimes a script to pick a model |
| `stack/services/<name>/`    | What you use: the chat interface, the document reader, the agent |
| `apps/<app>/`               | Install and uninstall scripts for desktop apps (Obsidian, OpenCode) |
| `src/bash/`                 | Helpers that `manage.sh` and `bootstrap.sh` use                 |
| `models/`                   | Downloaded models (git-ignored)                                 |

## ⚙️ Your own settings
Every service works without any configuration. To change something for your machine only,
copy the service's `.env.template` to `.env` next to it and edit that:

```bash
cd stack/engines/ollama
cp .env.template .env      # then uncomment and change what you need
```

`.env` files are git-ignored, so your choices, IP addresses and tokens stay on your
machine. Each `.env.template` lists the settings people usually change, with the default
next to each one. Start the service again from the menu to apply a change.

**Updating from before the downloaders/engines/services folders?** Git moves the repo's
files, but not your `.env` files or each service's `data/` folder (logins, chats, memory).
The first time you run `manage.sh` afterwards, it lists them and offers to move them from
the old folders, such as `stack/openwebui`, to the new ones, such as
`stack/services/openwebui`.

## 💻 Hardware
- **Linux with an NVIDIA GPU.** Ollama, vLLM, SGLang, llama.cpp and Docling run on the
  GPU. Open WebUI does not need one.
- **The services size themselves to your GPU.** Ollama picks its context size (how much
  text a model can keep in mind) from the VRAM: 32k tokens on a 32 GB card, enough for
  chats and documents. vLLM and SGLang fit as much context as the memory they are given
  holds. llama.cpp gives every model 64k and fits the model around that.
- **The PC's own memory (RAM) counts for llama.cpp.** It keeps what doesn't fit on the
  GPU there, so the GPU and the RAM together must hold a model, with room to spare. With
  32 GB of VRAM and 64 GB of RAM or more, MoE models of about 120B, such as gpt-oss 120B,
  run at a usable speed.
- **Agents need a bigger context.** Hermes Agent needs at least 64k, and VS Code's agent
  mode fills context quickly. The `agent/...` models that **downloaders → ollama →
  sync_models** builds from `stack/downloaders/ollama/specs/` have 128k, and
  `agent/qwen3.6:35b` has 256k. The Hermes in `stack/services/hermes` uses
  `agent/qwen3.6:35b` out of the box. For an agent outside the stack, point it at one of
  those models, at `http://localhost:11434/v1`, and tell it the same context size (131072,
  or 262144 for 256k). See
  [stack/downloaders/ollama/README.md](stack/downloaders/ollama/README.md) for how these
  custom models work.
- **The model lists are the maintainer's picks for a 32 GB RTX 5090,** and so are the
  context sizes in `stack/downloaders/ollama/specs/`. On a smaller card, trim
  `stack/downloaders/ollama/models.txt` and `stack/downloaders/huggingface/models.txt`
  before the first sync. As a rule of thumb, a model needs its download size in VRAM,
  plus room for the conversation.
- **vLLM and SGLang each claim most of the GPU's memory when they start** (vLLM 85%,
  SGLang what it works out for your card). Run only one of them, and stop it while you use
  Ollama's larger models or llama.cpp, or lower `VRAM_LIMIT` in its `.env`. llama.cpp takes
  what is free when it loads a model, leaves 4 GB for Docling and document search, and
  unloads the model after 30 minutes without a chat. Downloading models doesn't use the
  GPU, so it's fine while any of them runs.
- **Storage:** the full model lists take several hundred GB. To keep them on another disk,
  make `models/` a link to it before the first download:
  `ln -s /path/to/big/disk/ai-models models`.

## 🔌 Networking
All engines and services in `stack/` join one private Docker network, `ai-leverage`.
Containers reach each other by name over it, and by default nothing is reachable from
outside this PC.
`bootstrap.sh` creates the network, and `manage.sh` creates it if it is missing.

| Service    | From other containers     | From this PC                                   |
| ---------- | ------------------------- | ---------------------------------------------- |
| Open WebUI | `http://openwebui:8080`   | `http://localhost:3000`                        |
| Ollama     | `http://ollama:11434`     | `http://localhost:11434`                       |
| vLLM       | `http://vllm:8000/v1`     | `http://localhost:8000/v1`                     |
| SGLang     | `http://sglang:30000/v1`  | `http://localhost:30000/v1`                    |
| llama.cpp  | `http://llamacpp:8080/v1` | `http://localhost:8080` (chat page; API `/v1`) |
| Docling    | `http://docling:5001`     | `http://localhost:5001` (web UI at `/ui`)      |
| Hermes     | `http://hermes:8642/v1`   | `http://localhost:8642/v1` (needs its key)     |

- **Every port is published on `127.0.0.1` (this PC only).** Docker's published ports bypass
  host firewalls such as `ufw`, so this binding is what keeps them private.
- **Port already taken on this PC?** Each service's `.env.template` has a port setting.
  Containers keep using the addresses in the middle column, so nothing else changes.
- **Only services with their own login can be opened to your network.** For Open WebUI, see
  [Opening it to your home network](stack/services/openwebui/README.md#opening-it-to-your-home-network):
  a quick check of the account settings, then one setting in a local `.env`. Ollama, vLLM,
  SGLang, llama.cpp and Docling have no login, so they stay on this PC. So does Hermes,
  because it can change your files.
- **Personal settings stay out of git.** IP addresses, domains and tokens belong in a `.env`
  file next to the service's `compose.yaml`; `.env` files are git-ignored.
- **After changing a `compose.yaml` or `.env`, use Start** in `manage.sh` (or
  `sudo docker compose up -d`): it recreates the container with the new settings. Restart
  keeps the container's old settings.
- **The network name is fixed.** To change it, update `NETWORK_NAME` in
  `src/bash/docker-create-network.sh` and the `networks:` block at the bottom of every
  `stack/*/*/compose.yaml`.

## 🔒 Privacy
Every model runs on this PC, so your chats, documents and prompts stay here. What goes
online is what you start yourself: model downloads (huggingface.co, ollama.com) and the
programs themselves (Docker Hub, GitHub, Quay) on Start or Update.

Some of the programs would also send things on their own. The stack turns that off:

| Program                 | What it would send, and when                                                        | Turned off with                       |
| ----------------------- | ----------------------------------------------------------------------------------- | ------------------------------------- |
| vLLM                    | Your hardware, the model type and its settings, at every start and every 10 minutes | `VLLM_NO_USAGE_STATS`, `DO_NOT_TRACK` |
| Ollama                  | A signed request to ollama.com at every start and every 4 hours                     | `OLLAMA_NO_CLOUD`                     |
| Open WebUI              | A check on GitHub for a newer version each time it's opened                         | `ENABLE_VERSION_UPDATE_CHECK`         |
| Hugging Face downloader | A daily check on pypi.org for a newer `hf`                                          | `HF_HUB_DISABLE_UPDATE_CHECK`         |

- **`OLLAMA_NO_CLOUD` also turns off Ollama's cloud models and web search.** To use them,
  set `OLLAMA_NO_CLOUD=0` in `stack/engines/ollama/.env`.
- **SGLang, llama.cpp, Docling and Hermes send nothing on their own** as they're set up
  here. Open WebUI's image ships with its tracking already off. This was checked against
  each program's source in October 2026; updates can change it.
- **Hermes's voice features run on this PC.** Its built-in default for reading replies
  aloud is Microsoft's Edge service, so the stack sets Piper and Whisper instead. See
  [its README](stack/services/hermes/README.md#good-to-know) for an existing install.
- **What you add can go online.** Examples: a key for a cloud model in Open WebUI or
  Hermes, or web search.
- **The apps in `apps/` are ordinary desktop programs.** OpenCode updates itself and gets
  its list of models from opencode.ai when it starts. Obsidian checks for updates.

## 🧩 Adding to the stack
`stack/` has three groups, and `manage.sh` shows them in this order:

- **`downloaders/`** get models onto this PC. Each one fills `models/<its name>` from its
  `models.txt`, and works without an engine running.
- **`engines/`** run the models. Each one reads a folder in `models/` and downloads nothing
  itself. An engine that runs Hugging Face models, like vLLM, SGLang or llama.cpp, reads
  `models/huggingface`, so it needs no downloader of its own.
- **`services/`** are what you use. They reach the engines over the shared network.

A folder keeps what only it uses; something several folders share gets its own folder.
Put a new folder in the group that fits, and `manage.sh` finds it on its own:

- **`compose.yaml`** gives it Start, Stop and the rest of the menu. It publishes ports on
  `127.0.0.1`, joins the `ai-leverage` network (copy the `networks:` block from another
  service), and reads an optional `.env` (copy the `env_file:` block). Settings that are
  the same for everyone go here, with safe defaults.
- **`.env.template`** lists what someone might want to change on their own machine.
- **Every executable `*.sh`** shows up as an entry in that folder's menu, for example a
  `sync_models.sh` that downloads what `models.txt` lists.
- **While it runs, the menu shows where to open it:** the first port its `compose.yaml`
  publishes, as `http://localhost:<port>`. When that isn't the whole story, write what the
  menu should show in an `ai-leverage.url` label in `compose.yaml`: Docling's points at its
  web UI at `/ui`, and most engines' and Hermes's say `(API)`, because those are
  addresses for apps, not web pages.
- **An `ai-leverage.info` label adds a line under it while it runs,** about what it runs.
  vLLM and SGLang use it to show their model, as `model: ${HUGGINGFACE_MODEL}`.
- **Folder names are unique across the groups,** except where a downloader and an engine
  belong together, like the two `ollama` folders. Docker names each service after its
  folder, so two services with the same folder name would clash.
