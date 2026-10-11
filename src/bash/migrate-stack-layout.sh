#!/bin/bash
# ai-leverage/src/bash/migrate-stack-layout.sh
# One-time move for installs from before stack/ was split into downloaders/,
# engines/ and services/. Git moves the repo's own files, but not the ones it
# ignores: your .env settings and each service's data/ (logins, chats, memory)
# stay behind in the old folder, e.g. stack/openwebui. This moves them to the
# new one, e.g. stack/services/openwebui. A running service is stopped while
# its files move, then started again from its new folder.
# manage.sh runs this every time it starts; with nothing to move, it does nothing.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STACK_DIR="$REPO_DIR/stack"

BOLD='\033[1m'
YELLOW='\033[1;33m'
NC='\033[0m'

# What git ignores in a folder: moved to the new folder...
MOVE=(.env data output)
# ...or deleted, because the tool that made it sets it up again on its own
REBUILD=(.venv venv __pycache__)

shopt -s nullglob dotglob

has_compose() {
  [ -f "$1/compose.yaml" ] || [ -f "$1/docker-compose.yml" ]
}

# The new home of an old folder: the stack/<group>/<name> with a compose file
# (the service its data belongs to), or the only stack/<group>/<name> there is
new_home() {
  local dir
  local matches=()
  for dir in "$STACK_DIR"/*/"$1"/; do
    matches+=("${dir%/}")
  done
  if [ ${#matches[@]} -eq 1 ]; then
    echo "${matches[0]}"
    return
  fi
  for dir in "${matches[@]}"; do
    has_compose "$dir" && { echo "$dir"; return; }
  done
}

# Folders Docker created belong to root, so reading them can take sudo
is_empty_dir() {
  [ -d "$1" ] || return 1
  if [ -r "$1" ]; then
    [ -z "$(ls -A "$1")" ]
  else
    [ -z "$(sudo ls -A "$1")" ]
  fi
}

# Moves one file or folder, unless the new folder already has its own
move_entry() {
  local from=$1 to=$2
  [ -e "$from" ] || return 0
  # An empty folder holds nothing worth keeping
  if is_empty_dir "$from"; then
    rmdir "$from" 2> /dev/null || sudo rmdir "$from"
    echo "Removed $(basename "$from") (it was empty)"
    return
  fi
  # Neither does an empty one in the new folder, e.g. one Docker created there
  if is_empty_dir "$to"; then
    rmdir "$to" 2> /dev/null || sudo rmdir "$to"
  fi
  if [ -e "$to" ]; then
    echo "Not moved: ${to#"$REPO_DIR"/} already exists. Compare it with ${from#"$REPO_DIR"/} and keep one."
    return 1
  fi
  # Moving a folder that belongs to root takes sudo
  mv -- "$from" "$to" 2> /dev/null || sudo mv -- "$from" "$to" || return 1
  echo "Moved $(basename "$from")"
}

# The entries of an old folder that this moves or deletes
found() {
  local entry
  local list=()
  for entry in "${MOVE[@]}" "${REBUILD[@]}"; do
    [ -e "$1/$entry" ] && list+=("$entry")
  done
  echo "${list[*]}"
}

# Old folders with something to move: stack/<name>, where that folder now
# lives at stack/<group>/<name>
leftovers=()
for dir in "$STACK_DIR"/*/; do
  old=${dir%/}
  [ -n "$(new_home "$(basename "$old")")" ] && [ -n "$(found "$old")" ] && leftovers+=("$old")
done
[ ${#leftovers[@]} -eq 0 ] && exit 0

clear
echo -e "${BOLD}AI LEVERAGE${NC}: stack/ is now split into downloaders/, engines/ and services/."
echo "These old folders still hold your own files, which git doesn't move:"
echo
for old in "${leftovers[@]}"; do
  new=$(new_home "$(basename "$old")")
  echo -e "  ${YELLOW}${old#"$REPO_DIR"/}${NC} -> ${new#"$REPO_DIR"/}:  $(found "$old")"
done
echo
echo "They move to the new folders. A running service stops while its files move,"
echo "then starts again. A .venv is deleted: uv sets it up again the next time."
read -p "Move them now? (Y/n): " answer
if [[ "$answer" =~ ^[Nn] ]]; then
  echo "Nothing moved. manage.sh needs them in the new folders first; run it again when you're ready."
  exit 1
fi

failed=false
for old in "${leftovers[@]}"; do
  new=$(new_home "$(basename "$old")")
  echo -e "\n${BOLD}${old#"$REPO_DIR"/} -> ${new#"$REPO_DIR"/}${NC}"
  ok=true

  # .env first: Compose reads it to find the service (vLLM's model is set there)
  move_entry "$old/.env" "$new/.env" || ok=false

  # A container remembers the folder it was created from, running or not
  running=false
  exists=false
  if has_compose "$new"; then
    (cd "$new" && sudo docker compose ps --status running --quiet 2> /dev/null | grep -q .) && running=true
    (cd "$new" && sudo docker compose ps --all --quiet 2> /dev/null | grep -q .) && exists=true
  fi
  if $exists; then
    # Also stops one that keeps restarting, which doesn't count as running
    $running && echo "Stopping it while its files move..."
    (cd "$new" && sudo docker compose stop)
  fi

  for entry in "${MOVE[@]}"; do
    [ "$entry" == ".env" ] && continue
    move_entry "$old/$entry" "$new/$entry" || ok=false
  done
  for entry in "${REBUILD[@]}"; do
    if [ -e "$old/$entry" ]; then
      rm -rf -- "${old:?}/$entry" 2> /dev/null || sudo rm -rf -- "${old:?}/$entry"
      echo "Deleted $entry"
    fi
  done

  if $exists && ! $ok; then
    echo "Left stopped until the files above are sorted out."
  elif $running; then
    echo "Starting it again from its new folder..."
    (cd "$new" && sudo docker compose up -d)
  elif $exists; then
    # Off before, off after: only point its container at the new folder
    (cd "$new" && sudo docker compose up --no-start)
  fi
  $ok || failed=true

  rmdir "$old" 2> /dev/null || echo "Still in ${old#"$REPO_DIR"/}, left alone: $(ls -A "$old" | tr '\n' ' ')"
done

echo
if $failed; then
  echo "Some files were not moved; see above. manage.sh asks again next time."
else
  echo "Done. Everything is in its new folder."
fi
read -n 1 -s -r -p "Press any key to continue to the menu..."
echo
