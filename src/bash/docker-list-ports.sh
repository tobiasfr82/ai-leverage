#!/bin/bash
clear

echo -e "\033[1mAI LEVERAGE\033[0m"
echo -e "--------------------------------------------"
echo -e "Action: Viewing Docker Container Port Usage"
echo -e "Target: \033[1;33mAll Containers (Running & Stopped)\033[0m"
echo -e "--------------------------------------------"
echo "Authentication required to access Docker daemon..."

# 1. Verify Docker daemon accessibility
if ! sudo docker info > /dev/null 2>&1; then
    echo -e "\n\033[0;31mError: Cannot connect to Docker daemon.\033[0m"
    echo "Ensure Docker is running and check sudo permissions."
    exec bash
fi

echo -e "\n\033[1;36mFetching all container port mappings...\033[0m"
echo -e "--------------------------------------------"

# 2. Get the container port usage table (includes stopped/created/exited)
PORT_TABLE=$(sudo docker ps -a --format "table {{.Names}}\t{{.Ports}}" 2>/dev/null)

if [ -z "$PORT_TABLE" ]; then
    echo -e "\n\033[0;31mError: Failed to retrieve container information.\033[0m"
    exec bash
fi

echo "$PORT_TABLE"
echo -e "--------------------------------------------\n"

# Explain empty port fields
if echo "$PORT_TABLE" | grep -q "<nil>"; then
    echo -e "\033[1;33mInfo: Containers showing '<nil>' are not exposing network ports.\033[0m"
    echo "This is normal for stopped, created, or internal-only containers."
fi

echo -e "\n--------------------------------------------"
echo "Port usage list complete. Window will remain open for review."
exec bash