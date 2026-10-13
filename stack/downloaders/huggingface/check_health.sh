#!/bin/bash
# ai-leverage/stack/downloaders/huggingface/check_health.sh
# Lists the models in the shared models/huggingface folder and their size.

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
HF_HOME="$(cd ../../.. && pwd)/models/huggingface"
export HF_HOME
# Reads the folder only: no daily check on pypi.org for a newer hf
export HF_HUB_DISABLE_UPDATE_CHECK=1

uv run hf cache ls
