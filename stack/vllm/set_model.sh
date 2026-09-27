#!/bin/bash
# ai-leverage/stack/vllm/set_model.sh
# Pick which downloaded Hugging Face model vLLM serves. The choice is saved in
# .env (git-ignored), and vLLM can be restarted with it right away.

# Configuration Paths
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
ENV_FILE=".env"
MODELS_DIR="../../models/huggingface/hub"

# --- 1. INITIALIZE & PREVIEW ---
clear
echo "=========================================="
echo "      vLLM - MODEL MANAGEMENT         "
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
# Only models with .safetensors weights: GGUF-only downloads are for Ollama.
models=()
if [ -d "$MODELS_DIR" ]; then
    while IFS= read -r -d '' dir; do
        [ -n "$(find -L "$dir/snapshots" -name '*.safetensors' -print -quit 2>/dev/null)" ] || continue
        folder_name=$(basename "$dir")
        clean_name=$(echo "$folder_name" | sed 's/^models--//' | sed 's/--/\//g')
        models+=("$clean_name")
    done < <(find "$MODELS_DIR" -maxdepth 1 -mindepth 1 -type d -name "models--*" -print0 | sort -z)
fi

if [ ${#models[@]} -eq 0 ]; then
    echo "No models downloaded yet. Add some to stack/huggingface/models.txt and"
    echo "run stack/huggingface/sync_models.sh (manage.sh -> huggingface) first."
    exit 1
fi

# --- 3. SELECTION MENU ---
echo "Please select a model to deploy to vLLM:"
PS3="Selection (1-${#models[@]}): "

select SELECTED_MODEL in "${models[@]}"; do
    if [ -n "$SELECTED_MODEL" ]; then
        if [ "$SELECTED_MODEL" == "$CURRENT_MODEL" ]; then
            echo "Keep current model? No changes needed."
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
        break
    else
        echo "Invalid choice. Please try again."
    fi
done

# Menu closed without a choice (Ctrl+D)
[ -n "$SELECTED_MODEL" ] || exit 0

# --- 5. APPLY ---
read -p "Start vLLM with this model now? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    ../../src/bash/docker-create-network.sh && sudo docker compose up -d
    echo "Loading a model takes a few minutes. Follow it in manage.sh -> vllm -> View logs."
else
    echo "Start vLLM (manage.sh -> vllm -> Start) when ready."
fi
