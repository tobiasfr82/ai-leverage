#!/usr/bin/env bash
# ==============================================================================
# ICM MULTI-MODEL SPECIFICATION COMPILER (DYNAMIC DOCKER COMPOSE PARSING WITH SUDO)
# Usage: ./build_specs.sh [--dry-run | -d]
# ==============================================================================
set -euo pipefail

# 1. DYNAMIC PATH RESOLUTION
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SPECS_DIR="${SCRIPT_DIR}/specs"
COMPOSE_FILE="${SCRIPT_DIR}/compose.yaml"

if [ ! -d "$SPECS_DIR" ]; then
    echo "Error: Specification directory context not found at target: '$SPECS_DIR'"
    exit 1
fi

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "Error: Required configuration 'compose.yaml' is missing from '$SCRIPT_DIR'."
    exit 1
fi

# 2. DYNAMIC CONTAINER NAME EXTRACTION
# Extracts the raw value from compose and uses tr to clean up quotes and spaces safely
RAW_CONTAINER_NAME=$(awk '
    /^[[:space:]]*ollama:/ { inside=1; next }
    inside && /^[[:space:]]*container_name:/ {
        sub(/^[[:space:]]*container_name:[[:space:]]*/, "");
        print;
        exit
    }
    inside && /^[[:space:]]*[a-zA-Z0-9_-]+:/ && !/^[[:space:]]*(container_name|image|volumes|ports|environment|networks|deploy|labels|restart|devices|gpus|privileged):/ {
        inside=0
    }
' "$COMPOSE_FILE")

CONTAINER_NAME=$(echo "$RAW_CONTAINER_NAME" | tr -d '"'\''[:space:]')

# Fallback mechanism if container_name is omitted from compose.yaml
if [ -z "$CONTAINER_NAME" ]; then
    CONTAINER_NAME="ollama"
fi

# 3. PARSE VERIFICATION FLAGS
DRY_RUN=false
if [[ "${1:-}" == "--dry-run" || "${1:-}" == "-d" ]]; then
    DRY_RUN=true
fi

# 4. COLLECT SPECIFICATION TARGETS
shopt -s nullglob
SPEC_FILES=("${SPECS_DIR}"/*.model)
shopt -u nullglob

if [ ${#SPEC_FILES[@]} -eq 0 ]; then
    echo "No matching specification profiles (*.model) discovered in '$SPECS_DIR'."
    exit 0
fi

# 5. INITIALIZE USER INTERFACE BANNER (Executed before any sudo traps)
echo "======================================================================"
if [ "$DRY_RUN" = true ]; then
    echo " ICM PIPELINE: RUNNING IN DRY-RUN / VERIFICATION MODE"
else
    echo " ICM PIPELINE: INITIALIZING ACTIVE COMPILE PHASE (SUDO DOCKER)"
fi
echo " Target Container:  $CONTAINER_NAME (Extracted from compose.yaml)"
echo " Discovered ${#SPEC_FILES[@]} profile recipe(s) inside '$SPECS_DIR'"
echo "======================================================================"

# 6. PRE-FLIGHT CONTAINER CHECK WITH EXPLICIT SUDO NOTICE
if [ "$DRY_RUN" = false ]; then
    echo "System: Requesting administrative privileges (sudo) to query the Docker daemon..."
    if ! sudo docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo "Error: Target Docker container '${CONTAINER_NAME}' is not running."
        echo "Please launch your stack before executing this compiler."
        exit 1
    fi
    echo "System: Connection to Docker daemon verified."
    echo "----------------------------------------------------------------------"
fi

# 7. BATCH PROCESS ENGINE ITERATION
for SPEC_PATH in "${SPEC_FILES[@]}"; do
    FILENAME=$(basename "$SPEC_PATH")
    BASE_NAME="${FILENAME%.*}" # Drops the .model suffix

    # Derive naming structure tokens dynamically
    if [[ "$BASE_NAME" == *"_"* ]]; then
        NAMESPACE=$(echo "$BASE_NAME" | cut -d'_' -f1)
        MODEL_PART=$(echo "$BASE_NAME" | cut -d'_' -f2-)
        
        # Switches trailing hyphen size notation (e.g., -30b) to explicit tag identifiers (:30b)
        TAG_NAME=$(echo "$MODEL_PART" | sed 's/-\([0-9]\+b\)/:\1/')
        TARGET_MODEL="${NAMESPACE}/${TAG_NAME}"
    else
        TARGET_MODEL=$(echo "$BASE_NAME" | tr '[:upper:]' '[:lower:]' | sed 's/-\([0-9]\+b\)/:\1/')
    fi

    # Read base dependency safely
    BASE_DEPENDENCY=$(grep -i "^FROM" "$SPEC_PATH" | awk '{print $2}' || echo "UNKNOWN")

    echo "Source File:  $FILENAME"
    echo "Parsed Name:  $TARGET_MODEL"
    echo "Base Engine:  $BASE_DEPENDENCY"
    
    if [ "$DRY_RUN" = true ]; then
        echo "Status:       [DRY RUN] Logic Validated. No actions taken."
        echo "----------------------------------------------------------------------"
        continue
    fi

    echo "Validating baseline dependencies inside container for: $BASE_DEPENDENCY"

    # Query container internal storage
    if ! sudo docker exec -i "$CONTAINER_NAME" ollama list | grep -q "^${BASE_DEPENDENCY}\s"; then
        echo "Base weights absent from container environment. Running fetch routine..."
        if ! sudo docker exec -i "$CONTAINER_NAME" ollama pull "$BASE_DEPENDENCY"; then
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
    if sudo docker exec -i "$CONTAINER_NAME" ollama create "$TARGET_MODEL" -f "$TEMP_CONTAINER_PATH"; then
        echo "Successfully registered engine instance: $TARGET_MODEL"
    else
        echo "Error: Compilation sequence dropped for target model: $TARGET_MODEL"
    fi

    # Clean staging environment
    echo "Cleaning up container staging files..."
    sudo docker exec -i "$CONTAINER_NAME" rm -f "$TEMP_CONTAINER_PATH"
    echo "----------------------------------------------------------------------"
done

if [ "$DRY_RUN" = true ]; then
    echo "Dry-run verification loop completed cleanly."
else
    echo "All active model specification transformations completed."
fi