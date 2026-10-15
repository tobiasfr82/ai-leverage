#!/bin/bash
# ai-leverage/manage.sh
# Menu for everything in stack/, grouped in the order the parts build on each
# other: downloaders get models onto this PC, engines run them, and services are
# what you use. Start, stop, update and follow the logs of each engine and
# service, and run the scripts a folder brings along (model downloads and such).
# A new folder in a group shows up here on its own: a compose.yaml gives it
# Start/Stop, and every executable *.sh in it becomes a menu entry.
# Below them, the desktop apps in apps/: a folder with an app.conf gets Install,
# Update, Revert, Hold and Uninstall, all done by src/bash/app.sh.
# Engines and services get the same Update, Revert and Hold (src/bash/service.sh),
# and u opens the update overview of all of them (src/bash/check-updates.sh).
# f shows which downloaded models fit on this PC for what you need, biggest
# first, and how to run each one (src/python/fit_screen.py).

# --- Configuration ---
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_DIR="$BASE_DIR/stack"
APPS_DIR="$BASE_DIR/apps"

# Unified script directory (all helpers moved here)
SCRIPT_DIR="$BASE_DIR/src/bash"

# Where the update check keeps what it found (see src/bash/update-common.sh)
UPDATE_CACHE_DIR="$BASE_DIR/cache/updates"

# The groups in stack/, in menu order, each with the line shown next to its
# heading. A folder in stack/ that isn't listed here still shows up, after these.
STACK_GROUPS=(
  "downloaders|get models onto this PC"
  "engines|run the models"
  "services|what you use"
)

# Room for the longest status, [NOT INSTALLED], so the lists line up
STATUS_WIDTH=15

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

# --- Functions ---

# A version as the menus show it: a number gets a v (v2.1.287), anything else
# stays as it is (b11580, "new build", where another install came from)
show_version() {
  if [[ "$1" =~ ^[0-9] ]]; then echo "v$1"; else echo "$1"; fi
}

# Which ai-leverage this is: its release tag, or else its commit, and the
# branch when it isn't main. Nothing when it isn't a git checkout.
stack_version() {
  local version branch
  version=$(git -C "$BASE_DIR" describe --tags --always 2> /dev/null) || return
  branch=$(git -C "$BASE_DIR" branch --show-current 2> /dev/null)
  [ -n "$branch" ] && [ "$branch" != main ] && version+=" on $branch"
  echo "version $version"
}

pause() {
  read -n 1 -s -r -p "Press any key to return..."
  echo
}

# The folder's compose file, if it has one
compose_file() {
  local file
  for file in "$1/compose.yaml" "$1/docker-compose.yml"; do
    [ -f "$file" ] && { echo "$file"; return; }
  done
}

# Executable *.sh files in a folder, by name
list_scripts() {
  find "$1" -maxdepth 1 -type f -name '*.sh' -perm -u+x -printf '%f\n' | sort
}

# Every group as "name|description": the ones in STACK_GROUPS first, in that
# order, then any other folder in stack/
list_groups() {
  local dir name entry known
  printf '%s\n' "${STACK_GROUPS[@]}"
  for dir in "$STACK_DIR"/*/; do
    [ -d "$dir" ] || continue
    name=$(basename "$dir")
    known=false
    for entry in "${STACK_GROUPS[@]}"; do
      [ "${entry%%|*}" == "$name" ] && known=true
    done
    $known || echo "$name|"
  done
}

# The folders in a group the menu can do something with: ones with a compose
# file or with scripts to run
group_items() {
  local dir
  for dir in "$1"/*/; do
    [ -d "$dir" ] || continue
    if [ -n "$(compose_file "$dir")" ] || [ -n "$(list_scripts "$dir")" ]; then
      echo "${dir%/}"
    fi
  done
}

# Runs a command in this terminal. Ctrl+C stops the command, not the menu.
run_here() {
  trap true INT
  "$@"
  trap - INT
  echo
  pause
}

# Runs a helper from src/bash. On a desktop it opens in its own terminal window
# so this menu stays usable. Without a desktop (e.g. over SSH), or when none of
# the known terminals is installed, it runs right here instead.
open_helper() {
  local script="$1"; shift
  local cmd hold term
  cmd="$(printf '%q ' "$SCRIPT_DIR/$script" "$@")"
  # Ctrl+C stops the helper but keeps the window open, to read what it printed
  hold="trap true INT; $cmd; echo; read -n 1 -s -r -p 'Press any key to close...'"

  if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    for term in cosmic-term gnome-terminal ptyxis konsole xfce4-terminal kitty alacritty xterm; do
      command -v "$term" &> /dev/null || continue
      echo -e "${CYAN}Opening $script in a new window...${NC}"
      case "$term" in
        cosmic-term|gnome-terminal|ptyxis) setsid "$term" -- bash -c "$hold" ;;
        xfce4-terminal) setsid "$term" -x bash -c "$hold" ;;
        kitty)          setsid "$term" bash -c "$hold" ;;
        *)              setsid "$term" -e bash -c "$hold" ;;
      esac > /dev/null 2>&1 &
      sleep 0.5
      return
    done
  fi

  run_here bash -c "$cmd"
}

# Compose's name for a folder's project, which its containers are labelled
# with: the folder name in lowercase, keeping letters, digits, - and _
project_name() {
  basename "$1" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-'
}

# What runs, from one look at Docker. For each Compose project, STATES holds
# running, restarting or stopped, and URLS where to open it while it runs: its
# ai-leverage.url label (set in compose.yaml when the address needs more than a
# port, such as a path), or else the first port it publishes on this PC. INFOS
# holds its ai-leverage.info label while it runs, a line about what it runs,
# such as an engine's model.
declare -A STATES URLS INFOS
load_states() {
  STATES=()
  URLS=()
  INFOS=()
  local project state url info ports
  while IFS='|' read -r project state url info ports; do
    [ -n "$project" ] || continue
    case "$state" in
      running)
        STATES[$project]=running
        if [ -z "$url" ] && [[ "$ports" =~ :([0-9]+)- ]]; then
          url="http://localhost:${BASH_REMATCH[1]}"
        fi
        [ -n "$url" ] && URLS[$project]=$url
        [ -n "$info" ] && INFOS[$project]=$info
        ;;
      restarting)
        [ "${STATES[$project]}" == running ] || STATES[$project]=restarting
        ;;
      *)
        [ -n "${STATES[$project]}" ] || STATES[$project]=stopped
        ;;
    esac
  done < <(sudo docker ps --all --format '{{.Label "com.docker.compose.project"}}|{{.State}}|{{.Label "ai-leverage.url"}}|{{.Label "ai-leverage.info"}}|{{.Ports}}' 2> /dev/null)
}

# A folder's status: [UP], [RESTARTING] (it keeps crashing), [STOPPED], or
# [DOWN] when it has no container yet. Nothing for folders with scripts only.
# An optional width pads it, to line statuses up in a list.
get_status() {
  [ -n "$(compose_file "$1")" ] || return
  local label color project
  project=$(project_name "$1")
  case "${STATES[${project:-_}]}" in
    running)    label="[UP]";         color=$GREEN ;;
    restarting) label="[RESTARTING]"; color=$RED ;;
    stopped)    label="[STOPPED]";    color=$YELLOW ;;
    *)          label="[DOWN]";       color=$RED ;;
  esac
  printf "${color}%-${2:-0}s${NC}" "$label"
}

# Where to open a folder's service while it runs (see load_states)
get_url() {
  [ -n "$(compose_file "$1")" ] || return
  local project
  project=$(project_name "$1")
  echo "${URLS[${project:-_}]}"
}

# The address other containers, such as Open WebUI, reach a folder's service
# at: its ai-leverage.connect label, read from the compose file so it shows
# whether it runs or not. It's what goes in Open WebUI's connection settings.
get_connect() {
  local file
  file=$(compose_file "$1")
  [ -n "$file" ] || return
  sed -n 's/^ *ai-leverage\.connect: *"\(.*\)" *$/\1/p' "$file" | head -n 1
}

# The line about what a folder's service runs, while it runs (see load_states)
get_info() {
  [ -n "$(compose_file "$1")" ] || return
  local project
  project=$(project_name "$1")
  echo "${INFOS[${project:-_}]}"
}

# Stops every engine and service that runs, after asking. The services stop
# first, then the engines they use: the menu's order, backwards.
stop_all() {
  local items=("$@") active=() i dir
  load_states
  for (( i=${#items[@]}-1; i>=0; i-- )); do
    dir=${items[$i]}
    [ -n "$(compose_file "$dir")" ] || continue
    case "${STATES[$(project_name "$dir")]}" in
      running|restarting) active+=("$dir") ;;
    esac
  done
  if [ ${#active[@]} -eq 0 ]; then
    echo -e "\n${CYAN}Nothing is running.${NC}"
    sleep 1
    return
  fi

  echo -e "\n${RED}${BOLD}STOP ALL:${NC} $(for dir in "${active[@]}"; do printf '%s ' "$(basename "$dir")"; done)"
  read -p "Stop these? (y/N): " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo -e "${CYAN}Cancelled.${NC}"
    sleep 1
    return
  fi
  for dir in "${active[@]}"; do
    echo -e "\n${CYAN}Stopping ${dir#"$STACK_DIR"/}...${NC}"
    (cd "$dir" && sudo docker compose stop)
  done
  echo -e "\n${GREEN}Complete!${NC}"
  pause
}

run_cmd() {
  local dir=$1
  local cmd=$2
  echo -e "\n${CYAN}Executing: $cmd${NC}"
  if (cd "$dir" && eval "$cmd"); then
    echo -e "\n${GREEN}Complete!${NC}"
  else
    echo -e "\n${RED}Failed. See the messages above.${NC}"
  fi
  pause
}

ensure_network() {
  # Services join the shared "ai-leverage" network, which must exist before they start
  if ! "$SCRIPT_DIR/docker-create-network.sh"; then
    pause
    return 1
  fi
}

# A service's version and update state, from service.sh without going online:
# SVC_STATE is downloaded or missing, SVC_HELD is set while it's held,
# SVC_PREVIOUS is the version Revert goes back to
load_service() {
  IFS='|' read -r SVC_STATE SVC_VERSION SVC_HELD SVC_PREVIOUS < <("$SCRIPT_DIR/service.sh" "$1" status)
  SVC_VERSION=$(show_version "$SVC_VERSION")
  SVC_PREVIOUS=$(show_version "$SVC_PREVIOUS")
}

service_menu() {
  local path=$1
  # With its group, e.g. "engines/ollama": ollama is a downloader and an engine
  local name=${path#"$STACK_DIR"/}
  local short
  short=$(basename "$path")
  local has_compose=false
  [ -n "$(compose_file "$path")" ] && has_compose=true
  # Service actions take 1-8, so the folder's own scripts start at 9
  local first=1
  $has_compose && first=9

  while true; do
    # Before clearing the screen, in case sudo asks for your password
    load_states
    local status_indicator info connect
    status_indicator="$(get_status "$path")"
    if $has_compose; then
      load_service "$path"
      [ -n "$SVC_VERSION" ] && status_indicator+=" $SVC_VERSION"
      [ -n "$SVC_HELD" ] && status_indicator+=" ${YELLOW}(held)${NC}"
    fi
    status_indicator+=" $(get_url "$path")"
    info=$(get_info "$path")
    connect=$(get_connect "$path")
    local scripts
    mapfile -t scripts < <(list_scripts "$path")
    clear
    echo -e "${BOLD}AI LEVERAGE${NC} > ${YELLOW}${name/\// > }${NC} $status_indicator"
    [ -n "$info" ] && echo "  └ $info"
    # The address in bold, the note on where it goes after it
    [ -n "$connect" ] && echo -e "  Other services reach it at ${BOLD}${connect%% (*}${NC}${connect#"${connect%% (*}"}"
    echo -e "--------------------------------------------"
    if $has_compose; then
      echo -e "1) ${GREEN}Start${NC} (up, also applies .env changes)"
      echo -e "2) ${RED}Stop${NC} (stop)"
      echo -e "3) ${CYAN}Restart${NC} (restart)"
      echo -e "4) ${YELLOW}Update${NC} $short to its newest stable release (checks online first)"
      if [ -n "$SVC_PREVIOUS" ]; then
        echo -e "5) ${CYAN}Revert${NC} $short to $SVC_PREVIOUS, the version before the last update"
      else
        echo -e "5) ${CYAN}Revert${NC} $short to the version before the last update (none saved yet)"
      fi
      if [ -n "$SVC_HELD" ]; then
        echo -e "6) ${BOLD}Release${NC} the hold on $short, so Update updates it again"
      else
        echo -e "6) ${BOLD}Hold${NC} $short at ${SVC_VERSION:-its version}, so Update skips it"
      fi
      echo -e "7) ${BOLD}Rebuild${NC} (down & up --build)"
      echo -e "8) ${BOLD}View logs${NC}"
      echo -e "--------------------------------------------"
    fi
    if [ ${#scripts[@]} -gt 0 ]; then
      local i
      for i in "${!scripts[@]}"; do
        echo -e "$((first + i))) ${scripts[$i]%.sh}"
      done
      echo -e "--------------------------------------------"
    fi
    echo -e "b) Go back"
    echo -e "q) Quit"
    echo -e "--------------------------------------------"
    read -p "Selection: " choice

    case $choice in
      [Bb]) return ;;
      [Qq]) clear; exit 0 ;;
    esac

    if $has_compose; then
      case $choice in
        1) ensure_network && run_cmd "$path" "sudo docker compose up -d" ;;
        2) run_cmd "$path" "sudo docker compose stop" ;;
        3) ensure_network && run_cmd "$path" "sudo docker compose restart" ;;
        # The same steps as in the update overview: service.sh
        4) run_here "$SCRIPT_DIR/service.sh" "$path" update ;;
        5) run_here "$SCRIPT_DIR/service.sh" "$path" revert ;;
        6) run_here "$SCRIPT_DIR/service.sh" "$path" "$([ -n "$SVC_HELD" ] && echo release || echo hold)" ;;
        7)
          echo -e "\n${RED}${BOLD}REBUILDING:${NC} This deletes and recreates the container."
          read -p "Continue? (y/N): " confirm
          if [[ "$confirm" =~ ^[Yy]$ ]]; then
            ensure_network && run_cmd "$path" "sudo docker compose down && sudo docker compose up -d --build"
          else
            echo -e "${CYAN}Rebuild cancelled.${NC}"
            sleep 1
          fi
          ;;
        8) open_helper "docker-view-logs.sh" "$path" ;;
      esac
    fi

    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge "$first" ] && [ "$choice" -lt $((first + ${#scripts[@]})) ]; then
      local script=${scripts[$((choice - first))]}
      echo -e "\n${CYAN}Running $name/$script...${NC}\n"
      # From inside its own folder, so the script finds its models.txt, .env and so on
      run_here bash -c 'cd "$1" && "./$2"' _ "$path" "$script"
    fi
  done
}

# The folders in apps/ with an app.conf
list_apps() {
  local dir
  for dir in "$APPS_DIR"/*/; do
    [ -f "$dir/app.conf" ] && echo "${dir%/}"
  done
}

# An app's state, from app.sh without going online: APP_STATE is installed,
# missing or other (installed some other way, APP_VERSION then says where),
# APP_HELD is set while it's held, APP_PREVIOUS is the version Revert goes
# back to. Also its name, where it comes from, and what it is.
load_app() {
  IFS='|' read -r APP_STATE APP_VERSION APP_HELD APP_PREVIOUS APP_NAME APP_SOURCE APP_ABOUT \
    < <("$SCRIPT_DIR/app.sh" "$1" status)
  APP_VERSION=$(show_version "$APP_VERSION")
  APP_PREVIOUS=$(show_version "$APP_PREVIOUS")
}

# The loaded app's status: [INSTALLED], [HELD] (installed, and Update skips it),
# [OTHER INSTALL] (installed some other way), or [NOT INSTALLED]. An optional
# width pads it, to line statuses up in a list.
app_status() {
  local label color
  case "$APP_STATE" in
    installed)
      if [ -n "$APP_HELD" ]; then label="[HELD]"; color=$YELLOW
      else label="[INSTALLED]"; color=$GREEN; fi
      ;;
    other) label="[OTHER INSTALL]"; color=$YELLOW ;;
    *)     label="[NOT INSTALLED]"; color=$NC ;;
  esac
  printf "${color}%-${1:-0}s${NC}" "$label"
}

app_menu() {
  local path=$1
  local name
  name=$(basename "$path")
  # The app's actions take 1-5, so its own scripts start at 6
  local first=6

  while true; do
    load_app "$path"
    local scripts
    mapfile -t scripts < <(list_scripts "$path")
    clear
    echo -e "${BOLD}AI LEVERAGE${NC} > ${YELLOW}apps > $name${NC} $(app_status) $APP_VERSION"
    [ -n "$APP_ABOUT" ] && echo "  └ $APP_ABOUT"
    echo -e "--------------------------------------------"
    echo -e "1) ${GREEN}Install${NC} $APP_NAME ($APP_SOURCE)"
    echo -e "2) ${YELLOW}Update${NC} $APP_NAME to its newest stable release (checks online first)"
    if [ -n "$APP_PREVIOUS" ]; then
      echo -e "3) ${CYAN}Revert${NC} $APP_NAME to $APP_PREVIOUS, the version before the last update"
    else
      echo -e "3) ${CYAN}Revert${NC} $APP_NAME to the version before the last update (none saved yet)"
    fi
    if [ -n "$APP_HELD" ]; then
      echo -e "4) ${BOLD}Release${NC} the hold on $APP_NAME, so Update updates it again"
    else
      echo -e "4) ${BOLD}Hold${NC} $APP_NAME at ${APP_VERSION:-its version}, so Update skips it"
    fi
    echo -e "5) ${RED}Uninstall${NC} $APP_NAME (your own files and settings stay)"
    echo -e "--------------------------------------------"
    if [ ${#scripts[@]} -gt 0 ]; then
      local i
      for i in "${!scripts[@]}"; do
        echo -e "$((first + i))) ${scripts[$i]%.sh}"
      done
      echo -e "--------------------------------------------"
    fi
    echo -e "b) Go back"
    echo -e "q) Quit"
    echo -e "--------------------------------------------"
    read -p "Selection: " choice

    case $choice in
      [Bb]) return ;;
      [Qq]) clear; exit 0 ;;
      1) run_here "$SCRIPT_DIR/app.sh" "$path" install ;;
      2) run_here "$SCRIPT_DIR/app.sh" "$path" update ;;
      3) run_here "$SCRIPT_DIR/app.sh" "$path" revert ;;
      4) run_here "$SCRIPT_DIR/app.sh" "$path" "$([ -n "$APP_HELD" ] && echo release || echo hold)" ;;
      5) run_here "$SCRIPT_DIR/app.sh" "$path" uninstall ;;
    esac

    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge "$first" ] && [ "$choice" -lt $((first + ${#scripts[@]})) ]; then
      local script=${scripts[$((choice - first))]}
      echo -e "\n${CYAN}Running apps/$name/$script...${NC}\n"
      run_here bash -c 'cd "$1" && "./$2"' _ "$path" "$script"
    fi
  done
}

# What the last update check found, without going online: when it ran, and
# how many updates it found that haven't been installed since
update_summary() {
  local dir=$UPDATE_CACHE_DIR minutes age count
  if [ ! -f "$dir/.checked" ]; then
    echo "(looks online)"
    return
  fi
  minutes=$(( ($(date +%s) - $(stat -c %Y "$dir/.checked")) / 60 ))
  if [ $minutes -lt 1 ]; then age="just now"
  elif [ $minutes -lt 60 ]; then age="$minutes min ago"
  elif [ $minutes -lt 2880 ]; then age="$((minutes / 60)) h ago"
  else age="$((minutes / 1440)) days ago"; fi
  count=$(cat "$dir"/* 2> /dev/null | grep -c '^newer|')
  case $count in
    0) echo "(last check $age: no updates)" ;;
    1) echo "(last check $age: ${YELLOW}1 update${NC})" ;;
    *) echo "(last check $age: ${YELLOW}$count updates${NC})" ;;
  esac
}

# The newer version the last update check found for a folder, e.g. "↑ 0.40.4",
# without going online. Nothing when there's none, and none once it's updated.
update_hint() {
  # The same name the check gives it: stack/engines/ollama is stack-engines-ollama
  local key=${1#"$BASE_DIR"/} file result installed newest
  file="$UPDATE_CACHE_DIR/${key//\//-}"
  [ -f "$file" ] || return
  IFS='|' read -r result installed newest _ < "$file"
  [ "$result" == newer ] || return
  [ "$newest" == "$installed" ] && newest="new build"
  echo -e "${YELLOW}↑ $(show_version "$newest")${NC}"
}

main_menu() {
  while true; do
    # Before clearing the screen, in case sudo asks for your password
    load_states
    # What the PC has to spare (disk where models/ is, RAM, the GPU), as of
    # this drawing of the menu. r draws it again with fresh numbers.
    local system
    system=$("$SCRIPT_DIR/monitor-system.sh" --summary)
    clear
    echo -e "${BOLD}AI LEVERAGE STACK MANAGER${NC}   $(stack_version)"
    echo -e "--------------------------------------------"
    echo -e "$system"
    echo -e "--------------------------------------------"
    # A heading per group, and its folders right under it, with where to open
    # the ones that run. The numbers run on from one group to the next. A blank
    # line between groups and none elsewhere, so the menu fits one screen.
    local groups entry group members dir info gap=""
    local items=()
    mapfile -t groups < <(list_groups)
    for entry in "${groups[@]}"; do
      group=${entry%%|*}
      mapfile -t members < <(group_items "$STACK_DIR/$group")
      [ ${#members[@]} -eq 0 ] && continue
      printf "$gap${BOLD}%-13s${NC} %s\n" "${group^^}" "${entry#*|}"
      gap="\n"
      for dir in "${members[@]}"; do
        items+=("$dir")
        printf "%2d) ${BOLD}%-14s${NC} %s %s %s\n" "${#items[@]}" "$(basename "$dir")" "$(get_status "$dir" $STATUS_WIDTH)" "$(get_url "$dir")" "$(update_hint "$dir")"
        info=$(get_info "$dir")
        [ -n "$info" ] && echo "    └ $info"
      done
    done

    # The desktop apps, numbered on from the stack
    local apps
    mapfile -t apps < <(list_apps)
    if [ ${#apps[@]} -gt 0 ]; then
      printf "$gap${BOLD}%-13s${NC} %s\n" "APPS" "programs on this PC, outside Docker"
      for dir in "${apps[@]}"; do
        items+=("$dir")
        load_app "$dir"
        printf "%2d) ${BOLD}%-14s${NC} %s %s %s\n" "${#items[@]}" "$(basename "$dir")" "$(app_status $STATUS_WIDTH)" "$APP_VERSION" "$(update_hint "$dir")"
      done
    fi

    if [ ${#items[@]} -eq 0 ]; then
      echo -e "${RED}Nothing found in $STACK_DIR${NC}"
      read -n 1 -p "Check structure and press any key to exit..."
      exit 0
    fi

    echo -e "--------------------------------------------"
    echo -e "r) ${CYAN}Refresh${NC} disk, RAM, GPU, service and app status"
    echo -e "u) ${YELLOW}Check for updates${NC} of the engines, services and apps $(update_summary)"
    echo -e "f) ${CYAN}Model fit${NC}: the best models for what you need, and how to run them on this PC"
    # The short ones in pairs, the second of each lined up
    echo -e "m) ${CYAN}Monitor system${NC} (live)          p) ${CYAN}View Docker Ports${NC}"
    echo -e "s) ${RED}Stop all${NC} engines and services  q) Quit"
    echo -e "--------------------------------------------"
    read -p "Selection: " choice

    if [[ "$choice" == "q" ]]; then clear; exit 0; fi
    # Drawing the menu again is all a refresh takes
    if [[ "$choice" == "r" ]]; then continue; fi
    if [[ "$choice" == "u" ]]; then
      # In this window: it asks before it changes anything, and the menu
      # shows the new versions afterwards. Ctrl+C leaves it, not the menu.
      trap true INT
      "$SCRIPT_DIR/check-updates.sh" "${items[@]}"
      trap - INT
    fi
    if [[ "$choice" == "f" ]]; then
      # In this window, like u: a full screen of its own, which gives the
      # menu back as it was. Ctrl+C leaves it, not the menu.
      trap true INT
      python3 -I "$BASE_DIR/src/python/fit_screen.py"
      trap - INT
    fi
    if [[ "$choice" == "m" ]]; then open_helper "monitor-system.sh"; fi
    if [[ "$choice" == "p" ]]; then open_helper "docker-list-ports.sh"; fi
    if [[ "$choice" == "s" ]]; then stop_all "${items[@]}"; fi
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -le "${#items[@]}" ] && [ "$choice" -gt 0 ]; then
      dir=${items[$((choice-1))]}
      if [[ "$dir" == "$APPS_DIR"/* ]]; then app_menu "$dir"; else service_menu "$dir"; fi
    fi
  done
}

# Installs from before stack/ was split into groups keep their settings and data
# in the old folders until this moves them. It does nothing once they're moved.
"$SCRIPT_DIR/migrate-stack-layout.sh" || exit 1

main_menu
