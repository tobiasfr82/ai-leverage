# AI-Leverage

A bash & Python-native framework for running large language models locally with Docker.

## Overview
AI-Leverage runs a private AI stack on your own PC: a chat interface, four engines that
run the models, a document reader and an AI agent, all in Docker and all talking to each
other out of the box. One menu (`manage.sh`) starts, stops and updates everything, and plain text lists
decide which models get downloaded. The same menu installs and updates the desktop apps that go
with it: Obsidian, VS Code, Claude Code, Claude Desktop and OpenCode.

## 🚀 Quick start
```bash
./bootstrap.sh    # once per machine: installs uv, Docker and NVIDIA's Docker support
./manage.sh       # the menu for everything else
```

The menu lists everything on the left, in the order you need it: **engines** run the
models, **services** are what you use, and the **apps** come last. Getting models onto
this PC is in the **Models** menu, since you don't download every day. The right side is about the entry you highlight: its log at the top, and what was done
to it below that. The menu bar at the very top holds what isn't about one entry:

| Menu            | What's in it                                                        |
| --------------- | ------------------------------------------------------------------- |
| **AI Leverage** | About (version, folder, source), Theme, Quit                        |
| **Stack**       | Updates, Refresh, Stop all                                          |
| **Models**      | Downloaders ▸ (one per folder in `stack/downloaders`), Tuning ▸ Fit |
| **System**      | Monitor, Ports                                                      |
| **Help**        | Keys and mouse, Find any action, the README                         |

Its right end says how many updates the last check found; a click on that opens them.

- **Moving through the list is how you look at things.** An engine or service that runs
  shows its log live; a stopped one shows its last run (Docker keeps that log until the
  container is deleted). An entry without a log shows what it is. Type an entry's number to
  move to it.
- **Enter or a click opens what you can do with it,** in a box over the menu: Start, Stop,
  Restart, Update and the rest, with what each one does.
- **One key standard everywhere:** in a box or a menu, an entry's number or underlined
  letter does it at once, as in a desktop app: `4` Enter `1` starts the fourth entry, Alt+S
  `u` opens Updates. The arrows and the mouse only move, and Enter or a click does the
  highlighted entry. `b` goes back, and so does Esc. Only the list itself is different: a
  number there only moves, since that's how you look at an entry's log.
- **Whatever can't be undone asks first,** in a yes/no box: Stop or Restart of something
  that runs, Stop all, Rebuild, Update, Revert, Update all, and ctrl+c on an update that
  runs. `y` says yes; `n`, `b` or Esc say no, and No is what's highlighted.
- **What you start shows in the pane under the log,** with the command it ran and how it
  ended, while the menu stays usable, and so do Update, Revert and Hold, and the folders'
  scripts that only print, such as **sync_models**. What Update or Revert would ask, the
  menu asks first in a box of its own. Several entries can have something running at once:
  the list says which, and each entry's pane shows its own. Until an engine answers, the
  list says **◐ LOADING** and how long it's been, not ● UP: vLLM and SGLang take minutes to
  load a model.
- **Each pane works like a window.** At the right end of its frame, **save** writes it to a
  text file in `logs/`, and **▢** gives it the whole area for a long log; a double click on
  its frame does that too, and Esc or **❐** puts it back; `m` and `s` do the same from the
  keys. → goes from the list to the log, and `b` back. ctrl+c stops what runs, or stops
  following a log.
- **Alt and a menu's underlined letter opens it,** from anywhere: Alt+S is Stack, Alt+M
  Models, Alt+Y System (Stack has the S). A click on its title does too, and F10 opens the
  first one. In a menu, an entry's underlined letter does it at once, as in a desktop app,
  so Alt+S, `u` opens Updates. ↑↓ only move, and Enter does the highlighted entry. ← → go
  to the menu next to it; Esc, `b` or a click beside it closes it. (Some terminals keep F10
  or Alt for their own menus; a click always works.)
- **An entry with ▸ shows a menu beside it** as soon as it's highlighted, as in Norton
  Commander: Models › Downloaders lists the downloaders. Its letter, → or Enter goes into
  it, ← or Esc back out, so Alt+M, `d`, `h` opens huggingface.
- **Tab and shift+Tab go from area to area,** the menu bar included, and ↑ from the list's
  top entry goes up to the bar. There ← → choose a menu, its letter, Enter or ↓ opens it,
  and Esc or `b` goes back to the list.
- **A downloader opens from Models › Downloaders,** such as **huggingface**: what it is
  shows on the right, with its box of actions. What it runs shows in the pane under the log,
  and the menu says while it runs. ↑ or ↓ in the list brings the list back.
- **What asks you more runs in the terminal as usual,** with the menu out of the way:
  installing or removing an app, the scripts that ask questions, and sudo when it needs your
  password again. The menu comes back when they're done.
- **Everything the menu does is a script you can run yourself,** in any terminal, tmux or
  over ssh. The panes show each command, such as
  `src/bash/service.sh stack/engines/vllm start`, and `src/bash/service.sh` lists what else
  it does.
- **ctrl+p finds any action by name,** such as "start vllm" or "update hermes", and switches
  the colour theme. The menu remembers the theme in `config/menu.conf`.

At the top it shows what the PC has to spare, updated every 2 seconds:

```text
Disk  ████████        4.7 TB free / 7.2 TB · models use 969 GB
RAM   ███▌            78 GB free / 92 GB
GPU   ▌               VRAM 0.7 GB used / 31.8 GB · 0% busy · 11 W · 31°C  RTX 5090
```

**Disk** is the drive `models/` is on. A number turns yellow or red when the disk is nearly
full, RAM runs low, or the GPU gets hot. The menu reads the engines' and services' status
from Docker, which needs sudo. It reads it when it opens and after each thing you do, and
**Stack › Refresh** reads it again. **System › Monitor** opens a live monitor in its own
window. It also shows which engine uses how much of the GPU's memory, the CPU, and how fast
a download runs. **Stack › Updates** opens the update overview and checks everything for
updates; see [Updates](#-updates). **Models › Tuning › Fit** lists the best of your
downloaded models for the context you need, and how to run each one on this PC; see
[Hardware](#-hardware).

The menu is drawn with [Textual](https://textual.textualize.io). On its first start,
`manage.sh` sets it up with uv in `src/python/.venv`, which is about 13 MB. It's a terminal
program on purpose, not a desktop app: it works the same over ssh, in tmux and on a PC
without a desktop, and sudo asks where you type. That's also why it has its own menu bar
instead of your terminal's File/Edit/View, which a program inside a terminal can't change.
Over ssh, start it in tmux, so a dropped connection doesn't stop an update halfway.

1. Run **Models › Downloaders › ollama → sync_models** to download the models in
   `stack/downloaders/ollama/models.txt`. That list is large and made for a 32 GB GPU, so
   trim it to what you want first (see [Hardware](#-hardware)).
2. Start **ollama** under engines, then **docling** and **openwebui** under services.
3. Open `http://localhost:3000`. On the first visit you create the admin account;
   everything else is pre-set.

Below them, **apps** are programs on this PC itself, outside Docker. Each one has Install,
Update, Revert, Hold and Uninstall; see [apps/README.md](apps/README.md).

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
 stack/downloaders/ollama             stack/downloaders/huggingface
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
| `apps/<app>/`               | Desktop apps: where each comes from (`app.conf`), and its own scripts |
| `src/bash/`                 | Helpers that `manage.sh` and `bootstrap.sh` use                 |
| `src/python/`               | The menu (`menu.py`, its menu bar in `menubar.py`, its panes in `console.py`, the update overview in `updates.py`), the update check's registry lookup (`registry.py`), the model fit (`hardware.py`, `model_facts.py`, `model_fit.py`, `fit_screen.py`), and how GGUF files are named (`gguf_names.py`) |
| `config/`                   | Your settings for ai-leverage itself, such as what the model fit plans for (your copies are git-ignored) |
| `models/`                   | Downloaded models (git-ignored)                                 |
| `backups/`                  | Copies of the services' data that Update makes (git-ignored)    |
| `cache/`                    | What ai-leverage looked up and can look up again: update checks, model facts (git-ignored) |

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

Settings for ai-leverage itself, which no container reads, go in `config/`. For now,
that's `model-fit.conf`: what the model fit (**Models › Tuning › Fit**) plans for, the
context you need, whether the PC's memory may help, and how many conversations run at once.
Fit writes it for you, from `model-fit.conf.template` next to it, and you can edit it by
hand just as well.

**Updating from before the downloaders/engines/services folders?** Git moves the repo's
files, but not your `.env` files or each service's `data/` folder (logins, chats, memory).
The first time you run `manage.sh` afterwards, it lists them and offers to move them from
the old folders, such as `stack/openwebui`, to the new ones, such as
`stack/services/openwebui`.

## 🔄 Updates
Every engine, service and app follows its newest **stable** release, and each has the same
three actions in its menu:

| Action             | What it does                                                                                     |
| ------------------ | ------------------------------------------------------------------------------------------------ |
| **Update**         | Checks online for the newest release, says what it would install, and asks. First it keeps the version it replaces. |
| **Revert**         | Goes back to that kept version and holds it there, so a release that broke something stays away. |
| **Hold / Release** | Hold keeps it at its version, so Update skips it. Release ends the hold.                          |

**Stack › Updates** (Alt+S, `u`) opens the overview of all of them, in a box over
the menu: the version on this PC and the newest one. Each line changes as its answer comes
in. A row's number offers its Update, Revert and Hold. **a** is **Update all**, which updates
everything that has an update, one after another, after asking once. Each one runs in its
own pane under the log, and the overview closes so you can watch it there.

```text
ENGINES
 4  ollama         ● UP            v0.40.1    → v0.40.3     update available
 6  vllm           ○ STOPPED       v0.31.0                  up to date
SERVICES
 7  docling        ● UP            v1.12.0    → v1.37.0     update available
APPS
14  vscode         ● HELD          v1.140.0   → v1.141.0    held: Update all skips it
TOOLS  updated another way
    ai-leverage                    a51a585                  3 newer changes on GitHub (get them with: git pull)
    NVIDIA driver                  580.173.02               the system manages it; CUDA 13.0
```

- **Nothing updates on its own, and the check downloads nothing.** It asks each source
  which version is newest when you open the overview, and the menu shows what it found
  last: the count next to **Updates** at the top, and next to each engine, service or app
  with an update, the newest version, as `↑ v0.40.4`.
- **The overview is a script too:** `src/bash/check-updates.sh` shows the same in any
  terminal, and Update, Revert and Hold work there as in the menu.
- **An engine or service that runs is restarted by its update,** after a warning, because
  that cuts off open chats and makes an engine load its model again. One that's stopped
  stays stopped and uses the new version at its next Start.
- **One earlier version is kept** per engine and service: Docker keeps the image Update
  replaced under the name `ai-leverage-revert/<name>`, and removes the one before. Notes on
  it, and the hold, are in the service's `update/` folder (git-ignored). For the apps, see
  [apps/README.md](apps/README.md).
- **Update offers to back up a service's own data first.** A new version of Open WebUI or
  Hermes can convert its saved data (chats, memory) on its first start, and an older version
  may not read it anymore. So Update backs it up first, while the service is stopped, to
  `backups/services/<name>/` (git-ignored, readable only by you, since it can hold keys; the
  newest 3 stay). The menu says so in its question; in a terminal, Update asks whether to.
  Revert then puts that backup back as well, after backing up the data as it is, so nothing
  is lost (in a terminal, it asks).
  Your notes, which Hermes works in, are never copied.
- **The tools are listed, not updated:** ai-leverage itself (`git pull`), uv
  (`uv self update`), and Docker and the NVIDIA driver, which come with your system's
  updates.

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
  mode fills context quickly. The `agent/...` models that **Models › Downloaders › ollama →
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
  plus room for the conversation. **f** works that out for the models you have, below.
- **f finds the best models for what you need.** At the top you choose how much context
  you need, from 8k to the longest each model gets, and whether the PC's memory may help:
  on the GPU alone is fast, and with the PC's memory, bigger models and longer context run,
  slower. The list answers with the biggest models that manage it, each with the best way
  to run it here. On a 32 GB RTX 5090, for 64k on the GPU alone:

  ```text
  34 models hold 64k on the GPU alone. Biggest first.

        MODEL                         SIZE          8k   16k   32k   64k  128k  256k         HOW IT RUNS
     1  Qwen3.6-35B-A3B               35B MoE   ████████████████████████████████████   256k  Ollama · Q4_K_M
     4  Ornith-1.0-35B                35B MoE   ████████████████████████████████████   256k  vLLM · NVFP4
    14  gemma-4-31B-turbo             31B       ██████████████████████████████······  ~131k  vLLM · NVFP4
  ── 7 don't hold 64k ─────────────────────────────────────────────────────────────────────
        Qwen3.8-Flash-Next            177B MoE  ··························│···········     –  only with PC memory: p
  ```

  The bars show how far each model gets: green as the engine is set, yellow with 8-bit
  conversation memory (a setting that halves it, a little less precise), magenta with part
  of the model in the PC's memory. One model in several files, such as the AWQ download and
  Ollama's `qwen3.8:27b`, is one line. Enter opens a model: every way to run it, where the
  GPU's and the PC's memory goes, and what to do to use it. There, a line marked *not
  downloaded* is the same model in another size, worked out from its parameters; it only
  exists if someone publishes it. Biggest first is a rough guide, not a benchmark, and the
  numbers are estimates, checked against real starts; the engine's log says what it really
  got. Your choices are kept in `config/model-fit.conf`, and vLLM's and SGLang's
  **set_model** and llama.cpp's **list_models** use them for the estimate next to each model.
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
programs themselves (Docker Hub, GitHub, Quay) on Start or Update. The update overview (**u**)
asks the same places, and GitHub, which version is newest, without downloading anything;
only when you open it.

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
- **The menu goes online once.** On its first start, `manage.sh` downloads Textual, which
  draws the menu, through uv from pypi.org. It downloads again only when an update of
  ai-leverage moves Textual's version.
- **The model fit (Models › Tuning › Fit) works offline.** It reads this PC's hardware and
  the headers of the downloaded files, and keeps what it read in `cache/`.
- **What you add can go online.** Examples: a key for a cloud model in Open WebUI or
  Hermes, or web search.
- **The apps in `apps/` are ordinary desktop programs.** Install and Update go online to
  their makers' sources. **Claude Code and Claude Desktop work online by design:** what you
  ask them, and the files they read, go to Anthropic. VS Code sends usage data to Microsoft
  unless **Telemetry: Telemetry Level** is `off`. OpenCode updates itself and gets its list
  of models from opencode.ai when it starts. Obsidian checks for updates.

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
  `sync_models.sh` that downloads what `models.txt` lists. The menu runs it in the plain
  terminal, so it can ask things. A script that only prints and never asks can say
  `# menu: console` in the comment at its top, and the menu shows it in the pane under the
  log instead. Either way it runs in its folder, exactly as typed there, and sudo in it works
  while sudo still remembers your password; the menu asks for it first when it's needed.
- **Its `README.md` describes it in the menu.** The menu shows the first paragraph, and **i**
  reads the whole README. For a script, the menu shows the comment at the top of the script,
  after the line with its path, to say what it does.
- **While it runs, the menu shows where to open it:** the first port its `compose.yaml`
  publishes, as `http://localhost:<port>`. When that isn't the whole story, write what the
  menu should show in an `ai-leverage.url` label in `compose.yaml`: Docling's points at its
  web UI at `/ui`, and most engines' and Hermes's say `(API)`, because those are
  addresses for apps, not web pages. For the others, the menu offers to open them in your
  browser.
- **An `ai-leverage.connect` label tells other services where to find it:** the address
  containers such as Open WebUI use (its container name and its own port, e.g.
  `http://vllm:8000/v1`, not `localhost`), and where that goes in Open WebUI. Its own menu
  shows it as **Services use**.
- **An `ai-leverage.info` label adds a line under it while it runs,** about what it runs.
  vLLM and SGLang use it to show their model, as `model: ${HUGGINGFACE_MODEL}`.
- **An `ai-leverage.ready` label says where to ask whether it's ready,** for a service that
  needs a while after its container starts. The menu shows **◐ LOADING** until that address
  answers with success, then **● UP**. It asks every 2 seconds, only while something loads, and
  it asks the service itself, so it needs no sudo. Use an address that says "not yet" (or
  doesn't answer) until it's really usable, such as vLLM's
  `http://localhost:${VLLM_PORT:-8000}/health`. Without the label, running counts as ready.
- **Its version comes from its image,** for Update and the update overview. Use a tag that
  follows the newest stable release, such as `latest`. When the image doesn't carry its
  version, or carries a wrong one, two labels say where to find it:
  `ai-leverage.version-command` is a command that prints it, run in the downloaded image
  without network (Ollama's is `ollama --version`), and `ai-leverage.releases` names the
  GitHub project whose newest release is the newest version (`ollama/ollama`).
- **When an image's moving tag also carries development builds,** as Docling's `latest`
  does, Update follows the project's GitHub releases instead: the compose file names a
  release through a variable (`docling-serve:${DOCLING_IMAGE_TAG:-v1.37.0}`), the label
  `ai-leverage.follow: "releases"` turns it on, and Update writes the newest release's tag to
  that variable in the service's `.env`. Revert puts the one before back.
- **Folders in it that its containers write to, such as `data/`, are its own data,** which
  Update offers to back up first. An `ai-leverage.data` label says what they hold, for the
  warning (Open WebUI's: `your chats, users and uploads`), or `none` when nothing in them is
  worth a copy (Ollama's holds only its key). `ai-leverage.data-skip` names folders in them
  that backups leave out, such as a cache it fills again by itself (`data/cache`).
- **A desktop app** goes in `apps/<name>/` with an `app.conf` instead; see
  [apps/README.md](apps/README.md#adding-an-app).
- **Folder names are unique across the groups,** except where a downloader and an engine
  belong together, like the two `ollama` folders. Docker names each service after its
  folder, so two services with the same folder name would clash.
