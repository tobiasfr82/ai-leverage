#!/bin/bash

# Configuration
cd "$(dirname "$0")"
MODEL_FILE="models.txt"
CONTAINER_NAME="docling" # Matches your compose file
MODELS_DIR="./models"

# Ensure directories exist and have correct permissions for the Docker user (1001)
mkdir -p "$MODELS_DIR"
sudo chown -R 1001:1001 "$MODELS_DIR"

# 1. Start stack
sudo docker compose up -d

# 2. Parse Source of Truth
if [ ! -f "$MODEL_FILE" ]; then 
    echo "Error: $MODEL_FILE not found"
    exit 1
fi
readarray -t DESIRED_MODELS < <(grep -v '^#' "$MODEL_FILE" | grep -v '^$')

# 3. Execution
echo -e "\n--- Starting Docling Model Sync ---"

for model in "${DESIRED_MODELS[@]}"; do
    echo -e "\n[ SYNC ] Ensuring model is available: $model"
    # Docling tools download -i specifies the repo, -o specifies the output dir
    # Inside the container, /models maps to your local ./models folder
    sudo docker exec -u 1001 $CONTAINER_NAME docling-tools models download --all
    
    # Note: Currently, 'docling-tools' doesn't support a specific --repo flag for 'download --all'
    # but it will sync all necessary artifacts for the version installed.
done

echo -e "\n--- Docling is ready. ---"