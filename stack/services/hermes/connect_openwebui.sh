#!/bin/bash
# ai-leverage/stack/services/hermes/connect_openwebui.sh
# Lets Open WebUI use Hermes as a model. Hermes creates a random API key on its
# first start; this copies it into Open WebUI's .env (git-ignored), where
# stack/services/openwebui/compose.yaml picks it up.
#
# menu: console   (manage.sh's menu shows what it prints without leaving the menu: it never asks anything)

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
HERMES_ENV="data/.env"
OWUI_DIR="../openwebui"
OWUI_ENV="$OWUI_DIR/.env"

# --- 1. Hermes's key ---
# data/.env is private to the user Hermes runs as (HERMES_UID). With the
# default settings that's you; otherwise it takes sudo to read it.
if [ -r "$HERMES_ENV" ]; then
  key=$(grep -m1 '^API_SERVER_KEY=' "$HERMES_ENV")
elif sudo test -f "$HERMES_ENV"; then
  key=$(sudo grep -m1 '^API_SERVER_KEY=' "$HERMES_ENV")
else
  echo "Hermes has not started yet. Start it first: manage.sh -> hermes -> Start."
  exit 1
fi
key=$(echo "${key#API_SERVER_KEY=}" | tr -d "\"'\r")
if [ -z "$key" ]; then
  echo "No API_SERVER_KEY in stack/services/hermes/$HERMES_ENV yet. Restart Hermes and try again."
  exit 1
fi

# --- 2. Save it in Open WebUI's .env ---
[ -f "$OWUI_ENV" ] || cp "$OWUI_DIR/.env.template" "$OWUI_ENV"
# Rewritten in place, so the file keeps its owner and permissions
rest=$(grep -v '^HERMES_API_KEY=' "$OWUI_ENV")
printf '%s\nHERMES_API_KEY=%s\n' "$rest" "$key" > "$OWUI_ENV"
echo "Saved Hermes's key in stack/services/openwebui/.env."
echo

# --- 3. What happens next ---
# Open WebUI reads its connections from compose.yaml and .env on its very first
# start only. After that it keeps them in its own database.
if [ -e "$OWUI_DIR/data/webui.db" ]; then
  echo "Open WebUI has started before, so it keeps its own list of connections."
  echo "Add Hermes there once:"
  echo "  1. Open WebUI -> Admin Panel -> Settings -> Connections"
  echo "  2. Next to \"OpenAI API\", click + (Add Connection)"
  echo "  3. URL: http://hermes:8642/v1"
  echo "     Key: $key"
  echo "  4. Save. Hermes appears in the model list as \"hermes-agent\"."
else
  echo "Start Open WebUI (manage.sh -> openwebui -> Start)."
  echo "Hermes appears in its model list as \"hermes-agent\"."
fi
