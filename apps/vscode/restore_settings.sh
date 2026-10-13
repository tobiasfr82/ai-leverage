#!/bin/bash
# ai-leverage/apps/vscode/restore_settings.sh
# Puts back a backup made by backup_settings.sh: the settings in
# ~/.config/Code/User and the extensions it lists. The settings there now are
# moved aside first, not deleted. Close VS Code before running this.

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="$APP_DIR/data/backups"
CODE_DIR="$HOME/.config/Code"

GREEN='\033[0;32m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

mapfile -t backups < <(ls -1t "$BACKUP_DIR"/vscode-settings-*.tar.gz 2> /dev/null)
if [ ${#backups[@]} -eq 0 ]; then
    echo "There's no backup in apps/vscode/data/backups yet. Run backup_settings first."
    exit 1
fi
if pgrep -x code > /dev/null; then
    echo -e "${RED}✗ VS Code is running. Close it, then run this from a terminal outside VS Code.${NC}"
    exit 1
fi

echo "Backups, newest first:"
for i in "${!backups[@]}"; do
    printf '%2d) %s (%s MB)\n' $((i + 1)) "$(basename "${backups[$i]}")" "$(du -m "${backups[$i]}" | cut -f1)"
done
read -r -p "Which one? (Enter for 1): " choice
choice=${choice:-1}
if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt ${#backups[@]} ]; then
    echo -e "${CYAN}Cancelled.${NC}"
    exit 0
fi
file=${backups[$((choice - 1))]}

aside=""
if [ -d "$CODE_DIR/User" ]; then
    aside="$CODE_DIR/User.before-restore-$(date +%Y-%m-%d_%H%M)"
    mv "$CODE_DIR/User" "$aside" || exit 1
fi
mkdir -p "$CODE_DIR"
if ! tar -xzf "$file" -C "$CODE_DIR" User; then
    echo -e "${RED}✗ Couldn't unpack $(basename "$file").${NC}"
    [ -n "$aside" ] && rm -rf "$CODE_DIR/User" && mv "$aside" "$CODE_DIR/User" && echo "Your settings are back as they were."
    exit 1
fi
echo "●  Settings restored from $(basename "$file")"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
if tar -xzf "$file" -C "$tmp" extensions.txt 2> /dev/null; then
    if command -v code &> /dev/null; then
        echo "●  Installing $(wc -l < "$tmp/extensions.txt") extensions..."
        while read -r extension; do
            [ -n "$extension" ] && code --install-extension "$extension" > /dev/null &&
                echo "   $extension" || echo -e "   ${RED}$extension couldn't be installed${NC}"
        done < "$tmp/extensions.txt"
    else
        echo "●  VS Code isn't installed, so the extensions weren't installed. Install VS Code,"
        echo "   then run this again."
    fi
fi

echo -e "${GREEN}✓ Done.${NC}"
[ -n "$aside" ] && echo "The settings you had before are in ~/.config/Code/$(basename "$aside")."
