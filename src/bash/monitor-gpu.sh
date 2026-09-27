#!/bin/bash
# ai-leverage/src/bash/monitor-gpu.sh
# Live GPU usage: memory, load, temperature and power, refreshed every second.

if ! command -v nvidia-smi &> /dev/null; then
    echo "nvidia-smi not found. Is the NVIDIA driver installed?"
    exit 1
fi

# Watch every 1 second
watch -n 1 -d nvidia-smi
