#!/bin/bash
# ai-leverage/apps/obsidian/uninstall.sh
# Usage: ./uninstall.sh
set -euo pipefail

# 1. Setup Variables
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$REPO_DIR/${BASH_SOURCE[0]##*/}"
LOG_FILE="$REPO_DIR/uninstall.log"
FLATPAK_ID="md.obsidian.Obsidian"
DEB_PACKAGE="obsidian"
FLATPAK_DATA_DIR="$HOME/.var/app/$FLATPAK_ID"
DEB_CONFIG_DIR="$HOME/.config/obsidian"

# 2. Drop back to the invoking user when started through sudo
# A Flatpak '--user' installation belongs to one specific user. Running the whole
# script as root would inspect root's installation and report "not installed" while
# the app is still in the desktop user's launcher. The .deb path calls sudo on its
# own where it needs root.
if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    echo "●  Started with sudo. Flatpak user installations belong to '$SUDO_USER', not root."
    echo "●  Re-running as '$SUDO_USER' (the .deb path still elevates on its own)."
    exec sudo -u "$SUDO_USER" -- bash "$SCRIPT_PATH" ${1+"$@"}
fi

clear 2>/dev/null || true
echo "┌── AI-leverage: Uninstalling Obsidian"

# 3. Start a fresh log for this run
# An earlier run under 'sudo' can leave a root-owned log behind. Logging must never
# be the reason the uninstall itself fails, so fall back to a temp file instead.
LOG_HEADER="=== AI-leverage: Obsidian uninstall - $(date -Is) ==="
# The subshell keeps bash's own redirection error off the console
if ! ( echo "$LOG_HEADER" > "$LOG_FILE" ) 2>/dev/null; then
    echo "●  Note: '$LOG_FILE' is not writable (left by an earlier sudo run?)."
    LOG_FILE="$(mktemp -t "obsidian-uninstall-XXXXXX.log")"
    echo "●  Logging to $LOG_FILE instead."
    echo "$LOG_HEADER" > "$LOG_FILE"
fi

REMOVED=false

# 4. Remove the Flatpak, user scope first and then system scope
if command -v flatpak &> /dev/null; then
    for SCOPE in user system; do
        if flatpak info "--$SCOPE" "$FLATPAK_ID" &> /dev/null; then
            echo "●  Removing $SCOPE Flatpak $FLATPAK_ID..."
            echo "│" # Visual spacer

            # 'pipefail' is set, so this 'if' reflects flatpak's exit code, not tee's
            if flatpak uninstall -y "--$SCOPE" "$FLATPAK_ID" 2>&1 | tee -a "$LOG_FILE"; then
                echo "│" # Visual spacer
                echo "●  ✓ Flatpak removed ($SCOPE scope)."
                REMOVED=true
            else
                echo "│" # Visual spacer
                echo "└── ✗ Failed to remove the $SCOPE Flatpak. Please check $LOG_FILE for details."
                exit 1
            fi
        fi
    done
fi

# 5. Remove the .deb package
if command -v dpkg-query &> /dev/null && dpkg-query -W -f='${Status}' "$DEB_PACKAGE" 2>/dev/null | grep -q "install ok installed"; then
    echo "●  Removing the '$DEB_PACKAGE' .deb package (sudo required):"
    echo "│" # Visual spacer

    if sudo apt-get remove -y "$DEB_PACKAGE" 2>&1 | tee -a "$LOG_FILE"; then
        echo "│" # Visual spacer
        echo "●  ✓ .deb package removed."
        REMOVED=true
    else
        echo "│" # Visual spacer
        echo "└── ✗ Failed to remove the .deb package. Please check $LOG_FILE for details."
        exit 1
    fi
fi

# 6. Nothing found means nothing to do, so re-runs stay safe
if [ "$REMOVED" = false ]; then
    # install.sh also accepts a bare 'obsidian' on PATH as installed, so report that
    # honestly here instead of claiming the app is absent when it plainly is not.
    OTHER_BIN="$(command -v obsidian 2>/dev/null || true)"

    if [ -n "$OTHER_BIN" ]; then
        echo "●  Obsidian is installed outside Flatpak and apt, at: $OTHER_BIN"
        echo "●  That is an AppImage, snap or tarball install, which this script does not manage."
        echo "└── Aborted. Remove it with whatever created it, e.g. 'sudo snap remove obsidian'."
    else
        echo "●  Obsidian is not installed for user '$(id -un)'."
        echo "●  Checked: Flatpak user scope, Flatpak system scope, and the '$DEB_PACKAGE' .deb package."
        echo "└── Aborted. Nothing to uninstall."
        echo "●  Note: Flatpak user installations are per-user. If the app still shows up in your"
        echo "●  launcher, run this script as the user who owns it - check with:"
        echo "●    flatpak list --app | grep -i obsidian"
    fi

    echo "●  Your vaults and their per-vault settings in <vault>/.obsidian are untouched."
    exit 0
fi

# 7. Inform user about what was done and what's preserved
echo "└── ✓ Obsidian application removed."
echo "●  Note: Your vaults and their per-vault settings in <vault>/.obsidian are untouched."
echo "●  This is standard Linux behavior - uninstallers typically preserve user data."
echo "●  If you want to remove ALL Obsidian app data, run:"
echo "●    Flatpak: rm -rf \"$FLATPAK_DATA_DIR\""
echo "●    .deb:    rm -rf \"$DEB_CONFIG_DIR\""
