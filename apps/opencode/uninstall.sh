#!/bin/bash
# ai-leverage/apps/opencode/uninstall.sh

BIN_PATH="$HOME/.opencode/bin/opencode"

clear
echo "┌── AI-leverage: Uninstalling OpenCode"

# 1. Check if it actually exists
if [ ! -f "$BIN_PATH" ]; then
    echo "●  OpenCode binary not found at $BIN_PATH"
    echo "└── Aborted. Nothing to uninstall."
    echo "●  Note: User configurations and data are preserved in ~/.opencode"
    echo "●  This is standard Linux behavior - uninstallers typically preserve user data."
    echo "●  If you want to remove ALL OpenCode data, run:"
    echo "●    rm -rf ~/.opencode"    
    exit 0
fi

echo "●  Launching native OpenCode uninstaller..."
echo "│"

# 2. Hand over control to the native interactive uninstaller
"$BIN_PATH" uninstall

# 3. Post-uninstall cleanup
# Remove just the binary (not user data) to follow best practices
echo "│"
echo "●  Performing AI-leverage: Opencode final cleanup..."
rm -f "$BIN_PATH" 2>/dev/null

# 4. Inform user about what was done and what's preserved
echo "└── ✓ OpenCode binary removed."
echo "●  Note: User configurations and data are preserved in ~/.opencode"
echo "●  This is standard Linux behavior - uninstallers typically preserve user data."
echo "●  If you want to remove ALL OpenCode data, run:"
echo "●    rm -rf ~/.opencode"
