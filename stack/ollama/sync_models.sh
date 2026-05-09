#!/bin/bash

# Sudo Keep-alive: update existing sudo timestamp until script finishes
# Downloading models can take a very long while. This prevents the download to pause pending sudo input.
while true; do sudo -n true; sleep 60; kill -0 "$$" || exit; done 2>/dev/null &

# Configuration
cd "$(dirname "$0")"
MODEL_FILE="models.txt"
CONTAINER_NAME="ollama"

# 1. Start stack & Wait for API
sudo docker compose up -d
echo "Checking Ollama status..."
until curl -s http://localhost:11434/api/tags > /dev/null; do sleep 2; done

# 2. Parse Source of Truth (skip comments/empty lines)
if [ ! -f "$MODEL_FILE" ]; then 
    echo "Error: $MODEL_FILE not found"
    exit 1
fi
# Using a mapfile or read is safer for arrays with potential spaces/weird chars
readarray -t DESIRED_MODELS < <(grep -v '^#' "$MODEL_FILE" | grep -v '^$')

# 3. Get Current Local Models
# Removing -t here ensures we get a clean text list
CURRENT_MODELS=($(sudo docker exec $CONTAINER_NAME ollama list | tail -n +2 | awk '{print $1}'))

# --- STAGE 1: USER INPUT (Deletions) ---
DELETION_QUEUE=()
for current in "${CURRENT_MODELS[@]}"; do
    if [[ ! " ${DESIRED_MODELS[@]} " =~ " ${current} " ]]; then
        # Use /dev/tty to ensure read works even if inside a pipe/loop
        read -p "Model '$current' is NOT in models.txt. Delete it? (y/N): " confirm < /dev/tty
        if [[ $confirm == [yY] ]]; then
            DELETION_QUEUE+=("$current")
        fi
    fi
done

# --- STAGE 2: EXECUTION ---
echo -e "\n--- Starting Sync Operations ---"

# Handle Deletions first
for target in "${DELETION_QUEUE[@]}"; do
    echo "Removing: $target..."
    sudo docker exec $CONTAINER_NAME ollama rm "$target"
done

# Handle Sequential Downloads
for model in "${DESIRED_MODELS[@]}"; do
    if [[ ! " ${CURRENT_MODELS[@]} " =~ " ${model} " ]]; then
        echo -e "\n[ SYNC ] Pulling new model: $model"
        
        # FIX: Removed the '-t' flag. 
        # This prevents the 'garbled' terminal codes while still showing progress.
        sudo docker exec $CONTAINER_NAME ollama pull "$model"
    else
        echo "[ SKIP ] $model is already up to date."
    fi
done

echo -e "\n--- All operations complete. System is in sync. ---"