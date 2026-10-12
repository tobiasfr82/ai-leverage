#!/bin/bash
# ai-leverage/src/bash/pick-huggingface-model.sh
# Pick which downloaded Hugging Face model an engine serves. Every engine that
# runs one .safetensors model at a time (vLLM, SGLang) calls this from its own
# set_model.sh, inside its own folder. The choice is saved in that folder's .env
# (git-ignored), and the engine can be restarted with it right away.
# The engines never go online, so the list also shows what a download is
# missing, and which models in the downloader's models.txt aren't here yet.
# Usage: pick-huggingface-model.sh <engine name to show, e.g. vLLM>

ENGINE_NAME="${1:?usage: pick-huggingface-model.sh <engine name>}"
# The engine's folder, as the menu names it
ENGINE_FOLDER="$(basename "$PWD")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Configuration Paths
ENV_FILE=".env"
MODELS_DIR="$SCRIPT_DIR/../../models/huggingface/hub"
MODELS_LIST="$SCRIPT_DIR/../../stack/downloaders/huggingface/models.txt"

# --- 1. INITIALIZE & PREVIEW ---
clear
echo "=========================================="
echo "      $ENGINE_NAME - MODEL MANAGEMENT         "
echo "=========================================="

# Check if .env exists and get current model
CURRENT_MODEL=""
if [ -f "$ENV_FILE" ]; then
    # Extract value using grep/cut to avoid sourcing the whole file
    CURRENT_MODEL=$(grep "^HUGGINGFACE_MODEL=" "$ENV_FILE" | cut -d'=' -f2- | tr -d "\"'\r")
fi

# Display current status using a "Best Practice" header
if [ -z "$CURRENT_MODEL" ]; then
    echo -e "STATUS: \033[1;33mNo model currently selected\033[0m"
else
    echo -e "STATUS: \033[1;32mActive Model -> $CURRENT_MODEL\033[0m"
fi
echo "------------------------------------------"

# --- 2. SCAN FOR MODELS ---
# The engines never go online, so a model only runs when the downloader has
# fetched everything it needs. This names what a download lacks, if anything.
missing_parts() {
    local snap=$1 shard missing=""
    [ -e "$snap/config.json" ] || missing+=", config.json"
    # Every weight file the model's index lists
    if [ -e "$snap/model.safetensors.index.json" ]; then
        for shard in $(grep -o '"[^"]*\.safetensors"' "$snap/model.safetensors.index.json" | tr -d '"' | sort -u); do
            [ -e "$snap/$shard" ] || { missing+=", some weights"; break; }
        done
    fi
    if [ ! -e "$snap/tokenizer.json" ] && [ ! -e "$snap/vocab.json" ] \
        && [ -z "$(find -L "$snap" -maxdepth 1 \( -name '*.model' -o -name '*.tiktoken' \) -print -quit 2>/dev/null)" ]; then
        missing+=", tokenizer"
    fi
    # Without a chat template the engine starts, but can't chat
    if [ ! -e "$snap/chat_template.jinja" ] && [ ! -e "$snap/chat_template.json" ] \
        && ! grep -q '"chat_template"' "$snap/tokenizer_config.json" 2>/dev/null; then
        missing+=", chat template"
    fi
    echo "${missing#, }"
}

# Downloads with .safetensors weights: GGUF-only downloads are for llama.cpp.
# The engines load the version refs/main points at.
models=()
labels=()
missing_of=()
if [ -d "$MODELS_DIR" ]; then
    while IFS= read -r -d '' dir; do
        snap="$dir/snapshots/$(cat "$dir/refs/main" 2>/dev/null)"
        [ -n "$(find -L "$snap" -maxdepth 1 -name '*.safetensors' -print -quit 2>/dev/null)" ] || continue
        folder_name=$(basename "$dir")
        clean_name=$(echo "$folder_name" | sed 's/^models--//' | sed 's/--/\//g')
        missing=$(missing_parts "$snap")
        models+=("$clean_name")
        missing_of+=("$missing")
        label=$clean_name
        [ "$clean_name" == "$CURRENT_MODEL" ] && label+="  (current)"
        [ -n "$missing" ] && label+="  (missing: $missing)"
        labels+=("$label")
    done < <(find "$MODELS_DIR" -maxdepth 1 -mindepth 1 -type d -name "models--*" -print0 | sort -z)
fi

# Models the downloader's list asks for that aren't here yet. Lines with a
# size ("org/model:Q4_K_M") are GGUF models for llama.cpp, not for this engine.
not_downloaded=()
if [ -f "$MODELS_LIST" ]; then
    while read -r line || [ -n "$line" ]; do
        line="${line%%#*}"
        line="$(echo "$line" | tr -d ' \r\t')"
        line="${line##*|}"
        [ -z "$line" ] && continue
        [[ "$line" == *:* ]] && continue
        [[ " ${models[*]} " == *" $line "* ]] || not_downloaded+=("$line")
    done < "$MODELS_LIST"
fi

if [ ${#models[@]} -eq 0 ]; then
    echo "No models downloaded yet. Add some to stack/downloaders/huggingface/models.txt"
    echo "and run its sync_models (manage.sh -> huggingface -> sync_models) first."
    exit 1
fi

if [ ${#not_downloaded[@]} -gt 0 ] || [[ "${labels[*]}" == *"(missing: "* ]]; then
    for model in "${not_downloaded[@]}"; do
        echo -e "\033[1;33mNot downloaded yet:\033[0m $model"
    done
    echo "$ENGINE_NAME only runs what is downloaded. To fetch what's not downloaded or"
    echo "marked missing, run manage.sh -> huggingface -> sync_models. If files stay"
    echo "missing, check HF_INCLUDE in stack/downloaders/huggingface/.env."
    echo "------------------------------------------"
fi

# --- 3. SELECTION MENU ---
# One model per line, like the menus in manage.sh
echo "Please select a model to deploy to $ENGINE_NAME:"
echo
for i in "${!labels[@]}"; do
    printf '%2d) %s\n' $((i + 1)) "${labels[$i]}"
done
echo "------------------------------------------"
echo " b) Go back"
echo "------------------------------------------"

SELECTED_MODEL=""
while [ -z "$SELECTED_MODEL" ]; do
    # Ctrl+D goes back too
    read -p "Selection: " -r choice || { echo; exit 0; }
    [[ "$choice" =~ ^[Bb]$ ]] && exit 0
    if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt ${#models[@]} ]; then
        echo "Invalid choice. Please try again."
        continue
    fi
    missing=${missing_of[$((choice - 1))]}
    if [ -n "$missing" ]; then
        echo "This download is missing: $missing. $ENGINE_NAME can't run it properly."
        read -p "Choose it anyway? (y/N): " -r confirm
        [[ "$confirm" =~ ^[Yy]$ ]] || { echo "Pick another model, or b to go back."; continue; }
    fi
    SELECTED_MODEL=${models[$((choice - 1))]}
done

if [ "$SELECTED_MODEL" == "$CURRENT_MODEL" ]; then
    echo "That is the current model already. Nothing changed."
    exit 0
fi

# First run: start from the template so every setting is documented
[ -f "$ENV_FILE" ] || cp .env.template "$ENV_FILE"

# Surgical update logic
if grep -q "^HUGGINGFACE_MODEL=" "$ENV_FILE"; then
    sed -i "s|^HUGGINGFACE_MODEL=.*|HUGGINGFACE_MODEL=\"$SELECTED_MODEL\"|" "$ENV_FILE"
else
    echo "HUGGINGFACE_MODEL=\"$SELECTED_MODEL\"" >> "$ENV_FILE"
fi

# --- 4. TERMINATION ---
echo "------------------------------------------"
echo -e "Configuration saved: \033[1;34m$SELECTED_MODEL\033[0m"
echo "------------------------------------------"

# --- 5. APPLY ---
read -p "Start $ENGINE_NAME with this model now? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    "$SCRIPT_DIR/docker-create-network.sh" && sudo docker compose up -d
    echo "Loading a model takes a few minutes. Follow it in manage.sh -> $ENGINE_FOLDER -> View logs."
else
    echo "Start $ENGINE_NAME (manage.sh -> $ENGINE_FOLDER -> Start) when ready."
fi
