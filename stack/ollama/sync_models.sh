#!/bin/bash
# ai-leverage/stack/ollama/sync_models.sh
# Makes Ollama match models.txt: pulls what is missing, offers to delete what is
# no longer listed, then builds the custom models in specs/ (build_specs.sh).

# Configuration
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
REPO_DIR="$(cd ../.. && pwd)"
MODEL_FILE="models.txt"
CONTAINER_NAME="ollama"

if [ ! -f "$MODEL_FILE" ]; then
    echo "Error: $MODEL_FILE not found"
    exit 1
fi

# Sudo Keep-alive: update existing sudo timestamp until script finishes
# Downloading models can take a very long while. This prevents the download to pause pending sudo input.
while true; do sudo -n true; sleep 60; kill -0 "$$" || exit; done 2>/dev/null &

# True when the first argument equals any of the others
contains() {
    local item="$1"; shift
    local x
    for x in "$@"; do [ "$x" == "$item" ] && return 0; done
    return 1
}

# 1. Start Ollama & wait until it answers
"$REPO_DIR/src/bash/docker-create-network.sh" || exit 1
sudo docker compose up -d || exit 1
echo "Checking Ollama status..."
for _ in $(seq 30); do
    sudo docker exec "$CONTAINER_NAME" ollama list > /dev/null 2>&1 && break
    sleep 2
done
if ! sudo docker exec "$CONTAINER_NAME" ollama list > /dev/null 2>&1; then
    echo "Error: Ollama did not start. Check its logs (manage.sh -> ollama -> View logs)."
    exit 1
fi

# 2. Parse Source of Truth
# One model per line. Comments, blank lines and stray spaces are ignored, and a
# name without a tag gets ":latest", which is how 'ollama list' shows it.
readarray -t DESIRED_MODELS < <(
    sed -e 's/#.*//' -e 's/\r$//' "$MODEL_FILE" | awk 'NF { print $1 }' |
    while read -r model; do
        [[ "${model##*/}" == *:* ]] || model="$model:latest"
        echo "$model"
    done
)

# Custom models from specs/ and the base models they are built on
readarray -t SPEC_MODELS < <(./build_specs.sh --list)

# 3. Get Current Local Models
readarray -t CURRENT_MODELS < <(sudo docker exec "$CONTAINER_NAME" ollama list | tail -n +2 | awk '{ print $1 }')

# --- STAGE 1: USER INPUT (Deletions) ---
DELETION_QUEUE=()
for current in "${CURRENT_MODELS[@]}"; do
    contains "$current" "${DESIRED_MODELS[@]}" "${SPEC_MODELS[@]}" && continue
    # Use /dev/tty to ensure read works even if inside a pipe/loop
    read -p "Model '$current' is NOT in models.txt. Delete it? (y/N): " confirm < /dev/tty
    if [[ $confirm == [yY] ]]; then
        DELETION_QUEUE+=("$current")
    fi
done

# --- STAGE 2: EXECUTION ---
echo -e "\n--- Starting Sync Operations ---"

# Handle Deletions first
for target in "${DELETION_QUEUE[@]}"; do
    echo "Removing: $target..."
    sudo docker exec "$CONTAINER_NAME" ollama rm "$target"
done

# Handle Sequential Downloads
FAILED=()
for model in "${DESIRED_MODELS[@]}"; do
    if contains "$model" "${CURRENT_MODELS[@]}"; then
        echo "[ SKIP ] $model is already up to date."
        continue
    fi
    echo -e "\n[ SYNC ] Pulling new model: $model"
    sudo docker exec "$CONTAINER_NAME" ollama pull "$model" || FAILED+=("$model")
done

# --- STAGE 3: CUSTOM MODELS ---
if [ ${#SPEC_MODELS[@]} -gt 0 ]; then
    echo -e "\n--- Building custom models from specs/ ---"
    ./build_specs.sh
fi

if [ ${#FAILED[@]} -gt 0 ]; then
    echo -e "\n--- Done, but these models could not be pulled: ---"
    printf '  %s\n' "${FAILED[@]}"
    echo "Check the spelling in models.txt, or whether the model exists on ollama.com."
    exit 1
fi
echo -e "\n--- All operations complete. System is in sync. ---"
