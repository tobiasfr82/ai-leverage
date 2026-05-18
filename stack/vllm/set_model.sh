#!/bin/bash

# Configuration Paths
ENV_FILE=".env"
MODELS_DIR="../../models/huggingface/hub"

# --- 1. INITIALIZE & PREVIEW ---
clear
echo "=========================================="
echo "      vLLM - MODEL MANAGEMENT         "
echo "=========================================="

# Check if .env exists and get current model
if [ -f "$ENV_FILE" ]; then
    # Extract value using grep/cut to avoid sourcing the whole file
    CURRENT_MODEL=$(grep "^HUGGINGFACE_MODEL=" "$ENV_FILE" | cut -d'"' -f2)
fi

# Display current status using a "Best Practice" header
if [ -z "$CURRENT_MODEL" ]; then
    echo -e "STATUS: \033[1;33mNo model currently selected\033[0m"
else
    echo -e "STATUS: \033[1;32mActive Model -> $CURRENT_MODEL\033[0m"
fi
echo "------------------------------------------"

# --- 2. SCAN FOR MODELS ---
if [ ! -d "$MODELS_DIR" ]; then
    echo "ERROR: Model directory not found at $MODELS_DIR"
    exit 1
fi

models=()
while IFS= read -r -d '' dir; do
    folder_name=$(basename "$dir")
    clean_name=$(echo "$folder_name" | sed 's/^models--//' | sed 's/--/\//g')
    models+=("$clean_name")
done < <(find "$MODELS_DIR" -maxdepth 1 -mindepth 1 -type d -name "models--*" -print0)

if [ ${#models[@]} -eq 0 ]; then
    echo "No models found in warehouse. Check your download path."
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

        # Surgical update logic
        touch "$ENV_FILE"
        if grep -q "^HUGGINGFACE_MODEL=" "$ENV_FILE"; then
            sed -i "s|^HUGGINGFACE_MODEL=.*|HUGGINGFACE_MODEL=\"$SELECTED_MODEL\"|" "$ENV_FILE"
        else
            echo "HUGGINGFACE_MODEL=\"$SELECTED_MODEL\"" >> "$ENV_FILE"
        fi
        
        # --- 4. TERMINATION ---
        echo "------------------------------------------"
        echo -e "Configuration saved: \033[1;34m$SELECTED_MODEL\033[0m"
        echo "Stop and start vllm when ready."
        echo "------------------------------------------"
        break
    else
        echo "Invalid choice. Please try again."
    fi
done