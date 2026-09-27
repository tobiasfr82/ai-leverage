# AI-Leverage

A bash & Python-native framework for running large language models locally with Docker.

## Overview
AI-Leverage runs a private AI stack on your own PC: a chat interface, two engines that
run the models, and a document reader, all in Docker and all talking to each other out of
the box. One menu (`manage.sh`) starts, stops and updates everything, and plain text lists
decide which models get downloaded.

## 🚀 Quick start
```bash
./bootstrap.sh    # once per machine: installs uv, Docker and NVIDIA's Docker support
./manage.sh       # the menu for everything else
```

In the menu, start **ollama**, **docling** and **openwebui**, then run
**ollama → sync_models** to download the models in `stack/ollama/models.txt`. That list is
large and made for a 32 GB GPU, so trim it to what you want first (see
[Hardware](#-hardware)). Then open `http://localhost:3000`. On the first visit you create
the admin account; everything else is pre-set.

## 🏗️ How it fits together
```text
                   you, in the browser: http://localhost:3000
                                  │
                           ┌──────▼──────┐
                           │ Open WebUI  │  chat interface
                           └─┬────┬────┬─┘
         chat + embeddings   │    │    │   reading uploaded documents
                 ┌───────────┘    │    └───────────┐
            ┌────▼────┐      ┌────▼────┐      ┌────▼────┐
            │ Ollama  │      │  vLLM   │      │ Docling │  (its models ship
            └────┬────┘      └────┬────┘      └─────────┘   inside the image)
                 │                │
          models/ollama    models/huggingface
                 ▲                ▲
   stack/ollama/sync_models   stack/huggingface/sync_models
   (models.txt + specs/)      (models.txt)
```

- **Ollama** is the everyday engine: easy model switching, many models on one GPU.
- **vLLM** is the fast engine for one model at a time. Pick the model with
  `stack/vllm/set_model.sh` (menu: **vllm → set_model**).
- **Docling** turns uploaded PDFs and Office files into text Open WebUI can search.
- Models live in the shared `models/` folder at the top of the repo, never inside a
  container, so updating or rebuilding a service never re-downloads them.

| Folder                | What it is                                                           |
| --------------------- | -------------------------------------------------------------------- |
| `stack/<service>/`    | One folder per service: `compose.yaml`, and often a model list and scripts |
| `apps/<app>/`         | Install and uninstall scripts for desktop apps (Obsidian, OpenCode)  |
| `src/bash/`           | Helpers that `manage.sh` and `bootstrap.sh` use                      |
| `models/`             | Downloaded models (git-ignored)                                      |

## ⚙️ Your own settings
Every service works without any configuration. To change something for your machine only,
copy the service's `.env.template` to `.env` next to it and edit that:

```bash
cd stack/ollama
cp .env.template .env      # then uncomment and change what you need
```

`.env` files are git-ignored, so your choices, IP addresses and tokens stay on your
machine. Each `.env.template` lists the settings people usually change, with the default
next to each one. Start the service again from the menu to apply a change.

## 💻 Hardware
- **Linux with an NVIDIA GPU.** Ollama, vLLM and Docling run on the GPU. Open WebUI does
  not need one.
- **The services size themselves to your GPU.** Ollama picks its context size (how much
  text a model can keep in mind) from the VRAM: 32k tokens on a 32 GB card, enough for
  chats and documents. vLLM fits the longest context into the memory it is given.
- **Agents need a bigger context.** Hermes Agent needs at least 64k, and VS Code's agent
  mode fills context quickly. The `agent/...` models that **ollama → sync_models** builds
  from `stack/ollama/specs/` have 128k, and `agent/qwen3.6:35b` has 256k. Point the agent
  at one of those, at `http://localhost:11434/v1`, and tell it the same context size
  (131072, or 262144 for 256k). See
  [stack/ollama/README.md](stack/ollama/README.md) for how these custom models work.
- **The model lists are the maintainer's picks for a 32 GB RTX 5090,** and so are the
  context sizes in `stack/ollama/specs/`. On a smaller card, trim `stack/ollama/models.txt`
  and `stack/huggingface/models.txt` before the first sync.
  As a rule of thumb, a model needs its download size in VRAM, plus room for the
  conversation.
- **vLLM claims 85% of the GPU's memory when it starts.** Stop it while you use Ollama's
  larger models, or lower `VRAM_LIMIT` in `stack/vllm/.env`.
- **Storage:** the full model lists take several hundred GB. To keep them on another disk,
  make `models/` a link to it before the first download:
  `ln -s /path/to/big/disk/ai-models models`.

## 🔌 Networking
All services in `stack/` join one private Docker network, `ai-leverage`. Containers reach
each other by name over it, and by default nothing is reachable from outside this PC.
`bootstrap.sh` creates the network, and `manage.sh` creates it if it is missing.

| Service    | From other containers   | From this PC                                   |
| ---------- | ----------------------- | ---------------------------------------------- |
| Open WebUI | `http://openwebui:8080` | `http://localhost:3000`                        |
| Ollama     | `http://ollama:11434`   | `http://localhost:11434`                       |
| vLLM       | `http://vllm:8000/v1`   | `http://localhost:8000/v1`                     |
| Docling    | `http://docling:5001`   | `http://localhost:5001` (web UI at `/ui`)      |

- **Every port is published on `127.0.0.1` (this PC only).** Docker's published ports bypass
  host firewalls such as `ufw`, so this binding is what keeps them private.
- **Port already taken on this PC?** Each service's `.env.template` has a port setting.
  Containers keep using the addresses in the middle column, so nothing else changes.
- **Only services with their own login can be opened to your network.** For Open WebUI, see
  [Opening it to your home network](stack/openwebui/README.md#opening-it-to-your-home-network):
  a quick check of the account settings, then one setting in a local `.env`. Ollama, vLLM
  and Docling have no login, so they stay on this PC.
- **Personal settings stay out of git.** IP addresses, domains and tokens belong in a `.env`
  file next to the service's `compose.yaml`; `.env` files are git-ignored.
- **After changing a `compose.yaml` or `.env`, use Start** in `manage.sh` (or
  `sudo docker compose up -d`): it recreates the container with the new settings. Restart
  keeps the container's old settings.
- **The network name is fixed.** To change it, update `NETWORK_NAME` in
  `src/bash/docker-create-network.sh` and the `networks:` block at the bottom of every
  `stack/*/compose.yaml`.

## 🧩 Adding a service
Every folder in `stack/` follows the same pattern, and `manage.sh` finds it on its own:

- **`compose.yaml`** makes it a service in the menu. It publishes ports on `127.0.0.1`,
  joins the `ai-leverage` network (copy the `networks:` block from another service), and
  reads an optional `.env` (copy the `env_file:` block). Settings that are the same for
  everyone go here, with safe defaults.
- **`.env.template`** lists what someone might want to change on their own machine.
- **Every executable `*.sh`** shows up as an entry in that service's menu, for example a
  `sync_models.sh` that downloads what `models.txt` lists.
