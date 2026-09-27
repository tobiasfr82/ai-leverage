# AI-Leverage

A high-performance, bash & Python-native framework for local LLM orchestration using docker.

## Overview
AI-Leverage provides a containerized environment for running large-scale language models locally using Ollama, integrated with a bash & Python-based execution layer. Designed for low-latency decision-making and hardware-accelerated inference.

## 🏗️ Architecture
- **Inference Engine:** Ollama (Dockerized)
- **Logic Layer:** Python 3.12+ (PEP 8 Standards)

## 💻 Hardware Requirements
This project is optimized for high-VRAM and multi-core environments.
- **CPU:** High core-count (e.g., Ryzen 9 series)
- **GPU:** 24GB+ VRAM recommended (e.g., RTX 3090/4090/5090)
- **Storage:** ~600GB NVMe for model weights.

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
- **Only services with their own login can be opened to your network.** For Open WebUI, see
  [Opening it to your home network](stack/openwebui/README.md#opening-it-to-your-home-network):
  a quick check of the account settings, then one setting in a local `.env`. Ollama, vLLM
  and Docling have no login, so they stay on this PC.
- **Personal settings stay out of git.** IP addresses, domains and tokens belong in a `.env`
  file next to the service's `compose.yaml`; `.env` files are git-ignored.
- **After editing a `compose.yaml`, recreate the container** (`manage.sh` → Rebuild, or
  `sudo docker compose up -d --force-recreate`). Restart keeps the container's old settings.
- **The network name is fixed.** To change it, update `NETWORK_NAME` in
  `src/bash/docker-create-network.sh` and the `networks:` block at the bottom of every
  `stack/*/compose.yaml`.

