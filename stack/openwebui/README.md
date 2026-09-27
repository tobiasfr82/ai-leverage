# Open WebUI

The chat interface for the stack, at `http://localhost:3000` on this PC. It talks to Ollama,
vLLM and Docling over the shared `ai-leverage` network (see the main README).

## Fresh install: nothing to configure

On its very first start, while its database is still empty, Open WebUI takes its settings
from the environment variables in `compose.yaml`. They are pre-set to:

- use Ollama for chat models (`http://ollama:11434`)
- also list vLLM's model while vLLM runs (`http://vllm:8000/v1`)
- read uploaded documents with Docling (`http://docling:5001`)
- search documents with Ollama embeddings (`rag/qwen3-embedding:8b`, which
  **ollama → sync_models** builds from `stack/ollama/specs/`)

The only manual step is creating your admin account on the first visit.

## Existing install: settings live in the database

After the first start, Open WebUI saves these settings in its database
(`data/webui.db`) and ignores `compose.yaml` for them from then on. Change them in the
browser under **Admin Panel → Settings**.

Don't edit the database directly. Open WebUI changes how it stores settings between
versions, so a direct edit can silently stop working after an update.

### Moving an existing install onto the shared network

Installs from before the shared network reach Ollama and Docling through
`host.docker.internal`. Change these once, then press Save:

| Admin Panel → Settings →                | Set to                                   |
| --------------------------------------- | ---------------------------------------- |
| Connections → Ollama API                | `http://ollama:11434` (press verify)     |
| Connections → OpenAI API (optional)     | `http://vllm:8000/v1`, no key, for vLLM  |
| Documents → Content Extraction Engine   | Docling, server URL `http://docling:5001` |
| Documents → Embedding (Ollama) URL      | `http://ollama:11434`                    |
| Documents → Embedding model             | `rag/qwen3-embedding:8b`                 |

The Docling URL field only appears once **Docling** is selected as the extraction engine.

## Back up before updates or big changes

Stop Open WebUI first, so the copy is complete, then:

```bash
cp -a data/webui.db data/webui.db.bak_$(date +%F)
ls -lh data/webui.db*    # the copy must not be 0 bytes
```

To restore, stop Open WebUI and copy the backup back over `data/webui.db`.

## Opening it to your home network

By default only this PC can open Open WebUI. To use it from a laptop or phone on the same
network, follow these steps. Only Open WebUI gets opened: Ollama, vLLM and Docling have no
login, so they stay private and Open WebUI reaches them over the shared network.

### 1. Check who can get in

Everyone on your network will be able to see the login page. In **Admin Panel → Settings →
General**, make sure that:

- **new sign-ups are off**, otherwise anyone on your wifi can create an account
- **the default role for new users is "pending"**, so a new account waits for your approval

Also check that **Admin Panel → Users** only lists people you know, and that your admin
password is strong.

### 2. Open the door

```bash
cd stack/openwebui
cp .env.template .env        # skip if you already have a .env
```

In `.env`, set `OPENWEBUI_BIND_ADDRESS=0.0.0.0`. Then recreate the container, because
Docker only reads `.env` when it creates one:

```bash
sudo docker compose up -d --force-recreate
```

`.env` is git-ignored, so this choice stays on your machine. Anyone who clones the repo
still gets "this PC only".

### 3. Connect from the other device

Open `http://<pc-name>.local:3000`, where `<pc-name>` is what `hostname` prints on this PC.
If that name doesn't load, use the PC's network address instead. On this PC, run:

```bash
ip -4 route get 1.1.1.1 | grep -o 'src [0-9.]*'
```

and open `http://<that-address>:3000` on the other device.

### 4. Confirm the engines stay private

From the other device, `http://<pc-name>.local:11434` (Ollama) and
`http://<pc-name>.local:5001/ui` (Docling) must **not** load.

### Good to know

- **Plain http is fine inside your home, not over the internet.** Never forward port 3000
  on your router. For access from outside, use a private network such as Tailscale, or a
  tunnel with its own login in front, such as Cloudflare Tunnel with Access.
- **To close it again,** set `OPENWEBUI_BIND_ADDRESS=127.0.0.1` (or delete `.env`) and
  recreate the container.

## Known quirk: logged out after recreating

Open WebUI's login key is stored inside the container, not in `data/`, so recreating the
container (Rebuild, Update, `--force-recreate`) logs everyone out. Your account is
unaffected; just log in again.

To stay logged in, give it a fixed key in your local `.env`:

```bash
echo "WEBUI_SECRET_KEY=$(openssl rand -hex 32)" >> .env
```

Then Start it from the menu. That logs everyone out one last time.
