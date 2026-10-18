#!/bin/bash
# ai-leverage/src/bash/check-updates.sh
# The update overview. It lists every engine, service and app with its
# version on this PC and the newest stable release, looked up online without
# downloading anything. From here: Update all of them one after another, or
# Update, Revert or Hold one. The steps are the same as in each one's own
# menu (service.sh, app.sh). Below them, the tools ai-leverage relies on, for
# information: they're updated another way.
#
# It goes online when it opens and when you check again, never on its own.
# manage.sh's menu shows the same overview in a box of its own (Stack › Updates): it
# runs this with --print and does the steps in its panes.
#
# Usage: check-updates.sh [--print] [folder...]
#   The stack and app folders to list, in this order. Without any: every
#   folder in stack/ with a compose file, then every app in apps/.
#   --print  only check, and print what it finds, one line each as it comes,
#            without asking anything:
#              row|<folder>|result|installed|newest|note
#              tool|<name>|version|newest|note
#            (result as in update-common.sh's do_check)

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_DIR="$BASE_DIR/src/bash"
# Colors, ask, newer, github_latest and where the results are kept
# shellcheck source=update-common.sh
. "$SCRIPT_DIR/update-common.sh"
# read_choice: a choice typed and ended with Enter, or Esc to go back
# shellcheck source=read-choice.sh
. "$SCRIPT_DIR/read-choice.sh"
BOLD='\033[1m'

# Room for the longest status, [NOT INSTALLED], as in manage.sh
STATUS_WIDTH=15

pause() {
    read -n 1 -s -r -p "Press any key to return..."
    echo
}

has_compose() { [ -f "$1/compose.yaml" ] || [ -f "$1/docker-compose.yml" ]; }

# --- The rows ---

# ROW_PATH, ROW_KIND (service or app) and ROW_GROUP (its heading), in order
ROW_PATH=() ROW_KIND=() ROW_GROUP=()
add_row() {
    local dir=${1%/}
    [ -d "$dir" ] || return
    dir=$(cd "$dir" && pwd)
    if [[ "$dir" == "$BASE_DIR"/apps/* ]] && [ -f "$dir/app.conf" ]; then
        ROW_PATH+=("$dir") ROW_KIND+=(app) ROW_GROUP+=(APPS)
    elif [[ "$dir" == "$BASE_DIR"/stack/*/* ]] && has_compose "$dir"; then
        ROW_PATH+=("$dir") ROW_KIND+=(service)
        ROW_GROUP+=("$(basename "$(dirname "$dir")" | tr '[:lower:]' '[:upper:]')")
    fi
}

PRINT=false
if [ "${1:-}" == --print ]; then
    PRINT=true
    shift
fi
# Whether every folder is checked: then what was kept for folders that are
# gone can go too
EVERY_FOLDER=false
if [ $# -gt 0 ]; then
    for arg in "$@"; do add_row "$arg"; done
else
    EVERY_FOLDER=true
    for dir in "$BASE_DIR"/stack/*/*/ "$BASE_DIR"/apps/*/; do add_row "$dir"; done
fi

# What the checks found, by row: result|installed|newest|note (update-common.sh)
ROW_RESULT=() ROW_INSTALLED=() ROW_NEWEST=() ROW_NOTE=()

# Checks the given rows. The services at the same time, each on its own; the
# apps one after another, because apt can't check two sources at once.
check_rows() {
    local tmp i
    tmp=$(mktemp -d)
    for i in "$@"; do
        [ "${ROW_KIND[$i]}" == service ] || continue
        "$SCRIPT_DIR/service.sh" "${ROW_PATH[$i]}" check > "$tmp/$i" 2> /dev/null < /dev/null &
    done
    (
        for i in "$@"; do
            [ "${ROW_KIND[$i]}" == app ] || continue
            "$SCRIPT_DIR/app.sh" "${ROW_PATH[$i]}" check > "$tmp/$i" 2> /dev/null < /dev/null
        done
    ) &
    wait
    for i in "$@"; do
        IFS='|' read -r "ROW_RESULT[$i]" "ROW_INSTALLED[$i]" "ROW_NEWEST[$i]" "ROW_NOTE[$i]" < "$tmp/$i" 2> /dev/null
        [ -n "${ROW_RESULT[$i]}" ] || ROW_RESULT[$i]=failed
    done
    rm -rf "$tmp"
}

# --- The tools, for information ---

# TOOL_LINES: name|version|newest|note, one per tool
check_tools() {
    TOOL_LINES=()
    local version newest note branch main behind major pop

    # ai-leverage itself: what GitHub has that this copy doesn't. git updates it.
    if git -C "$BASE_DIR" rev-parse --git-dir > /dev/null 2>&1; then
        version=$(git -C "$BASE_DIR" rev-parse --short HEAD)
        branch=$(git -C "$BASE_DIR" symbolic-ref --short -q HEAD)
        main=$(git -C "$BASE_DIR" symbolic-ref --short -q refs/remotes/origin/HEAD) || main=origin/main
        if ! timeout 30 git -C "$BASE_DIR" fetch -q origin 2> /dev/null; then
            note="couldn't reach GitHub"
        else
            behind=$(git -C "$BASE_DIR" rev-list --count "HEAD..$main" 2> /dev/null || echo 0)
            if [ "$branch" == "${main#origin/}" ]; then
                if [ "$behind" -eq 0 ]; then note="up to date with GitHub"
                else note="$behind newer change$([ "$behind" -ne 1 ] && echo s) on GitHub (get them with: git pull)"; fi
            elif [ "$behind" -eq 0 ]; then
                note="on branch ${branch:-(none)}, which has everything from ${main#origin/} on GitHub"
            else
                note="on branch ${branch:-(none)}; ${main#origin/} on GitHub has $behind change$([ "$behind" -ne 1 ] && echo s) it doesn't"
            fi
        fi
        TOOL_LINES+=("ai-leverage|$version||$note")
    else
        TOOL_LINES+=("ai-leverage|||not a git copy: get the newest from GitHub")
    fi

    # uv runs the Hugging Face downloader. bootstrap.sh installs it, and it
    # updates itself.
    if command -v uv &> /dev/null; then
        version=$(uv --version 2> /dev/null | awk '{ print $2 }')
        newest=$(github_latest astral-sh/uv)
        if [ -z "$newest" ]; then note="couldn't look it up online"
        elif newer "$newest" "$version"; then note="update with: uv self update"
        else newest="" note="up to date"; fi
        TOOL_LINES+=("uv|$version|$newest|$note")
    fi

    # Textual draws the menus. src/python/uv.lock pins its version, so it
    # moves with ai-leverage itself, not on its own.
    version=$("$BASE_DIR/src/python/.venv/bin/python" -I -c \
        'import importlib.metadata as m; print(m.version("textual"))' 2> /dev/null)
    [ -n "$version" ] && TOOL_LINES+=("Textual|$version||draws the menus; it moves with ai-leverage (git pull)")

    # Docker and the NVIDIA Container Toolkit come with the system's updates
    if command -v docker &> /dev/null; then
        version=$(docker --version 2> /dev/null | sed -n 's/^Docker version \([^,]*\).*/\1/p')
        TOOL_LINES+=("Docker|$version||your system updates it (sudo apt upgrade)")
        version=$(docker compose version --short 2> /dev/null)
        TOOL_LINES+=("Compose|${version%%+*}||your system updates it")
    fi
    if command -v nvidia-ctk &> /dev/null; then
        version=$(nvidia-ctk --version 2> /dev/null | head -n 1 | awk '{ print $NF }')
        TOOL_LINES+=("GPU toolkit|$version||NVIDIA Container Toolkit; your system updates it")
    fi

    # The NVIDIA driver belongs to the system. On Pop!_OS, say when Pop's own
    # driver package names a newer branch than the one installed.
    if command -v nvidia-smi &> /dev/null; then
        version=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2> /dev/null | head -n 1)
        note="the system manages it; CUDA $(nvidia-smi 2> /dev/null | sed -n 's/.*CUDA Version: \([0-9.]*\).*/\1/p' | head -n 1)"
        pop=$(apt-cache depends system76-driver-nvidia 2> /dev/null | grep -oE 'nvidia-driver-[0-9]+' | head -n 1)
        major=${version%%.*}
        if [ -n "$pop" ] && [ -n "$major" ] && [ "${pop##*-}" -gt "$major" ]; then
            note="$note; Pop!_OS now installs ${pop##*-}"
        fi
        TOOL_LINES+=("NVIDIA driver|$version||$note")
    fi
}

check_all() {
    local services=0 apps=0 i
    for i in "${!ROW_KIND[@]}"; do
        if [ "${ROW_KIND[$i]}" == service ]; then services=$((services + 1)); else apps=$((apps + 1)); fi
    done
    # Asked here, so the checks running side by side don't each ask for it
    sudo -v || exit 1
    echo -e "${CYAN}Looking online for newer versions of $services engines and services, $apps apps"
    echo -e "and the tools. Nothing is downloaded...${NC}"
    local tools
    tools=$(mktemp)
    check_tools_to "$tools" &
    check_rows "${!ROW_PATH[@]}"
    wait
    mapfile -t TOOL_LINES < "$tools"
    rm -f "$tools"
    checked
    CHECKED_AT=$(date +%H:%M)
}

# check_tools in the background, its lines into a file, and kept for the
# menu, which shows them before it checks again
check_tools_to() {
    check_tools
    printf '%s\n' "${TOOL_LINES[@]}" > "$1"
    mkdir -p "$UPDATE_CACHE_DIR"
    printf '%s\n' "${TOOL_LINES[@]}" > "$UPDATE_CACHE_DIR/.tools"
}

# When the check was done, for the main menu. A check of every folder also
# drops what was kept for folders that are gone.
checked() {
    local keep=" " i rel file
    mkdir -p "$UPDATE_CACHE_DIR"
    touch "$UPDATE_CACHE_DIR/.checked"
    $EVERY_FOLDER || return 0
    for i in "${!ROW_PATH[@]}"; do
        rel=${ROW_PATH[$i]#"$BASE_DIR"/}
        keep+="${rel//\//-} "
    done
    for file in "$UPDATE_CACHE_DIR"/*; do
        [ -f "$file" ] || continue
        [[ "$keep" == *" $(basename "$file") "* ]] || rm -f "$file"
    done
}

# --print: every check side by side, as in check_rows, each line printed as
# soon as its check is done. One echo is one write, so lines never mix.
print_all() {
    sudo -v || exit 1
    local i
    (
        check_tools_to /dev/null
        for i in "${TOOL_LINES[@]}"; do echo "tool|$i"; done
    ) &
    for i in "${!ROW_PATH[@]}"; do
        [ "${ROW_KIND[$i]}" == service ] && print_row "$i" &
    done
    (
        for i in "${!ROW_PATH[@]}"; do
            [ "${ROW_KIND[$i]}" == app ] && print_row "$i"
        done
    ) &
    wait
    checked
}

print_row() {
    local found
    found=$("$(tool_of "$1")" "${ROW_PATH[$1]}" check 2> /dev/null < /dev/null | head -n 1)
    echo "row|${ROW_PATH[$1]}|${found:-failed|||}"
}

# --- Drawing ---

# Which Compose projects run: running, restarting or stopped, as in manage.sh
declare -A STATES
load_states() {
    STATES=()
    local project state
    while IFS='|' read -r project state; do
        [ -n "$project" ] || continue
        case "$state" in
            running)    STATES[$project]=running ;;
            restarting) [ "${STATES[$project]}" == running ] || STATES[$project]=restarting ;;
            *)          [ -n "${STATES[$project]}" ] || STATES[$project]=stopped ;;
        esac
    done < <(sudo docker ps --all --format '{{.Label "com.docker.compose.project"}}|{{.State}}' 2> /dev/null)
}

project_of() { basename "$1" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-'; }

is_running() {
    case "${STATES[$(project_of "$1")]}" in running|restarting) return 0 ;; esac
    return 1
}

# A row's status in brackets: run state for a service, install state for an
# app (from what its check found). An optional width pads it, for the list.
row_status() {
    local i=$1 label color
    if [ "${ROW_KIND[$i]}" == service ]; then
        case "${STATES[$(project_of "${ROW_PATH[$i]}")]}" in
            running)    label="[UP]";         color=$GREEN ;;
            restarting) label="[RESTARTING]"; color=$RED ;;
            stopped)    label="[STOPPED]";    color=$YELLOW ;;
            *)          label="[DOWN]";       color=$RED ;;
        esac
    else
        case "${ROW_RESULT[$i]}" in
            held)    label="[HELD]";          color=$YELLOW ;;
            other)   label="[OTHER INSTALL]"; color=$YELLOW ;;
            missing) label="[NOT INSTALLED]"; color=$NC ;;
            *)       label="[INSTALLED]";     color=$GREEN ;;
        esac
    fi
    printf "${color}%-${2:-0}s${NC}" "$label"
}

# What the check found, in words
row_text() {
    local i=$1 note=${ROW_NOTE[$1]}
    case "${ROW_RESULT[$i]}" in
        current) echo -e "${GREEN}up to date${NC}" ;;
        newer)   echo -e "${YELLOW}update available${NC}${note:+ ($note)}" ;;
        held)
            if [ "${ROW_NEWEST[$i]}" != "${ROW_INSTALLED[$i]}" ]; then echo -e "${CYAN}held${NC}, Update all skips it"
            else echo -e "${CYAN}held${NC}"; fi
            ;;
        missing)
            if [ "${ROW_KIND[$i]}" == service ]; then echo "not downloaded yet (Start downloads it)"
            else echo "not installed"; fi
            ;;
        other)   echo "installed another way, at ${ROW_INSTALLED[$i]}" ;;
        *)       echo -e "${RED}couldn't check online${NC}${note:+ ($note)}" ;;
    esac
}

# Installed and newest version, with an arrow when they differ
versions() {
    local installed=$1 newest=$2 arrow="  "
    [ -n "$newest" ] && [ "$newest" != "$installed" ] && arrow="→ "
    [ "$newest" == "$installed" ] && newest=""
    printf "%-${VERSION_WIDTH}s %s%-${VERSION_WIDTH}s" "$installed" "$arrow" "$newest"
}

# Room for the longest version on the screen, at least 12 characters, so the
# columns line up even with a long one such as "build 2026-10-14"
set_version_width() {
    local i name version newest
    VERSION_WIDTH=12
    for i in "${!ROW_PATH[@]}"; do
        for version in "${ROW_INSTALLED[$i]}" "${ROW_NEWEST[$i]}"; do
            [ ${#version} -gt $VERSION_WIDTH ] && VERSION_WIDTH=${#version}
        done
    done
    for i in "${TOOL_LINES[@]}"; do
        IFS='|' read -r name version newest _ <<< "$i"
        for version in "$version" "$newest"; do
            [ ${#version} -gt $VERSION_WIDTH ] && VERSION_WIDTH=${#version}
        done
    done
}

count_updates() {
    local i n=0
    for i in "${!ROW_RESULT[@]}"; do
        [ "${ROW_RESULT[$i]}" == newer ] && n=$((n + 1))
    done
    echo "$n"
}

draw() {
    local i group="" installed name version newest note
    set_version_width
    clear
    echo -e "${BOLD}AI LEVERAGE${NC} > ${YELLOW}Updates${NC}   checked $CHECKED_AT"
    echo "Each one's version on this PC and its newest stable release."
    echo -e "------------------------------------------------------------------------------"
    for i in "${!ROW_PATH[@]}"; do
        if [ "${ROW_GROUP[$i]}" != "$group" ]; then
            [ -n "$group" ] && echo
            group=${ROW_GROUP[$i]}
            echo -e "${BOLD}$group${NC}"
        fi
        installed=${ROW_INSTALLED[$i]}
        [ "${ROW_RESULT[$i]}" == other ] && installed=""
        printf "%2d) ${BOLD}%-14s${NC} %s %s %s\n" "$((i + 1))" "$(basename "${ROW_PATH[$i]}")" \
            "$(row_status "$i" $STATUS_WIDTH)" "$(versions "$installed" "${ROW_NEWEST[$i]}")" "$(row_text "$i")"
    done
    echo
    echo -e "${BOLD}TOOLS${NC} updated another way"
    for i in "${TOOL_LINES[@]}"; do
        IFS='|' read -r name version newest note <<< "$i"
        printf "    ${BOLD}%-14s${NC} %-${STATUS_WIDTH}s %s %s\n" "$name" "" "$(versions "$version" "$newest")" "$note"
    done
    echo -e "------------------------------------------------------------------------------"
    local n
    n=$(count_updates)
    if [ "$n" -gt 0 ]; then
        echo -e "a) ${YELLOW}Update all${NC}: $n update$([ "$n" -ne 1 ] && echo s), one after another (held ones stay as they are)"
    else
        echo -e "a) Update all (nothing to update)"
    fi
    echo -e "1-${#ROW_PATH[@]}) Update, Revert or Hold one of them"
    echo -e "c) ${CYAN}Check again${NC}"
    echo -e "Esc) Go back"
    echo -e "------------------------------------------------------------------------------"
}

# --- Actions ---

tool_of() { [ "${ROW_KIND[$1]}" == app ] && echo "$SCRIPT_DIR/app.sh" || echo "$SCRIPT_DIR/service.sh"; }

# Update, Revert or Hold one row, with the same entries as in its own menu.
# Only Esc goes back; anything else draws it again.
row_menu() {
    local i=$1 name state version held previous label choice action
    name=$(basename "${ROW_PATH[$i]}")
    while true; do
        # Before clearing the screen, in case sudo asks for your password
        IFS='|' read -r state version held previous label _ < <("$(tool_of "$i")" "${ROW_PATH[$i]}" status)
        # An app's own name, such as OpenCode; a service goes by its folder
        [ "${ROW_KIND[$i]}" == app ] && [ -n "$label" ] || label=$name
        load_states
        clear
        echo -e "${BOLD}AI LEVERAGE${NC} > ${YELLOW}Updates > $name${NC} $(row_status "$i") $version"
        echo -e "  └ $(row_text "$i")"
        echo -e "--------------------------------------------"
        echo -e "1) ${YELLOW}Update${NC} $label to its newest stable release (checks online first)"
        if [ -n "$previous" ]; then
            echo -e "2) ${CYAN}Revert${NC} $label to $previous, the version before the last update"
        else
            echo -e "2) ${CYAN}Revert${NC} $label to the version before the last update (none saved yet)"
        fi
        if [ -n "$held" ]; then
            echo -e "3) ${BOLD}Release${NC} the hold on $label, so Update updates it again"
        else
            echo -e "3) ${BOLD}Hold${NC} $label at ${version:-its version}, so Update skips it"
        fi
        echo -e "--------------------------------------------"
        echo -e "Esc) Go back"
        echo -e "--------------------------------------------"
        read_choice "Selection: " || return
        choice=$REPLY
        case "$choice" in
            1) action=update ;;
            2) action=revert ;;
            3) if [ -n "$held" ]; then action=release; else action=hold; fi ;;
            *) continue ;;
        esac
        echo
        trap true INT
        "$(tool_of "$i")" "${ROW_PATH[$i]}" "$action"
        trap - INT
        echo
        pause
        # What it is now, for this menu and the overview
        echo -e "${CYAN}Checking $label again...${NC}"
        check_rows "$i"
    done
}

update_all() {
    local todo=() i n=0 running=false backups=false ok=() failed=()
    load_states
    for i in "${!ROW_RESULT[@]}"; do
        [ "${ROW_RESULT[$i]}" == newer ] && todo+=("$i")
    done
    if [ ${#todo[@]} -eq 0 ]; then
        echo -e "\n${GREEN}Nothing to update.${NC}"
        sleep 1
        return
    fi
    echo
    echo "Update all updates these, one after another:"
    for i in "${todo[@]}"; do
        local note="" data=""
        if [ "${ROW_KIND[$i]}" == service ]; then
            if is_running "${ROW_PATH[$i]}"; then
                note="running: restarts it"
                running=true
            fi
            data=$("$(tool_of "$i")" "${ROW_PATH[$i]}" data 2> /dev/null)
            if [ -n "$data" ]; then
                note="${note:+$note; }backs up its data first, ${data##*|}"
                backups=true
            fi
        fi
        printf "   %-14s %s → %s%s\n" "$(basename "${ROW_PATH[$i]}")" "${ROW_INSTALLED[$i]}" "${ROW_NEWEST[$i]}" "${note:+  ($note)}"
    done
    if $running; then
        echo -e "${YELLOW}The running ones restart: open chats are cut off, and an engine loads its model again.${NC}"
    fi
    if $backups; then
        echo -e "${YELLOW}A new version may convert the data it finds, so the old version can't read it
after a Revert. The backups (in backups/) let Revert put it back.${NC}"
    fi
    ask "Update these ${#todo[@]}?" || { echo -e "${CYAN}Cancelled.${NC}"; sleep 1; return; }

    trap true INT
    for i in "${todo[@]}"; do
        n=$((n + 1))
        echo -e "\n${BOLD}── $n of ${#todo[@]}: $(basename "${ROW_PATH[$i]}") ──${NC}"
        if "$(tool_of "$i")" "${ROW_PATH[$i]}" update --yes; then
            ok+=("$(basename "${ROW_PATH[$i]}")")
        else
            failed+=("$(basename "${ROW_PATH[$i]}")")
        fi
    done
    trap - INT

    echo -e "\n${BOLD}── Done ──${NC}"
    [ ${#ok[@]} -gt 0 ] && echo -e "${GREEN}√ Updated: ${ok[*]}${NC}"
    [ ${#failed[@]} -gt 0 ] && echo -e "${RED}× Failed: ${failed[*]} (see the messages above)${NC}"
    pause
    check_rows "${todo[@]}"
}

# --- Main ---

if [ ${#ROW_PATH[@]} -eq 0 ]; then
    echo "Nothing to check: no stack folder with a compose file, and no app."
    exit 0
fi

if $PRINT; then
    print_all
    exit 0
fi

check_all
while true; do
    load_states
    draw
    read_choice "Selection: " || exit 0
    choice=$REPLY
    case "$choice" in
        [Aa]) update_all ;;
        [Cc]) check_all ;;
        *)
            if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#ROW_PATH[@]} ]; then
                row_menu $((choice - 1))
            fi
            ;;
    esac
done
