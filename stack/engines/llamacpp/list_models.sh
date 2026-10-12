#!/bin/bash
# ai-leverage/stack/engines/llamacpp/list_models.sh
# Lists the models llama.cpp can run: the GGUF downloads in the shared
# models/huggingface folder, under the names Open WebUI shows for them. Also
# lists the GGUF lines in the downloader's models.txt that aren't downloaded
# yet, because llama.cpp never goes online to fetch them.

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
MODELS_DIR="../../../models/huggingface/hub"
MODELS_LIST="../../downloaders/huggingface/models.txt"
# Files next to a model that aren't a model themselves
SIDE_FILES='mmproj|imatrix|mtp-|eagle3-|dflash-|dspark-'

PORT=$(grep -E '^LLAMACPP_PORT=' .env 2>/dev/null | cut -d= -f2- | tr -d "\"' \r")

echo "=========================================="
echo "          llama.cpp - MODELS              "
echo "=========================================="

# --- 1. DOWNLOADED ---
# Named like llama.cpp names them: organization/model:size. The size is the
# last part of the file name, e.g. Q4_K_M in gpt-oss-120b-Q4_K_M.gguf.
declare -A seen first_parts
lines=()
for dir in "$MODELS_DIR"/models--*/; do
    snap="${dir}snapshots/$(cat "${dir}refs/main" 2>/dev/null)"
    [ -d "$snap" ] || continue
    repo=$(basename "$dir")
    repo=${repo#models--}
    repo=${repo//--//}
    reads_images=$(find -L "$snap" -name '*mmproj*.gguf' -print -quit 2>/dev/null)
    while IFS= read -r -d '' file; do
        path=${file#"$snap"/}
        [[ "${path##*/}" =~ $SIDE_FILES ]] && continue
        name=${path%.gguf}
        part=1 parts=1
        if [[ "$name" =~ ^(.+)-([0-9]{5})-of-([0-9]{5})$ ]]; then
            name=${BASH_REMATCH[1]}
            part=$((10#${BASH_REMATCH[2]}))
            parts=$((10#${BASH_REMATCH[3]}))
        fi
        [ "$part" -eq 1 ] || continue
        [[ "$name" =~ [-.]([A-Za-z0-9_]+)$ ]] || continue
        model="$repo:${BASH_REMATCH[1]^^}"
        first_parts[$repo]+="$path"$'\n'
        [ -n "${seen[$model]}" ] && continue
        seen[$model]=1

        # Every part present? An interrupted download leaves some out.
        files=() note=""
        for (( i = 1; i <= parts; i++ )); do
            part_file="$snap/$name.gguf"
            [ "$parts" -gt 1 ] && part_file=$(printf '%s/%s-%05d-of-%05d.gguf' "$snap" "$name" "$i" "$parts")
            if [ -e "$part_file" ]; then files+=("$part_file"); else note="  (incomplete: run sync_models)"; fi
        done
        bytes=$(du -cbL "${files[@]}" 2>/dev/null | tail -1 | cut -f1)
        size=$(awk -v bytes="${bytes:-0}" 'BEGIN { printf "%.1f GB", bytes / 1e9 }')
        [ -n "$reads_images" ] && [ -z "$note" ] && note="  reads images"
        lines+=("$(printf '  %-52s %9s%s' "$model" "$size" "$note")")
    done < <(find -L "$snap" -type f -name '*.gguf' -print0 2>/dev/null | sort -z)
done

if [ ${#lines[@]} -eq 0 ]; then
    echo "No GGUF models downloaded yet. Add one to"
    echo "stack/downloaders/huggingface/models.txt as organization/model:size, e.g."
    echo "unsloth/gpt-oss-120b-GGUF:Q4_K_M, and run huggingface -> sync_models."
else
    echo "Pick one of these in Open WebUI, or on llama.cpp's own chat page at"
    echo "http://localhost:${PORT:-8080}:"
    echo
    printf '%s\n' "${lines[@]}"
fi

# --- 2. NOT DOWNLOADED YET ---
# Lines in models.txt with a size. A line counts as downloaded when one of its
# model's files names that size, which is how llama.cpp finds it too.
not_downloaded=()
if [ -f "$MODELS_LIST" ]; then
    shopt -s nocasematch
    while read -r line || [ -n "$line" ]; do
        line="${line%%#*}"
        line="$(echo "$line" | tr -d ' \r\t')"
        line="${line##*|}"
        [[ "$line" == *:* ]] || continue
        repo=${line%%:*} size=${line#*:} found=false
        if [[ "$size" =~ ^[A-Za-z0-9_-]+$ ]]; then
            while IFS= read -r path; do
                [[ -n "$path" && "$path" =~ ${size}[.-] ]] && found=true && break
            done <<< "${first_parts[$repo]}"
        fi
        $found || not_downloaded+=("$line")
    done < "$MODELS_LIST"
    shopt -u nocasematch
fi

echo "------------------------------------------"
if [ ${#not_downloaded[@]} -gt 0 ]; then
    for model in "${not_downloaded[@]}"; do
        echo -e "\033[1;33mNot downloaded yet:\033[0m $model"
    done
    echo "llama.cpp only runs what is downloaded: run manage.sh -> huggingface ->"
    echo "sync_models."
    echo "------------------------------------------"
fi
echo "llama.cpp reads this list when it starts. After a download, Restart it"
echo "(manage.sh -> llamacpp -> Restart) so Open WebUI shows the new models."
