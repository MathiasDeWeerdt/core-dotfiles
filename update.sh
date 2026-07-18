#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Core Dotfiles — Update everything
# ─────────────────────────────────────────────────────────────────────
# Upgrades all packages, runtimes, agents, and dotfiles in one shot.
# Run this whenever you want to bring everything current.
# ─────────────────────────────────────────────────────────────────────
set -uo pipefail

GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[✓]${NC} $*"; }
info() { echo -e "${BLUE}[→]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }

DOTFILES="$HOME/Documents/core-dotfiles"
ERRORS=()

step()  { echo ""; echo -e "${BLUE}═══ $* ═══${NC}"; echo ""; }
fail()  { ERRORS+=("$*"); warn "Failed: $*"; }

# ── 1. System packages ──────────────────────────────────────────────
step "System packages"

info "Upgrading official packages..."
sudo pacman -Syu --noconfirm || fail "pacman update"

if command -v yay &>/dev/null; then
    info "Upgrading AUR packages..."
    yay -Syu --noconfirm --answerclean All --answerdiff None || fail "yay update"
fi

log "System packages current"

# ── 2. Dotfiles ──────────────────────────────────────────────────────
step "Dotfiles"

if [[ -d "$DOTFILES" ]]; then
    info "Pulling latest dotfiles..."
    cd "$DOTFILES"
    git pull --ff-only 2>/dev/null || warn "git pull failed — resolve manually"
    stow -d "$DOTFILES" -t "$HOME" -R --adopt zsh p10k foot tmux git fonts local-bin flameshot 2>/dev/null || true
    log "Dotfiles updated"
else
    warn "Dotfiles not found at $DOTFILES — run install.sh first"
fi

# ── 3. Runtimes ─────────────────────────────────────────────────────
step "Language runtimes"

# Node
if [[ -s "$HOME/.nvm/nvm.sh" ]]; then
    export NVM_DIR="$HOME/.nvm"
    source "$NVM_DIR/nvm.sh"
    info "Upgrading Node.js LTS..."
    nvm install --lts --reinstall-packages-from=current 2>/dev/null || \
        nvm install --lts 2>/dev/null || fail "nvm"
    nvm alias default 'lts/*' 2>/dev/null || true
    log "Node: $(node --version 2>/dev/null || echo '?')"
fi

# Rust
if command -v rustup &>/dev/null; then
    info "Upgrading Rust..."
    rustup update 2>/dev/null || fail "rustup"
    log "Rust: $(rustc --version 2>/dev/null || echo '?')"
fi

# Java — just show status
if command -v archlinux-java &>/dev/null; then
    archlinux-java status 2>/dev/null
fi

# ── 4. Package managers ──────────────────────────────────────────────
step "Package managers"

# npm globals
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"

if command -v npm &>/dev/null; then
    info "Upgrading npm global packages..."
    npm update -g 2>/dev/null || fail "npm update"
    log "npm globals updated"
fi

# pipx
if command -v pipx &>/dev/null; then
    info "Upgrading pipx packages..."
    pipx upgrade-all 2>/dev/null || warn "pipx upgrade (some may fail)"
fi

# ── 5. Shell & tools ────────────────────────────────────────────────
step "Shell & tools"

# Oh My Zsh
if [[ -d "$HOME/.oh-my-zsh" ]]; then
    info "Upgrading Oh My Zsh..."
    zsh -c 'source "$ZSH/oh-my-zsh.sh" && omz update' 2>/dev/null || warn "omz update"
fi

# Tmux plugins
if [[ -f "$HOME/.tmux/plugins/tpm/bin/update_plugins" ]]; then
    info "Upgrading tmux plugins..."
    "$HOME/.tmux/plugins/tpm/bin/update_plugins" all 2>/dev/null || true
fi

# Powerlevel10k
P10K_DIR="$HOME/.oh-my-zsh/custom/themes/powerlevel10k"
if [[ -d "$P10K_DIR" ]]; then
    info "Upgrading Powerlevel10k..."
    (cd "$P10K_DIR" && git pull --ff-only 2>/dev/null) || warn "p10k update"
fi

# ── Summary ──────────────────────────────────────────────────────────
echo ""
echo -e "${BLUE}═══ Done ═══${NC}"
echo ""

if [[ ${#ERRORS[@]} -gt 0 ]]; then
    echo -e "  ${YELLOW}${#ERRORS[@]} step(s) had issues:${NC}"
    for e in "${ERRORS[@]}"; do
        echo -e "    ✗ $e"
    done
else
    echo -e "  ${GREEN}Everything is up to date.${NC}"
fi

echo ""
echo "  System:  $(pacman -Q | wc -l) packages"
echo "  Shell:   zsh $(zsh --version 2>/dev/null | awk '{print $2}')"
echo "  Node:    $(node --version 2>/dev/null || echo '—')"
echo "  Go:      $(go version 2>/dev/null | awk '{print $3}' || echo '—')"
echo "  Rust:    $(rustc --version 2>/dev/null | awk '{print $2}' || echo '—')"
echo "  Java:    $(java --version 2>/dev/null | head -1 || echo '—')"
echo "  Docker:  $(docker --version 2>/dev/null | awk '{print $3}' | tr -d ',' || echo '—')"
echo ""
