# Enable Powerlevel10k instant prompt. Should stay close to the top of ~/.zshrc.
# Initialization code that may require console input (password prompts, [y/n]
# confirmations, etc.) must go above this block; everything else may go below.
if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
  source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi

# If you come from bash you might have to change your $PATH.
# export PATH=$HOME/bin:$HOME/.local/bin:/usr/local/bin:$PATH

# Path to your Oh My Zsh installation.
export ZSH="$HOME/.oh-my-zsh"

# Set name of the theme to load --- if set to "random", it will
# load a random theme each time Oh My Zsh is loaded, in which case,
# to know which specific one was loaded, run: echo $RANDOM_THEME
# See https://github.com/ohmyzsh/ohmyzsh/wiki/Themes
ZSH_THEME="powerlevel10k/powerlevel10k"

# Set list of themes to pick from when loading at random
# Setting this variable when ZSH_THEME=random will cause zsh to load
# a theme from this variable instead of looking in $ZSH/themes/
# If set to an empty array, this variable will have no effect.
# ZSH_THEME_RANDOM_CANDIDATES=( "robbyrussell" "agnoster" )

# Uncomment the following line to use case-sensitive completion.
# CASE_SENSITIVE="true"

# Uncomment the following line to use hyphen-insensitive completion.
# Case-sensitive completion must be off. _ and - will be interchangeable.
# HYPHEN_INSENSITIVE="true"

# Uncomment one of the following lines to change the auto-update behavior
# zstyle ':omz:update' mode disabled  # disable automatic updates
# zstyle ':omz:update' mode auto      # update automatically without asking
# zstyle ':omz:update' mode reminder  # just remind me to update when it's time

# Uncomment the following line to change how often to auto-update (in days).
# zstyle ':omz:update' frequency 13

# Uncomment the following line if pasting URLs and other text is messed up.
# DISABLE_MAGIC_FUNCTIONS="true"

# Uncomment the following line to disable colors in ls.
# DISABLE_LS_COLORS="true"

# Uncomment the following line to disable auto-setting terminal title.
# DISABLE_AUTO_TITLE="true"

# Uncomment the following line to enable command auto-correction.
# ENABLE_CORRECTION="true"

# Uncomment the following line to display red dots whilst waiting for completion.
# You can also set it to another string to have that shown instead of the default red dots.
# e.g. COMPLETION_WAITING_DOTS="%F{yellow}waiting...%f"
# Caution: this setting can cause issues with multiline prompts in zsh < 5.7.1 (see #5765)
# COMPLETION_WAITING_DOTS="true"

# Uncomment the following line if you want to disable marking untracked files
# under VCS as dirty. This makes repository status check for large repositories
# much, much faster.
# DISABLE_UNTRACKED_FILES_DIRTY="true"

# Uncomment the following line if you want to change the command execution time
# stamp shown in the history command output.
# You can set one of the optional three formats:
# "mm/dd/yyyy"|"dd.mm.yyyy"|"yyyy-mm-dd"
# or set a custom format using the strftime function format specifications,
# see 'man strftime' for details.
# HIST_STAMPS="mm/dd/yyyy"

# Would you like to use another custom folder than $ZSH/custom?
# ZSH_CUSTOM=/path/to/new-custom-folder

# Which plugins would you like to load?
# Standard plugins can be found in $ZSH/plugins/
# Custom plugins may be added to $ZSH_CUSTOM/plugins/
# Example format: plugins=(rails git textmate ruby lighthouse)
# Add wisely, as too many plugins slow down shell startup.
plugins=(git fzf fzf-tab docker docker-compose npm nvm dotnet node ssh tmux zsh-syntax-highlighting zsh-autosuggestions magic-enter encode64 extract)
# ZSH_TMUX_AUTOSTART=true
source $ZSH/oh-my-zsh.sh

# --- Smarter filename completion ---

# CRITICAL: without this, zsh's completion system skips dotfiles (.zshrc, .gitconfig, etc.)
# This is what was missing — fzf-tab doesn't generate completions, zsh does
setopt globdots

# zsh: case-insensitive substring matching for all completions
zstyle ':completion:*' matcher-list 'm:{a-zA-Z}={A-Za-z}' 'r:|=*' 'l:|=* r:|=*'

# fzf-tab: prefer shorter matches first
# NOTE: --hidden and --no-ignore only work for fzf's own file-search mode (Ctrl+T),
# NOT when fzf reads from stdin (which is how fzf-tab feeds completions)
zstyle ':fzf-tab:*' fzf-flags --tiebreak=length,begin

# User configuration

# export MANPATH="/usr/local/man:$MANPATH"

# You may need to manually set your language environment
# export LANG=en_US.UTF-8

# Preferred editor for local and remote sessions
# if [[ -n $SSH_CONNECTION ]]; then
#   export EDITOR='vim'
# else
#   export EDITOR='nvim'
# fi

# Compilation flags
# export ARCHFLAGS="-arch $(uname -m)"

# Set personal aliases, overriding those provided by Oh My Zsh libs,
# plugins, and themes. Aliases can be placed here, though Oh My Zsh
# users are encouraged to define aliases within a top-level file in
# the $ZSH_CUSTOM folder, with .zsh extension. Examples:
# - $ZSH_CUSTOM/aliases.zsh
# - $ZSH_CUSTOM/macos.zsh
# For a full list of active aliases, run `alias`.
#
# Example aliases
# alias zshconfig="mate ~/.zshrc"
# alias ohmyzsh="mate ~/.oh-my-zsh"

# Cross-platform ls: use GNU flags when available, fallback for BSD/macOS
if ls --group-directories-first &>/dev/null; then
    alias ls='ls --color -h --group-directories-first'
else
    alias ls='ls -G -h'
fi
alias dev='~/.config/tmux/dev-session'

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
        # Wait a moment for the port to be released
        sleep 0.5
    else
        echo "No process found on port $port"
        echo "Note: If you still get 'Address already in use', the port might be in TIME_WAIT state."
        echo "      Wait a few seconds or use 'ss -tan | grep :$port' to check socket states."
    fi
}

# To customize prompt, run `p10k configure` or edit ~/.p10k.zsh.
[[ ! -f ~/.p10k.zsh ]] || source ~/.p10k.zsh

eval "$(keychain --eval id_ed25519 id_rsa 2>/dev/null | sed '/^ \* /d')"

export NVM_DIR=~/.nvm
source /usr/share/nvm/nvm.sh

export PATH=$PATH:/home/mathias/.local/bin

# export ANDROID_HOME=$HOME/android-sdk
# export PATH=$PATH:$ANDROID_HOME/platform-tools

export ANDROID_HOME=/opt/android-sdk
export ANDROID_SDK_ROOT=$ANDROID_HOME

# export JAVA_HOME=/usr/lib/jvm/java-21-openjdk
# export JAVA_HOME=/home/mathias/Documents/java/graalvm-jdk-23.0.2+7.1

export PATH=$PATH:/home/mathias/go/bin
# export PATH=/home/mathias/Documents/java/graalvm-jdk-23.0.2+7.1/bin/:$PATH


export CHROME_EXECUTABLE=google-chrome-stable

PATH="/home/mathias/perl5/bin${PATH:+:${PATH}}"; export PATH;
PERL5LIB="/home/mathias/perl5/lib/perl5${PERL5LIB:+:${PERL5LIB}}"; export PERL5LIB;
PERL_LOCAL_LIB_ROOT="/home/mathias/perl5${PERL_LOCAL_LIB_ROOT:+:${PERL_LOCAL_LIB_ROOT}}"; export PERL_LOCAL_LIB_ROOT;
PERL_MB_OPT="--install_base \"/home/mathias/perl5\""; export PERL_MB_OPT;
PERL_MM_OPT="INSTALL_BASE=/home/mathias/perl5"; export PERL_MM_OPT;

eval "$(zoxide init zsh)"

# eval "$(keychain --eval id_ed25519 id_rsa >/dev/null 2>&1)"
# eval "$(keychain --eval id_ed25519 id_rsa)"

#ssh-add ~/.ssh/id_ed25519
#ssh-add ~/.ssh/id_rsa_niacs
# eval $(keychain --eval --agents ssh id_ed25519)
# eval $(keychain --eval --agents ssh id_ed25519 2>/dev/null) >/dev/null

# Start SSH agent if not already running
#if [ -z "$SSH_AUTH_SOCK" ]; then
#  eval "$(ssh-agent -s)" > /dev/null
#fi

# Add keys if not already added
#ssh-add -l >/dev/null 2>&1
#if [ $? -ne 0 ]; then
#  ssh-add ~/.ssh/id_rsa_personal ~/.ssh/id_rsa_work >/dev/null 2>&1
#fi

# . "$HOME/.local/share/krita/ai_diffusion/server/uv/env"

MAGIC_ENTER_GIT_COMMAND='git status -u .'
MAGIC_ENTER_OTHER_COMMAND='ls -lh .'

# Local credentials are kept outside this repository.
[[ ! -r "$HOME/.config/core-dotfiles/secrets.zsh" ]] || source "$HOME/.config/core-dotfiles/secrets.zsh"

# OpenRouter via Copilot CLI
export COPILOT_PROVIDER_BASE_URL=https://openrouter.ai/api/v1

export COPILOT_PROVIDER_MODEL_ID=deepseek-v4-pro
export COPILOT_PROVIDER_WIRE_MODEL=deepseek/deepseek-v4-pro


# bun completions
[ -s "/home/mathias/.bun/_bun" ] && source "/home/mathias/.bun/_bun"
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion
