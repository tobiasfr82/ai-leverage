# Hermes Agent

[Hermes Agent](https://github.com/NousResearch/hermes-agent) is an AI agent: instead of only
answering, it reads, writes, renames and links files, runs commands and remembers what it
learned across chats. Here it thinks with Ollama's models and works on one folder of yours,
such as an Obsidian vault. You talk to it in the terminal or, as a model called
`hermes-agent`, in Open WebUI.

```text
  you ──► terminal (hermes → chat) ──┐
  you ──► Open WebUI, "hermes-agent" ─┴──► Hermes ──► Ollama: agent/qwen3.6:35b
                                             │
                                             ▼
                               /workspace = HERMES_WORKSPACE
                               (your notes: the only folder of yours it sees)
```

## First start

1. **Get the model.** Run **Models › Downloaders › ollama → sync_models**. It builds
   `agent/qwen3.6:35b`, which Hermes uses by default (see `first-start-config.yaml`).
2. **Give Hermes your notes.** Without this, it works in an empty `data/workspace` folder.

   ```bash
   cd stack/services/hermes
   cp .env.template .env
   ```

   In `.env`, set `HERMES_WORKSPACE` to your vault, for example
   `HERMES_WORKSPACE=/home/you/notes/second-brain`, and check that `HERMES_UID`/`HERMES_GID`
   match `id -u` and `id -g` (both are 1000 for the first user on most Linux systems).
3. **Start it:** **hermes → Start**. The first start downloads about 1 GB.
4. **Chat:** **hermes → chat** opens Hermes in the terminal. Type `/help` for its commands.
5. **Optional, Open WebUI:** run **hermes → connect_openwebui**. It hands Hermes's key to
   Open WebUI and tells you the one remaining step, if any.

`data/` holds Hermes's own settings, memory, skills and chat history. Hermes creates it on
the first start, and git ignores it. `data/config.yaml` is where the settings live from then
on; `first-start-config.yaml` only fills it the first time.

## What Hermes can reach

Hermes runs in its own container. Inside it, it sees:

- **`/workspace`**: the folder `HERMES_WORKSPACE` points at. It can read, change, rename and
  delete anything in there.
- **`/opt/data`**: its own `data/` folder.
- **Ollama, the internet, and the other containers** on the `ai-leverage` network.

It cannot see the rest of your files, your SSH keys or the Docker engine. Its file tools
can only write to those two folders.

### Open WebUI is a second door to the same Hermes

Open WebUI does not get a separate, weaker Hermes. Whoever chats with `hermes-agent` in Open
WebUI directs the same agent, with the same access to `/workspace`, as you do in the
terminal. What keeps this safe:

- **Only admins see `hermes-agent` in Open WebUI.** A model nobody has set access for yet
  is hidden from regular accounts. Keep it that way when others use your Open WebUI: don't
  make `hermes-agent` public or share it, and don't make other people admins.
- **Risky commands are refused.** Chats from Open WebUI have nobody to approve a risky
  command, such as deleting a folder, so Hermes refuses those outright (`unattended_mode:
  deny` in `data/config.yaml`). In the terminal it asks you first.
- **The API has a random key.** Hermes created it on the first start (`API_SERVER_KEY` in
  `data/.env`), and only Open WebUI knows it.

### Keep your notes under git

The real risk is not someone else. It's an agent confidently making a bad edit to 40 notes
at once, or following instructions hidden in a web page it read. Ordinary note edits are
not "risky commands", so nothing stops them. Git makes every change visible and reversible:

```bash
cd /path/to/your/vault
git init && git add -A && git commit -m "Before Hermes"
```

After a Hermes session, `git status` and `git diff` show exactly what it changed, and
`git checkout -- <file>` undoes a change.

## Several vaults

A **profile** is a separate Hermes: its own memory, personality (`SOUL.md`), skills and
settings. One profile per vault keeps what Hermes learns about one vault out of the others.
In Open WebUI, each profile can show up as its own model.

What a profile is **not** is a wall. All profiles run in this one container, so each of
them can reach everything in `/workspace`. To keep them apart:

- **Separate by habit:** point `HERMES_WORKSPACE` at a folder that holds all your vaults,
  and give each profile its own vault as a starting folder. Each profile goes to its own
  vault, but nothing technically stops it from going into another one.
- **Separate for real:** run a second Hermes container, with its own `data` folder and only
  the other vault as its workspace. Use this when a vault must never mix with the others,
  for example one with work data.

Creating a profile for a vault in `/workspace/work-brain`:

```bash
./chat.sh profile create work-brain
./chat.sh -p work-brain config set terminal.cwd /workspace/work-brain
```

and add this line to `data/profiles/work-brain/.env`:

```bash
OBSIDIAN_VAULT_PATH=/workspace/work-brain
```

Chat with it with `./chat.sh -p work-brain`. To see it in Open WebUI as well, it needs its
own API port and key, and its own gateway: see Hermes's
[multi-profile guide](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/open-webui#multi-user-setup-with-profiles).
Open WebUI then reaches it at `http://hermes:<its port>/v1`.

## Good to know

- **Switch models** in a chat with `/model`, or permanently with `./chat.sh model`. Hermes
  needs a context of at least 64k tokens; the `agent/...` models in
  [stack/downloaders/ollama/specs](../../downloaders/ollama/specs) are built for that.
- **Replies take a while.** Hermes may read and write several files before it answers. In
  Open WebUI you see each step as it happens.
- **New key?** If you delete `data/`, Hermes creates a new key on its next start. Run
  **hermes → connect_openwebui** again, and update the key in Open WebUI.
- **Update** in the menu downloads the newest release, and **Revert** goes back one.
  Hermes's own `hermes update` does not work in a container. Revert brings back the
  program, not `data/`: copy `data/` first if an update worries you.
- **Voice stays on this PC.** When Hermes reads a reply aloud or turns speech into text, it
  uses Piper and Whisper on this PC, instead of its default of Microsoft's Edge service.
  This only applies to a new install. Hermes set up before this change keeps its own
  `data/config.yaml`, so switch it once with
  `./chat.sh config set tts.provider piper` and `./chat.sh config set stt.provider local`.
