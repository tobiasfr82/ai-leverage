#!/bin/bash
# ai-leverage/stack/engines/vllm/set_model.sh
# Pick which downloaded Hugging Face model vLLM serves. The choice is saved in
# .env (git-ignored), and vLLM can be restarted with it right away.
# The picker itself is shared with SGLang: src/bash/pick-huggingface-model.sh

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
exec ../../../src/bash/pick-huggingface-model.sh vLLM
