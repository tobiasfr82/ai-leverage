#!/bin/bash
# ai-leverage/manage.sh
# Menu for everything in stack/: start, stop, update and follow the logs of each
# service, and run the scripts a folder brings along (model downloads and such).
# A new folder shows up here on its own: a compose.yaml makes it a service, and
# every executable *.sh in it becomes a menu entry.

# --- Configuration ---
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_DIR="$BASE_DIR/stack"

# Unified script directory (all helpers moved here)
SCRIPT_DIR="$BASE_DIR/src/bash"

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

get_status() {
  local dir=$1
  if [ -z "$(compose_file "$dir")" ]; then
    echo -e "${CYAN}[TOOLS]${NC}"
  # Improved status check to differentiate between Running and Stopped
  elif (cd "$dir" && sudo docker compose ps --format "{{.State}}" 2> /dev/null | grep -q "running"); then
    echo -e "${GREEN}[UP]${NC}"
  elif (cd "$dir" && sudo docker compose ps --all --quiet 2> /dev/null | grep -q .); then
    echo -e "${YELLOW}[STOPPED]${NC}"
  else
    echo -e "${RED}[DOWN]${NC}"
  fi
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
  local name
  name=$(basename "$path")
  local has_compose=false
  [ -n "$(compose_file "$path")" ] && has_compose=true
  # Service actions take 1-6, so the folder's own scripts start at 7
  local first=1
  $has_compose && first=7

  while true; do
    local status_indicator
    status_indicator=$(get_status "$path")
    local scripts
    mapfile -t scripts < <(list_scripts "$path")
    clear
    echo -e "${BOLD}AI LEVERAGE${NC} > ${YELLOW}$name${NC} $status_indicator"
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
    clear
    echo -e "${BOLD}AI LEVERAGE STACK MANAGER${NC}"
    echo -e "--------------------------------------------"
    # Services (folders with a compose file) first, then folders with only scripts
    local services tools dir
    mapfile -t services < <(for dir in "$STACK_DIR"/*/; do [ -n "$(compose_file "$dir")" ] && echo "${dir%/}"; done)
    mapfile -t tools < <(for dir in "$STACK_DIR"/*/; do [ -z "$(compose_file "$dir")" ] && [ -n "$(list_scripts "$dir")" ] && echo "${dir%/}"; done)
    local projects=("${services[@]}" "${tools[@]}")

    if [ ${#projects[@]} -eq 0 ]; then
      echo -e "${RED}No services found in $STACK_DIR${NC}"
      read -n 1 -p "Check structure and press any key to exit..."
      exit 0
    fi

    local i
    for i in "${!projects[@]}"; do
      local path="${projects[$i]}"
      local status
      status=$(get_status "$path")
      echo -e "$((i+1))) ${BOLD}$(basename "$path")${NC} $status"
    done

    echo -e "--------------------------------------------"
    echo -e "m) ${CYAN}Monitor GPU${NC}"
    echo -e "p) ${CYAN}View Docker Ports${NC}"
    echo -e "q) Quit"
    echo -e "--------------------------------------------"
    read -p "Select service: " choice

    if [[ "$choice" == "q" ]]; then clear; exit 0; fi
    if [[ "$choice" == "m" ]]; then open_helper "monitor-gpu.sh"; fi
    if [[ "$choice" == "p" ]]; then open_helper "docker-list-ports.sh"; fi
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -le "${#projects[@]}" ] && [ "$choice" -gt 0 ]; then
      service_menu "${projects[$((choice-1))]}"
    fi
  done
}

main_menu
