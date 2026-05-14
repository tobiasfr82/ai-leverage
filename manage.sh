#!/bin/bash

# --- Configuration ---
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_DIR="$BASE_DIR/stack"

GPU_SCRIPT_DIR="$BASE_DIR/src/monitor-gpu"
LOG_SCRIPT_DIR="$BASE_DIR/src/docker-logs"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

# --- Functions ---

open_in_cosmic() {
    local dir="$1"
    local script="$2"
    local arg="$3"
    local full_path="$dir/$script"

    if [ ! -f "$full_path" ]; then
        echo -e "${RED}ERROR: Script not found!${NC}"
        read -n 1 -s -r -p "Press any key to return..."
        return
    fi

    echo -e "${CYAN}Launching $script...${NC}"
    # Using Export to ensure the script in the new window picks up the target name
    export TARGET_ARG="$arg"
    setsid cosmic-term -- bash -c "cd '$dir' && ./$script \"\$TARGET_ARG\"; exec bash" >/dev/null 2>&1 &
    sleep 0.5
}

get_status() {
    local dir=$1
    # Improved status check to differentiate between Running and Stopped
    if (cd "$dir" && sudo docker compose ps --format "{{.State}}" | grep -q "running"); then
        echo -e "${GREEN}[UP]${NC}"
    elif (cd "$dir" && sudo docker compose ps --quiet | grep -q .); then
        echo -e "${YELLOW}[STOPPED]${NC}"
    else
        echo -e "${RED}[DOWN]${NC}"
    fi
}

run_cmd() {
    local dir=$1
    local cmd=$2
    echo -e "\n${CYAN}Executing: $cmd${NC}"
    cd "$dir" && eval "$cmd"
    echo -e "\n${GREEN}Complete!${NC}"
    read -n 1 -s -r -p "Press any key to return..."
}

service_menu() {
    local path=$1
    local name=$(basename "$path")

    while true; do
        local status_indicator=$(get_status "$path")
        clear
        echo -e "${BOLD}AI LEVERAGE${NC} > ${YELLOW}$name${NC} $status_indicator"
        echo -e "--------------------------------------------"
        echo -e "1) ${GREEN}Start${NC} (up)"
        echo -e "2) ${RED}Stop${NC} (stop)"
        echo -e "3) ${CYAN}Restart${NC} (restart)"
        echo -e "4) ${YELLOW}Update${NC} (pull & cleanup)"
        echo -e "5) ${BOLD}Rebuild${NC} (down & up --build)"
        echo -e "6) ${BOLD}View logs${NC}"
        echo -e "--------------------------------------------"
        echo -e "b) Go back"
        echo -e "q) Quit"
        echo -e "--------------------------------------------"
        read -p "Selection: " choice

        case $choice in
            1) run_cmd "$path" "sudo docker compose up -d" ;;
            2) run_cmd "$path" "sudo docker compose stop" ;;
            3) run_cmd "$path" "sudo docker compose restart" ;;
            4) 
                echo -e "${CYAN}Starting Update & Cleanup...${NC}"
                # Pulls new images, recreates the container, then wipes the old dangling layers
                run_cmd "$path" "sudo docker compose pull && sudo docker compose up -d && sudo docker image prune -f" 
                ;;
            5) 
                echo -e "\n${RED}${BOLD}REBUILDING:${NC} This deletes and recreates the container."
                read -p "Continue? (y/N): " confirm
                if [[ "$confirm" =~ ^[Yy]$ ]]; then
                    run_cmd "$path" "sudo docker compose down && sudo docker compose up -d --build"
                else
                    echo -e "${CYAN}Rebuild cancelled.${NC}"
                    sleep 1
                fi
                ;;
            6) open_in_cosmic "$LOG_SCRIPT_DIR" "view-logs.sh" "$name" ;;
            [Bb]) return ;;
            [Qq]) clear; exit 0 ;;
        esac
    done
}

main_menu() {
    while true; do
        clear
        echo -e "${BOLD}AI LEVERAGE STACK MANAGER${NC}"
        echo -e "--------------------------------------------"
        
        mapfile -t projects < <(find "$STACK_DIR" -maxdepth 2 \( -name "compose.yaml" -o -name "docker-compose.yml" \) -exec dirname {} + | sort -u)

        if [ ${#projects[@]} -eq 0 ]; then
            echo -e "${RED}No services found in $STACK_DIR${NC}"
            read -n 1 -p "Check structure and press any key to exit..."
            exit 0
        fi

        for i in "${!projects[@]}"; do
            local path="${projects[$i]}"
            local status=$(get_status "$path")
            echo -e "$((i+1))) ${BOLD}$(basename "$path")${NC} $status"
        done

        echo -e "--------------------------------------------"
        echo -e "m) ${CYAN}Monitor GPU${NC}"
        echo -e "q) Quit"
        echo -e "--------------------------------------------"
        read -p "Select service: " choice

        if [[ "$choice" == "q" ]]; then clear; exit 0; fi
        if [[ "$choice" == "m" ]]; then open_in_cosmic "$GPU_SCRIPT_DIR" "monitor-gpu.sh"; fi
        
        if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -le "${#projects[@]}" ] && [ "$choice" -gt 0 ]; then
            service_menu "${projects[$((choice-1))]}"
        fi
    done
}

main_menu