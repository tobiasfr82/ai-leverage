#!/bin/bash
# ai-leverage/stack/huggingface/check_health.sh
# Lists the models in the shared models/huggingface folder and their size.

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
HF_HOME="$(cd ../.. && pwd)/models/huggingface"
export HF_HOME

uv run hf cache ls
