#!/bin/bash
set -e

# Colors for output
BLUE='\033[0;34m'
GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${BLUE}🚀 Initializing Crawl4AI Stack...${NC}"

# Ensure we are in the correct directory
cd "$(dirname "$0")"

# 1. Initialize the virtual environment using uv
# This is nearly instant compared to standard venv
echo -e "${BLUE}📦 Syncing dependencies...${NC}"
uv sync

# 2. Run Crawl4AI post-install steps
# This downloads Chromium and fixes Linux system dependencies
echo -e "${BLUE}🌐 Setting up Playwright browsers...${NC}"
uv run crawl4ai-setup

# 3. Verify the installation
echo -e "${BLUE}🩺 Running diagnostic check...${NC}"
uv run crawl4ai-doctor

echo -e "${GREEN}✅ Crawl4AI is ready!${NC}"