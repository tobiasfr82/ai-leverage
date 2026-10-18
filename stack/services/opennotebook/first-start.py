"""ai-leverage/stack/services/opennotebook/first-start.py

Sets Open Notebook up for the stack, once, right after its very first start.

Open Notebook keeps its settings in its database, so they can't be pre-set in
compose.yaml like Open WebUI's. This asks its API instead, the same way its
own settings page does:
  1. Web pages you add as sources are read by Open Notebook itself, not by
     Jina's cloud reader (its default), which would see every address.
  2. Connections to the stack's engines: Ollama, vLLM, SGLang and llama.cpp.
     Ollama's gets a context size, since Open Notebook would ask for 8192
     tokens otherwise.
  3. The default models, from Ollama: a chat model and the embedding model
     that document search needs. Both come from Models › Downloaders ›
     Ollama → Sync models.
It changes nothing that's already there, then leaves a mark in data/notebook,
so later starts end at once.

It runs in the throwaway container opennotebook-setup (see compose.yaml), with
the settings compose.yaml gives it. To run it again, delete
data/notebook/.ai-leverage-first-start and Start Open Notebook.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "http://opennotebook:5055"
MARK = "/app/data/.ai-leverage-first-start"
PASSWORD = os.environ.get("OPEN_NOTEBOOK_PASSWORD", "")
CHAT_MODEL = os.environ.get("CHAT_MODEL") or "agent/qwen3.6:35b"
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL") or "rag/qwen3-embedding:8b"
OLLAMA_CONTEXT = int(os.environ.get("OLLAMA_CONTEXT") or 32768)

# (name in Open Notebook, its provider, the address over the shared network,
# what it's used for)
ENGINES = [
    ("Ollama", "ollama", "http://ollama:11434", ["language", "embedding"]),
    ("vLLM", "openai_compatible", "http://vllm:8000/v1", ["language"]),
    ("SGLang", "openai_compatible", "http://sglang:30000/v1", ["language"]),
    ("llama.cpp", "openai_compatible", "http://llamacpp:8080/v1", ["language"]),
]

# The default roles the chat model takes, and the one the embedding model takes
CHAT_ROLES = ["default_chat_model", "default_transformation_model", "large_context_model",
              "default_tools_model"]
EMBEDDING_ROLE = "default_embedding_model"


def call(method, path, body=None):
    """Open Notebook's answer to one API request, as JSON"""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(API + path, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if PASSWORD:
        request.add_header("Authorization", f"Bearer {PASSWORD}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b"null")


def wait_for_api(seconds=600):
    """Whether the API answers within this many seconds. The very first start
    sets up the database first."""
    end = time.time() + seconds
    while time.time() < end:
        try:
            with urllib.request.urlopen(API + "/health", timeout=5):
                return True
        except (OSError, urllib.error.URLError):
            time.sleep(3)
    return False


def connections():
    """The engine connections, as {name: id}, adding the ones that are missing"""
    found = {}
    existing = call("GET", "/api/credentials")
    for name, provider, url, modalities in ENGINES:
        match = next((c for c in existing if (c.get("base_url") or "").rstrip("/") == url), None)
        if match:
            found[name] = match["id"]
            continue
        body = {"name": name, "provider": provider, "base_url": url, "modalities": modalities}
        if provider == "ollama":
            body["num_ctx"] = OLLAMA_CONTEXT
        found[name] = call("POST", "/api/credentials", body)["id"]
        size = f", {OLLAMA_CONTEXT} tokens of context" if provider == "ollama" else ""
        print(f"Added the connection to {name}: {url}{size}")
    return found


def model(name, kind, credential):
    """The ID of an Ollama model in Open Notebook's list, adding it when it isn't there"""
    for entry in call("GET", "/api/models"):
        if entry["provider"] == "ollama" and entry["name"] == name and entry["type"] == kind:
            return entry["id"]
    print(f"Added {name} from Ollama as a{'n' if kind[0] in 'aeiou' else ''} {kind} model")
    return call("POST", "/api/models", {"name": name, "provider": "ollama", "type": kind,
                                         "credential": credential})["id"]


def main():
    if os.path.exists(MARK):
        print("Open Notebook was set up for the stack on an earlier start, so there's nothing to do.")
        return 0
    print("Setting Open Notebook up for the stack (first start only)...")
    if not wait_for_api():
        print("Open Notebook's API didn't answer within 10 minutes. Start it again to retry.")
        return 1
    try:
        call("PUT", "/api/settings", {"default_content_processing_engine_url": "simple"})
        print("Web pages you add are read by Open Notebook itself, not by Jina's cloud reader")
        ollama = connections()["Ollama"]
        defaults = call("GET", "/api/models/defaults")
        empty = [role for role in CHAT_ROLES + [EMBEDDING_ROLE] if not defaults.get(role)]
        update = {}
        if any(role in CHAT_ROLES for role in empty):
            chat = model(CHAT_MODEL, "language", ollama)
            update.update({role: chat for role in CHAT_ROLES if role in empty})
        if EMBEDDING_ROLE in empty:
            update[EMBEDDING_ROLE] = model(EMBEDDING_MODEL, "embedding", ollama)
        if update:
            call("PUT", "/api/models/defaults", update)
            print(f"Default models: {CHAT_MODEL} to chat, {EMBEDDING_MODEL} to search documents")
    except (OSError, urllib.error.URLError, ValueError, KeyError) as error:
        detail = error.read().decode(errors="replace")[:300] if isinstance(error, urllib.error.HTTPError) else ""
        print(f"Setting Open Notebook up failed: {error} {detail}".rstrip())
        print("Start it again to retry. What worked so far stays.")
        return 1
    with open(MARK, "w") as f:
        f.write(time.strftime("Set up for ai-leverage on %Y-%m-%d %H:%M\n"))
    print("Done. Open Notebook is set up for the stack.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
