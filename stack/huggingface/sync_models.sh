#!/bin/bash
# ai-leverage/stack/huggingface/sync_models.sh
# Downloads every model in models.txt into the shared models/huggingface folder,
# where vLLM finds them. Files already downloaded are skipped, so re-runs are quick.

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
MODELS_FILE="models.txt"

# 1. Optional settings for this machine: token and download filters (.env.template)
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# The shared model warehouse. vLLM mounts this same folder, so it is not a
# setting: to keep models on another disk, make models/ a link to it instead.
HF_HOME="$(cd ../.. && pwd)/models/huggingface"
export HF_HOME

# Filters may be separated by spaces or commas: "*.safetensors *.json".
# 'read -a' splits them without the shell expanding the * itself.
read -ra INCLUDES <<< "${HF_INCLUDE//,/ }"
read -ra EXCLUDES <<< "${HF_EXCLUDE//,/ }"
DOWNLOAD_ARGS=()
for pattern in "${INCLUDES[@]}"; do DOWNLOAD_ARGS+=(--include "$pattern"); done
for pattern in "${EXCLUDES[@]}"; do DOWNLOAD_ARGS+=(--exclude "$pattern"); done
[[ "${HF_QUIET,,}" == "true" ]] && DOWNLOAD_ARGS+=(--quiet)

echo "---------------------------------------------------"
echo "   Hugging Face Warehouse: Sequential Sync         "
echo "   Into: $HF_HOME"
echo "---------------------------------------------------"

# 2. Processing Loop
# Lines are "org/model", or "GATED|org/model" for models that need a token.
FAILED=()
SKIPPED=()
while read -r line || [ -n "$line" ]; do
    line="${line%%#*}"
    line="$(echo "$line" | tr -d ' \r\t')"
    [ -z "$line" ] && continue

    REPO="${line##*|}"
    GATED=false
    [[ "$line" == GATED\|* ]] && GATED=true

    if [ "$GATED" = true ] && [ -z "${HF_TOKEN:-}" ]; then
        echo "SKIPPED (gated, needs HF_TOKEN in .env): $REPO"
        SKIPPED+=("$REPO")
        echo "---------------------------------------------------"
        continue
    fi

    echo "SYNCING: $REPO"

    # 3. Execution: one model at a time, in the order of models.txt
    if uv run hf download "$REPO" "${DOWNLOAD_ARGS[@]}" < /dev/null; then
        echo "COMPLETED: $REPO"
    else
        echo "FAILED: $REPO"
        FAILED+=("$REPO")
    fi
    echo "---------------------------------------------------"
done < "$MODELS_FILE"

# 4. Summary
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
