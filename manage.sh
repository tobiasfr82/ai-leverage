#!/bin/bash
# ai-leverage/manage.sh
# Menu for everything in stack/, grouped in the order the parts build on each
# other: downloaders get models onto this PC, engines run them, and services are
# what you use. Start, stop, update and follow the logs of each engine and
# service, and run the scripts a folder brings along (model downloads and such).
# A new folder in a group shows up here on its own: a compose.yaml gives it
# Start/Stop, and every executable *.sh in it becomes a menu entry.

# --- Configuration ---
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_DIR="$BASE_DIR/stack"

# Unified script directory (all helpers moved here)
SCRIPT_DIR="$BASE_DIR/src/bash"

# The groups in stack/, in menu order, each with the line shown next to its
# heading. A folder in stack/ that isn't listed here still shows up, after these.
STACK_GROUPS=(
  "downloaders|get models onto this PC"
  "engines|run the models"
  "services|what you use"
)

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

# --- Functions ---

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
# port, such as a path), or else the first port it publishes on this PC.
declare -A STATES URLS
load_states() {
  STATES=()
  URLS=()
  local project state url ports
  while IFS='|' read -r project state url ports; do
    [ -n "$project" ] || continue
    case "$state" in
      running)
        STATES[$project]=running
        if [ -z "$url" ] && [[ "$ports" =~ :([0-9]+)- ]]; then
          url="http://localhost:${BASH_REMATCH[1]}"
        fi
        [ -n "$url" ] && URLS[$project]=$url
        ;;
      restarting)
        [ "${STATES[$project]}" == running ] || STATES[$project]=restarting
        ;;
      *)
        [ -n "${STATES[$project]}" ] || STATES[$project]=stopped
        ;;
    esac
  done < <(sudo docker ps --all --format '{{.Label "com.docker.compose.project"}}|{{.State}}|{{.Label "ai-leverage.url"}}|{{.Ports}}' 2> /dev/null)
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

service_menu() {
  local path=$1
  # With its group, e.g. "engines/ollama": ollama is a downloader and an engine
  local name=${path#"$STACK_DIR"/}
  local has_compose=false
  [ -n "$(compose_file "$path")" ] && has_compose=true
  # Service actions take 1-6, so the folder's own scripts start at 7
  local first=1
  $has_compose && first=7

  while true; do
    # Before clearing the screen, in case sudo asks for your password
    load_states
    local status_indicator
    status_indicator="$(get_status "$path") $(get_url "$path")"
    local scripts
    mapfile -t scripts < <(list_scripts "$path")
    clear
    echo -e "${BOLD}AI LEVERAGE${NC} > ${YELLOW}${name/\// > }${NC} $status_indicator"
    echo -e "--------------------------------------------"
    if $has_compose; then
      echo -e "1) ${GREEN}Start${NC} (up, also applies .env changes)"
      echo -e "2) ${RED}Stop${NC} (stop)"
      echo -e "3) ${CYAN}Restart${NC} (restart)"
      echo -e "4) ${YELLOW}Update${NC} (pull & cleanup)"
      echo -e "5) ${BOLD}Rebuild${NC} (down & up --build)"
      echo -e "6) ${BOLD}View logs${NC}"
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
        4)
          echo -e "${CYAN}Starting Update & Cleanup...${NC}"
          # Pulls new images, recreates the container, then wipes the old dangling layers
          ensure_network && run_cmd "$path" "sudo docker compose pull && sudo docker compose up -d && sudo docker image prune -f"
          ;;
        5)
          echo -e "\n${RED}${BOLD}REBUILDING:${NC} This deletes and recreates the container."
          read -p "Continue? (y/N): " confirm
          if [[ "$confirm" =~ ^[Yy]$ ]]; then
            ensure_network && run_cmd "$path" "sudo docker compose down && sudo docker compose up -d --build"
          else
            echo -e "${CYAN}Rebuild cancelled.${NC}"
            sleep 1
          fi
          ;;
        6) open_helper "docker-view-logs.sh" "$path" ;;
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

main_menu() {
  while true; do
    # Before clearing the screen, in case sudo asks for your password
    load_states
    clear
    echo -e "${BOLD}AI LEVERAGE STACK MANAGER${NC}"
    echo -e "--------------------------------------------"
    # A heading per group, and its folders under it, with where to open the
    # ones that run. The numbers run on from one group to the next.
    local groups entry group members dir
    local items=()
    mapfile -t groups < <(list_groups)
    for entry in "${groups[@]}"; do
      group=${entry%%|*}
      mapfile -t members < <(group_items "$STACK_DIR/$group")
      [ ${#members[@]} -eq 0 ] && continue
      printf "${BOLD}%-13s${NC} %s\n\n" "${group^^}" "${entry#*|}"
      for dir in "${members[@]}"; do
        items+=("$dir")
        printf "%2d) ${BOLD}%-14s${NC} %s %s\n" "${#items[@]}" "$(basename "$dir")" "$(get_status "$dir" 12)" "$(get_url "$dir")"
      done
      echo
    done

    if [ ${#items[@]} -eq 0 ]; then
      echo -e "${RED}Nothing found in $STACK_DIR${NC}"
      read -n 1 -p "Check structure and press any key to exit..."
      exit 0
    fi

    echo -e "--------------------------------------------"
    echo -e "m) ${CYAN}Monitor GPU${NC}"
    echo -e "p) ${CYAN}View Docker Ports${NC}"
    echo -e "s) ${RED}Stop all${NC} engines and services"
    echo -e "q) Quit"
    echo -e "--------------------------------------------"
    read -p "Selection: " choice

    if [[ "$choice" == "q" ]]; then clear; exit 0; fi
    if [[ "$choice" == "m" ]]; then open_helper "monitor-gpu.sh"; fi
    if [[ "$choice" == "p" ]]; then open_helper "docker-list-ports.sh"; fi
    if [[ "$choice" == "s" ]]; then stop_all "${items[@]}"; fi
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -le "${#items[@]}" ] && [ "$choice" -gt 0 ]; then
      service_menu "${items[$((choice-1))]}"
    fi
  done
}

# Installs from before stack/ was split into groups keep their settings and data
# in the old folders until this moves them. It does nothing once they're moved.
"$SCRIPT_DIR/migrate-stack-layout.sh" || exit 1

main_menu
