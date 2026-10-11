#!/bin/bash
# ai-leverage/stack/hermes/chat.sh
# Opens a chat with Hermes in this terminal. Anything after the script name goes
# to the hermes command inside the container, for example:
#   ./chat.sh model           pick another model
#   ./chat.sh profile list    show the profiles

if ! sudo docker ps --format '{{.Names}}' | grep -qx hermes; then
  echo "Hermes is not running. Start it first: manage.sh -> hermes -> Start."
  exit 1
fi

# Runs as Hermes's own user inside the container, so its files stay readable
exec sudo docker exec -it hermes hermes "$@"
