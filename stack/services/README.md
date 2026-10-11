# Services

What you use: the chat interface, the document reader and the AI agent. They reach the
engines, and each other, by name over the shared `ai-leverage` network.

| Service      | What it does                                        | This PC                    |
| ------------ | --------------------------------------------------- | -------------------------- |
| `openwebui/` | The chat interface, in your browser                 | `http://localhost:3000`    |
| `docling/`   | Turns uploaded PDFs and Office files into text      | `http://localhost:5001/ui` |
| `hermes/`    | An AI agent that reads and changes one folder of yours, such as your notes | `http://localhost:8642/v1` |
