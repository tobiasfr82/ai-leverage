#!/bin/bash
# ai-leverage/src/bash/service.sh
# Runs and updates the engines and services in stack/: Start, Stop, Restart,
# Rebuild and their logs, and Update, Revert and Hold the way app.sh does them
# for the apps, with the same steps (update-common.sh). manage.sh's menu runs
# this script for all of them, so each command it shows works the
# same typed in a terminal, e.g. src/bash/service.sh stack/engines/vllm start
#
# Each follows the newest stable release of its Docker image. Update first
# keeps the image it replaces, so Revert can go back to it; Hold keeps it
# where it is.
#
# The version numbers come from the image's own version label. When an image
# has none, or a wrong one, its compose.yaml names a command that prints the
# version, and the GitHub project whose newest release is the newest version:
#   ai-leverage.version-command: "ollama --version"
#   ai-leverage.releases: "ollama/ollama"
# The command runs once per image, in a throwaway container without network.
#
# An image whose moving tag (latest) also carries development builds follows
# the project's GitHub releases instead. Its compose file names a release
# through a variable, and Update moves that to the newest release, in .env:
#   image: quay.io/docling-project/docling-serve:${DOCLING_IMAGE_TAG:-v1.37.0}
#   ai-leverage.follow: "releases"
#   ai-leverage.releases: "docling-project/docling-serve"
#
# Usage: service.sh <stack folder> <action> [options]
#   start    start it, or create its container first; applies changes in its .env
#   stop     stop it; its settings and data stay
#   restart  stop and start it again as it is (changes in its .env need start)
#   rebuild  delete its container and create it again from the images on this
#            PC, after asking; its settings and data stay
#   logs     what it printed since its last start (at most the last 500
#            lines): while it runs, that and then as it comes (ctrl+c stops
#            following); once stopped, its last run. Docker keeps the log
#            until the container is deleted (rebuild, or a start that
#            creates it again). --follow, --since <time> and --tail <lines>
#            work as in docker compose logs instead
#   status   one line for manage.sh, without going online:
#            state|version|held|previous|backup
#            state is downloaded, or missing (Start downloads it); backup is
#            the copy of its data Revert would put back, if Update made one
#   check    look online for a newer version, without downloading it:
#            result|installed|newest|note (see update-common.sh)
#   update   download the newest version, after asking; restarts it if it runs
#   revert   go back to the version before the last update, and hold it there
#   hold     keep it at its version: Update skips it
#   release  end the hold
#   data     what Update backs up first, as "what it holds|size"; nothing
#            when it keeps no data of its own (see load_data)
#   --yes    don't ask first (the menu asks in a dialog of its own, and the
#            update overview's Update all asks once); data is backed up

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_DIR="$BASE_DIR/src/bash"
REGISTRY="$BASE_DIR/src/python/registry.py"

usage() {
    sed -n '/^# Usage:/,/^$/s/^# \{0,1\}//p' "${BASH_SOURCE[0]}"
    exit 1
}

[ $# -ge 2 ] || usage
FOLDER=$1 ACTION=$2
shift 2
FOLLOW=false LOG_ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --yes) ASSUME_YES=true ;;
        --follow) FOLLOW=true ;;
        --since | --tail)
            [ $# -ge 2 ] || usage
            LOG_ARGS+=("$1" "$2")
            shift
            ;;
        *) usage ;;
    esac
    shift
done
# The log's options are only for logs
{ ! $FOLLOW && [ ${#LOG_ARGS[@]} -eq 0 ]; } || [ "$ACTION" == logs ] || usage

SERVICE_DIR="$(cd "$FOLDER" 2> /dev/null && pwd)" || { echo "No folder $FOLDER"; exit 1; }
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
VERSION_CACHE_DIR="$BASE_DIR/cache/image-versions"

compose() { (cd "$SERVICE_DIR" && sudo docker compose "$@"); }

# --- Running it ---
# Start, Stop, Restart, Rebuild and the logs need nothing looked up first, so
# they run before the images are read (at the bottom of this file).

DIM='\033[2m'

# The shared network every container joins. It says something only when it
# creates it, or can't.
ensure_network() {
    local out
    out=$("$SCRIPT_DIR/docker-create-network.sh") || { echo "$out"; return 1; }
    [[ "$out" == *"already exists"* ]] || echo "$out"
}

do_start()   { ensure_network && compose up -d; }
do_stop()    { compose stop; }
do_restart() { ensure_network && compose restart; }

do_rebuild() {
    echo "Rebuild deletes $APP's container and creates it again from the images on this PC."
    echo "Its settings and data stay. To get a newer version, use update instead."
    ask "Rebuild $APP?" || { echo "Nothing changed."; return 0; }
    ensure_network && compose down && compose up -d --build
}

do_logs() {
    local args=(logs --no-log-prefix "${LOG_ARGS[@]}")
    $FOLLOW && args+=(--follow)
    if $FOLLOW || [ ${#LOG_ARGS[@]} -gt 0 ]; then
        compose "${args[@]}"
        return
    fi
    local container started
    container=$(compose ps -a -q 2> /dev/null | head -n 1)
    if [ -z "$container" ]; then
        echo "$APP has no container yet, so no log. Start creates it."
        return 1
    fi
    started=$(sudo docker inspect -f '{{.State.StartedAt}}' "$container" 2> /dev/null)
    if [[ "$started" == 0001-* ]]; then
        echo "$APP's container was created but never started, so it has no log yet."
        return 0
    fi
    [ -n "$started" ] && args+=(--since "$started")
    args+=(--tail 500)
    if is_running; then
        echo -e "${DIM}── $APP's log since it started $(when "$started"). ctrl+c stops following ──${NC}"
        compose "${args[@]}" --follow
    else
        echo -e "${DIM}── $APP's last run, from $(when "$started") until it stopped $(when \
            "$(sudo docker inspect -f '{{.State.FinishedAt}}' "$container" 2> /dev/null)") ──${NC}"
        compose "${args[@]}"
    fi
}

# A time Docker gave, as said: "at 19:42" today, else "on Oct 14 at 19:42"
when() {
    local day
    day=$(date -d "$1" +%F 2> /dev/null) || { echo "at an unknown time"; return; }
    if [ "$day" == "$(date +%F)" ]; then
        date -d "$1" +"at %H:%M"
    else
        date -d "$1" +"on %b %-d at %H:%M"
    fi
}

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
# makes them new. TAG_VARS: for a service that follows releases, the
# variable that names its tag (DOCLING_IMAGE_TAG), else empty.
load_services() {
    SERVICES=() IMAGES=() VERSION_COMMANDS=() RELEASES=() TAG_VARS=()
    local name image command releases tag_var
    while IFS='|' read -r name image command releases tag_var; do
        # A tag of its own, so Revert can name it: ollama/ollama is ollama/ollama:latest
        [[ "${image##*/}" == *[:@]* ]] || image="$image:latest"
        SERVICES+=("$name") IMAGES+=("$image") VERSION_COMMANDS+=("$command") RELEASES+=("$releases")
        TAG_VARS+=("$tag_var")
    done < <(python3 -I -c '
import json, re, sys
services = json.loads(sys.argv[1] or "{}").get("services", {})
# The image lines as written, with their variables
raw = json.loads(sys.argv[2] or "{}").get("services", {})
for name, service in services.items():
    if "build" in service or not service.get("image"):
        continue
    labels = service.get("labels") or {}
    if isinstance(labels, list):
        labels = dict(label.split("=", 1) for label in labels if "=" in label)
    tag_var = ""
    if labels.get("ai-leverage.follow") == "releases":
        match = re.search(r":\$\{(\w+):?-[^}]*\}$", raw.get(name, {}).get("image", ""))
        tag_var = match.group(1) if match else ""
    print("|".join([name, service["image"],
                    labels.get("ai-leverage.version-command", "").replace("|", " "),
                    labels.get("ai-leverage.releases", ""), tag_var]))
' "$(compose_json)" "$(cd "$SERVICE_DIR" && docker compose config --no-interpolate --format json 2> /dev/null)")
    [ ${#SERVICES[@]} -gt 0 ] || { echo "$REL runs no downloaded image."; exit 1; }
}

# Sets NAME=value in the service's .env, which compose reads, adding the line
# when it isn't there yet
set_env() {
    local file="$SERVICE_DIR/.env"
    if [ -f "$file" ] && grep -q "^$1=" "$file"; then
        sed -i "s|^$1=.*|$1=$2|" "$file"
    else
        printf '\n# Set by Update, which follows the newest release (manage.sh -> Update)\n%s=%s\n' "$1" "$2" >> "$file"
    fi
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

# --- The service's own data ---

# Where Update keeps copies of a service's own data, ignored by git like
# models/: backups/services/openwebui for stack/services/openwebui. Each copy
# is one file, readable only by you, since the data may hold keys.
BACKUP_DIR="$BASE_DIR/backups/${REL#stack/}"
BACKUPS_KEPT=3
# Set when it was stopped for a copy, so it starts again afterwards
WAS_RUNNING=false

# DATA_PATHS: the folders in the service's folder that its containers write
# to, such as data/. Not what they only read, nor folders elsewhere (models/,
# your notes). Its compose labels can say more:
#   ai-leverage.data: "your chats and uploads"  what they hold, for the warning
#   ai-leverage.data: "none"                     nothing worth a copy
#   ai-leverage.data-skip: "data/cache"          a folder directly in one of
#       them that copies leave out, and putting a copy back leaves alone
load_data() {
    DATA_PATHS=() DATA_SKIP=() DATA_ABOUT=""
    {
        read -r -a DATA_PATHS
        read -r -a DATA_SKIP
        read -r DATA_ABOUT
    } < <(compose_json | python3 -I -c '
import json, os, sys
base = os.path.realpath(sys.argv[1])
paths, skip, about = set(), set(), []
for service in json.load(sys.stdin).get("services", {}).values():
    labels = service.get("labels") or {}
    if isinstance(labels, list):
        labels = dict(label.split("=", 1) for label in labels if "=" in label)
    if labels.get("ai-leverage.data") == "none":
        continue
    if labels.get("ai-leverage.data"):
        about.append(labels["ai-leverage.data"])
    skip.update(labels.get("ai-leverage.data-skip", "").split())
    for volume in service.get("volumes") or []:
        if volume.get("type") != "bind" or volume.get("read_only"):
            continue
        path = os.path.relpath(os.path.realpath(volume["source"]), base)
        if path != "." and not path.startswith("..") and os.path.exists(os.path.join(base, path)):
            paths.add(path)
# A folder inside another one goes along with it
paths = [p for p in paths if not any(p.startswith(q + "/") for q in paths)]
print(" ".join(sorted(paths)))
print(" ".join(sorted(skip)))
print(" and ".join(about))
' "$SERVICE_DIR")
}

# The data folders as words: "data/", or "data/ and logs/"
data_names() {
    local names=("${DATA_PATHS[@]/%//}")
    if [ ${#names[@]} -gt 1 ]; then
        echo "${names[*]:0:${#names[@]}-1} and ${names[-1]}"
    else
        echo "${names[0]}"
    fi
}

# How much a copy holds, e.g. "213 MB"
data_size() {
    local total skipped=0 p
    total=$(cd "$SERVICE_DIR" && sudo du -sbc "${DATA_PATHS[@]}" 2> /dev/null | tail -n 1 | cut -f1)
    for p in "${DATA_SKIP[@]}"; do
        [ -e "$SERVICE_DIR/$p" ] || continue
        skipped=$((skipped + $(cd "$SERVICE_DIR" && sudo du -sb "$p" 2> /dev/null | cut -f1)))
    done
    numfmt --to=si --suffix=B $((${total:-0} - skipped)) | sed -E 's/([0-9])([a-zA-Z])/\1 \2/'
}

# Stops it, if it runs, so its data holds still while it's copied
stop_for_copy() {
    if is_running; then
        WAS_RUNNING=true
        echo -e "${CYAN}●  Stopping $APP for the copy...${NC}"
        compose stop || return 1
    fi
    return 0
}

start_again() {
    $WAS_RUNNING && compose up -d
    return 0
}

# Copies the data folders into one file in BACKUP_DIR, named after when and
# what (2026-10-14_1402_0.12.0.tar.gz), and sets BACKUP_FILE to it. Only the
# newest BACKUPS_KEPT stay.
make_backup() {
    local name file p excludes=()
    name=$(date +%Y-%m-%d_%H%M)_$(echo "$1" | tr -c 'A-Za-z0-9._\n-' '-')
    file="$BACKUP_DIR/$name.tar.gz"
    for p in "${DATA_SKIP[@]}"; do
        excludes+=("--exclude=$p")
    done
    mkdir -p "$BACKUP_DIR" || return 1
    echo -e "${CYAN}●  Backing up $(data_names) to ${file#"$BASE_DIR"/}...${NC}"
    if ! sudo tar -czf "$file" -C "$SERVICE_DIR" "${excludes[@]}" "${DATA_PATHS[@]}"; then
        sudo rm -f "$file"
        return 1
    fi
    sudo chown "$(id -u):$(id -g)" "$file" && chmod 600 "$file" || return 1
    BACKUP_FILE=$file
    ls -1 "$BACKUP_DIR"/*.tar.gz | sort -r | tail -n +$((BACKUPS_KEPT + 1)) | xargs -r rm -f --
    return 0
}

# Puts a copy back: the data folders hold what they held then. What the labels
# leave out stays as it is.
restore_backup() {
    local p entry s keep
    echo -e "${CYAN}●  Putting back $(data_names) from ${1#"$BASE_DIR"/}...${NC}"
    for p in "${DATA_PATHS[@]}"; do
        [ -n "$p" ] && [ -d "$SERVICE_DIR/$p" ] || continue
        while IFS= read -r -d '' entry; do
            keep=false
            for s in "${DATA_SKIP[@]}"; do
                [ "$entry" == "$SERVICE_DIR/$s" ] && keep=true
            done
            $keep || sudo rm -rf -- "$entry" || return 1
        done < <(sudo find "$SERVICE_DIR/$p" -mindepth 1 -maxdepth 1 -print0)
    done
    sudo tar -xzpf "$1" -C "$SERVICE_DIR"
}

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
    local i digest line label="" created="" newest tag current
    REMOTE_DIGESTS=() TARGETS=() NEW_TAGS=()
    for i in "${!IMAGES[@]}"; do
        TARGETS[$i]=${IMAGES[$i]}
        # One that follows releases: the tag of the newest, if it's newer
        if [ -n "${TAG_VARS[$i]}" ]; then
            newest=$(github_latest "$(releases_repo "$i")")
            [ -n "$newest" ] || { echo "No release found on GitHub for $APP." >&2; return 1; }
            tag=${IMAGES[$i]##*:}
            current=$(clean_version "$tag")
            if [ -n "$current" ] && newer "$newest" "$current"; then
                NEW_TAGS[$i]=${tag/"$current"/"$newest"}
                TARGETS[$i]=${IMAGES[$i]%:*}:${NEW_TAGS[$i]}
            fi
        fi
        digest=$(python3 -I "$REGISTRY" "${TARGETS[$i]}") || return 1
        REMOTE_DIGESTS[$i]=$digest
    done
    LATEST_REF=${REMOTE_DIGESTS[0]}
    if ! docker_is_newer; then
        LATEST_VERSION=$(docker_version)
        return 0
    fi
    LATEST_VERSION=""
    if [ -z "${VERSION_COMMANDS[0]}" ] && line=$(python3 -I "$REGISTRY" "${TARGETS[0]}" --labels); then
        IFS='|' read -r _ label created <<< "$line"
        LATEST_VERSION=$(clean_version "$label")
    fi
    if [ -z "$LATEST_VERSION" ]; then
        line=$(releases_repo 0)
        [ -n "$line" ] && LATEST_VERSION=$(github_latest "$line")
    fi
    if [ -z "$LATEST_VERSION" ]; then
        [ -n "$created" ] || created=$(python3 -I "$REGISTRY" "${TARGETS[0]}" --labels 2> /dev/null | cut -d'|' -f3)
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
    BACKUP_WANTED=false
    load_data
    [ ${#DATA_PATHS[@]} -gt 0 ] || return 0
    echo -e "   ${YELLOW}$APP keeps ${DATA_ABOUT:-its own data} in $(data_names) ($(data_size)).
   The new version may convert it when it first starts. After that, Revert
   brings back the old version, but it may not be able to read it.${NC}"
    ask_yes "Back up $(data_names) first, to ${BACKUP_DIR#"$BASE_DIR"/}/?" && BACKUP_WANTED=true
    return 0
}

docker_revert_warning() {
    is_running && echo -e "${YELLOW}$APP is running, so reverting restarts it: open chats are cut off,
and an engine loads its model again.${NC}"
    RESTORE_FILE=""
    load_data
    [ ${#DATA_PATHS[@]} -gt 0 ] || return 0
    local file
    file=$(cat "$REVERT_DIR/backup" 2> /dev/null)
    if [ -z "$file" ] || [ ! -f "$file" ]; then
        echo -e "${YELLOW}$APP keeps ${DATA_ABOUT:-its own data} in $(data_names), and there's no backup from
before the update. If the newer version converted it, the older one may not
be able to read it.${NC}"
        return 0
    fi
    echo -e "${YELLOW}Before the update, $(data_names) was backed up to ${file#"$BASE_DIR"/}.
The older version may not be able to read what the newer one changed since.${NC}"
    echo "Putting that backup back first backs up $(data_names) as it is now, so nothing is lost."
    ask_yes "Put the backup back as well?" && RESTORE_FILE=$file
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

# Restarts it on its new image if it runs (or ran before a copy), then
# removes the images nothing uses or names anymore
docker_apply() {
    if is_running || $WAS_RUNNING; then
        "$SCRIPT_DIR/docker-create-network.sh" > /dev/null || return 1
        echo -e "${CYAN}●  Restarting $APP on the new image...${NC}"
        compose up -d || return 1
    fi
    sudo docker image prune -f > /dev/null
    load_local
}

# One that follows releases moves to the newest release's tag, in .env. Its
# tags before go to the revert point, to put back on Revert.
move_tags() {
    local i
    for i in "${!SERVICES[@]}"; do
        [ -n "${NEW_TAGS[$i]:-}" ] || continue
        echo "${TAG_VARS[$i]}=${IMAGES[$i]##*:}" >> "$REVERT_DIR/tags"
        echo "   ${TAG_VARS[$i]}=${NEW_TAGS[$i]} in ${SERVICE_DIR#"$BASE_DIR"/}/.env"
        set_env "${TAG_VARS[$i]}" "${NEW_TAGS[$i]}"
    done
    load_services
}

put_tags_back() {
    local line
    [ -f "$REVERT_DIR/tags" ] || return 0
    while IFS= read -r line; do
        set_env "${line%%=*}" "${line#*=}"
    done < "$REVERT_DIR/tags"
    load_services
}

docker_update() {
    local i
    move_tags
    # Docker's own progress bars, one per layer
    compose pull --ignore-buildable || { put_tags_back; return 1; }
    if ${BACKUP_WANTED:-false}; then
        # Named after the version the data belongs to, the one being replaced
        if ! stop_for_copy || ! make_backup "$(docker_version)"; then
            echo -e "${RED}✗ The backup failed, so $APP stays on its version.${NC}"
            put_tags_back
            for i in "${!SERVICES[@]}"; do
                [ -n "${LOCAL_IDS[$i]}" ] && sudo docker tag "${LOCAL_IDS[$i]}" "${IMAGES[$i]}"
            done
            start_again
            sudo docker image prune -f > /dev/null
            return 1
        fi
        echo "$BACKUP_FILE" > "$REVERT_DIR/backup"
    fi
    docker_apply
}

docker_after_update() {
    is_running || echo "   $APP isn't running. Start it to use the new version."
    return 0
}

# Gives the compose file's tags back to the kept images, and the data its
# backup, if that was asked for
docker_install_ref() {
    local pair service id i
    if [ -n "${RESTORE_FILE:-}" ]; then
        if ! stop_for_copy || ! make_backup "$(docker_version)_before-revert"; then
            echo -e "${RED}✗ Couldn't back up $(data_names) as it is now, so nothing was put back.${NC}"
            start_again
            return 1
        fi
        if ! restore_backup "$RESTORE_FILE"; then
            echo -e "${RED}✗ Putting the backup back failed. $(data_names) as it was is in"
            echo -e "${BACKUP_FILE#"$BASE_DIR"/}.${NC}"
            return 1
        fi
    fi
    # The release it followed before, for one that follows releases
    put_tags_back
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
    local st=missing version="" held="" previous="" backup=""
    if m installed; then
        st=downloaded
        version=$(m version)
    fi
    m held && held=held
    if read_previous; then
        previous=$VERSION
        backup=$(cat "$REVERT_DIR/backup" 2> /dev/null)
        [ -f "$backup" ] && backup=${backup#"$BASE_DIR"/} || backup=""
    fi
    echo "$st|$version|$held|$previous|$backup"
}

case "$ACTION" in
    start)   do_start; exit ;;
    stop)    do_stop; exit ;;
    restart) do_restart; exit ;;
    rebuild) do_rebuild; exit ;;
    logs)    do_logs; exit ;;
esac

load_services
load_local

case "$ACTION" in
    status)  do_status ;;
    check)   do_check ;;
    update)  do_update ;;
    revert)  do_revert ;;
    hold)    do_hold ;;
    release) do_release ;;
    data)
        load_data
        [ ${#DATA_PATHS[@]} -eq 0 ] || echo "${DATA_ABOUT:-its own data}|$(data_size)"
        ;;
    *)       usage ;;
esac
