#!/bin/bash
# ai-leverage/src/bash/app.sh
# Installs, updates and removes the desktop apps in apps/, the same way for
# each. An app's app.conf says where it comes from (METHOD):
#   flatpak  a Flatpak from Flathub
#   apt      a package from its maker's own apt repository
#   script   its maker's install script, for an app that has neither
# Every app follows its newest stable release. Update first saves the version
# it replaces, so Revert can go back to it; Hold keeps an app where it is.
# apps/README.md describes app.conf.
#
# Usage: app.sh <app folder or name> <action>
#   install    install it, unless it's there already
#   update     check for a newer release (online) and install it, after asking
#   revert     go back to the version before the last update, and hold it there
#   hold       keep it at its version: Update skips it
#   release    end the hold
#   uninstall  remove the program; your own files and settings stay
#   status     one line for manage.sh, without going online:
#              state|version|held|previous|name|source|about
#              state is installed, missing, or other (installed some other
#              way; version then says where)

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

usage() {
    sed -n '/^# Usage:/,/^$/s/^# \{0,1\}//p' "${BASH_SOURCE[0]}"
    exit 1
}

[ $# -eq 2 ] || usage
ACTION=$2

# A Flatpak --user install, and everything under $HOME, belong to the desktop
# user, not root. So when started with sudo, run as that user; the steps that
# need root call sudo themselves.
if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ]; then
    exec sudo -u "$SUDO_USER" -- "$BASE_DIR/src/bash/app.sh" "$@"
fi

# An app's folder, or just its name
if [ -d "$1" ]; then
    APP_DIR="$(cd "$1" && pwd)"
else
    APP_DIR="$BASE_DIR/apps/$1"
fi
CONF="$APP_DIR/app.conf"
[ -f "$CONF" ] || { echo "No app.conf in $APP_DIR"; exit 1; }

# What app.conf can set, with their defaults (see apps/README.md)
NAME="" ABOUT="" METHOD="" COMMAND="" KEEPS=""
REPLACES=()
FLATPAK_ID="" FLATPAK_REMOTE=flathub FLATPAK_REMOTE_URL=https://dl.flathub.org/repo/flathub.flatpakrepo
APT_PACKAGE="" APT_URI="" APT_SUITE="" APT_COMPONENTS=main APT_ARCHS=""
APT_SOURCE_FILE="" APT_KEY_URL="" APT_KEY_FILE="" APT_KEY_FINGERPRINT=""
SCRIPT_INSTALLER_URL="" SCRIPT_VERSION_ARG=--version SCRIPT_BIN="" SCRIPT_UNINSTALL="" GITHUB_REPO=""
# shellcheck source=/dev/null
. "$CONF"
APP="${NAME:-$(basename "$APP_DIR")}"

case "$METHOD" in
    flatpak|apt|script) ;;
    *) echo "app.conf of $APP: METHOD must be flatpak, apt or script, not '$METHOD'"; exit 1 ;;
esac

# Kept per app, git-ignored: the version Update replaced (and for apt, its
# package file), and the hold for apps whose source has no hold of its own
REVERT_DIR="$APP_DIR/data/revert"
PREVIOUS_FILE="$REVERT_DIR/previous"
HOLD_FILE="$APP_DIR/data/held"

# --- Small helpers ---

ask() {
    local reply
    read -r -p "$1 (y/N): " reply
    [[ "$reply" =~ ^[Yy]$ ]]
}

# The host part of a URL, to say where something comes from
host_of() {
    local host=${1#*://}
    echo "${host%%/*}"
}

# A path with the home folder written as ~
tilde() {
    echo "${1/#$HOME/\~}"
}

# "a" is a newer version than "b"
newer() {
    [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -n 1)" == "$1" ]
}

# --- Flatpak ---
# Versions are Flathub commits; Flathub keeps the old ones, so Revert can
# fetch the one before. Hold is Flatpak's own mask.

flatpak_source() { echo "Flatpak from ${FLATPAK_REMOTE^}"; }

flatpak_installed() {
    command -v flatpak &> /dev/null && flatpak info --user "$FLATPAK_ID" &> /dev/null
}

flatpak_field() {
    LC_ALL=C flatpak info --user "$FLATPAK_ID" 2> /dev/null | awk -v f="$1:" '$1 == f { print $2; exit }'
}

flatpak_ref()     { flatpak_field Commit; }
flatpak_version() { local v; v=$(flatpak_field Version); echo "${v:-$(flatpak_ref | cut -c1-12)}"; }

# Sets LATEST_REF and LATEST_VERSION from the remote. Goes online. The
# version number the remote lists can lag behind the app it serves (Flathub
# listed Obsidian 1.14.4 as 1.13.7), so the newest is told by its build date.
flatpak_latest() {
    local info
    info=$(LC_ALL=C flatpak remote-info --user "$FLATPAK_REMOTE" "$FLATPAK_ID" 2> /dev/null) || return 1
    LATEST_REF=$(awk '$1 == "Commit:" { print $2; exit }' <<< "$info")
    LATEST_VERSION="the ${FLATPAK_REMOTE^} build from $(awk '$1 == "Date:" { print $2; exit }' <<< "$info")"
    [ -n "$LATEST_REF" ]
}

flatpak_is_newer() { [ "$LATEST_REF" != "$(flatpak_ref)" ]; }

flatpak_install() {
    if ! command -v flatpak &> /dev/null; then
        command -v apt-get &> /dev/null && ask "Flatpak isn't installed. Install it with apt?" || {
            echo "Install Flatpak with your system's package manager, then try again."
            return 1
        }
        sudo apt-get install -y flatpak || return 1
    fi
    flatpak remote-add --if-not-exists --user "$FLATPAK_REMOTE" "$FLATPAK_REMOTE_URL" &&
        flatpak install -y --user "$FLATPAK_REMOTE" "$FLATPAK_ID"
}

flatpak_update()     { flatpak update -y --user "$FLATPAK_ID"; }
flatpak_save()       { :; }
flatpak_install_ref() { flatpak update -y --user --commit="$1" "$FLATPAK_ID"; }
flatpak_hold()       { flatpak mask --user "$FLATPAK_ID"; }
flatpak_release()    { flatpak mask --user --remove "$FLATPAK_ID"; }
flatpak_held()       { flatpak mask --user 2> /dev/null | grep -qF -- "$FLATPAK_ID"; }
flatpak_uninstall()  { flatpak uninstall -y --user "$FLATPAK_ID"; }

flatpak_other() {
    command -v flatpak &> /dev/null && flatpak info --system "$FLATPAK_ID" &> /dev/null &&
        echo "a system-wide Flatpak"
}

# --- apt ---
# The maker's repository is set up the way the maker documents it: their key
# (checked against APT_KEY_FINGERPRINT), their file names. Versions are package
# versions. Update saves the package it replaces, so Revert works even once
# the repository has dropped that version. Hold is apt's own, which also keeps
# "sudo apt upgrade" and the system's updater from moving it.

apt_source() { echo "apt, from $(host_of "$APT_URI")"; }

apt_installed() { [ -n "$(apt_ref)" ]; }

# The installed package version, as apt writes it
apt_ref() {
    dpkg-query -W -f='${Status}|${Version}' "$APT_PACKAGE" 2> /dev/null | awk -F'|' '$1 ~ / installed$/ { print $2 }'
}

# Without the epoch and the packaging revision: 1:1.140.0-1790759618 is 1.140.0
apt_short() {
    local v=${1#*:}
    echo "${v%%-*}"
}

apt_version() { apt_short "$(apt_ref)"; }

# The file in /etc/apt that lists the app's repository, if any does
apt_source_file() {
    local uri
    uri=$(sed 's/[][\.*^$+?(){}|]/\\&/g' <<< "${APT_URI%/}")
    grep -l -s -E "^[[:space:]]*(deb[[:space:]].*[[:space:]]|URIs:[[:space:]]*(.*[[:space:]])?)${uri}/?([[:space:]]|$)" \
        /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources | head -n 1
}

apt_add_source() {
    local existing tmp fingerprints
    existing=$(apt_source_file)
    if [ -n "$existing" ]; then
        echo "●  Using the apt source already in $existing"
        return 0
    fi
    for tool in curl gpg; do
        command -v "$tool" &> /dev/null && continue
        echo "●  Installing $tool, to fetch and check the repository's key..."
        sudo apt-get install -y "$([ "$tool" == gpg ] && echo gnupg || echo curl)" || return 1
    done

    tmp=$(mktemp -d)
    echo "●  Adding the $(host_of "$APT_URI") repository to apt..."
    if ! curl -fsSL "$APT_KEY_URL" -o "$tmp/key"; then
        echo -e "${RED}✗ Couldn't download the repository's key from $APT_KEY_URL${NC}"
        rm -rf "$tmp"
        return 1
    fi
    fingerprints=$(gpg --show-keys --with-colons "$tmp/key" 2> /dev/null | awk -F: '$1 == "fpr" { print $10 }')
    if ! grep -qx "$APT_KEY_FINGERPRINT" <<< "$fingerprints"; then
        echo -e "${RED}✗ The key from $APT_KEY_URL isn't the one app.conf expects"
        echo -e "  ($APT_KEY_FINGERPRINT). Stopped without changing anything.${NC}"
        rm -rf "$tmp"
        return 1
    fi
    # A .gpg file holds the key in binary, a .asc file as text
    if [[ "$APT_KEY_FILE" == *.gpg ]] && grep -q -- '-----BEGIN PGP' "$tmp/key"; then
        gpg --dearmor < "$tmp/key" > "$tmp/key.gpg" && mv "$tmp/key.gpg" "$tmp/key"
    fi

    {
        echo "# Added by ai-leverage for $APP (apps/$(basename "$APP_DIR")/app.conf)"
        if [[ "$APT_SOURCE_FILE" == *.sources ]]; then
            echo "Types: deb"
            echo "URIs: $APT_URI"
            echo "Suites: $APT_SUITE"
            echo "Components: $APT_COMPONENTS"
            [ -n "$APT_ARCHS" ] && echo "Architectures: $APT_ARCHS"
            echo "Signed-By: $APT_KEY_FILE"
        else
            echo "deb [${APT_ARCHS:+arch=$APT_ARCHS }signed-by=$APT_KEY_FILE] $APT_URI $APT_SUITE $APT_COMPONENTS"
        fi
    } > "$tmp/source"

    sudo install -D -m 0644 "$tmp/key" "$APT_KEY_FILE" &&
        sudo install -D -m 0644 "$tmp/source" "$APT_SOURCE_FILE"
    local status=$?
    rm -rf "$tmp"
    return $status
}

# Fetches the newest package list of the app's repository only, so a check
# takes seconds and leaves the rest of apt as it is
apt_refresh() {
    local file
    file=$(apt_source_file)
    if [ -z "$file" ]; then
        echo -e "${RED}✗ No apt source lists $APT_URI. Install $APP from this menu to add it.${NC}"
        return 1
    fi
    sudo apt-get update -qq -o Dir::Etc::sourcelist="$file" -o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0
}

apt_latest() {
    apt_refresh || return 1
    LATEST_REF=$(LC_ALL=C apt-cache policy "$APT_PACKAGE" | awk '$1 == "Candidate:" { print $2 }')
    [ -n "$LATEST_REF" ] && [ "$LATEST_REF" != "(none)" ] || return 1
    LATEST_VERSION=$(apt_short "$LATEST_REF")
}

apt_is_newer() { dpkg --compare-versions "$LATEST_REF" gt "$(apt_ref)"; }

apt_install() {
    apt_add_source && apt_refresh && sudo apt-get install -y "$APT_PACKAGE"
}

apt_update() { sudo apt-get install -y --only-upgrade "$APT_PACKAGE"; }

# Saves the installed package next to the revert note. From the repository if
# it still has that version, otherwise from apt's own download cache.
apt_save() {
    local ref cached
    ref=$(apt_ref)
    echo "●  Saving $APP $(apt_short "$ref") first, so Revert can go back to it..."
    if (cd "$REVERT_DIR" && apt-get download -q "$APT_PACKAGE=$ref" 2> /dev/null); then
        return 0
    fi
    cached=$(ls /var/cache/apt/archives/"${APT_PACKAGE}_${ref//:/%3a}"_*.deb 2> /dev/null | head -n 1)
    [ -n "$cached" ] && cp "$cached" "$REVERT_DIR/"
}

# Installs a version again: the saved package if there is one, otherwise the
# version from the repository
apt_install_ref() {
    local saved
    saved=$(ls "$REVERT_DIR"/*.deb 2> /dev/null | head -n 1)
    if [ -n "$saved" ]; then
        sudo apt-get install -y --allow-downgrades "$saved"
    else
        sudo apt-get install -y --allow-downgrades "$APT_PACKAGE=$1"
    fi
}

apt_hold()    { sudo apt-mark hold "$APT_PACKAGE" > /dev/null; }
apt_release() { sudo apt-mark unhold "$APT_PACKAGE" > /dev/null; }
apt_held()    { [ -n "$(apt-mark showhold "$APT_PACKAGE" 2> /dev/null)" ]; }

# Removes the package, then its repository: the file app.conf names and its
# key, unless another apt source still uses that key
apt_uninstall() {
    sudo apt-get remove -y "$APT_PACKAGE" || return 1
    if [ -f "$APT_SOURCE_FILE" ]; then
        echo "●  Removing its apt source, $APT_SOURCE_FILE"
        sudo rm -f "$APT_SOURCE_FILE"
    fi
    if [ -f "$APT_KEY_FILE" ] && ! grep -rqsF "$APT_KEY_FILE" /etc/apt/sources.list /etc/apt/sources.list.d/; then
        sudo rm -f "$APT_KEY_FILE"
    fi
    local other
    other=$(apt_source_file)
    [ -n "$other" ] && echo "●  $other still lists its repository. It isn't from app.conf, so it stays."
    return 0
}

apt_other() { :; }

# --- The maker's install script ---
# Versions are release numbers, the newest from GitHub. Update and Revert run
# the installer for that exact version. Hold is a note in data/.

script_source() { echo "the installer from $(host_of "$SCRIPT_INSTALLER_URL")"; }

script_installed() { [ -x "$SCRIPT_BIN" ]; }

script_ref() {
    script_installed || return
    local v
    v=$("$SCRIPT_BIN" --version 2> /dev/null | head -n 1)
    echo "${v#v}"
}

script_version() { script_ref; }

# The newest release on GitHub; drafts and pre-releases don't count
script_latest() {
    LATEST_REF=$(curl -fsSL "https://api.github.com/repos/$GITHUB_REPO/releases/latest" 2> /dev/null |
        sed -n 's/.*"tag_name": *"v\{0,1\}\([^"]*\)".*/\1/p' | head -n 1)
    LATEST_VERSION=$LATEST_REF
    [ -n "$LATEST_REF" ]
}

script_is_newer() { newer "$LATEST_REF" "$(script_ref)"; }

# Downloads the installer and runs it, for one version or else the newest
script_run_installer() {
    local installer status
    installer=$(mktemp)
    if ! curl -fsSL "$SCRIPT_INSTALLER_URL" -o "$installer"; then
        echo -e "${RED}✗ Couldn't download the installer from $SCRIPT_INSTALLER_URL${NC}"
        rm -f "$installer"
        return 1
    fi
    if [ -n "$1" ]; then
        bash "$installer" "$SCRIPT_VERSION_ARG" "$1"
    else
        bash "$installer"
    fi
    status=$?
    rm -f "$installer"
    return $status
}

script_install()     { script_run_installer; }
script_update()      { script_run_installer "$LATEST_REF"; }
script_save()        { :; }
script_install_ref() { script_run_installer "$1"; }
script_hold()        { mkdir -p "$(dirname "$HOLD_FILE")" && touch "$HOLD_FILE"; }
script_release()     { rm -f "$HOLD_FILE"; }
script_held()        { [ -f "$HOLD_FILE" ]; }

script_uninstall() {
    if [ -n "$SCRIPT_UNINSTALL" ]; then
        # shellcheck disable=SC2086 # app.conf's arguments, split on purpose
        "$SCRIPT_BIN" $SCRIPT_UNINSTALL || return 1
    fi
    rm -f "$SCRIPT_BIN"
}

script_other() { :; }

# --- What every app has ---

m() { "${METHOD}_$1" "${@:2}"; }

# Where a copy of the app from somewhere else is, if there is one: a path
# from REPLACES, its COMMAND on PATH, or what the method knows about
other_install() {
    local path
    for path in "${REPLACES[@]}"; do
        [ -e "$path" ] && { tilde "$path"; return 0; }
    done
    if [ -n "$COMMAND" ] && path=$(command -v "$COMMAND"); then
        tilde "$path"
        return 0
    fi
    path=$(m other)
    [ -n "$path" ] && echo "$path"
}

state() {
    if m installed; then
        echo installed
    elif [ -n "$(other_install)" ]; then
        echo other
    else
        echo missing
    fi
}

# The version Update replaced: VERSION to show, REF to install it again
read_previous() {
    VERSION="" REF=""
    [ -f "$PREVIOUS_FILE" ] || return 1
    # shellcheck source=/dev/null
    . "$PREVIOUS_FILE"
    [ -n "$REF" ]
}

# Removes the copies in REPLACES, once the app is installed from app.conf's
# source, so one copy of it is left on PATH
remove_replaced() {
    local path removed=false
    for path in "${REPLACES[@]}"; do
        [ -e "$path" ] || [ -L "$path" ] || continue
        # Only ever below the home folder, never the home folder itself
        [[ "$path" == "$HOME"/?* ]] || continue
        echo "●  Removing the copy installed another way: $(tilde "$path")"
        rm -rf -- "$path"
        removed=true
    done
    if $removed && [ -n "$COMMAND" ]; then
        echo "●  Open a new terminal (or run 'hash -r' in an open one), so '$COMMAND' is found"
        echo "   in its new place."
    fi
}

do_status() {
    local st version="" held="" previous=""
    st=$(state)
    case "$st" in
        installed)
            version=$(m version)
            m held && held=held
            read_previous && previous=$VERSION
            ;;
        other) version=$(other_install) ;;
    esac
    echo "$st|$version|$held|$previous|$APP|$(m source)|$ABOUT"
}

do_install() {
    local where
    case "$(state)" in
        installed)
            echo -e "${GREEN}✓ $APP $(m version) is already installed ($(m source)).${NC}"
            remove_replaced
            return 0
            ;;
        other)
            where=$(other_install)
            if [ ${#REPLACES[@]} -eq 0 ]; then
                echo "$APP is already installed another way, at $where."
                echo "Remove that copy with whatever installed it first, so there's one $APP"
                echo "that Update knows about."
                return 1
            fi
            echo "$APP is already installed another way, at $where."
            echo "Installing it from $(m source) removes that copy afterwards:"
            printf '   %s\n' "${REPLACES[@]/#$HOME/\~}"
            [ -n "$KEEPS" ] && echo "$KEEPS"
            ask "Install $APP from $(m source)?" || { echo -e "${CYAN}Cancelled.${NC}"; return 0; }
            ;;
    esac
    echo -e "${CYAN}●  Installing $APP ($(m source))...${NC}"
    if ! m install || ! m installed; then
        echo -e "${RED}✗ $APP couldn't be installed. See the messages above.${NC}"
        return 1
    fi
    remove_replaced
    echo -e "${GREEN}✓ $APP $(m version) is installed.${NC}"
}

do_update() {
    local current
    if ! m installed; then
        echo "$APP isn't installed from this menu yet. Install it first."
        return 1
    fi
    current=$(m version)
    if m held; then
        echo "$APP is held at $current. Release the hold to update it."
        return 0
    fi
    echo -e "${CYAN}●  Checking for a newer $APP ($(m source))...${NC}"
    if ! m latest; then
        echo -e "${RED}✗ Couldn't find out the newest version. See the messages above.${NC}"
        return 1
    fi
    if ! m is_newer; then
        echo -e "${GREEN}✓ $APP $current is the newest stable release.${NC}"
        return 0
    fi
    local note=""
    [ "$LATEST_VERSION" == "$current" ] && note=" (a new build of the same version)"
    echo "   $APP $current → $LATEST_VERSION$note"
    ask "Update $APP?" || { echo -e "${CYAN}Cancelled.${NC}"; return 0; }

    # The revert point: the version being replaced
    rm -rf "$REVERT_DIR"
    mkdir -p "$REVERT_DIR"
    printf 'VERSION=%q\nREF=%q\n' "$current" "$(m ref)" > "$PREVIOUS_FILE"
    if ! m save; then
        echo -e "${YELLOW}Couldn't save $current, so Revert can only go back to it while"
        echo -e "its source still offers it.${NC}"
        ask "Update anyway?" || { rm -rf "$REVERT_DIR"; echo -e "${CYAN}Cancelled.${NC}"; return 0; }
    fi

    if ! m update; then
        echo -e "${RED}✗ The update failed. See the messages above.${NC}"
        return 1
    fi
    echo -e "${GREEN}✓ $APP is now $(m version). Revert goes back to $current.${NC}"
}

do_revert() {
    local current
    if ! m installed; then
        echo "$APP isn't installed from this menu."
        return 1
    fi
    if ! read_previous; then
        echo "There's no earlier version of $APP to go back to. Revert works after an"
        echo "Update from this menu."
        return 0
    fi
    current=$(m version)
    echo "$APP goes back from $current to $VERSION, and is held there so Update skips it."
    ask "Revert $APP?" || { echo -e "${CYAN}Cancelled.${NC}"; return 0; }
    m held && { m release || return 1; }
    if ! m install_ref "$REF"; then
        echo -e "${RED}✗ Couldn't go back to $VERSION. See the messages above.${NC}"
        return 1
    fi
    m hold
    rm -rf "$REVERT_DIR"
    echo -e "${GREEN}✓ $APP is back on $(m version) and held there.${NC}"
    echo "Release the hold once a fixed version is out, then Update."
}

do_hold() {
    if ! m installed; then
        echo "$APP isn't installed from this menu."
        return 1
    fi
    if m held; then
        echo "$APP is already held at $(m version)."
        return 0
    fi
    m hold || return 1
    echo -e "${GREEN}✓ $APP stays at $(m version). Update skips it until you release the hold.${NC}"
    [ "$METHOD" == apt ] && echo "   This also keeps \"sudo apt upgrade\" and the system's updater from updating it."
    return 0
}

do_release() {
    if ! m installed || ! m held; then
        echo "$APP isn't held."
        return 0
    fi
    m release || return 1
    echo -e "${GREEN}✓ $APP isn't held anymore. Update can update it again.${NC}"
}

do_uninstall() {
    local st
    st=$(state)
    if [ "$st" == other ]; then
        echo "$APP is installed another way, at $(other_install). Remove it with whatever installed it."
        return 1
    fi
    if [ "$st" == missing ]; then
        echo "$APP isn't installed."
        return 0
    fi
    echo "This removes $APP $(m version) ($(m source))."
    [ -n "$KEEPS" ] && echo "$KEEPS"
    ask "Uninstall $APP?" || { echo -e "${CYAN}Cancelled.${NC}"; return 0; }
    m held && { m release || return 1; }
    if ! m uninstall; then
        echo -e "${RED}✗ $APP couldn't be removed. See the messages above.${NC}"
        return 1
    fi
    rm -rf "$REVERT_DIR" "$HOLD_FILE"
    echo -e "${GREEN}✓ $APP is uninstalled.${NC}"
}

case "$ACTION" in
    status)    do_status ;;
    install)   do_install ;;
    update)    do_update ;;
    revert)    do_revert ;;
    hold)      do_hold ;;
    release)   do_release ;;
    uninstall) do_uninstall ;;
    *)         usage ;;
esac
