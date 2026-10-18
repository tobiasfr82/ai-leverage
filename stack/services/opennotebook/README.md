# Open Notebook

[Open Notebook](https://github.com/lfnovo/open-notebook) is a research notebook on this PC,
like Google's NotebookLM: put sources in a notebook (PDFs, web pages, YouTube videos, audio),
then chat with them, write notes, have it summarise them, or turn them into a podcast. It
thinks with the stack's engines, at `http://localhost:8502`.

```text
  you, in the browser: http://localhost:8502
                 │
        ┌────────▼────────┐  shared network   ┌──────────────────────────────┐
        │  opennotebook   ├───────────────────► Ollama, vLLM, SGLang,        │
        │ page, API and   │                   │ llama.cpp (and cloud models, │
        │ worker          │                   │ if you add a key)            │
        └────────┬────────┘                   └──────────────────────────────┘
                 │ its own network: no internet, nothing else on it
   ┌─────────────▼──────────┐   ┌────────────────────┐
   │ opennotebook-surrealdb │   │ opennotebook-setup │  runs once, at the first start
   │ the database           │   └────────────────────┘
   └────────────────────────┘
```

## First start

1. **Get the models.** Run **Models › Downloaders › Ollama → Sync models**. It builds
   `agent/qwen3.6:35b` to chat with and `rag/qwen3-embedding:8b` to search documents, the two
   models Open Notebook uses by default.
2. **Start it:** **opennotebook → Start**. The first start downloads about 650 MB, and adds
   two random keys to `.env`: one encrypts the API keys you add for cloud models, the other is
   the database's password. Keep `.env` together with `data/`; with other keys, Open Notebook
   can't open its own database.
3. **Open `http://localhost:8502`.** There's no account to create.

On that first start, `opennotebook-setup` sets Open Notebook up for the stack, through
Open Notebook's own API (see `first-start.py`):

- **web pages you add are read by Open Notebook itself.** Its default sends every address to
  Jina's cloud reader, which fetches the page for it.
- **connections to Ollama, vLLM, SGLang and llama.cpp** (`http://ollama:11434`,
  `http://vllm:8000/v1`, `http://sglang:30000/v1`, `http://llamacpp:8080/v1`)
- **the default models:** `agent/qwen3.6:35b` to chat and `rag/qwen3-embedding:8b` to search,
  both from Ollama

It changes nothing that's already there, and later starts skip it. The models and the
context size can be changed for that first start in `.env`; after it, change them in Open
Notebook under **Manage › Models**. To use vLLM's, SGLang's or llama.cpp's model, start that
engine, then in **Manage › Models** open its connection and choose **Discover models**.

## How much text the models keep in mind

Open Notebook would ask Ollama for 8192 tokens, so the first start sets its Ollama connection
to 32768, which fits any of the stack's models on a 32 GB card. `agent/qwen3.6:35b` holds
262144 there: for long documents, raise it in **Manage › Models**, on the Ollama connection.
A bigger size than the GPU holds makes Ollama put part of the model in the PC's memory, which
works but answers much more slowly. For the engines, the context is what the engine was
started with.

## Cloud models

Add a key in **Manage › Models** to use Gemini, Claude, OpenAI, OpenRouter and others next to
the local engines. Open Notebook stores the key encrypted in its database. Whatever a cloud
model works on (your sources, notes and questions) goes to that provider, so choose per
notebook what stays on this PC.

## Privacy

Open Notebook has no tracking. Two things would go online by default, and the stack turns
them off:

| What it would do                                                    | Turned off with                                                    |
| ------------------------------------------------------------------- | ------------------------------------------------------------------ |
| Send each web page you add to Jina's cloud reader (r.jina.ai)       | The first start sets **Manage › Settings → URL Processing Engine** to Simple |
| Ask GitHub for its newest version when its page opens (once a day)  | `extra_hosts` in `compose.yaml` points that address back at the container |

- **What still goes online is what you add:** the web pages and YouTube videos you add as
  sources are fetched from their sites, and cloud models get what they work on.
- **Docling (`OPEN_NOTEBOOK_ENABLE_DOCLING` in `.env`) downloads several GB** from pypi.org and
  huggingface.co when it installs, on the next Start. It's off by default. Open Notebook
  can't use the stack's own Docling service: it only runs Docling inside its own container.
- **The database has no internet and no port on this PC.** It sits on Open Notebook's own
  network, which only Open Notebook joins.

## No login without a password

Open Notebook has one password for everyone, and none by default. That's fine while only
this PC can open it, as set up here. Only pages at Open Notebook's own address may use its
API, so a website open in your browser can't read your notebooks through `localhost`. Other
containers on the shared network reach its API at `http://opennotebook:5055`, without a
password unless you set one.

### Opening it to your home network

1. Set a password, and let other devices in, in `.env` (`cp .env.template .env` first):

   ```bash
   OPEN_NOTEBOOK_PASSWORD=a-long-password
   OPENNOTEBOOK_BIND_ADDRESS=0.0.0.0
   OPENNOTEBOOK_URL=http://192.168.1.20:8502    # this PC's address on your network
   ```

2. **opennotebook → Start** applies it. Open the page at the `OPENNOTEBOOK_URL` address, from
   this PC too: the page sends its requests there.

## Podcasts and speech

Podcasts need a voice (text-to-speech), and audio and video sources need speech-to-text.
Ollama and the other engines can't do either, so for now these use a cloud provider you add
in **Manage › Models**, such as OpenAI, ElevenLabs or Google. A local speech service for
Open Notebook, Hermes and Open WebUI is planned.

## Updates and backups

**Update** follows Open Notebook's releases (`v1-latest`) and SurrealDB's 2.x fixes. A new
version may convert the database on its first start, so Update offers to back up `data/` first,
to `backups/services/opennotebook/`, and **Revert** puts it back. The copy leaves out
`data/notebook/.cache`, what the add-ons downloaded, which comes back by itself.

| Folder              | What it holds                                         |
| ------------------- | ----------------------------------------------------- |
| `data/surrealdb/`   | The database: notebooks, sources, notes, chats, keys  |
| `data/notebook/`    | Uploaded files, podcasts, the add-ons' downloads      |
