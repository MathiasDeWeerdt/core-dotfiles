# Enable Powerlevel10k instant prompt. Should stay close to the top of ~/.zshrc.
# Initialization code that may require console input (password prompts, [y/n]
# confirmations, etc.) must go above this block; everything else may go below.
if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
  source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi

# ── Path to Oh My Zsh ──────────────────────────────────────────────
export ZSH="$HOME/.oh-my-zsh"

# ── Theme ───────────────────────────────────────────────────────────
ZSH_THEME="powerlevel10k/powerlevel10k"

# ── Plugins ─────────────────────────────────────────────────────────
plugins=(
  git
  fzf
  fzf-tab
  docker
  docker-compose
  npm
  nvm
  dotnet
  node
  ssh
  tmux
  zsh-syntax-highlighting
  zsh-autosuggestions
  magic-enter
  encode64
  extract
)
source $ZSH/oh-my-zsh.sh

# ── Smarter filename completion ─────────────────────────────────────

# Show dotfiles in completions
setopt globdots

# Case-insensitive substring matching for all completions
zstyle ':completion:*' matcher-list 'm:{a-zA-Z}={A-Za-z}' 'r:|=*' 'l:|=* r:|=*'

# fzf-tab: prefer shorter matches first
zstyle ':fzf-tab:*' fzf-flags --tiebreak=length,begin

# ── Aliases ─────────────────────────────────────────────────────────

# Cross-platform ls: use GNU flags when available, fallback for BSD/macOS
if ls --group-directories-first &>/dev/null; then
    alias ls='ls --color -h --group-directories-first'
else
    alias ls='ls -G -h'
fi

# Launch the tmux dev session
alias dev='~/.config/tmux/dev-session'

# ── Functions ───────────────────────────────────────────────────────

# Kill process on specified port
killport() {
    if [ -z "$1" ]; then
        echo "Usage: killport <port>"
        return 1
    fi

    local port=$1
    local pids=""

    # Try multiple methods to find the process
    # Method 1: lsof
    pids=$(lsof -ti:$port 2>/dev/null)

    # Method 2: fuser (if lsof didn't find anything)
    if [ -z "$pids" ]; then
        pids=$(fuser $port/tcp 2>&1 | grep -o '[0-9]*' | head -1)
    fi

    # Method 3: ss/netstat
    if [ -z "$pids" ]; then
        pids=$(ss -tlnp 2>/dev/null | grep ":$port " | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u | head -1)
    fi

    if [ -n "$pids" ]; then
        echo "Found process(es) on port $port: $pids"
        echo "$pids" | xargs -r kill -9 2>/dev/null
        echo "Killed process(es) on port $port"
        sleep 0.5
    else
        echo "No process found on port $port"
        echo "Note: If you still get 'Address already in use', the port might be in TIME_WAIT state."
        echo "      Wait a few seconds or use 'ss -tan | grep :$port' to check socket states."
    fi
}

# ── Prompt ──────────────────────────────────────────────────────────
# To customize prompt, run `p10k configure` or edit ~/.p10k.zsh.
[[ ! -f ~/.p10k.zsh ]] || source ~/.p10k.zsh

# ── SSH Agent ───────────────────────────────────────────────────────
# Load SSH keys into agent automatically
eval "$(keychain --eval 2>/dev/null | sed '/^ \* /d')"

# ── Node.js (nvm) ───────────────────────────────────────────────────
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"

# ── PATH ────────────────────────────────────────────────────────────
export PATH="$HOME/.local/bin:$HOME/go/bin:$PATH"

# ── Rust ────────────────────────────────────────────────────────────
[ -f "$HOME/.cargo/env" ] && source "$HOME/.cargo/env"

# ── zoxide (smarter cd) ─────────────────────────────────────────────
eval "$(zoxide init zsh)"

# ── Magic Enter ─────────────────────────────────────────────────────
MAGIC_ENTER_GIT_COMMAND='git status -u .'
MAGIC_ENTER_OTHER_COMMAND='ls -lh .'

# ── Shell integrations ──────────────────────────────────────────────
# bun completions
[ -s "$HOME/.bun/_bun" ] && source "$HOME/.bun/_bun"

# ── Optional: cloud / AI provider keys ──────────────────────────────
# Set these in your environment or a separate secrets file.
#
#   export COPILOT_PROVIDER_BASE_URL=https://openrouter.ai/api/v1
#   export COPILOT_PROVIDER_API_KEY=your-openrouter-api-key
#   export COPILOT_PROVIDER_MODEL_ID=deepseek-v4-pro
#   export COPILOT_PROVIDER_WIRE_MODEL=deepseek/deepseek-v4-pro
#   export GITHUB_PERSONAL_ACCESS_TOKEN=ghp_your-token-here

# ── Optional: Android SDK (uncomment if needed) ─────────────────────
# export ANDROID_HOME=/opt/android-sdk
# export ANDROID_SDK_ROOT=$ANDROID_HOME
# export PATH=$PATH:$ANDROID_HOME/platform-tools

# ── Optional: Flutter (uncomment if needed) ─────────────────────────
# export PATH="$HOME/development/flutter/bin:$PATH"
