#!/bin/bash
# ai-leverage/apps/opencode/install.sh

# 1. Setup Variables
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$REPO_DIR/install.log"

clear
echo "●  Initializing paths:"
echo "   - REPO_DIR: $REPO_DIR"
echo "   - LOG_FILE: $LOG_FILE"
echo ""
echo "┌── AI-leverage: Installing OpenCode"

# 2. Pre-flight Check for curl
if ! command -v curl &> /dev/null; then
    echo "●  Error: 'curl' is required to download the installer."
    exit 1
fi

# 2.5 Check if already installed
if command -v opencode &> /dev/null; then
    echo "●  ✓ OpenCode is already installed. Skipping download."
else
    # 3. Download the Installer Safely
    echo "●  Downloading official OpenCode installer..."
    curl -fsSL https://opencode.ai/install > /tmp/opencode_install.sh

    # 4. Execute, display live output, AND log it
    echo "●  Running installer:"
    echo "│" # Visual spacer
    
    bash /tmp/opencode_install.sh 2>&1 | tee "$LOG_FILE"
    
    echo "│" # Visual spacer

    # 5. Verify Success
    # pipestatus[0] gets the exit code of the bash script, ignoring the exit code of 'tee'
    if [ ${PIPESTATUS[0]} -eq 0 ]; then
        echo "●  ✓ OpenCode binary installed successfully."
        rm /tmp/opencode_install.sh
    else
        echo "└── ✗ Installation failed. Please check $LOG_FILE for details."
        exit 1
    fi
fi

echo "└── Step 1 Complete."