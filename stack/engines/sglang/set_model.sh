#!/bin/bash
# ai-leverage/stack/engines/sglang/set_model.sh
# Pick which downloaded Hugging Face model SGLang serves. The choice is saved in
# .env (git-ignored), and SGLang can be restarted with it right away.
# The picker itself is shared with vLLM: src/bash/pick-huggingface-model.sh

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1

# SGLang won't start without an admin key (see .env.template). Nobody types it,
# so the first run makes a random one.
[ -f .env ] || cp .env.template .env
if ! grep -Eq "^SGLANG_ADMIN_API_KEY=[\"']?[^\"'[:space:]]" .env; then
    key=$(tr -dc 'a-f0-9' < /dev/urandom | head -c 64)
    if grep -q "^SGLANG_ADMIN_API_KEY=" .env; then
        sed -i "s|^SGLANG_ADMIN_API_KEY=.*|SGLANG_ADMIN_API_KEY=\"$key\"|" .env
    else
        echo "SGLANG_ADMIN_API_KEY=\"$key\"" >> .env
    fi
fi

exec ../../../src/bash/pick-huggingface-model.sh SGLang
