# ai-leverage/src/bash/update-common.sh
# The steps of Update, Revert, Hold and the online check, the same for the
# apps (app.sh) and the engines and services (service.sh). Not run on its own:
# both scripts load it, and bring the functions for their kind of source.
#
# The script that loads it sets:
#   APP            the name to show
#   METHOD         picks the source's functions, <METHOD>_<step> (see m)
#   REVERT_DIR     where the revert point is kept; PREVIOUS_FILE is in it
#   NOT_INSTALLED  what Update, Revert and Hold say when it isn't there
#   CACHE_KEY      its entry in the update overview's results
#
# Each source brings: installed, version, ref, latest (sets LATEST_REF and
# LATEST_VERSION, online), is_newer, save, update, install_ref, hold, release,
# held, source. Optional: update_warning, revert_warning, drop_previous,
# after_update, hold_note.

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PREVIOUS_FILE="$REVERT_DIR/previous"

# The update overview keeps what the last check found, one file per app or
# service, so the main menu can count the updates without going online
UPDATE_CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/ai-leverage/updates"

# Set by --yes: Update all asked once for everything
ASSUME_YES=${ASSUME_YES:-false}

ask() {
    local reply
    if $ASSUME_YES; then
        echo "$1 (y/N): y"
        return 0
    fi
    read -r -p "$1 (y/N): " reply
    [[ "$reply" =~ ^[Yy]$ ]]
}

# The same, where yes is the safe answer: Enter says yes, only n says no
ask_yes() {
    local reply
    if $ASSUME_YES; then
        echo "$1 (Y/n): y"
        return 0
    fi
    read -r -p "$1 (Y/n): " reply
    [[ ! "$reply" =~ ^[Nn]$ ]]
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

# The newest release of a GitHub project, without a leading v; drafts and
# pre-releases don't count
github_latest() {
    curl -fsSL "https://api.github.com/repos/$1/releases/latest" 2> /dev/null |
        sed -n 's/.*"tag_name": *"v\{0,1\}\([^"]*\)".*/\1/p' | head -n 1
}

m() { "${METHOD}_$1" "${@:2}"; }

# A step only some sources have
hook() {
    if declare -F "${METHOD}_$1" > /dev/null; then m "$@"; fi
}

# What the last check found is out of date once something changed
forget_check() {
    rm -f "$UPDATE_CACHE_DIR/$CACHE_KEY"
}

# The version Update replaced: VERSION to show, REF to install it again
read_previous() {
    VERSION="" REF=""
    [ -f "$PREVIOUS_FILE" ] || return 1
    # shellcheck source=/dev/null
    . "$PREVIOUS_FILE"
    [ -n "$REF" ]
}

# One line for the update overview, after looking online:
#   result|installed|newest|note
# result is current, newer, held (newer or not; Update skips it), missing,
# or failed (note says why). Also kept for the main menu's count.
do_check() {
    local current result note=""
    if ! m installed; then
        echo "missing|||"
        return 0
    fi
    current=$(m version)
    if ! m latest > /dev/null 2>&1; then
        echo "failed|$current||"
        return 0
    fi
    if m held; then
        result=held
    elif m is_newer; then
        result=newer
        [ "$LATEST_VERSION" == "$current" ] && note="a new build of the same version"
    else
        result=current
        LATEST_VERSION=$current
    fi
    mkdir -p "$UPDATE_CACHE_DIR"
    echo "$result|$current|$LATEST_VERSION|$note" | tee "$UPDATE_CACHE_DIR/$CACHE_KEY"
}

do_update() {
    local current
    if ! m installed; then
        echo "$NOT_INSTALLED"
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
        forget_check
        return 0
    fi
    local note=""
    [ "$LATEST_VERSION" == "$current" ] && note=" (a new build of the same version)"
    echo "   $APP $current → $LATEST_VERSION$note"
    hook update_warning
    ask "Update $APP?" || { echo -e "${CYAN}Cancelled.${NC}"; return 0; }

    # The revert point: the version being replaced
    hook drop_previous
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
    forget_check
    echo -e "${GREEN}✓ $APP is now $(m version). Revert goes back to $current.${NC}"
    hook after_update
    return 0
}

do_revert() {
    local current
    if ! m installed; then
        echo "$NOT_INSTALLED"
        return 1
    fi
    if ! read_previous; then
        echo "There's no earlier version of $APP to go back to. Revert works after an"
        echo "Update from this menu."
        return 0
    fi
    current=$(m version)
    echo "$APP goes back from $current to $VERSION, and is held there so Update skips it."
    hook revert_warning
    ask "Revert $APP?" || { echo -e "${CYAN}Cancelled.${NC}"; return 0; }
    m held && { m release || return 1; }
    if ! m install_ref "$REF"; then
        echo -e "${RED}✗ Couldn't go back to $VERSION. See the messages above.${NC}"
        return 1
    fi
    m hold
    rm -rf "$REVERT_DIR"
    forget_check
    echo -e "${GREEN}✓ $APP is back on $(m version) and held there.${NC}"
    echo "Release the hold once a fixed version is out, then Update."
}

do_hold() {
    if ! m installed; then
        echo "$NOT_INSTALLED"
        return 1
    fi
    if m held; then
        echo "$APP is already held at $(m version)."
        return 0
    fi
    m hold || return 1
    forget_check
    echo -e "${GREEN}✓ $APP stays at $(m version). Update skips it until you release the hold.${NC}"
    hook hold_note
    return 0
}

do_release() {
    if ! m installed || ! m held; then
        echo "$APP isn't held."
        return 0
    fi
    m release || return 1
    forget_check
    echo -e "${GREEN}✓ $APP isn't held anymore. Update can update it again.${NC}"
}
