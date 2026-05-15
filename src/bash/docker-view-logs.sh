#!/bin/bash
clear

# Input from manage.sh or environment
TARGET="${1:-$TARGET_ENV}"

echo -e "\033[1mAI LEVERAGE\033[0m"
echo -e "--------------------------------------------"
echo -e "Action: Viewing Docker Logs"
echo -e "Target: \033[1;33m$TARGET\033[0m"
echo -e "--------------------------------------------"
echo "Authentication required to access Docker daemon..."

# 1. Get the container status (running, exited, created, etc.)
# We use -a to ensure we find it even if it is stopped
STATUS=$(sudo docker inspect -f '{{.State.Status}}' "$TARGET" 2>/dev/null)

if [ -z "$STATUS" ]; then
    echo -e "\n\033[0;31mError: Container '$TARGET' does not exist.\033[0m"
    echo "Check your compose.yaml container_name mapping."
    exec bash
fi

echo -e "Status: \033[1;36m$STATUS\033[0m"
echo -e "--------------------------------------------\n"

if [ "$STATUS" == "running" ]; then
    echo "--- Streaming logs (Ctrl+C to stop) ---"
    sudo docker logs -f --tail=100 "$TARGET"
else
    echo "--- Showing static logs (Container is $STATUS) ---"
    sudo docker logs --tail=200 "$TARGET"
    echo -e "\n--------------------------------------------"
    echo "End of log history. Window will remain open for review."
    exec bash
fi