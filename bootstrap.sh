#!/bin/bash
set -e

# --- 1. Check/Install Python 3.10 ---
if ! command -v python3.10 &> /dev/null; then
    echo "Python 3.10 not found. It's needed for some functionality in AI-Leverage to function."
    read -p "Do you want to install Python 3.10? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        # Check if we're on Pop! OS (based on Ubuntu) or Ubuntu/Debian directly
        if lsb_release -i 2>/dev/null | grep -qi "Pop" || command -v apt &> /dev/null; then
            echo "Detected Debian/Ubuntu/Pop! OS, installing Python 3.10 via Deadsnakes PPA..."
            sudo apt update
            sudo apt install -y software-properties-common
            sudo add-apt-repository -y ppa:deadsnakes/ppa
            sudo apt update
            sudo apt install -y python3.10 python3.10-dev python3.10-venv
        # Check if we're on CentOS/RHEL/Fedora
        elif command -v yum &> /dev/null; then
            echo "Detected RHEL/CentOS/Fedora, installing Python 3.10..."
            sudo yum install -y yum-utils
            sudo yum install -y python3.10 python3.10-devel python3.10-libs
        # Check if we're on Arch Linux
        elif command -v pacman &> /dev/null; then
            echo "Detected Arch Linux. Python 3.10 must be built from the Arch User Repository (AUR)."
            if command -v yay &> /dev/null; then
                yay -S --noconfirm python310
            elif command -v paru &> /dev/null; then
                paru -S --noconfirm python310
            else
                echo "AUR helper (yay/paru) not found. Please install the 'python310' package manually from the AUR."
                exit 1
            fi
        else
            echo "Unsupported distribution. Please install Python 3.10 manually."
            exit 1
        fi
    else
        echo "Python 3.10 installation skipped. Please install manually."
        exit 1
    fi
else
    echo "Python 3.10 is already installed."
fi

# --- 2. Check/Install UV ---
if ! command -v uv &> /dev/null; then
    echo "UV not found. Installing now..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    if [ -f "$HOME/.local/bin/env" ]; then
        source "$HOME/.local/bin/env"
    elif [ -d "$HOME/.local/bin" ]; then
        export PATH="$HOME/.local/bin:$PATH"
    fi
else
    echo "UV is already installed."
fi

# --- 3. Check/Install Docker ---
if ! command -v docker &> /dev/null; then
    echo "Docker not found."
    read -p "Do you want to install Docker? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        # Check if we're on Pop! OS or Ubuntu/Debian
        if lsb_release -i 2>/dev/null | grep -qi "Pop" || command -v apt &> /dev/null; then
            echo "Detected Debian/Ubuntu/Pop! OS, installing official Docker CE..."
            sudo apt update
            sudo apt install -y apt-transport-https ca-certificates curl gnupg lsb-release
            
            # Use modern keyring location instead of deprecated apt-key/trusted.gpg.d
            sudo mkdir -p /etc/apt/keyrings
            curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
            
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
            
            sudo apt update
            sudo apt install -y docker-ce docker-ce-cli containerd.io
            sudo usermod -aG docker "$USER"
            echo "User added to the docker group. You may need to log out and log back in for changes to apply."
        # Check if we're on CentOS/RHEL/Fedora
        elif command -v yum &> /dev/null; then
            echo "Detected RHEL/CentOS/Fedora, installing Docker CE..."
            sudo yum install -y yum-utils
            sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
            sudo yum install -y docker-ce docker-ce-cli containerd.io
            sudo systemctl start docker
            sudo systemctl enable docker
            sudo usermod -aG docker "$USER"
        # Check if we're on Arch Linux
        elif command -v pacman &> /dev/null; then
            echo "Detected Arch Linux, installing Docker..."
            sudo pacman -S --noconfirm docker
            sudo usermod -aG docker "$USER"
            sudo systemctl enable docker --now
        else
            echo "Unsupported distribution. Please install Docker manually."
            exit 1
        fi
    else
        echo "Docker installation skipped."
    fi
else
    echo "Docker is already installed."
fi

# --- 4. Initialize Crawl4AI Stack ---
#echo "Initializing Crawl4AI Stack..."
#if [ -d "stack/crawl4ai" ]; then
#    cd stack/crawl4ai
#    chmod +x setup.sh
#    ./setup.sh
#    cd ../..
#fi

echo "Environment bootstrap complete!"