#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Core Dotfiles — Bootstrap for CachyOS / Arch Linux (GNOME + Wayland)
# ─────────────────────────────────────────────────────────────────────
# One command to go from fresh install to fully-configured terminal.
#
# Usage:
#   ./install.sh                  Full install
#   ./install.sh --help           Show this help
#   ./install.sh --dry-run        Print what would happen, don't execute
#   ./install.sh --skip-packages  Skip pacman/AUR installs (re-run only)
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Argument parsing ─────────────────────────────────────────────────
DRY_RUN=false
SKIP_PACKAGES=false
CONFIGS_ONLY=false
ASSUME_YES=false
_ERRORS=()

usage() {
    cat <<'EOF'
core-dotfiles — Bootstrap for CachyOS / Arch Linux (GNOME + Wayland)

USAGE
    ./install.sh [FLAGS]

FLAGS
    --help, -h         Show this help and exit
    --dry-run          Print what would happen without making changes
    --skip-packages    Skip pacman and AUR package installs (for re-runs)
    --configs-only     Deploy configs, global memory, and expose; no system setup
    --yes              Accept the full bootstrap confirmation

EXAMPLES
    ./install.sh                        Full bootstrap
    ./install.sh --dry-run              Preview everything first
    ./install.sh --skip-packages        Re-deploy configs only

ENV
    TARGET_USER=name   Override target user (default: mathias)
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h) usage ;;
        --dry-run) DRY_RUN=true; shift ;;
        --skip-packages) SKIP_PACKAGES=true; shift ;;
        --configs-only) CONFIGS_ONLY=true; shift ;;
        --yes) ASSUME_YES=true; shift ;;
        *) echo "Unknown flag: $1 (use --help)"; exit 1 ;;
    esac
done

$DRY_RUN && echo -e "\033[1;33m═══ DRY RUN — no changes will be made ═══\033[0m" && echo ""

# Error tracker — wrap commands with: run "description" command...
run() {
    local desc="$1"; shift
    if $DRY_RUN; then
        info "[dry-run] $desc"
        return 0
    fi
    if "$@"; then
        return 0
    else
        _ERRORS+=("$desc")
        warn "Failed: $desc"
        return 1
    fi
}

# ── Configuration ───────────────────────────────────────────────────
# Explicit environment values win over the optional local env file.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
declare -A CONFIG_OVERRIDES=()
for key in TARGET_USER DESIRED_HOSTNAME DOTFILES_DIR SSH_KEY_TYPE; do
    [[ ! -v "$key" ]] || CONFIG_OVERRIDES[$key]="${!key}"
done
if [[ -f "$SCRIPT_DIR/env" ]]; then
    source "$SCRIPT_DIR/env"
fi
for key in "${!CONFIG_OVERRIDES[@]}"; do
    printf -v "$key" '%s' "${CONFIG_OVERRIDES[$key]}"
done
TARGET_USER="${TARGET_USER:-$USER}"
DESIRED_HOSTNAME="${DESIRED_HOSTNAME:-$(hostname)}"
DOTFILES_DIR="${DOTFILES_DIR:-$SCRIPT_DIR}"
SSH_KEY_TYPE="${SSH_KEY_TYPE:-ed25519}"
DOTFILES="$DOTFILES_DIR"

# Exit before any writes, downloads, prompts, sudo, or service commands.
if $DRY_RUN; then
    printf 'Target user: %s; hostname: %s; repository: %s\n' "$TARGET_USER" "$DESIRED_HOSTNAME" "$DOTFILES"
    if ! $CONFIGS_ONLY; then
        printf 'Would configure hostname/hosts, ensure SSH key, install runtimes/plugins,\nconfigure firewall/Docker/GNOME, and set the login shell.\n'
        $SKIP_PACKAGES || printf 'Would install official/AUR packages from the maintained package lists.\n'
    fi
    exec bash "$DOTFILES/scripts/deploy.sh" --dry-run
fi
if $CONFIGS_ONLY; then
    if [[ "$EUID" -eq 0 || "$(id -un)" != "$TARGET_USER" ]]; then
        printf 'Deploy as the target user without sudo.\n' >&2
        exit 1
    fi
    exec bash "$DOTFILES/scripts/deploy.sh"
fi

# ── Colors ──────────────────────────────────────────────────────────
BOLD='\033[1m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()   { echo -e "${GREEN}[✓]${NC} $*"; }
info()  { echo -e "${BLUE}[→]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
err()   { echo -e "${RED}[✗]${NC} $*"; }

# ── Pre-flight ──────────────────────────────────────────────────────
if [[ "$(whoami)" == "root" ]]; then
    err "Do not run as root. This script uses sudo where needed."
    exit 1
fi

# ── Distro detection ─────────────────────────────────────────────────
[[ ! -r /etc/os-release ]] || source /etc/os-release
DISTRO=${ID:-unknown}
ARCH_BASED=("arch" "cachyos" "endeavouros" "manjaro" "artix" "arcolinux" "garuda")

is_arch_based() {
    for d in "${ARCH_BASED[@]}"; do
        [[ "$DISTRO" == "$d" ]] && return 0
    done
    [[ "${ID_LIKE:-}" == *"arch"* ]] && return 0
    return 1
}

if ! is_arch_based; then
    err "This script targets Arch-based distributions (Arch, CachyOS, EndeavourOS, Manjaro, etc.)."
    err "Detected: $DISTRO ${ID_LIKE:+($ID_LIKE)}"
    exit 1
fi

log "Detected Arch-based distro: ${PRETTY_NAME:-$DISTRO}"

# ── User check ───────────────────────────────────────────────────────
if [[ "$(whoami)" != "$TARGET_USER" ]]; then
    err "Running as '$(whoami)', but target user is '$TARGET_USER'."
    err "Run as the target user, or set TARGET_USER=$USER."
    exit 1
fi

# ── Confirmation ─────────────────────────────────────────────────────
echo ""
echo -e "  ${BOLD}Core Dotfiles — Bootstrap${NC}"
echo -e "  Target: ${GREEN}${PRETTY_NAME:-$DISTRO}${NC}  |  User: ${GREEN}$TARGET_USER${NC}  |  Hostname: ${GREEN}${DESIRED_HOSTNAME}${NC}"
echo ""
echo -e "  This will:"
echo -e "    • Install ${BLUE}55+${NC} system packages"
echo -e "    • Install ${BLUE}6${NC} CLI coding agents"
echo -e "    • Configure zsh, tmux, foot, git"
echo -e "    • Set hostname to ${YELLOW}${DESIRED_HOSTNAME}${NC}"
echo -e "    • Change default shell to ${YELLOW}zsh${NC}"
echo -e "    • Generate SSH key if none exists"
echo ""
if $ASSUME_YES; then REPLY=y; else read -rp "  Continue? [y/N] " REPLY; fi
echo ""
if [[ ! "$REPLY" =~ ^[Yy]$ ]]; then
    err "Aborted by user."
    exit 0
fi

# ── Hostname ────────────────────────────────────────────────────────
CURRENT_HOSTNAME=$(hostnamectl --static 2>/dev/null || cat /etc/hostname 2>/dev/null || echo "")
if [[ "$CURRENT_HOSTNAME" == "$DESIRED_HOSTNAME" ]]; then
    log "Hostname already set to '$DESIRED_HOSTNAME'"
else
    info "Setting hostname from '$CURRENT_HOSTNAME' to '$DESIRED_HOSTNAME'..."
    sudo hostnamectl set-hostname "$DESIRED_HOSTNAME"
    log "Hostname set to '$DESIRED_HOSTNAME'"
fi

# Ensure /etc/hosts has the hostname entry (avoids "unable to resolve hostname" warnings)
HOSTS_LINE="127.0.0.1 $DESIRED_HOSTNAME"
if awk -v host="$DESIRED_HOSTNAME" '$1 !~ /^#/ { for (i=2;i<=NF;i++) if ($i==host) found=1 } END {exit !found}' /etc/hosts; then
    log "/etc/hosts already has '$DESIRED_HOSTNAME' entry"
else
    info "Adding '$DESIRED_HOSTNAME' to /etc/hosts..."
    echo "$HOSTS_LINE" | sudo tee -a /etc/hosts >/dev/null
    log "Hosts file updated"
fi

# ── SSH keys ────────────────────────────────────────────────────────
case "$SSH_KEY_TYPE" in ed25519|rsa|ecdsa) ;; *) err "Unsupported SSH_KEY_TYPE"; exit 1 ;; esac
SSH_KEY="$HOME/.ssh/id_$SSH_KEY_TYPE"
if [[ -f "$SSH_KEY" ]]; then
    log "SSH key already exists: $SSH_KEY"
else
    info "Generating new $SSH_KEY_TYPE SSH key..."
    mkdir -p "$HOME/.ssh"
    chmod 700 "$HOME/.ssh"
    ssh-keygen -t "$SSH_KEY_TYPE" -f "$SSH_KEY" -N "" -C "$TARGET_USER@$DESIRED_HOSTNAME"
    log "SSH key generated: $SSH_KEY"
    echo ""
    echo -e "  ${GREEN}Public key:${NC}"
    cat "$SSH_KEY.pub"
    echo ""
fi

# ── 1. System packages (official repos) ─────────────────────────────
section() { echo; echo -e "${BLUE}═══ $* ═══${NC}"; echo; }

# Speed up downloads and builds
if ! grep -q '^ParallelDownloads' /etc/pacman.conf 2>/dev/null; then
    info "Enabling parallel downloads in pacman..."
    sudo sed -i 's/^#ParallelDownloads.*/ParallelDownloads = 5/' /etc/pacman.conf
fi
if ! grep -q '^MAKEFLAGS' /etc/makepkg.conf 2>/dev/null; then
    echo "MAKEFLAGS=\"-j\$(nproc)\"" | sudo tee -a /etc/makepkg.conf >/dev/null
fi

section "1/11 — System packages (pacman)"

if $SKIP_PACKAGES; then
    log "Skipping package installs (--skip-packages)"
else

PACMAN_PKGS=(
    # Shell & terminal
    zsh git curl wget
    foot tmux fzf fd ripgrep jq zoxide

    # CLI tools
    htop fastfetch ncdu wl-clipboard stow
    keychain tree rsync aria2 lsof

    # Dev runtimes
    go dotnet-sdk python python-pip python-pipx python-setuptools nvm python-flask dnsmasq

    # Java — all LTS versions (including latest)
    jdk17-openjdk jdk21-openjdk jdk-openjdk

    # Docker
    docker docker-buildx docker-compose

    # Virtualization
    qemu-desktop virt-manager

    # Build tools
    base-devel cmake gcc

    # GitHub
    github-cli

    # Fonts
    noto-fonts noto-fonts-cjk ttf-dejavu

    # Communication
    discord telegram-desktop

    # Browsers
    chromium firefox

    # Security / networking tools
    nmap smbclient hashcat impacket proxychains-ng
    openbsd-netcat gawk nano vim lm_sensors binwalk
    bettercap aircrack-ng socat maven
    metasploit wireshark-qt tcpdump
    flameshot xclip
    orchis-theme
    wireguard-tools gnome-shell-extensions gnome-shell-extension-appindicator
    ufw gufw
    nautilus-python
)

# --noconfirm keeps the default "No" for package conflicts.
if pacman -Q gnu-netcat &>/dev/null; then
    info "Replacing gnu-netcat with openbsd-netcat..."
    if ! run "Remove conflicting gnu-netcat" sudo pacman -R --noconfirm gnu-netcat; then
        err "Could not remove gnu-netcat; package installation stopped."
        exit 1
    fi
fi

info "Installing ${#PACMAN_PKGS[@]} packages..."
if ! run "Install official packages" sudo pacman -Syu --needed --noconfirm "${PACMAN_PKGS[@]}"; then
    err "Official package installation failed."
    exit 1
fi
log "Official packages installed"
fi  # SKIP_PACKAGES

# ── 2. AUR helper (yay) ─────────────────────────────────────────────
section "2/11 — AUR helper"

if $SKIP_PACKAGES; then
    log "Skipping AUR helper (--skip-packages)"
elif command -v yay &>/dev/null; then
    log "yay already installed"
else
    info "Installing yay..."
    sudo pacman -S --needed --noconfirm git base-devel
    YAY_TMP=$(mktemp -d)
    git clone https://aur.archlinux.org/yay.git "$YAY_TMP"
    (cd "$YAY_TMP" && makepkg -si --noconfirm)
    rm -rf "$YAY_TMP"
    log "yay installed"
fi

# ── 3. AUR packages ─────────────────────────────────────────────────
section "3/11 — AUR packages"

if $SKIP_PACKAGES; then
    log "Skipping AUR packages (--skip-packages)"
else

AUR_PKGS=(
    claude-code
    opencode-bin
    jdk8-openjdk
    jdk11-openjdk
    google-chrome
    netexec
    bettercap-ui
    quickemu
    burpsuite
    visual-studio-code-bin
    gnome-shell-extension-no-overview
    gnome-shell-extension-clipboard-indicator
    gdm-settings
    preload
    nautilus-open-any-terminal
)

info "Installing ${#AUR_PKGS[@]} AUR packages..."
if pacman -Q gnome-shell-extension-clipboard-history &>/dev/null; then
    info "Clipboard Indicator replaces Clipboard History. Review the package replacement before continuing."
    yay -S --needed gnome-shell-extension-clipboard-indicator
    if ! pacman -Q gnome-shell-extension-clipboard-indicator &>/dev/null; then
        err "Clipboard Indicator was not installed. Stopping before the remaining AUR packages."
        exit 1
    fi
fi
yay -S --needed --noconfirm --answerclean All --answerdiff None --combinedupgrade "${AUR_PKGS[@]}"
log "AUR packages installed"
fi  # SKIP_PACKAGES

# Enable preload daemon (adaptive readahead — faster app startup)
if systemctl is-active --quiet preload 2>/dev/null; then
    log "preload daemon already running"
elif command -v preload &>/dev/null; then
    info "Enabling preload daemon..."
    sudo systemctl enable --now preload
    log "preload daemon started"
fi

# Burp Suite Professional — launcher is stowed to ~/.local/bin/.
# Place your burpsuite_pro*.jar in ~/Burpsuite-Professional/ manually.

# ── 4. Oh My Zsh ────────────────────────────────────────────────────
section "4/11 — Oh My Zsh + plugins"

if [[ -d "$HOME/.oh-my-zsh" ]]; then
    log "Oh My Zsh already installed"
else
    info "Installing Oh My Zsh..."
    RUNZSH=no CHSH=no sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
    log "Oh My Zsh installed"
fi

# Custom plugins
ZSH_CUSTOM="${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}"
PLUGIN_DIR="$ZSH_CUSTOM/plugins"

declare -A CUSTOM_PLUGINS=(
    [fzf-tab]="https://github.com/Aloxaf/fzf-tab"
    [zsh-autosuggestions]="https://github.com/zsh-users/zsh-autosuggestions"
    [zsh-syntax-highlighting]="https://github.com/zsh-users/zsh-syntax-highlighting.git"
)

for plugin in "${!CUSTOM_PLUGINS[@]}"; do
    if [[ -d "$PLUGIN_DIR/$plugin" ]]; then
        log "Plugin '$plugin' already installed"
    else
        info "Installing plugin: $plugin"
        git clone --depth=1 "${CUSTOM_PLUGINS[$plugin]}" "$PLUGIN_DIR/$plugin"
    fi
done

# Powerlevel10k theme
P10K_DIR="$ZSH_CUSTOM/themes/powerlevel10k"
if [[ -d "$P10K_DIR" ]]; then
    log "Powerlevel10k already installed"
else
    info "Installing Powerlevel10k..."
    git clone --depth=1 https://github.com/romkatv/powerlevel10k.git "$P10K_DIR"
    log "Powerlevel10k installed"
fi

# ── 5. Tmux Plugin Manager ──────────────────────────────────────────
section "5/11 — Tmux Plugin Manager"

TPM_DIR="$HOME/.tmux/plugins/tpm"
if [[ -d "$TPM_DIR" ]]; then
    log "TPM already installed"
else
    info "Installing TPM..."
    git clone --depth=1 https://github.com/tmux-plugins/tpm "$TPM_DIR"
    log "TPM installed"
fi

# Plugins are installed after the new tmux config is deployed.

# ── 6. Fonts — MesloLGS NF ──────────────────────────────────────────
section "6/11 — Nerd Fonts"

FONT_DIR="$HOME/.local/share/fonts"
if ls "$FONT_DIR"/MesloLGS*.ttf >/dev/null 2>&1; then
    log "MesloLGS NF fonts present"
else
    info "MesloLGS NF fonts not found — they will be stowed in step 10"
fi
fc-cache -fv "$FONT_DIR" >/dev/null 2>&1 || true

# ── 7. Language runtimes ────────────────────────────────────────────
section "7/11 — Language runtimes"

# Node.js via nvm. Support existing user-managed installations too.
export NVM_DIR="$HOME/.nvm"
if [[ -s "$NVM_DIR/nvm.sh" ]]; then
    source "$NVM_DIR/nvm.sh"
elif [[ -s /usr/share/nvm/nvm.sh ]]; then
    source /usr/share/nvm/nvm.sh
else
    err "nvm is missing; install the nvm package or rerun without --skip-packages."
    exit 1
fi
nvm install --lts
nvm alias default 'lts/*'

# Rust via rustup
if command -v rustup &>/dev/null; then
    log "Rust already installed: $(rustc --version)"
else
    info "Installing Rust via rustup..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    source "$HOME/.cargo/env"
    log "Rust installed: $(rustc --version)"
fi

# Java: set up archlinux-java for easy switching
if command -v archlinux-java &>/dev/null; then
    info "Available Java versions:"
    archlinux-java status
    # Default to the latest installed JDK
    LATEST_JDK=$(archlinux-java status 2>/dev/null | grep -oP 'java-\d+-openjdk' | sort -V | tail -1)
    if [[ -n "$LATEST_JDK" ]]; then
        sudo archlinux-java set "$LATEST_JDK" 2>/dev/null || true
        log "Java default set to $LATEST_JDK"
    fi
fi

# ── 8. Power & firewall ─────────────────────────────────────────────
section "8/11 — Power & firewall"

# Set performance power profile (needs D-Bus — best-effort)
if command -v powerprofilesctl &>/dev/null && timeout 5 powerprofilesctl set performance 2>/dev/null; then
    log "Power profile: performance"
fi

# ufw firewall

if systemctl is-active --quiet ufw 2>/dev/null; then
    log "ufw already running"
else
    info "Enabling ufw with safe defaults..."
    sudo ufw default deny incoming
    sudo ufw default allow outgoing
    sudo ufw --force enable
    log "ufw enabled (deny incoming, allow outgoing)"
fi

# ── 9. Docker ────────────────────────────────────────────────────────
section "9/11 — Docker"

if systemctl is-active --quiet docker 2>/dev/null; then
    log "Docker service is running"
else
    info "Enabling and starting Docker..."
    sudo systemctl enable --now docker
    log "Docker started"
fi

# Add user to docker group
if id -nG "$USER" | tr ' ' '\n' | grep -qx docker; then
    log "User already in docker group"
else
    info "Adding $USER to docker group..."
    sudo usermod -aG docker "$USER"
    warn "You'll need to log out and back in for docker group to take effect."
fi

# ── 9. CLI coding agents ────────────────────────────────────────────
section "10/11 — CLI coding agents"

# Ensure nvm's Node is active (not system node, which lacks npm globals prefix)
export NVM_DIR="$HOME/.nvm"
if [ -s "$NVM_DIR/nvm.sh" ]; then
    source "$NVM_DIR/nvm.sh"
    nvm use default 2>/dev/null || { nvm install --lts && nvm alias default 'lts/*'; }
fi

NPM_GLOBALS=(
    codewhale
    "@openai/codex"
    "@github/copilot"
    bun
    "@nestjs/cli"
    "@earendil-works/pi-coding-agent"
)

for pkg in "${NPM_GLOBALS[@]}"; do
    if npm list -g "$pkg" --depth=0 2>/dev/null | grep -q "$pkg@"; then
        log "npm: $pkg already installed"
    else
        info "npm: installing $pkg..."
        npm install -g "$pkg"
    fi
done

# Copilot uses the standalone @github/copilot package above.

# Python security tools via pipx (isolated environments)
PIPX_TOOLS=(
    "donpapi|git+https://github.com/login-securite/DonPAPI.git"
    "mitm6|mitm6"
)

for entry in "${PIPX_TOOLS[@]}"; do
    name="${entry%%|*}"
    pkg="${entry##*|}"
    if command -v "$name" &>/dev/null; then
        log "pipx: $name already installed"
    else
        info "pipx: installing $name..."
        pipx install "$pkg" || { warn "$name install failed"; _ERRORS+=("pipx: $name"); }
    fi
done

log "Coding agents ready"

# ── Deploy public configs, private memory, and matching expose tools ──
section "11/11 — Dotfiles and expose"
bash "$DOTFILES/scripts/deploy.sh"
if [[ -x "$TPM_DIR/bin/install_plugins" ]]; then
    "$TPM_DIR/bin/install_plugins"
fi
# Fonts are available only after deployment.
fc-cache -f "$HOME/.local/share/fonts"

# ── GNOME settings (run separately if D-Bus is unresponsive) ─────────
if command -v gsettings &>/dev/null && [[ "${XDG_CURRENT_DESKTOP:-}" =~ GNOME ]]; then
    info "Configuring GNOME settings (desktop, wallpaper, theme, power)..."

    # Delegate to dedicated script
    if [[ -f "$DOTFILES/scripts/gnome-settings.sh" ]]; then
        bash "$DOTFILES/scripts/gnome-settings.sh" 2>&1 | while IFS= read -r line; do info "  $line"; done
    fi

fi

# ── Set default shell ────────────────────────────────────────────────
ZSH_PATH=$(command -v zsh || echo "/usr/bin/zsh")
LOGIN_SHELL=$(getent passwd "$USER" | cut -d: -f7)
if [[ "$LOGIN_SHELL" == "$ZSH_PATH" ]]; then
    log "Default shell is already zsh"
else
    info "Setting default shell to zsh..."
    sudo chsh -s "$ZSH_PATH" "$USER"
    log "Default shell set to zsh (takes effect on next login)"
fi

# ── Final ────────────────────────────────────────────────────────────
section "Done"

# Error summary
if [[ ${#_ERRORS[@]} -gt 0 ]]; then
    echo ""
    echo -e "${YELLOW}${#_ERRORS[@]} step(s) had issues:${NC}"
    for e in "${_ERRORS[@]}"; do
        echo -e "  ${RED}✗${NC} $e"
    done
    echo ""
else
    echo -e "  ${GREEN}All steps completed successfully.${NC}"
fi

echo ""
echo "  Shell:     zsh $(zsh --version 2>/dev/null | awk '{print $2}')"
echo "  Terminal:  foot $(foot --version 2>/dev/null)"
echo "  Node:      $(node --version 2>/dev/null || echo 'not loaded — restart shell')"
echo "  Go:        $(go version 2>/dev/null | awk '{print $3}' || echo 'not found')"
echo "  Rust:      $(rustc --version 2>/dev/null | awk '{print $2}' || echo 'not loaded')"
echo "  Java:      $(java --version 2>/dev/null | head -1 || echo 'not found')"
echo "  Docker:    $(docker --version 2>/dev/null | awk '{print $3}' | tr -d ',')"
echo ""
echo -e "${GREEN}All done. Start a new terminal or run:${NC}"
echo "  exec zsh"
echo ""
echo -e "${YELLOW}Notes:${NC}"
echo "  - Log out and back in for docker group membership."
echo "  - Run 'p10k configure' to customize your prompt."
echo "  - Set API keys for Copilot / OpenRouter in your environment."

(( ${#_ERRORS[@]} == 0 ))
