#!/bin/bash
# ai-leverage/src/bash/service.sh
# Updates the engines and services in stack/ the way app.sh updates the apps,
# with the same steps (update-common.sh). Each follows the newest stable
# release of its Docker image. Update first keeps the image it replaces, so
# Revert can go back to it; Hold keeps it where it is.
#
# The version numbers come from the image's own version label. When an image
# has none, or a wrong one, its compose.yaml names a command that prints the
# version, and the GitHub project whose newest release is the newest version:
#   ai-leverage.version-command: "ollama --version"
#   ai-leverage.releases: "ollama/ollama"
# The command runs once per image, in a throwaway container without network.
#
# Usage: service.sh <stack folder> <action> [--yes]
#   status   one line for manage.sh, without going online:
#            state|version|held|previous
#            state is downloaded, or missing (Start downloads it)
#   check    look online for a newer version, without downloading it:
#            result|installed|newest|note (see update-common.sh)
#   update   download the newest version, after asking; restarts it if it runs
#   revert   go back to the version before the last update, and hold it there
#   hold     keep it at its version: Update skips it
#   release  end the hold
#   --yes    don't ask first (the update overview's Update all asks once)

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_DIR="$BASE_DIR/src/bash"
REGISTRY="$BASE_DIR/src/python/registry.py"

usage() {
    sed -n '/^# Usage:/,/^$/s/^# \{0,1\}//p' "${BASH_SOURCE[0]}"
    exit 1
}

[ $# -eq 2 ] || { [ $# -eq 3 ] && [ "$3" == --yes ]; } || usage
ACTION=$2
[ "${3:-}" == --yes ] && ASSUME_YES=true

SERVICE_DIR="$(cd "$1" 2> /dev/null && pwd)" || { echo "No folder $1"; exit 1; }
[ -f "$SERVICE_DIR/compose.yaml" ] || [ -f "$SERVICE_DIR/docker-compose.yml" ] ||
    { echo "No compose file in $SERVICE_DIR"; exit 1; }

APP=$(basename "$SERVICE_DIR")
METHOD=docker
# Compose's name for the folder's project, as in manage.sh
PROJECT=$(echo "$APP" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')

# Kept per service, git-ignored: the image Update replaced, and the hold
REVERT_DIR="$SERVICE_DIR/update/revert"
HOLD_FILE="$SERVICE_DIR/update/held"
NOT_INSTALLED="$APP isn't downloaded yet. Start downloads it."
REL=${SERVICE_DIR#"$BASE_DIR"/}
CACHE_KEY=${REL//\//-}

# shellcheck source=update-common.sh
. "$SCRIPT_DIR/update-common.sh"

# Versions read with a version command, by image: an image never changes
VERSION_CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/ai-leverage/image-versions"

compose() { (cd "$SERVICE_DIR" && sudo docker compose "$@"); }

# --- What the compose file names ---

# The compose file as Docker reads it, .env included. A setting that only
# matters for starting, such as a model not chosen yet, gets a stand-in.
compose_json() {
    local out vars
    if out=$(cd "$SERVICE_DIR" && docker compose config --format json 2> /dev/null); then
        echo "$out"
        return
    fi
    vars=$(cat "$SERVICE_DIR"/compose.yaml "$SERVICE_DIR"/docker-compose.yml 2> /dev/null |
        grep -oE '\$\{[A-Za-z_][A-Za-z0-9_]*:?\?' | sed -E 's/^\$\{//; s/:?\?$//' | sort -u)
    # shellcheck disable=SC2046 # one NAME=- per variable
    (cd "$SERVICE_DIR" && env $(printf '%s=- ' $vars) docker compose config --format json 2> /dev/null)
}

# SERVICES, IMAGES, VERSION_COMMANDS, RELEASES: one entry per service in the
# compose file that runs a downloaded image. The first is the one whose
# version the menu shows. Services built on this PC are left out: Rebuild
# makes them new.
load_services() {
    SERVICES=() IMAGES=() VERSION_COMMANDS=() RELEASES=()
    local name image command releases
    while IFS='|' read -r name image command releases; do
        # A tag of its own, so Revert can name it: ollama/ollama is ollama/ollama:latest
        [[ "${image##*/}" == *[:@]* ]] || image="$image:latest"
        SERVICES+=("$name") IMAGES+=("$image") VERSION_COMMANDS+=("$command") RELEASES+=("$releases")
    done < <(compose_json | python3 -I -c '
import json, sys
for name, service in json.load(sys.stdin).get("services", {}).items():
    if "build" in service or not service.get("image"):
        continue
    labels = service.get("labels") or {}
    if isinstance(labels, list):
        labels = dict(label.split("=", 1) for label in labels if "=" in label)
    print("|".join([name, service["image"],
                    labels.get("ai-leverage.version-command", "").replace("|", " "),
                    labels.get("ai-leverage.releases", "")]))
')
    [ ${#SERVICES[@]} -gt 0 ] || { echo "$REL runs no downloaded image."; exit 1; }
}

# --- What's on this PC ---

# LOCAL_IDS: the image each service runs on. The one the compose file names,
# once it's downloaded; otherwise the one its container was made from, such
# as an older tag the compose file named before.
load_local() {
    LOCAL_IDS=()
    local i id cid
    for i in "${!SERVICES[@]}"; do
        id=$(sudo docker image inspect -f '{{.Id}}' "${IMAGES[$i]}" 2> /dev/null)
        if [ -z "$id" ]; then
            cid=$(compose ps -a -q "${SERVICES[$i]}" 2> /dev/null | head -n 1)
            [ -n "$cid" ] && id=$(sudo docker inspect -f '{{.Image}}' "$cid" 2> /dev/null)
        fi
        LOCAL_IDS[$i]=$id
    done
}

is_running() {
    [ -n "$(compose ps -q --status running --status restarting 2> /dev/null)" ]
}

# Where Update keeps the image it replaces, until the next Update
revert_tag() { echo "ai-leverage-revert/$PROJECT:${SERVICES[$1]}"; }

# A version label as a plain number: "vllm/vllm-openai:v0.31.0" is 0.31.0 and
# "v0.5.21-runtime" is 0.5.21. llama.cpp's build numbers (b11580) stay as
# they are. Anything else, such as "main", says nothing.
clean_version() {
    local v=${1##*:}
    if [[ "$v" =~ ^v?([0-9]+(\.[0-9]+)+) ]]; then
        echo "${BASH_REMATCH[1]}"
    elif [[ "$v" =~ ^b[0-9]+$ ]]; then
        echo "$v"
    fi
}

# The version of a downloaded image (service number, image ID)
image_version() {
    local i=$1 id=$2 v="" cache
    if [ -n "${VERSION_COMMANDS[$i]}" ]; then
        cache="$VERSION_CACHE_DIR/${id#sha256:}"
        if [ ! -s "$cache" ]; then
            v=$(timeout 60 sudo docker run --rm --network none --entrypoint sh "$id" \
                -c "${VERSION_COMMANDS[$i]}" 2>&1 | grep -oE '[0-9]+(\.[0-9]+)+' | head -n 1)
            [ -n "$v" ] && mkdir -p "$VERSION_CACHE_DIR" && echo "$v" > "$cache"
        fi
        v=$(cat "$cache" 2> /dev/null)
    else
        v=$(clean_version "$(sudo docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.version"}}' "$id" 2> /dev/null)")
    fi
    [ -n "$v" ] || v="build $(sudo docker image inspect -f '{{.Created}}' "$id" 2> /dev/null | cut -c1-10)"
    echo "$v"
}

# The GitHub project whose releases name a service's versions: from
# compose.yaml, or the project the image says it was built from
releases_repo() {
    local source
    if [ -n "${RELEASES[$1]}" ]; then
        echo "${RELEASES[$1]}"
        return
    fi
    [ -n "${LOCAL_IDS[$1]}" ] || return
    source=$(sudo docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.source"}}' "${LOCAL_IDS[$1]}" 2> /dev/null)
    if [[ "$source" =~ ^https://github\.com/([^/]+/[^/]+) ]]; then
        echo "${BASH_REMATCH[1]%.git}"
    fi
}

# --- The Docker source, for update-common.sh ---

docker_source() {
    local first=${IMAGES[0]%%/*}
    if [[ "${IMAGES[0]}" == */* ]] && [[ "$first" == *.* || "$first" == *:* ]]; then
        echo "Docker image from $first"
    else
        echo "Docker image from Docker Hub"
    fi
}

docker_installed() { [ -n "${LOCAL_IDS[0]}" ]; }
docker_version()   { image_version 0 "${LOCAL_IDS[0]}"; }

# The images to go back to, as service=image ID
docker_ref() {
    local i pairs=()
    for i in "${!SERVICES[@]}"; do
        [ -n "${LOCAL_IDS[$i]}" ] && pairs+=("${SERVICES[$i]}=${LOCAL_IDS[$i]}")
    done
    echo "${pairs[*]}"
}

# Sets REMOTE_DIGESTS from the registries; LATEST_VERSION only when there's
# something newer, since finding it out takes more requests. Goes online.
docker_latest() {
    local i digest line label="" created=""
    REMOTE_DIGESTS=()
    for i in "${!IMAGES[@]}"; do
        digest=$(python3 -I "$REGISTRY" "${IMAGES[$i]}") || return 1
        REMOTE_DIGESTS[$i]=$digest
    done
    LATEST_REF=${REMOTE_DIGESTS[0]}
    if ! docker_is_newer; then
        LATEST_VERSION=$(docker_version)
        return 0
    fi
    LATEST_VERSION=""
    if [ -z "${VERSION_COMMANDS[0]}" ] && line=$(python3 -I "$REGISTRY" "${IMAGES[0]}" --labels); then
        IFS='|' read -r _ label created <<< "$line"
        LATEST_VERSION=$(clean_version "$label")
    fi
    if [ -z "$LATEST_VERSION" ]; then
        line=$(releases_repo 0)
        [ -n "$line" ] && LATEST_VERSION=$(github_latest "$line")
    fi
    if [ -z "$LATEST_VERSION" ]; then
        [ -n "$created" ] || created=$(python3 -I "$REGISTRY" "${IMAGES[0]}" --labels 2> /dev/null | cut -d'|' -f3)
        LATEST_VERSION="build ${created:-of today}"
    fi
    return 0
}

# Newer when a registry's digest isn't one this PC's image was downloaded as
docker_is_newer() {
    local i
    for i in "${!IMAGES[@]}"; do
        [ -n "${LOCAL_IDS[$i]}" ] || return 0
        sudo docker image inspect -f '{{range .RepoDigests}}{{println .}}{{end}}' "${LOCAL_IDS[$i]}" 2> /dev/null |
            grep -qF "@${REMOTE_DIGESTS[$i]}" || return 0
    done
    return 1
}

docker_update_warning() {
    is_running && echo -e "   ${YELLOW}$APP is running, so updating restarts it: open chats are cut off,
   and an engine loads its model again.${NC}"
    return 0
}

docker_revert_warning() {
    is_running && echo -e "${YELLOW}$APP is running, so reverting restarts it: open chats are cut off,
and an engine loads its model again.${NC}"
    return 0
}

# The image the last Update kept goes, so one earlier version is all that's
# kept. Its other names go too, such as the pinned tag of a version the
# compose file named before, so the cleanup can remove it.
docker_drop_previous() {
    local i old tag
    for i in "${!SERVICES[@]}"; do
        old=$(sudo docker image inspect -f '{{.Id}}' "$(revert_tag "$i")" 2> /dev/null) || continue
        # Refused while a stopped container still uses it; the next tag takes the name anyway
        sudo docker rmi "$(revert_tag "$i")" > /dev/null 2>&1
        [ "$old" == "${LOCAL_IDS[$i]}" ] && continue
        for tag in $(sudo docker image inspect -f '{{join .RepoTags " "}}' "$old" 2> /dev/null); do
            [ "$tag" != "${IMAGES[$i]}" ] && sudo docker rmi "$tag" > /dev/null 2>&1
        done
    done
    return 0
}

docker_save() {
    local i
    for i in "${!SERVICES[@]}"; do
        [ -n "${LOCAL_IDS[$i]}" ] || continue
        sudo docker tag "${LOCAL_IDS[$i]}" "$(revert_tag "$i")" || return 1
    done
}

# Restarts it on its new image if it runs, then removes the images nothing
# uses or names anymore
docker_apply() {
    if is_running; then
        "$SCRIPT_DIR/docker-create-network.sh" > /dev/null || return 1
        echo -e "${CYAN}●  Restarting $APP on the new image...${NC}"
        compose up -d || return 1
    fi
    sudo docker image prune -f > /dev/null
    load_local
}

docker_update() {
    # Docker's own progress bars, one per layer
    compose pull --ignore-buildable || return 1
    docker_apply
}

docker_after_update() {
    is_running || echo "   $APP isn't running. Start it to use the new version."
    return 0
}

# Gives the compose file's tags back to the kept images
docker_install_ref() {
    local pair service id i
    for pair in $1; do
        service=${pair%%=*} id=${pair#*=}
        for i in "${!SERVICES[@]}"; do
            [ "${SERVICES[$i]}" == "$service" ] || continue
            sudo docker tag "$id" "${IMAGES[$i]}" || return 1
            sudo docker rmi "$(revert_tag "$i")" > /dev/null 2>&1
        done
    done
    docker_apply
}

docker_hold()    { mkdir -p "$(dirname "$HOLD_FILE")" && touch "$HOLD_FILE"; }
docker_release() { rm -f "$HOLD_FILE"; }
docker_held()    { [ -f "$HOLD_FILE" ]; }

do_status() {
    local st=missing version="" held="" previous=""
    if m installed; then
        st=downloaded
        version=$(m version)
    fi
    m held && held=held
    read_previous && previous=$VERSION
    echo "$st|$version|$held|$previous"
}

load_services
load_local

case "$ACTION" in
    status)  do_status ;;
    check)   do_check ;;
    update)  do_update ;;
    revert)  do_revert ;;
    hold)    do_hold ;;
    release) do_release ;;
    *)       usage ;;
esac
