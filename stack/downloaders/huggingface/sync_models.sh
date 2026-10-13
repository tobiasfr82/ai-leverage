#!/bin/bash
# ai-leverage/stack/downloaders/huggingface/sync_models.sh
# Downloads every model in models.txt into the shared models/huggingface folder,
# where vLLM, SGLang and llama.cpp find them. Files already downloaded are
# skipped, so re-runs are quick.

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
MODELS_FILE="models.txt"

# 1. Optional settings for this machine: token and download filters (.env.template)
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# The shared model warehouse. The engines mount this same folder, so it is not a
# setting: to keep models on another disk, make models/ a link to it instead.
HF_HOME="$(cd ../../.. && pwd)/models/huggingface"
export HF_HOME

# The downloads themselves are all that goes to huggingface.co: no daily check
# on pypi.org for a newer hf, and fewer details about this PC in each request.
export HF_HUB_DISABLE_UPDATE_CHECK=1 HF_HUB_DISABLE_TELEMETRY=1

# Whitelist of the file types to download for vLLM and SGLang: the weights in
# .safetensors format, plus the model's small files (settings, tokenizer, chat
# template). Everything else is skipped, such as older weight formats that can
# run code when they are opened (.bin, .pth), the model's own Python code, GGUF
# files and READMEs. HF_INCLUDE in .env replaces this list; "*" downloads
# everything. Lines with a size (GGUF, for llama.cpp) don't use it: see download.
DEFAULT_INCLUDE="*.safetensors *.json *.jinja *.model *.txt *.tiktoken"
INCLUDE_LIST="${HF_INCLUDE:-$DEFAULT_INCLUDE}"

# Filters may be separated by spaces or commas: "*.safetensors *.json".
# 'read -a' splits them without the shell expanding the * itself.
read -ra INCLUDES <<< "${INCLUDE_LIST//,/ }"
read -ra EXCLUDES <<< "${HF_EXCLUDE//,/ }"
DOWNLOAD_ARGS=()
for pattern in "${INCLUDES[@]}"; do DOWNLOAD_ARGS+=(--include "$pattern"); done
for pattern in "${EXCLUDES[@]}"; do DOWNLOAD_ARGS+=(--exclude "$pattern"); done
QUIET=()
[[ "${HF_QUIET,,}" == "true" ]] && QUIET=(--quiet)

# A line without a size is for vLLM and SGLang, which need .safetensors weights.
# Says so when a model has none, for example a GGUF model whose line lacks a size.
warn_if_no_weights() {
    local repo=$1 dir snap sizes example
    dir="$HF_HOME/hub/models--${repo//\//--}"
    snap="$dir/snapshots/$(cat "$dir/refs/main" 2>/dev/null)"
    [ -n "$(find -L "$snap" -maxdepth 1 -name '*.safetensors' -print -quit 2>/dev/null)" ] && return
    echo "NOTE: $repo has no .safetensors weights, so vLLM and SGLang can't run it."
    if sizes=$(uv run python -I gguf_files.py "$repo" --sizes < /dev/null 2>/dev/null); then
        example=${sizes%%,*}
        [[ ", $sizes," == *", Q4_K_M,"* ]] && example=Q4_K_M
        echo "It's a GGUF model, for llama.cpp: add the size you want to its line in"
        echo "models.txt, e.g. $repo:$example. Its sizes: $sizes"
    fi
}

# Downloads one line's model. "org/model" gets the whitelist above.
# "org/model:size" gets only the GGUF files of that size, which gguf_files.py
# picks the way llama.cpp does, plus the file for reading images if there is one.
download() {
    local model=$1 repo=${1%%:*} list files
    if [[ "$model" != *:* ]]; then
        uv run hf download "$repo" "${DOWNLOAD_ARGS[@]}" "${QUIET[@]}" < /dev/null || return 1
        warn_if_no_weights "$repo"
        return 0
    fi
    list=$(uv run python -I gguf_files.py "$repo" "${model#*:}" < /dev/null) || return 1
    mapfile -t files <<< "$list"
    uv run hf download "$repo" "${files[@]}" "${QUIET[@]}" < /dev/null
}

echo "---------------------------------------------------"
echo "   Hugging Face Warehouse: Sequential Sync         "
echo "   Into: $HF_HOME"
echo "---------------------------------------------------"

# 2. Processing Loop
# Lines are "org/model" for vLLM and SGLang, or "org/model:size" for the GGUF
# version llama.cpp runs. "GATED|" in front marks models that need a token.
FAILED=()
SKIPPED=()
GGUF_SYNCED=false
while read -r line || [ -n "$line" ]; do
    line="${line%%#*}"
    line="$(echo "$line" | tr -d ' \r\t')"
    [ -z "$line" ] && continue

    MODEL="${line##*|}"
    GATED=false
    [[ "$line" == GATED\|* ]] && GATED=true

    if [ "$GATED" = true ] && [ -z "${HF_TOKEN:-}" ]; then
        echo "SKIPPED (gated, needs HF_TOKEN in .env): $MODEL"
        SKIPPED+=("$MODEL")
        echo "---------------------------------------------------"
        continue
    fi

    echo "SYNCING: $MODEL"

    # 3. Execution: one model at a time, in the order of models.txt
    if download "$MODEL"; then
        echo "COMPLETED: $MODEL"
        [[ "$MODEL" == *:* ]] && GGUF_SYNCED=true
    else
        echo "FAILED: $MODEL"
        FAILED+=("$MODEL")
    fi
    echo "---------------------------------------------------"
done < "$MODELS_FILE"

# 4. Summary
if [ "$GGUF_SYNCED" = true ]; then
    echo "llama.cpp reads its list of models when it starts. If it runs, Restart it"
    echo "(manage.sh -> llamacpp -> Restart) so it lists new GGUF downloads."
fi
if [ ${#SKIPPED[@]} -gt 0 ]; then
    echo "Skipped ${#SKIPPED[@]} gated model(s). Accept their terms on huggingface.co,"
    echo "then put your access token in .env (see .env.template)."
fi
if [ ${#FAILED[@]} -gt 0 ]; then
    echo "Failed:"
    printf '  %s\n' "${FAILED[@]}"
    exit 1
fi
echo "   Sync Operation Finished"
echo "---------------------------------------------------"
