#!/bin/bash
# ai-leverage/src/bash/docker-view-logs.sh
# Shows the logs of one service. Used by manage.sh.
# Usage: docker-view-logs.sh <service folder, e.g. stack/ollama>
clear

SERVICE_DIR="$1"
TARGET="$(basename "$SERVICE_DIR")"

echo -e "\033[1mAI LEVERAGE\033[0m"
echo -e "--------------------------------------------"
echo -e "Action: Viewing Docker Logs"
echo -e "Target: \033[1;33m$TARGET\033[0m"
echo -e "--------------------------------------------"
echo "Authentication required to access Docker daemon..."

cd "$SERVICE_DIR" || exit 1

# 1. Get the container status. Compose finds the container from the folder,
# whatever it is named. --all includes stopped containers.
if sudo docker compose ps --status running --quiet | grep -q .; then
    STATUS="running"
elif sudo docker compose ps --all --quiet | grep -q .; then
    STATUS="stopped"
else
    echo -e "\n\033[0;31mError: '$TARGET' has no container yet. Start it first.\033[0m"
    exit 1
fi

echo -e "Status: \033[1;36m$STATUS\033[0m"
echo -e "--------------------------------------------\n"

if [ "$STATUS" == "running" ]; then
    echo "--- Streaming logs (Ctrl+C to stop) ---"
    sudo docker compose logs -f --tail=100 --no-log-prefix
else
    echo "--- Showing static logs (Container is $STATUS) ---"
    sudo docker compose logs --tail=200 --no-log-prefix
    echo -e "\n--------------------------------------------"
    echo "End of log history."
fi
