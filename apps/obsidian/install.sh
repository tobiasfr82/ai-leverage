#!/bin/bash
# ai-leverage/apps/obsidian/install.sh
# Usage: ./install.sh [--deb]
set -euo pipefail

# 1. Setup Variables
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$REPO_DIR/${BASH_SOURCE[0]##*/}"
LOG_FILE="$REPO_DIR/install.log"
FLATPAK_ID="md.obsidian.Obsidian"
FLATHUB_URL="https://dl.flathub.org/repo/flathub.flatpakrepo"
DEB_PACKAGE="obsidian"
VERSION_URL="https://raw.githubusercontent.com/obsidianmd/obsidian-releases/master/desktop-releases.json"
RELEASE_URL="https://github.com/obsidianmd/obsidian-releases/releases/download"
USE_DEB=false
DEB_REQUESTED=false

# 2. Parse Arguments
# ${1+"$@"} instead of "$@": under 'set -u', bash older than 4.4 treats "$@" as
# unbound when there are no positional parameters, which is the default invocation.
for arg in ${1+"$@"}; do
    case "$arg" in
        --deb)
            USE_DEB=true
            DEB_REQUESTED=true
            ;;
        -h|--help)
            echo "Usage: ./install.sh [--deb]"
            echo "  (default)  Install Obsidian as a Flatpak from Flathub - distro-agnostic and sandboxed."
            echo "  --deb      Install the official .deb via apt instead - Debian/Ubuntu, amd64 only."
            echo ""
            echo "If flatpak is not installed, the .deb path is used automatically, exactly as if"
            echo "--deb had been passed. That install is machine-wide and needs sudo."
            echo ""
            echo "Run this WITHOUT sudo. Flatpak user installations belong to the user who owns"
            echo "them, and the .deb path calls sudo on its own where it actually needs root."
            exit 0
            ;;
        *)
            echo "●  Error: Unknown argument '$arg'. Try './install.sh --help'."
            exit 1
            ;;
    esac
done

# 3. Drop back to the invoking user when started through sudo
# A Flatpak '--user' installation belongs to one specific user. Running the whole
# script as root would install into root's installation, where the desktop user
# would never see it. The .deb path calls sudo on its own where it needs root.
if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    echo "●  Started with sudo. Flatpak user installations belong to '$SUDO_USER', not root."
    echo "●  Re-running as '$SUDO_USER' (the .deb path still elevates on its own)."
    exec sudo -u "$SUDO_USER" -- bash "$SCRIPT_PATH" ${1+"$@"}
fi

clear 2>/dev/null || true
echo "●  Initializing paths:"
echo "   - REPO_DIR: $REPO_DIR"
echo "   - LOG_FILE: $LOG_FILE"
echo ""
echo "┌── AI-leverage: Installing Obsidian"

# 4. Start a fresh log for this run
# An earlier run under 'sudo' can leave a root-owned log behind. Logging must never
# be the reason the install itself fails, so fall back to a temp file instead.
LOG_HEADER="=== AI-leverage: Obsidian install - $(date -Is) ==="
# The subshell keeps bash's own redirection error off the console
if ! ( echo "$LOG_HEADER" > "$LOG_FILE" ) 2>/dev/null; then
    echo "●  Note: '$LOG_FILE' is not writable (left by an earlier sudo run?)."
    LOG_FILE="$(mktemp -t "obsidian-install-XXXXXX.log")"
    echo "●  Logging to $LOG_FILE instead."
    echo "$LOG_HEADER" > "$LOG_FILE"
fi

# 5. Check if already installed
# Any of the three install shapes counts, so re-runs are a no-op.
INSTALLED_VIA=""
if command -v flatpak &> /dev/null && flatpak info "$FLATPAK_ID" &> /dev/null; then
    INSTALLED_VIA="Flatpak ($FLATPAK_ID)"
elif command -v dpkg-query &> /dev/null && dpkg-query -W -f='${Status}' "$DEB_PACKAGE" 2>/dev/null | grep -q "install ok installed"; then
    INSTALLED_VIA=".deb package ($DEB_PACKAGE)"
elif command -v obsidian &> /dev/null; then
    INSTALLED_VIA="$(command -v obsidian)"
fi

if [ -n "$INSTALLED_VIA" ]; then
    echo "●  ✓ Obsidian is already installed for user '$(id -un)' via $INSTALLED_VIA."
    echo "●  Skipping installation."
    echo "└── Installation complete."
    exit 0
fi

# 6. Pick the installation method
# Flatpak is the primary path; the .deb is used on request or when Flatpak is missing.
if [ "$USE_DEB" = false ] && ! command -v flatpak &> /dev/null; then
    echo "●  Flatpak not found. Falling back to the official .deb package."
    USE_DEB=true
fi

if [ "$USE_DEB" = false ]; then
    # 7a. Primary: Flatpak from Flathub
    echo "●  Ensuring the Flathub remote exists..."
    if ! flatpak remote-add --if-not-exists --user flathub "$FLATHUB_URL" 2>&1 | tee -a "$LOG_FILE"; then
        echo "└── ✗ Could not configure the Flathub remote. Please check $LOG_FILE for details."
        exit 1
    fi

    echo "●  Installing $FLATPAK_ID from Flathub (user scope):"
    echo "│" # Visual spacer

    # 'pipefail' is set, so this 'if' reflects flatpak's exit code, not tee's
    if flatpak install -y --user flathub "$FLATPAK_ID" 2>&1 | tee -a "$LOG_FILE"; then
        echo "│" # Visual spacer
        echo "●  ✓ Obsidian Flatpak installed successfully."
    else
        echo "│" # Visual spacer
        echo "└── ✗ Installation failed. Please check $LOG_FILE for details."
        exit 1
    fi
else
    # 7b. Fallback: official .deb from the Obsidian release channel
    if ! command -v curl &> /dev/null; then
        echo "└── ✗ Error: 'curl' is required to download the .deb package."
        exit 1
    fi

    if ! command -v apt-get &> /dev/null; then
        if [ "$DEB_REQUESTED" = true ]; then
            echo "└── ✗ Error: 'apt-get' not found. The .deb fallback needs a Debian/Ubuntu system."
        else
            # Only reachable when flatpak was missing, so pointing at Flatpak is the real fix
            echo "●  Error: neither flatpak nor apt-get is available on this system."
            echo "└── ✗ Install flatpak (e.g. 'sudo dnf install flatpak') and re-run."
        fi
        exit 1
    fi

    ARCH="$(dpkg --print-architecture)"
    if [ "$ARCH" != "amd64" ]; then
        echo "●  Detected architecture: $ARCH"
        echo "●  Obsidian only publishes an amd64 .deb."
        if [ "$DEB_REQUESTED" = true ]; then
            echo "└── ✗ Re-run without --deb to use the Flatpak instead."
        else
            # We are only here because flatpak was missing, so suggesting it would be a dead end
            echo "└── ✗ Install flatpak and re-run, or use the official AppImage/tar.gz for $ARCH."
        fi
        exit 1
    fi

    # Private scratch dir, cleaned up on every exit path
    TMP_DIR="$(mktemp -d)"
    trap 'rm -rf "$TMP_DIR"' EXIT

    echo "●  Resolving the latest Obsidian desktop version..."
    if ! curl -fsSL "$VERSION_URL" -o "$TMP_DIR/desktop-releases.json"; then
        echo "└── ✗ Could not reach $VERSION_URL"
        exit 1
    fi

    VERSION="$(awk -F'"' '/"latestVersion"/ {print $4; exit}' "$TMP_DIR/desktop-releases.json")"
    if [ -z "$VERSION" ]; then
        echo "└── ✗ Could not determine the latest Obsidian version from $VERSION_URL"
        exit 1
    fi

    DEB_FILE="obsidian_${VERSION}_amd64.deb"
    DEB_URL="$RELEASE_URL/v${VERSION}/$DEB_FILE"
    echo "   - Version: $VERSION"
    echo "   - Package: $DEB_URL"

    echo "●  Downloading $DEB_FILE..."
    if ! curl -fsSL "$DEB_URL" -o "$TMP_DIR/$DEB_FILE"; then
        echo "└── ✗ Download failed: $DEB_URL"
        exit 1
    fi

    echo "●  Installing with apt (sudo required):"
    echo "│" # Visual spacer

    # apt resolves the .deb's dependencies; dpkg alone would not
    if sudo apt-get install -y "$TMP_DIR/$DEB_FILE" 2>&1 | tee -a "$LOG_FILE"; then
        echo "│" # Visual spacer
        echo "●  ✓ Obsidian .deb installed successfully."
    else
        echo "│" # Visual spacer
        echo "└── ✗ Installation failed. Please check $LOG_FILE for details."
        exit 1
    fi
fi

echo "└── Installation complete."
