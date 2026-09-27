# Open WebUI

The chat interface for the stack, at `http://localhost:3000` on this PC. It talks to Ollama
and Docling over the shared `ai-leverage` network (see the main README).

## Fresh install: nothing to configure

On its very first start, while its database is still empty, Open WebUI takes its settings
from the environment variables in `compose.yaml`. They are pre-set to:

- use Ollama for chat models (`http://ollama:11434`)
- read uploaded documents with Docling (`http://docling:5001`)
- search documents with Ollama embeddings (`qwen3-embedding:8b`, listed in
  `stack/ollama/models.txt`)

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
| Documents → Content Extraction Engine   | Docling, server URL `http://docling:5001` |
| Documents → Embedding (Ollama) URL      | `http://ollama:11434`                    |

The Docling URL field only appears once **Docling** is selected as the extraction engine.

## Back up before updates or big changes

Stop Open WebUI first, so the copy is complete, then:

```bash
cp -a data/webui.db data/webui.db.bak_$(date +%F)
ls -lh data/webui.db*    # the copy must not be 0 bytes
```

To restore, stop Open WebUI and copy the backup back over `data/webui.db`.

## Opening it to other devices

By default only this PC can open it. To let a laptop on your home network in, copy
`.env.template` to `.env`, set `OPENWEBUI_BIND_ADDRESS=0.0.0.0`, and recreate the container.
`.env` is git-ignored, so this choice stays on your machine.

## Known quirk: logged out after recreating

Open WebUI's login key is stored inside the container, not in `data/`, so recreating the
container (Rebuild, Update, `--force-recreate`) logs everyone out. Your account is
unaffected; just log in again.
