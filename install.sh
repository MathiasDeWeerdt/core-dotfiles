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
set -uo pipefail

# ── Argument parsing ─────────────────────────────────────────────────
DRY_RUN=false
SKIP_PACKAGES=false
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
# Load env file: env.example provides defaults, env overrides them
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$SCRIPT_DIR/env" ]]; then
    source "$SCRIPT_DIR/env"
elif [[ -f "$SCRIPT_DIR/env.example" ]]; then
    source "$SCRIPT_DIR/env.example"
fi

# CLI environment overrides take precedence (e.g. TARGET_USER=foo ./install.sh)
TARGET_USER="${TARGET_USER:-mathias}"
DESIRED_HOSTNAME="${DESIRED_HOSTNAME:-bytebadger}"
DOTFILES_DIR="${DOTFILES_DIR:-$HOME/Documents/core-dotfiles}"
SSH_KEY_TYPE="${SSH_KEY_TYPE:-ed25519}"
DOTFILES="$DOTFILES_DIR"

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
detect_distro() {
    if [[ -f /etc/os-release ]]; then
        source /etc/os-release 2>/dev/null
        echo "${ID:-unknown}"
    else
        echo "unknown"
    fi
}

DISTRO=$(detect_distro)
ARCH_BASED=("arch" "cachyos" "endeavouros" "manjaro" "artix" "arcolinux" "garuda")

is_arch_based() {
    for d in "${ARCH_BASED[@]}"; do
        [[ "$DISTRO" == "$d" ]] && return 0
    done
    [[ "$ID_LIKE" == *"arch"* ]] && return 0
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
    warn "Running as '$(whoami)', but target user is '$TARGET_USER'."
    warn "Override with: TARGET_USER=yourname ./install.sh"
fi

# ── Confirmation ─────────────────────────────────────────────────────
echo ""
echo -e "  ${BOLD}Core Dotfiles — Bootstrap${NC}"
echo -e "  Target: ${GREEN}${PRETTY_NAME:-$DISTRO}${NC}  |  User: ${GREEN}$TARGET_USER${NC}  |  Hostname: ${GREEN}${DESIRED_HOSTNAME}${NC}"
echo ""
echo -e "  This will:"
echo -e "    • Install ${BLUE}55+${NC} system packages"
echo -e "    • Install ${BLUE}5${NC} CLI coding agents"
echo -e "    • Configure zsh, tmux, foot, git"
echo -e "    • Set hostname to ${YELLOW}${DESIRED_HOSTNAME}${NC}"
echo -e "    • Change default shell to ${YELLOW}zsh${NC}"
echo -e "    • Generate SSH key if none exists"
echo ""
read -rp "  Continue? [y/N] " REPLY
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
if grep -qF "$HOSTS_LINE" /etc/hosts 2>/dev/null; then
    log "/etc/hosts already has '$DESIRED_HOSTNAME' entry"
else
    info "Adding '$DESIRED_HOSTNAME' to /etc/hosts..."
    echo "$HOSTS_LINE" | sudo tee -a /etc/hosts >/dev/null
    log "Hosts file updated"
fi

# ── SSH keys ────────────────────────────────────────────────────────
SSH_KEY="$HOME/.ssh/id_ed25519"
if [[ -f "$SSH_KEY" ]]; then
    log "SSH key already exists: $SSH_KEY"
else
    info "Generating new ed25519 SSH key..."
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
    go dotnet-sdk python python-pip python-pipx python-setuptools

    # Java — all LTS versions (including latest)
    jdk17-openjdk jdk21-openjdk jdk-openjdk

    # Docker
    docker docker-buildx docker-compose

    # Virtualization
    qemu-desktop

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
    wireguard-tools gnome-shell-extensions gnome-shell-extension-appindicator
    ufw gufw
)

info "Installing ${#PACMAN_PKGS[@]} packages..."
sudo pacman -Syu --needed --noconfirm "${PACMAN_PKGS[@]}"
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
    gnome-shell-extension-clipboard-history
)

info "Installing ${#AUR_PKGS[@]} AUR packages..."
yay -S --needed --noconfirm --answerclean All --answerdiff None --combinedupgrade "${AUR_PKGS[@]}"
log "AUR packages installed"
fi  # SKIP_PACKAGES

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

# Install tmux plugins silently (only on first run)
PLUGINS_INSTALLED="$HOME/.tmux/plugins/tmux-sensible"
if [[ -d "$PLUGINS_INSTALLED" ]]; then
    log "Tmux plugins already installed"
else
    info "Installing tmux plugins..."
    "$TPM_DIR/bin/install_plugins" 2>/dev/null || true
    log "Tmux plugins installed"
fi

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

# Node.js via nvm
export NVM_DIR="$HOME/.nvm"
if [[ -s "$NVM_DIR/nvm.sh" ]]; then
    log "nvm already installed"
else
    info "Installing nvm..."
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.5/install.sh | bash
    log "nvm installed"
fi

# Load nvm for this session
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"

# Install Node LTS
if command -v node &>/dev/null; then
    log "Node.js $(node --version) already present"
else
    info "Installing Node.js LTS via nvm..."
    nvm install --lts
    nvm alias default 'lts/*'
    log "Node.js LTS installed: $(node --version)"
fi

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

# Set performance power profile
if command -v powerprofilesctl &>/dev/null; then
    info "Setting power profile to performance..."
    powerprofilesctl set performance 2>/dev/null && \
        log "Power profile: performance" || \
        warn "Could not set power profile"
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
if groups "$USER" | grep -q docker; then
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
    bun
    "@nestjs/cli"
)

for pkg in "${NPM_GLOBALS[@]}"; do
    pkg_name=$(echo "$pkg" | sed 's/@//g' | tr '/' '-')
    if npm list -g --depth=0 2>/dev/null | grep -q "$pkg_name"; then
        log "npm: $pkg already installed"
    else
        info "npm: installing $pkg..."
        npm install -g "$pkg"
    fi
done

# GitHub Copilot CLI (gh extension)
if command -v gh &>/dev/null; then
    if gh extension list 2>/dev/null | grep -q 'gh-copilot'; then
        log "GitHub Copilot CLI already installed"
    else
        info "Installing GitHub Copilot CLI extension..."
        gh extension install github/gh-copilot 2>/dev/null || \
            warn "Copilot CLI install failed — run: gh auth login && gh extension install github/gh-copilot"
    fi
else
    warn "gh CLI not found — skipping Copilot CLI (install github-cli and run 'gh auth login')"
fi

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
        pipx install "$pkg" 2>/dev/null || warn "$name install failed — install manually if needed"
    fi
done

log "Coding agents ready"

# ── 10. Deploy dotfiles (stow) ──────────────────────────────────────
section "11/11 — Dotfiles (stow)"

cd "$DOTFILES"

STOW_PACKAGES=(zsh p10k foot tmux git fonts local-bin flameshot)

info "Stowing dotfiles..."
stow -d "$DOTFILES" -t "$HOME" -R --adopt "${STOW_PACKAGES[@]}" 2>/dev/null || \
    stow -d "$DOTFILES" -t "$HOME" --adopt "${STOW_PACKAGES[@]}"

log "Dotfiles deployed"

# ── GNOME keybindings ────────────────────────────────────────────────
if command -v gsettings &>/dev/null && [[ "${XDG_CURRENT_DESKTOP:-}" =~ GNOME ]]; then
    info "Configuring GNOME shortcuts..."

    setup_keybinding() {
        local name="$1" binding="$2" command="$3"
        # Check if this binding already exists
        for i in $(seq 0 9); do
            local existing=$(gsettings get org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom${i}/ name 2>/dev/null | tr -d "'")
            if [[ "$existing" == "$name" ]]; then
                log "Keybinding '$name' already configured"
                return 0
            fi
        done

        # Find the first empty slot
        local slot=0
        while gsettings get org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom${slot}/ name 2>/dev/null | grep -q .; do
            ((slot++))
        done

        local path="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom${slot}/"
        gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$path" name "$name"
        gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$path" command "$command"
        gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$path" binding "$binding"

        # Add to the list of enabled custom keybindings
        local current_list=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings)
        if [[ "$current_list" == "@as []" ]]; then
            current_list="['$path']"
        elif ! echo "$current_list" | grep -q "$path"; then
            current_list=$(echo "$current_list" | sed "s/]$/, '$path']/")
        fi
        gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$current_list"
        log "Keybinding '$name' → $binding: $command"
    }

    setup_keybinding "Terminal"     "<Control><Alt>t"      "foot -m"
    setup_keybinding "Screenshot"   "<Shift><Control>a"    "$HOME/.local/bin/flameshot-gui"

    # Mouse: disable acceleration
    gsettings set org.gnome.desktop.peripherals.mouse accel-profile flat 2>/dev/null || true

    # Wallpapers: copy and set up slideshow rotation
    if ls "$DOTFILES/wallpapers/"*.{png,jpg} &>/dev/null; then
        BG_DIR="$HOME/.local/share/backgrounds"
        mkdir -p "$BG_DIR"
        cp "$DOTFILES/wallpapers/"*.{png,jpg} "$BG_DIR/" 2>/dev/null || true

        # Create slideshow XML
        xml="$BG_DIR/slideshow.xml"
        echo '<background><starttime><year>2026</year><month>01</month><day>01</day><hour>00</hour><minute>00</minute><second>00</second></starttime>' > "$xml"
        prev=""
        for img in "$BG_DIR/"*.{png,jpg}; do
            [[ -f "$img" ]] || continue
            echo "  <static><duration>1795.0</duration><file>$img</file></static>" >> "$xml"
            [[ -n "$prev" ]] && echo "  <transition><duration>5.0</duration><from>$prev</from><to>$img</to></transition>" >> "$xml"
            prev="$img"
        done
        echo '</background>' >> "$xml"

        gsettings set org.gnome.desktop.background picture-uri "file://$xml" 2>/dev/null || true
        gsettings set org.gnome.desktop.background picture-options 'zoom' 2>/dev/null || true
        gsettings set org.gnome.desktop.screensaver picture-uri "file://$xml" 2>/dev/null || true

        # GDM login screen wallpaper
        if [[ -f "$DOTFILES/wallpapers/wallhaven-mlgzzy.png" ]]; then
            sudo cp "$DOTFILES/wallpapers/wallhaven-mlgzzy.png" /usr/share/backgrounds/gnome/core-wallpaper.png 2>/dev/null || true
            sudo -u gdm dbus-launch gsettings set org.gnome.desktop.background picture-uri \
                "file:///usr/share/backgrounds/gnome/core-wallpaper.png" 2>/dev/null || true
            sudo -u gdm dbus-launch gsettings set org.gnome.desktop.background picture-options 'zoom' 2>/dev/null || true
        fi

        log "Wallpapers configured (desktop, lockscreen, login)"
    fi
fi

# ── Set default shell ────────────────────────────────────────────────
ZSH_PATH=$(command -v zsh || echo "/usr/bin/zsh")
if [[ "$SHELL" == "$ZSH_PATH" ]]; then
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
