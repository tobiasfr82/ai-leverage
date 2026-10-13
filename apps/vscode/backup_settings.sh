#!/bin/bash
# ai-leverage/apps/vscode/backup_settings.sh
# Saves your VS Code setup into apps/vscode/data/backups/ (git-ignored), one
# dated file per run: everything in ~/.config/Code/User (settings, keybindings,
# snippets, profiles, and what VS Code remembers per workspace) and the list of
# installed extensions. restore_settings.sh puts a backup back.
# Uninstalling VS Code leaves these settings alone anyway. A backup is for a
# fresh start, or to take your setup to another PC.

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="$APP_DIR/data/backups"
CODE_DIR="$HOME/.config/Code"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

if [ ! -d "$CODE_DIR/User" ]; then
    echo -e "${RED}✗ There are no VS Code settings in ~/.config/Code/User to back up.${NC}"
    exit 1
fi

mkdir -p "$BACKUP_DIR"
file="$BACKUP_DIR/vscode-settings-$(date +%Y-%m-%d_%H%M).tar.gz"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

parts=(-C "$CODE_DIR" User)
if command -v code &> /dev/null; then
    code --list-extensions > "$tmp/extensions.txt"
    echo "●  $(wc -l < "$tmp/extensions.txt") extensions listed"
    parts+=(-C "$tmp" extensions.txt)
else
    echo "●  VS Code isn't installed, so the backup can't list its extensions."
fi

if ! tar -czf "$file" "${parts[@]}"; then
    rm -f "$file"
    echo -e "${RED}✗ The backup failed. See the messages above.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Saved to apps/vscode/data/backups/$(basename "$file") ($(du -m "$file" | cut -f1) MB)${NC}"
