#!/bin/bash
# ai-leverage/apps/opencode/install.sh

# 1. Setup Variables
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$REPO_DIR/install.log"
BIN_PATH="$HOME/.opencode/bin/opencode"

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
# The installer puts it in ~/.opencode/bin, which only reaches PATH in a new
# terminal, so look there too; otherwise a second run right after installing
# would install it again.
if command -v opencode &> /dev/null || [ -x "$BIN_PATH" ]; then
    echo "●  ✓ OpenCode is already installed. Skipping download."
else
    # 3. Download the Installer Safely
    echo "●  Downloading official OpenCode installer..."
    INSTALLER="$(mktemp)"
    trap 'rm -f "$INSTALLER"' EXIT
    if ! curl -fsSL https://opencode.ai/install -o "$INSTALLER"; then
        echo "└── ✗ Could not download the installer."
        exit 1
    fi

    # 4. Execute, display live output, AND log it
    echo "●  Running installer:"
    echo "│" # Visual spacer

    bash "$INSTALLER" 2>&1 | tee "$LOG_FILE"
    # Saved right away: PIPESTATUS[0] is the installer's exit code, not tee's,
    # and the next command would overwrite it
    STATUS=${PIPESTATUS[0]}

    echo "│" # Visual spacer

    # 5. Verify Success
    if [ "$STATUS" -eq 0 ]; then
        echo "●  ✓ OpenCode binary installed successfully."
        echo "●  Open a new terminal to use the 'opencode' command."
    else
        echo "└── ✗ Installation failed. Please check $LOG_FILE for details."
        exit 1
    fi
fi

echo "└── Installation complete."