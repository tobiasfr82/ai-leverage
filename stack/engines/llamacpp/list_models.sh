#!/bin/bash
# ai-leverage/stack/engines/llamacpp/list_models.sh
# Lists the GGUF models llama.cpp can run, under the names Open WebUI shows
# for them, and how each fits this PC.
#
# The downloads come from the shared models/huggingface folder. It also lists
# the GGUF lines in the downloader's models.txt that aren't downloaded yet,
# because llama.cpp never goes online to fetch them. How each fits, with the
# context llama.cpp is set to, is estimated by src/python/model_fit.py
# (Models › Tuning › Fit in the menu compares all engines). What's downloaded
# comes from src/python/model_facts.py, which names the files by the same
# rules as the downloader and llama.cpp (gguf_names.py).
#
# menu: console   (manage.sh's menu shows what it prints without leaving the menu: it never asks anything)

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
PYTHON_DIR="../../../src/python"

PORT=$(grep -E '^LLAMACPP_PORT=' .env 2>/dev/null | cut -d= -f2- | tr -d "\"' \r")

# How each model fits, e.g. "set to 64k: 63.3 GB in PC memory, a bit slower ·
# most: ...". Lines starting with # are notes for under the list.
declare -A fit_of
fit_notes=()
while IFS=$'\t' read -r name fit; do
    if [ "$name" == "#" ]; then fit_notes+=("$fit"); elif [ -n "$name" ]; then fit_of[$name]=$fit; fi
done < <(python3 -I "$PYTHON_DIR/model_fit.py" --engine llamacpp 2>/dev/null)

echo "=========================================="
echo "          llama.cpp - MODELS              "
echo "=========================================="

if ! found=$(python3 -I "$PYTHON_DIR/model_facts.py" --gguf); then
    echo "Couldn't read the models (see the error above)."
    exit 1
fi

# --- 1. DOWNLOADED ---
# Named like llama.cpp names them: organization/model:size, with the size in
# GB (1 GB = 1024 MB, like manage.sh's status lines and the fit)
lines=() not_downloaded=()
while IFS=$'\t' read -r model size note; do
    [ -n "$model" ] || continue
    if [ "$model" == "not downloaded" ]; then
        not_downloaded+=("$size")
        continue
    fi
    case "$note" in
        incomplete) note="  (incomplete: run sync_models)" ;;
        "reads images") note="  reads images" ;;
    esac
    lines+=("$(printf '  %-52s %9s%s' "$model" "$size" "$note")")
    [ -n "${fit_of[$model]}" ] && lines+=("    └ ${fit_of[$model]}")
done <<< "$found"

if [ ${#lines[@]} -eq 0 ]; then
    echo "No GGUF models downloaded yet. Add one to"
    echo "stack/downloaders/huggingface/models.txt as organization/model:size, e.g."
    echo "unsloth/gpt-oss-120b-GGUF:Q4_K_M, and run Models › Downloaders › Huggingface → Sync models."
else
    echo "Pick one of these in Open WebUI, or on llama.cpp's own chat page at"
    echo "http://localhost:${PORT:-8080}:"
    echo
    printf '%s\n' "${lines[@]}"
    for note in "${fit_notes[@]}"; do
        echo "$note" | fold -s -w 78
    done
fi

# --- 2. NOT DOWNLOADED YET ---
# Lines in models.txt with a size that no downloaded file names
echo "------------------------------------------"
if [ ${#not_downloaded[@]} -gt 0 ]; then
    for model in "${not_downloaded[@]}"; do
        echo -e "\033[1;33mNot downloaded yet:\033[0m $model"
    done
    echo "llama.cpp only runs what is downloaded: run Models › Downloaders ›"
    echo "Huggingface → Sync models in the menu."
    echo "------------------------------------------"
fi
echo "llama.cpp reads this list when it starts. After a download, Restart it"
echo "(in the menu: llamacpp → Restart) so Open WebUI shows the new models."
