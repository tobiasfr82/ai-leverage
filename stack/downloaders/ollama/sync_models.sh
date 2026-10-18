#!/bin/bash
# ai-leverage/stack/downloaders/ollama/sync_models.sh
# Downloads every model in models.txt into the shared models/ollama folder,
# then builds the custom models in specs/.
#
# A downloaded model that's no longer listed: it asks whether to delete it,
# before downloading anything, in the terminal or, run from the menu, in its
# notification. Run where nobody can answer, it keeps it and names it at the
# end. The custom models from specs/ (build_specs.sh) and the base models
# they're built on count as listed. It downloads with a temporary Ollama of its own (temporary_ollama.sh),
# so the Ollama engine can stay as it is, running or not.
# Usage: ./sync_models.sh [--remove-unlisted]
#   --remove-unlisted  only asks about the unlisted models, and deletes the ones you say
#
# menu: console   (the menu shows what it prints without leaving the menu, and asks in its notification)

# Configuration
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
REPO_DIR="$(cd ../../.. && pwd)"
MODEL_FILE="models.txt"
source ./temporary_ollama.sh
# shellcheck source=../../../src/bash/ask.sh
source "$REPO_DIR/src/bash/ask.sh"

REMOVE_ONLY=false
[ "$1" == "--remove-unlisted" ] && REMOVE_ONLY=true
if $REMOVE_ONLY && ! can_ask; then
    echo "Removing unlisted models asks about each one, so it runs in a terminal or from the menu."
    exit 1
fi

if [ ! -f "$MODEL_FILE" ]; then
    echo "Error: $MODEL_FILE not found"
    exit 1
fi

# Sudo Keep-alive: update existing sudo timestamp until script finishes
# Downloading models can take a very long while. This prevents the download to pause pending sudo input.
# Not on its output, which would stay open after the script ends, while the loop sleeps
while true; do sudo -n true; sleep 60; kill -0 "$$" || exit; done > /dev/null 2>&1 &

# True when the first argument equals any of the others
contains() {
    local item="$1"; shift
    local x
    for x in "$@"; do [ "$x" == "$item" ] && return 0; done
    return 1
}

# 1. Start the temporary Ollama & wait until it answers
start_downloader "$REPO_DIR" "$PWD/specs" || exit 1

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

# 3. Get Current Local Models, with their size ("qwen3:8b<tab>5.2 GB")
declare -A SIZE_OF
CURRENT_MODELS=()
while IFS=$'\t' read -r name size; do
    CURRENT_MODELS+=("$name")
    SIZE_OF[$name]=$size
done < <(ollama_cmd list | tail -n +2 | awk '{ print $1 "\t" $3 " " $4 }')

# The downloaded models that aren't in models.txt or specs/
UNLISTED=()
for current in "${CURRENT_MODELS[@]}"; do
    contains "$current" "${DESIRED_MODELS[@]}" "${SPEC_MODELS[@]}" || UNLISTED+=("$current")
done

# --- STAGE 1: USER INPUT (Deletions) ---
# In the terminal, or in its notification when run from the menu; where nobody can answer, none
DELETION_QUEUE=()
if can_ask; then
    for current in "${UNLISTED[@]}"; do
        if ask_yes_no "$current (${SIZE_OF[$current]}) isn't in models.txt. Delete it?" "delete it" "keep it"; then
            DELETION_QUEUE+=("$current")
        fi
    done
fi

# --- STAGE 2: EXECUTION ---
$REMOVE_ONLY || echo -e "\n--- Starting Sync Operations ---"

# Handle Deletions first
for target in "${DELETION_QUEUE[@]}"; do
    echo "Removing: $target..."
    ollama_cmd rm "$target"
done
if $REMOVE_ONLY; then
    [ ${#UNLISTED[@]} -eq 0 ] && echo "Every downloaded model is in models.txt or specs/."
    exit 0
fi

# Handle Sequential Downloads
FAILED=()
for model in "${DESIRED_MODELS[@]}"; do
    if contains "$model" "${CURRENT_MODELS[@]}"; then
        echo "[ SKIP ] $model is already up to date."
        continue
    fi
    echo -e "\n[ SYNC ] Pulling new model: $model"
    ollama_cmd pull "$model" || FAILED+=("$model")
done

# --- STAGE 3: CUSTOM MODELS ---
if [ ${#SPEC_MODELS[@]} -gt 0 ]; then
    echo -e "\n--- Building custom models from specs/ ---"
    ./build_specs.sh
fi

# The unlisted ones it kept, when nobody could be asked
if ! can_ask && [ ${#UNLISTED[@]} -gt 0 ]; then
    echo -e "\n--- Not in models.txt any more, kept: ---"
    for model in "${UNLISTED[@]}"; do
        echo "  $model (${SIZE_OF[$model]})"
    done
    echo "Remove unlisted models (remove_unlisted_models.sh) asks whether to delete them, in a terminal or from the menu."
fi

if [ ${#FAILED[@]} -gt 0 ]; then
    echo -e "\n--- Done, but these models could not be pulled: ---"
    printf '  %s\n' "${FAILED[@]}"
    echo "Check the spelling in models.txt, or whether the model exists on ollama.com."
    exit 1
fi
echo -e "\n--- All operations complete. System is in sync. ---"
