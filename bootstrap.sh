#!/bin/bash
# ai-leverage/bootstrap.sh
# One-time setup for this machine. Installs what the repo needs and leaves
# anything already in place alone, so it is safe to run again.
#   1. uv - runs the Python tools, and fetches the Python version each one needs
#   2. Docker with the Compose plugin - runs the services in stack/
#   3. NVIDIA Container Toolkit - lets Docker hand the GPU to a service
#   4. The shared "ai-leverage" Docker network
# Afterwards, start the services with ./manage.sh.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Distribution details (ID, ID_LIKE, VERSION_CODENAME...), used to pick package sources
[ -f /etc/os-release ] && . /etc/os-release

ask() {
    read -p "$1 (y/N): " -n 1 -r
    echo
    [[ $REPLY =~ ^[Yy]$ ]]
}

# --- 1. Check/Install UV ---
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

# --- 2. Check/Install Docker ---
install_docker() {
    if command -v apt-get &> /dev/null; then
        # Docker's own repository. Ubuntu-based systems (Pop!_OS, Mint...) use the
        # packages for the Ubuntu release they are built on.
        local distro codename
        case " ${ID:-} ${ID_LIKE:-} " in
            *" ubuntu "*) distro=ubuntu; codename="${UBUNTU_CODENAME:-$VERSION_CODENAME}" ;;
            *" debian "*) distro=debian; codename="$VERSION_CODENAME" ;;
            *) return 1 ;;
        esac
        echo "Detected $distro ($codename), installing Docker from Docker's repository..."
        sudo apt-get update
        sudo apt-get install -y ca-certificates curl gnupg
        sudo install -m 0755 -d /etc/apt/keyrings
        curl -fsSL "https://download.docker.com/linux/$distro/gpg" | sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/$distro $codename stable" \
            | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        sudo apt-get update
        sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    elif command -v pacman &> /dev/null; then
        echo "Detected Arch Linux, installing Docker..."
        sudo pacman -S --noconfirm docker docker-compose
    elif command -v dnf &> /dev/null || command -v yum &> /dev/null; then
        # Docker's install script covers Fedora, RHEL and CentOS
        echo "Detected Fedora/RHEL/CentOS, installing Docker with Docker's install script..."
        curl -fsSL https://get.docker.com | sudo sh
    else
        return 1
    fi
    sudo systemctl enable --now docker
}

if command -v docker &> /dev/null; then
    echo "Docker is already installed."
elif ask "Docker not found. Do you want to install Docker?"; then
    if ! install_docker; then
        echo "Could not install Docker on this system. Install it by hand:"
        echo "  https://docs.docker.com/engine/install/"
        exit 1
    fi
else
    echo "Docker installation skipped."
fi

# Every service is started with 'docker compose', which is a separate package
if command -v docker &> /dev/null && ! docker compose version &> /dev/null; then
    echo "Docker is installed, but the Compose plugin is missing. Install the package"
    echo "'docker-compose-plugin' (Docker's repository) or 'docker-compose-v2' (Ubuntu's"
    echo "own docker.io), then run this script again."
fi

# --- 3. Check/Install the NVIDIA Container Toolkit ---
# Ollama, vLLM and Docling run on an NVIDIA GPU. The toolkit is what lets Docker
# hand the GPU to them; without it they refuse to start.
install_nvidia_toolkit() {
    if command -v apt-get &> /dev/null; then
        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
            | sudo gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
        curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
            | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
            | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null
        sudo apt-get update
        sudo apt-get install -y nvidia-container-toolkit
    elif command -v pacman &> /dev/null; then
        sudo pacman -S --noconfirm nvidia-container-toolkit
    elif command -v dnf &> /dev/null; then
        curl -fsSL https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo \
            | sudo tee /etc/yum.repos.d/nvidia-container-toolkit.repo > /dev/null
        sudo dnf install -y nvidia-container-toolkit
    else
        return 1
    fi
    sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
}

if ! command -v nvidia-smi &> /dev/null; then
    echo "No NVIDIA driver found (nvidia-smi is missing). Ollama, vLLM and Docling need"
    echo "an NVIDIA GPU. Install the driver, reboot, and run this script again."
elif command -v nvidia-ctk &> /dev/null; then
    echo "NVIDIA Container Toolkit is already installed."
elif ! command -v docker &> /dev/null; then
    echo "Docker not found. Skipping the NVIDIA Container Toolkit."
elif ask "NVIDIA Container Toolkit not found. Docker needs it to use the GPU. Install it?"; then
    if ! install_nvidia_toolkit; then
        echo "Could not install the NVIDIA Container Toolkit. Install it by hand:"
        echo "  https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html"
        exit 1
    fi
else
    echo "NVIDIA Container Toolkit installation skipped."
fi

# --- 4. Create the shared Docker network ---
# Every service in stack/ joins this network so they can reach each other by name.
# Not fatal: manage.sh creates it too, the first time you start a service.
if command -v docker &> /dev/null; then
    "$REPO_DIR/src/bash/docker-create-network.sh" \
        || echo "Could not create the shared Docker network now; manage.sh will try again later."
else
    echo "Docker not found. Skipping the shared Docker network."
fi

echo "Environment bootstrap complete! Start the services with ./manage.sh"
