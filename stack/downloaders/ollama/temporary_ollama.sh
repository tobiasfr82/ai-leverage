# ai-leverage/stack/downloaders/ollama/temporary_ollama.sh
# Used by sync_models.sh and build_specs.sh; not a menu entry of its own.
# Starts a temporary Ollama that downloads into the shared models/ollama folder,
# the one the Ollama engine (stack/engines/ollama) runs its models from. It gets
# no GPU and no open port, so downloading never takes memory from a running
# engine, and it is removed when the script that started it ends. The engine
# sees each finished model straight away, whether it is running or not.

DOWNLOADER="ollama-downloader"
# The engine's image too, so both are the same Ollama version
DOWNLOADER_IMAGE="ollama/ollama:latest"

# Runs an ollama command, e.g. "ollama_cmd pull gemma4:31b", in the temporary Ollama
ollama_cmd() {
    sudo docker exec "$DOWNLOADER" ollama "$@"
}

stop_downloader() {
    sudo docker stop "$DOWNLOADER" > /dev/null 2>&1
}

# Starts the temporary Ollama and waits until it answers. If one is running
# already (sync_models.sh runs build_specs.sh), that one is used.
# Usage: start_downloader <repo folder> <specs folder>
start_downloader() {
    local repo_dir=$1 specs_dir=$2
    if sudo docker ps --format '{{.Names}}' | grep -qx "$DOWNLOADER"; then
        return 0
    fi
    # A stopped one left over from an interrupted run
    sudo docker rm --force "$DOWNLOADER" > /dev/null 2>&1 || true
    mkdir -p "$repo_dir/models/ollama"

    echo "Starting a temporary Ollama to download with..."
    # OLLAMA_NOPRUNE: on start, Ollama deletes unfinished downloads in its
    # folder. This one starts on every sync, so without it an interrupted
    # download would start over instead of carrying on where it stopped.
    # OLLAMA_NO_CLOUD: like the engine, no contact with ollama.com beyond the
    # downloads themselves.
    sudo docker run --detach --rm --name "$DOWNLOADER" \
        --env OLLAMA_NOPRUNE=1 \
        --env OLLAMA_NO_CLOUD=1 \
        --volume "$repo_dir/models/ollama:/root/.ollama/models" \
        --volume "$specs_dir:/specs:ro" \
        "$DOWNLOADER_IMAGE" > /dev/null || return 1
    trap stop_downloader EXIT

    for _ in $(seq 30); do
        ollama_cmd list > /dev/null 2>&1 && return 0
        sleep 2
    done
    echo "Error: the temporary Ollama did not start. Its last messages:"
    sudo docker logs --tail 20 "$DOWNLOADER"
    return 1
}
