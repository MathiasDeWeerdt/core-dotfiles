#!/usr/bin/env bash
# Upgrade packages and redeploy the same configs/tools as install.sh.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DRY_RUN=false
CONFIGS_ONLY=false
ERRORS=()
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --configs-only) CONFIGS_ONLY=true ;;
        --help|-h) printf 'Usage: ./update.sh [--dry-run] [--configs-only]\n'; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$arg" >&2; exit 1 ;;
    esac
done
if $DRY_RUN; then
    $CONFIGS_ONLY || printf 'Would update system/AUR packages, clean Git checkouts, runtimes, npm globals, pipx and shell plugins.\n'
    exec bash "$ROOT/scripts/deploy.sh" --dry-run
fi
if $CONFIGS_ONLY; then
    exec bash "$ROOT/scripts/deploy.sh"
fi

run() {
    local description=$1
    shift
    printf '\n%s\n' "$description"
    if "$@"; then
        printf 'OK: %s\n' "$description"
    else
        ERRORS+=("$description")
        printf 'FAILED: %s\n' "$description" >&2
    fi
}

# Never auto-stash, merge, or replace local edits, including stowed dotfiles.
update_checkout() {
    local directory=$1
    if [[ -n "$(git -C "$directory" status --porcelain)" ]]; then
        printf 'Checkout has local changes; pull skipped: %s\n' "$directory" >&2
        return 1
    fi
    git -C "$directory" pull --ff-only
}
run 'Update repository' update_checkout "$ROOT"
run 'Update official packages' sudo pacman -Syu --noconfirm
if command -v yay >/dev/null; then
    run 'Update AUR packages' yay -Sua --noconfirm --answerclean All --answerdiff None
fi

export NVM_DIR="$HOME/.nvm"
if [[ -s "$NVM_DIR/nvm.sh" ]]; then
    # User-managed nvm is separate from the packaged version.
    run 'Update user-managed nvm' update_checkout "$NVM_DIR"
    source "$NVM_DIR/nvm.sh"
elif [[ -s /usr/share/nvm/nvm.sh ]]; then
    source /usr/share/nvm/nvm.sh
fi
if command -v nvm >/dev/null; then
    run 'Update Node.js LTS' nvm install --lts --reinstall-packages-from=current
    run 'Set default Node.js LTS' nvm alias default 'lts/*'
fi
command -v rustup >/dev/null && run 'Update Rust' rustup update
command -v npm >/dev/null && run 'Update npm globals' npm update -g
run 'Update official DeepSeek Harness' python3 "$ROOT/scripts/install-dsh.py"
command -v pipx >/dev/null && run 'Update pipx tools' pipx upgrade-all

ZSH_DIR=${ZSH:-$HOME/.oh-my-zsh}
[[ ! -d "$ZSH_DIR/.git" ]] || run 'Update Oh My Zsh' update_checkout "$ZSH_DIR"
CUSTOM_DIR=${ZSH_CUSTOM:-$ZSH_DIR/custom}
for directory in "$CUSTOM_DIR/themes/powerlevel10k" \
    "$CUSTOM_DIR/plugins/fzf-tab" "$CUSTOM_DIR/plugins/zsh-autosuggestions" \
    "$CUSTOM_DIR/plugins/zsh-syntax-highlighting"; do
    [[ ! -d "$directory/.git" ]] || run "Update $directory" update_checkout "$directory"
done
if [[ -x "$HOME/.tmux/plugins/tpm/bin/update_plugins" ]]; then
    run 'Update tmux plugins' "$HOME/.tmux/plugins/tpm/bin/update_plugins" all
fi
run 'Deploy configs, global memory, and expose' bash "$ROOT/scripts/deploy.sh"

if (( ${#ERRORS[@]} )); then
    printf '\nUpdate incomplete (%s failed or skipped steps):\n' "${#ERRORS[@]}" >&2
    printf '  %s\n' "${ERRORS[@]}" >&2
    exit 1
fi
printf '\nAll requested updates and deployment completed successfully.\n'
