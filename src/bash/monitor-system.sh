#!/bin/bash
# ai-leverage/src/bash/monitor-system.sh
# What the PC has to spare for the stack: disk space where the models are, RAM,
# and the GPU's load, memory, power and temperature.
#   monitor-system.sh            live, updated every 2 seconds, including which
#                                engine uses how much of the GPU's memory
#   monitor-system.sh --summary  three lines, once: the top of manage.sh's menu
# Sizes count the way df -h and free -h do, so 1 GB is 1024 MB.

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODELS_DIR="$BASE_DIR/models"
INTERVAL=2

RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# --- Formatting ---

# Bytes in, "4.8 TB", "66 GB", "7.5 GB", "512 MB" or "40 KB" out
human() {
    awk -v b="${1:-0}" 'BEGIN {
        if (b >= 1024^4)         printf "%.1f TB", b / 1024^4
        else if (b >= 10*1024^3) printf "%.0f GB", b / 1024^3
        else if (b >= 1024^3)    printf "%.1f GB", b / 1024^3
        else if (b >= 1024^2)    printf "%.0f MB", b / 1024^2
        else                     printf "%.0f KB", b / 1024
    }'
}

# MB in (as nvidia-smi gives them), "27.3" GB out
gb() {
    awk -v m="${1:-0}" 'BEGIN { printf "%.1f", m / 1024 }'
}

# A whole number from what nvidia-smi gives, or nothing when it says [N/A]
num() {
    awk -v v="$1" 'BEGIN { if (v ~ /^[ ]*[0-9.]+[ ]*$/) printf "%.0f", v }'
}

# Colors a text yellow or red. Usage: warn <level: 0 ok, 1 yellow, 2 red> <text>
warn() {
    case "$1" in
        2) printf "${RED}%s${NC}" "$2" ;;
        1) printf "${YELLOW}%s${NC}" "$2" ;;
        *) printf "%s" "$2" ;;
    esac
}

# --- What the PC has ---

# The folder the models are in, or the repo before the first download. A link
# to another disk is followed, so the numbers are for that disk.
models_path() {
    if [ -e "$MODELS_DIR" ]; then readlink -f "$MODELS_DIR"; else echo "$BASE_DIR"; fi
}

# Free space on the disk the models are on. Yellow under 200 GB, red under 50 GB.
disk_text() {
    local path size avail level=0
    path=$(models_path)
    read -r size avail < <(df -B1 --output=size,avail "$path" 2>/dev/null | tail -1)
    [ -n "$avail" ] || { echo "unknown"; return; }
    [ "$avail" -lt $((200 * 1024**3)) ] && level=1
    [ "$avail" -lt $((50 * 1024**3)) ] && level=2
    warn "$level" "$(human "$avail") free / $(human "$size")"
}

# The size of everything in models/, or of each folder in it with --each
models_size() {
    local path
    [ -e "$MODELS_DIR" ] || return
    path=$(readlink -f "$MODELS_DIR")
    if [ "$1" == "--each" ]; then
        du -sb "$path"/*/ 2>/dev/null | while read -r bytes dir; do
            printf '%s %s · ' "$(basename "$dir")" "$(human "$bytes")"
        done | sed 's/ · $//'
    else
        human "$(du -sb "$path" 2>/dev/null | cut -f1)"
    fi
}

# RAM free for new programs (what free calls available), and swap in use. Free
# RAM turns yellow under 8 GB and red under 3 GB; swap in use over 1 GB is a
# sign RAM ran out.
ram_text() {
    local total avail swap_total swap_free swap_used level=0 text
    read -r total avail swap_total swap_free < <(awk '
        /^MemTotal:/ {t=$2} /^MemAvailable:/ {a=$2} /^SwapTotal:/ {st=$2} /^SwapFree:/ {sf=$2}
        END {printf "%.0f %.0f %.0f %.0f\n", t*1024, a*1024, st*1024, sf*1024}' /proc/meminfo)
    swap_used=$((swap_total - swap_free))
    [ "$avail" -lt $((8 * 1024**3)) ] && level=1
    [ "$avail" -lt $((3 * 1024**3)) ] && level=2
    text=$(warn "$level" "$(human "$avail") free / $(human "$total")")
    if [ "$1" == "--used" ]; then
        text="$(human $((total - avail))) used · $text"
    fi
    if [ "$swap_used" -gt $((1024**3)) ]; then
        text+=" · $(warn 1 "$(human "$swap_used") swapped")"
    elif [ "$1" == "--used" ]; then
        text+=" · no swap in use"
    fi
    echo "$text"
}

# The GPU's numbers, one line per GPU, as
# "index|name|load %|memory used MB|memory total MB|watts|watt limit|°C|fan %".
# Empty when there is no NVIDIA GPU, or when its driver doesn't answer.
gpu_query() {
    command -v nvidia-smi &> /dev/null || return
    timeout 3 nvidia-smi --format=csv,noheader,nounits \
        --query-gpu=index,name,utilization.gpu,memory.used,memory.total,power.draw,power.limit,temperature.gpu,fan.speed \
        2>/dev/null | sed 's/, /|/g'
}

# Load, memory, power and temperature. Temperature turns yellow from 80°C and
# red from 90°C, where the card starts slowing itself down.
gpu_text() {
    local index name load used total watts limit temp fan level=0 text
    IFS='|' read -r index name load used total watts limit temp fan <<< "$1"
    temp=$(num "$temp")
    [ -n "$temp" ] && [ "$temp" -ge 80 ] && level=1
    [ -n "$temp" ] && [ "$temp" -ge 90 ] && level=2
    text="$(num "$load")% busy · VRAM $(gb "$used") GB used / $(gb "$total") GB"
    watts=$(num "$watts")
    if [ -n "$watts" ]; then
        text+=" · $watts W"
        [ "$2" == "--detail" ] && [ -n "$(num "$limit")" ] && text+=" / $(num "$limit") W"
    fi
    [ -n "$temp" ] && text+=" · $(warn "$level" "${temp}°C")"
    if [ "$2" == "--detail" ] && [ -n "$(num "$fan")" ]; then
        if [ "$(num "$fan")" -eq 0 ]; then text+=" · fan off"; else text+=" · fan $(num "$fan")%"; fi
    fi
    echo "$text"
}

# --- The menu's summary ---

summary() {
    local line gpus models
    models=$(models_size)
    echo -e "Disk   $(disk_text)${models:+ · models use $models}"
    echo -e "RAM    $(ram_text)"
    if ! command -v nvidia-smi &> /dev/null; then
        echo "GPU    no NVIDIA GPU found (nvidia-smi is missing)"
        return
    fi
    gpus=$(gpu_query)
    if [ -z "$gpus" ]; then
        echo -e "GPU    $(warn 2 "the NVIDIA driver doesn't answer")"
        return
    fi
    while IFS= read -r line; do
        if [ "$(wc -l <<< "$gpus")" -gt 1 ]; then
            echo -e "GPU ${line%%|*}  $(gpu_text "$line")"
        else
            echo -e "GPU    $(gpu_text "$line")"
        fi
    done <<< "$gpus"
}

if [ "$1" == "--summary" ]; then
    summary
    exit 0
fi

# --- The live monitor ---

# Which program uses how much GPU memory, summed per Docker container (named
# like the stack's folders: llamacpp, ollama, docling...) and for everything
# else on this PC. Docker only names its containers with sudo; without it the
# program's own name is used.
declare -A CONTAINER_NAMES
load_container_names() {
    CONTAINER_NAMES=()
    $DOCKER_OK || return
    local id name
    while read -r id name; do
        [ -n "$id" ] && CONTAINER_NAMES[$id]=$name
    done < <(sudo -n docker ps --no-trunc --format '{{.ID}} {{.Names}}' 2>/dev/null)
}

gpu_users() {
    local pid pname mem cgroup who
    declare -A sums
    while IFS=',' read -r pid pname mem; do
        pid=${pid// /} mem=${mem// /}
        [ -n "$pid" ] || continue
        cgroup=$(cat "/proc/$pid/cgroup" 2>/dev/null)
        if [[ "$cgroup" =~ docker[-/]([0-9a-f]{64}) ]]; then
            who=${CONTAINER_NAMES[${BASH_REMATCH[1]}]:-$(basename "${pname# }")}
        else
            who="this desktop and other programs"
        fi
        sums[$who]=$(( ${sums[$who]:-0} + ${mem:-0} ))
    done < <(timeout 3 nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader,nounits 2>/dev/null)
    for who in "${!sums[@]}"; do
        echo "${sums[$who]} $who"
    done | sort -rn | while read -r mem who; do
        printf '         %-32s %5s GB\n' "$who" "$(gb "$mem")"
    done
}

# CPU load and network traffic since the last look. Measured in the main loop
# rather than inside frame, which runs in a subshell and would forget the last
# look each time. The network is the connection to the internet, so it shows
# how fast a model download runs.
NET_IFACE=$(ip route show default 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "dev") {print $(i + 1); exit}}')
CPU_PREV="" NET_PREV="" NET_TIME="" CPU_TEXT="measuring..." NET_TEXT="measuring..."
sample() {
    local cpu net now rate
    cpu=$(awk '/^cpu / {idle = $5 + $6; total = 0; for (i = 2; i <= 9; i++) total += $i; printf "%.0f %.0f", idle, total}' /proc/stat)
    if [ -n "$CPU_PREV" ]; then
        CPU_TEXT="$(awk -v a="$CPU_PREV" -v b="$cpu" 'BEGIN {
            split(a, p, " "); split(b, n, " "); dt = n[2] - p[2]
            printf "%.0f", (dt > 0 ? 100 * (1 - (n[1] - p[1]) / dt) : 0) }')% busy · $(nproc) threads"
    fi
    CPU_PREV=$cpu

    [ -n "$NET_IFACE" ] || { NET_TEXT=""; return; }
    # /proc/net/dev can glue a big number to the name ("eth0:123456789"), so
    # split at the colon first. Received bytes come first, sent ones ninth.
    net=$(awk -v ifc="$NET_IFACE" '{ line = $0; sub(/^ +/, "", line); n = index(line, ":")
        if (substr(line, 1, n - 1) == ifc) { split(substr(line, n + 1), f, " "); printf "%.0f %.0f", f[1], f[9] } }' /proc/net/dev)
    now=$(date +%s.%N)
    if [ -n "$NET_PREV" ] && [ -n "$net" ]; then
        rate=$(awk -v a="$NET_PREV" -v b="$net" -v t0="$NET_TIME" -v t1="$now" 'BEGIN {
            split(a, p, " "); split(b, n, " "); dt = t1 - t0; if (dt <= 0) dt = 1
            printf "%.0f %.0f", (n[1] - p[1]) / dt, (n[2] - p[2]) / dt }')
        NET_TEXT="$(human "${rate% *}")/s in · $(human "${rate#* }")/s out"
    fi
    NET_PREV=$net
    NET_TIME=$now
}

frame() {
    local line name gpus models_each
    echo -e "${BOLD}SYSTEM MONITOR${NC}   $(date +%H:%M:%S)"
    echo -e "Updates every $INTERVAL seconds. ${CYAN}n${NC}: NVIDIA's own table · any other key closes"
    echo "--------------------------------------------"
    gpus=$(gpu_query)
    if [ -z "$gpus" ]; then
        if command -v nvidia-smi &> /dev/null; then
            echo -e "GPU    $(warn 2 "the NVIDIA driver doesn't answer")"
        else
            echo "GPU    no NVIDIA GPU found (nvidia-smi is missing)"
        fi
    else
        load_container_names
        while IFS= read -r line; do
            IFS='|' read -r _ name _ <<< "$line"
            echo -e "GPU    $name"
            echo -e "       $(gpu_text "$line" --detail)"
        done <<< "$gpus"
        echo "       Memory in use by:"
        gpu_users
        $DOCKER_OK || echo "       (engine names need Docker access: start the monitor again)"
    fi
    echo -e "RAM    $(ram_text --used)"
    echo -e "CPU    $CPU_TEXT"
    echo -e "Disk   $(disk_text), where models/ is"
    models_each=$(models_size --each)
    [ -n "$models_each" ] && echo "       $models_each"
    [ -n "$NET_TEXT" ] && echo "Net    $NET_TEXT"
}

# Docker names the containers only with sudo. Asked once, up front, so the
# password prompt doesn't appear in the middle of the numbers. Ctrl+C at the
# prompt goes on without engine names instead of closing the monitor.
DOCKER_OK=false
if command -v docker &> /dev/null; then
    if ! sudo -n true 2>/dev/null; then
        echo "To show which engine uses the GPU, the monitor asks Docker, which needs sudo."
        echo "Press Ctrl+C at the password prompt to go without engine names."
    fi
    trap 'true' INT
    sudo -v 2>/dev/null && DOCKER_OK=true
    trap - INT
fi

# Draws over the previous frame instead of clearing the screen, so it doesn't
# flicker. Hides the cursor while it runs.
tput civis 2>/dev/null
trap 'tput cnorm 2>/dev/null; echo' EXIT
clear
sample
sleep 0.5
sample
view=summary
while true; do
    if [ "$view" == "nvidia" ]; then
        out=$(echo -e "${BOLD}NVIDIA's own table${NC}   $(date +%H:%M:%S) · ${CYAN}n${NC}: back · any other key closes"
              timeout 3 nvidia-smi 2>&1)
    else
        out=$(frame)
    fi
    printf '\033[H'
    while IFS= read -r line; do
        printf '%s\033[K\n' "$line"
    done <<< "$out"
    printf '\033[J'
    if read -rsn1 -t "$INTERVAL" key; then
        if [ "$key" == "n" ]; then
            if [ "$view" == "nvidia" ]; then view=summary; else view=nvidia; fi
            clear
        else
            break
        fi
    fi
    sample
done
