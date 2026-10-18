#!/bin/bash
# ai-leverage/stack/engines/vllm/set_model.sh
# Picks which downloaded model vLLM serves and saves it in its .env; vLLM
# can restart with it right away.
#
# The choice goes in .env, which git ignores. The picker itself is shared with
# SGLang: src/bash/pick-huggingface-model.sh

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
exec ../../../src/bash/pick-huggingface-model.sh vLLM
