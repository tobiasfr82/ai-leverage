#!/bin/bash

# ==============================================================================
# HUGGING FACE SYNC SCRIPT (v3.1 - Sequential Mechanical Ed.)
# ==============================================================================

ENV_FILE=".env"
MODELS_FILE="models.txt"

# 1. Parameter Extraction
HF_HOME=$(grep "^HF_HOME=" "$ENV_FILE" | cut -d'=' -f2 | tr -d '"' | tr -d '\r')
HF_TOKEN=$(grep "^HF_TOKEN=" "$ENV_FILE" | cut -d'=' -f2 | tr -d '"' | tr -d '\r')
HF_INCLUDE=$(grep "^HF_INCLUDE=" "$ENV_FILE" | cut -d'=' -f2 | tr -d '"' | tr -d '\r')
HF_EXCLUDE=$(grep "^HF_EXCLUDE=" "$ENV_FILE" | cut -d'=' -f2 | tr -d '"' | tr -d '\r')
HF_QUIET=$(grep "^HF_QUIET=" "$ENV_FILE" | cut -d'=' -f2 | tr -d '"' | tr -d '\r' | tr '[:upper:]' '[:lower:]')

Q_FLAG=""
[[ "$HF_QUIET" == "true" ]] && Q_FLAG="--quiet"

echo "---------------------------------------------------"
echo "   Hugging Face Warehouse: Sequential Sync         "
echo "---------------------------------------------------"

# 2. Processing Loop
# This loop is inherently blocking: it won't start 'n+1' until 'n' finishes.
while read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue

    STATUS=$(echo "$line" | cut -d'|' -f1 | tr -d ' ' | tr -d '\r')
    REPO=$(echo "$line" | cut -d'|' -f2 | tr -d ' ' | tr -d '\r')

    echo "SYNCING [$STATUS]: $REPO"

    # 3. Execution
    # uv run blocks the loop until the process terminates
    uv run --env-file "$ENV_FILE" hf download "$REPO" \
        --include "$HF_INCLUDE" \
        --exclude "$HF_EXCLUDE" \
        $Q_FLAG

    EXIT_CODE=$?

    # 4. Results check
    if [ $EXIT_CODE -eq 0 ]; then
        echo "COMPLETED: $REPO"
    else
        echo "FAILED: $REPO (Exit Code: $EXIT_CODE)"
    fi

    # 5. Cool-down (Mechanical Pause)
    # 2-second pause to ensure all file handles are closed and network resets
    echo "WAITING: Cooling down for 2 seconds..."
    sleep 2
    echo "---------------------------------------------------"

done < "$MODELS_FILE"

echo "   Sync Operation Finished"
echo "---------------------------------------------------"