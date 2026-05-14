#!/bin/bash

# 1. Path Discovery (Portable)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../" && pwd)"
MODELS_DIR="$ROOT_DIR/models/hf_hub"
CONTAINER_NAME="docling"

# 2. Preparation
echo "--- Preparing Centralized Models Directory ---"
# Create the directory if it's missing
mkdir -p "$MODELS_DIR"

# Temporarily open permissions so the Root container can write the initial files
# We use 777 here specifically for the download phase to prevent Errno 13
sudo chmod -R 777 "$MODELS_DIR"

# 3. Execution
cd "$SCRIPT_DIR"
echo "Starting stack..."
sudo docker compose up -d

echo "Pulling Docling weights (this may take a moment)..."
# We execute the download command inside the container
sudo docker exec -it $CONTAINER_NAME docling-tools models download --all

# 4. Reclaim Ownership
echo "Download complete. Reclaiming ownership for $USER..."
# This changes all files from Root/1001 back to Tobias
sudo chown -R $USER:$USER "$MODELS_DIR"
# Set standard permissions (755 for dirs, 644 for files)
sudo find "$MODELS_DIR" -type d -exec chmod 755 {} +
sudo find "$MODELS_DIR" -type f -exec chmod 644 {} +

echo "--- Sync Complete: Models are ready and secure ---"