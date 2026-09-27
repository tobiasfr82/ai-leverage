#!/bin/bash
# ai-leverage/src/bash/docker-create-network.sh
# Creates the shared Docker network that every service in stack/ joins.
# Containers on it reach each other by name (e.g. http://ollama:11434) without
# opening any ports to the rest of your network. Safe to run repeatedly.
# Used by manage.sh and bootstrap.sh.

# Must match the network name at the bottom of every stack/*/compose.yaml
NETWORK_NAME="ai-leverage"

if ! command -v docker &> /dev/null; then
    echo -e "\033[0;31mError: Docker is not installed.\033[0m"
    exit 1
fi

if sudo docker network inspect "$NETWORK_NAME" > /dev/null 2>&1; then
    echo "Shared Docker network '$NETWORK_NAME' already exists."
    exit 0
fi

echo "Creating shared Docker network '$NETWORK_NAME'..."
if sudo docker network create "$NETWORK_NAME" > /dev/null; then
    echo -e "\033[0;32mCreated shared Docker network '$NETWORK_NAME'.\033[0m"
else
    echo -e "\033[0;31mError: Could not create Docker network '$NETWORK_NAME'.\033[0m"
    echo "Ensure Docker is running and check sudo permissions."
    exit 1
fi
