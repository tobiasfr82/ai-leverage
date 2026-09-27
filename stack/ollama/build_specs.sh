#!/usr/bin/env bash
# ==============================================================================
# ICM MULTI-MODEL SPECIFICATION COMPILER
# Builds a custom Ollama model from every specs/*.model file.
# Usage: ./build_specs.sh [--dry-run | -d | --list]
#   --dry-run  show what would be built, change nothing
#   --list     print the model names the specs produce and the base models they
#              need, one per line (sync_models.sh uses this to keep them)
# ==============================================================================
set -euo pipefail

# 1. PATH RESOLUTION
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "$SCRIPT_DIR/../.." && pwd)
SPECS_DIR="${SCRIPT_DIR}/specs"
CONTAINER_NAME="ollama"

# 2. NAMING CONVENTION
# "icm-crew_gemma4-31b.model" -> "icm-crew/gemma4:31b"
# The part before the first "_" becomes the namespace, and a trailing size such
# as "-31b" becomes the tag.
spec_target() {
    local base_name
    base_name=$(basename "$1" .model)
    if [[ "$base_name" == *"_"* ]]; then
        local namespace="${base_name%%_*}"
        local model_part="${base_name#*_}"
        echo "${namespace}/$(echo "$model_part" | sed 's/-\([0-9]\+b\)/:\1/')"
    else
        echo "$base_name" | tr '[:upper:]' '[:lower:]' | sed 's/-\([0-9]\+b\)/:\1/'
    fi
}

# The model named on the spec's FROM line
spec_base() {
    awk 'toupper($1) == "FROM" { print $2; exit }' "$1"
}

# 3. PARSE FLAGS
MODE="build"
case "${1:-}" in
    --dry-run|-d) MODE="dry-run" ;;
    --list)       MODE="list" ;;
    "")           ;;
    *) echo "Usage: ./build_specs.sh [--dry-run | -d | --list]"; exit 1 ;;
esac

# 4. COLLECT SPECIFICATION TARGETS
shopt -s nullglob
SPEC_FILES=("${SPECS_DIR}"/*.model)
shopt -u nullglob

if [ "$MODE" = "list" ]; then
    for SPEC_PATH in ${SPEC_FILES[@]+"${SPEC_FILES[@]}"}; do
        spec_target "$SPEC_PATH"
        spec_base "$SPEC_PATH"
    done
    exit 0
fi

if [ ${#SPEC_FILES[@]} -eq 0 ]; then
    echo "No specification profiles (*.model) found in '$SPECS_DIR'."
    exit 0
fi

# 5. BANNER (printed before anything asks for sudo)
echo "======================================================================"
if [ "$MODE" = "dry-run" ]; then
    echo " ICM PIPELINE: RUNNING IN DRY-RUN / VERIFICATION MODE"
else
    echo " ICM PIPELINE: INITIALIZING ACTIVE COMPILE PHASE (SUDO DOCKER)"
fi
echo " Target Container:  $CONTAINER_NAME"
echo " Discovered ${#SPEC_FILES[@]} profile recipe(s) inside '$SPECS_DIR'"
echo "======================================================================"

# 6. MAKE SURE OLLAMA IS RUNNING
if [ "$MODE" = "build" ]; then
    echo "System: Requesting administrative privileges (sudo) to query the Docker daemon..."
    if ! sudo docker exec "$CONTAINER_NAME" ollama list > /dev/null 2>&1; then
        echo "System: Ollama is not running. Starting it..."
        "$REPO_DIR/src/bash/docker-create-network.sh"
        (cd "$SCRIPT_DIR" && sudo docker compose up -d)
        for _ in $(seq 30); do
            sudo docker exec "$CONTAINER_NAME" ollama list > /dev/null 2>&1 && break
            sleep 2
        done
        if ! sudo docker exec "$CONTAINER_NAME" ollama list > /dev/null 2>&1; then
            echo "Error: Ollama did not start. Check its logs (manage.sh -> ollama -> View logs)."
            exit 1
        fi
    fi
    echo "System: Connection to Docker daemon verified."
    echo "----------------------------------------------------------------------"
fi

# 7. BATCH PROCESS ENGINE ITERATION
for SPEC_PATH in "${SPEC_FILES[@]}"; do
    FILENAME=$(basename "$SPEC_PATH")
    TARGET_MODEL=$(spec_target "$SPEC_PATH")
    BASE_DEPENDENCY=$(spec_base "$SPEC_PATH")

    echo "Source File:  $FILENAME"
    echo "Parsed Name:  $TARGET_MODEL"
    echo "Base Engine:  ${BASE_DEPENDENCY:-UNKNOWN}"

    if [ "$MODE" = "dry-run" ]; then
        echo "Status:       [DRY RUN] Logic Validated. No actions taken."
        echo "----------------------------------------------------------------------"
        continue
    fi

    if [ -z "$BASE_DEPENDENCY" ]; then
        echo "Error: '$FILENAME' has no FROM line. Skipping target."
        echo "----------------------------------------------------------------------"
        continue
    fi

    echo "Validating baseline dependencies inside container for: $BASE_DEPENDENCY"

    # Query container internal storage
    if ! sudo docker exec "$CONTAINER_NAME" ollama list | grep -q "^${BASE_DEPENDENCY}\s"; then
        echo "Base weights absent from container environment. Running fetch routine..."
        if ! sudo docker exec "$CONTAINER_NAME" ollama pull "$BASE_DEPENDENCY"; then
            echo "Network Failure: Unable to fetch weights for '$BASE_DEPENDENCY' inside container. Skipping target."
            continue
        fi
    else
        echo "Base weights validated in container storage cache."
    fi

    # Stage specification file inside container
    TEMP_CONTAINER_PATH="/tmp/${FILENAME}.modelfile"
    echo "Staging specification manifest inside container: $TEMP_CONTAINER_PATH"
    sudo docker cp "$SPEC_PATH" "${CONTAINER_NAME}:${TEMP_CONTAINER_PATH}"

    # Compile the target engine
    echo "Building custom engine signature inside container..."
    if sudo docker exec "$CONTAINER_NAME" ollama create "$TARGET_MODEL" -f "$TEMP_CONTAINER_PATH"; then
        echo "Successfully registered engine instance: $TARGET_MODEL"
    else
        echo "Error: Compilation sequence dropped for target model: $TARGET_MODEL"
    fi

    # Clean staging environment
    echo "Cleaning up container staging files..."
    sudo docker exec "$CONTAINER_NAME" rm -f "$TEMP_CONTAINER_PATH"
    echo "----------------------------------------------------------------------"
done

if [ "$MODE" = "dry-run" ]; then
    echo "Dry-run verification loop completed cleanly."
else
    echo "All active model specification transformations completed."
fi
