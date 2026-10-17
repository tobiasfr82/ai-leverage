#!/bin/bash
# ai-leverage/stack/downloaders/huggingface/check_health.sh
# Lists the models in the shared models/huggingface folder and their size.
#
# menu: console   (manage.sh's menu shows what it prints without leaving the menu: it never asks anything)

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
HF_HOME="$(cd ../../.. && pwd)/models/huggingface"
export HF_HOME
# Reads the folder only: no daily check on pypi.org for a newer hf
export HF_HUB_DISABLE_UPDATE_CHECK=1

uv run hf cache ls
