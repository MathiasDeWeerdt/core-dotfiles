# Enable Powerlevel10k instant prompt. Should stay close to the top of ~/.zshrc.
# Initialization code that may require console input (password prompts, [y/n]
# confirmations, etc.) must go above this block; everything else may go below.
if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
  source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi

# export PATH="$PATH:/home/mathias/.local/bin"
source /usr/share/cachyos-zsh-config/cachyos-config.zsh

# To customize prompt, run `p10k configure` or edit ~/.p10k.zsh.
[[ ! -f ~/.p10k.zsh ]] || source ~/.p10k.zsh

export PATH="$PATH:/home/mathias/.local/bin/"

source /usr/share/nvm/init-nvm.sh
eval "$(zoxide init zsh)"

# bun completions
[ -s "/home/mathias/.bun/_bun" ] && source "/home/mathias/.bun/_bun"

unsetopt correct     # disables command correction
unsetopt correct_all # disables argument correction too

# bun
export BUN_INSTALL="$HOME/.bun"
export PATH="$BUN_INSTALL/bin:$PATH"
export JIMBER_PAT="d719cbbb2d6f7b3b5563c78c2bb31d353b61443e13c2db8c6b9dcff2f1393472"
export PATH="$JIMBER_PAT:$PATH"

# CodeWhale search provider fallback aliases
alias cw='codewhale'
alias cw-fallback='DEEPSEEK_SEARCH_PROVIDER=duckduckgo codewhale'

# ls with hidden-first sorting: .dirs → dirs → .files → files
unalias ls 2>/dev/null
ls() {
  emulate -L zsh
  setopt localoptions extendedglob nullglob

  local -a opts targets
  local default_opts=(--color -h)

  for arg in "$@"; do
    if [[ "$arg" == -* ]]; then
      opts+=("$arg")
    else
      targets+=("$arg")
    fi
  done

  (( ${#targets} )) || targets=(".")

  # Detect -a / -A / --all / --almost-all
  local show_hidden=false
  local show_dotdot=false
  for opt in "${opts[@]}"; do
    if [[ "$opt" == "--all" ]]; then
      show_hidden=true; show_dotdot=true
    elif [[ "$opt" == "--almost-all" ]]; then
      show_hidden=true
    elif [[ "$opt" == -*a* && "$opt" != *A* && "$opt" != "--almost-all" ]]; then
      show_hidden=true; show_dotdot=true
    elif [[ "$opt" == -*A* && "$opt" != "--all" ]]; then
      show_hidden=true
    fi
  done

  # If any target is not a directory, fall back to normal ls
  local all_dirs=true
  for t in "${targets[@]}"; do
    [[ -d "$t" ]] || { all_dirs=false; break; }
  done

  if ! $all_dirs; then
    command ls $default_opts "${opts[@]}" "${targets[@]}"
    return
  fi

  local first=true
  for dir in "${targets[@]}"; do
    $first || print     # blank line between directories
    first=false

    (( ${#targets} > 1 )) && print "${dir}:"

    local -a dotdirs dirs dotfiles files

    if $show_hidden; then
      dotdirs=("$dir"/.*(/))
      if $show_dotdot; then
        dotdirs=("$dir/." "$dir/.." $dotdirs)
      fi
      dotfiles=("$dir"/.*(^/))
    fi

    dirs=("$dir"/*(/))
    files=("$dir"/*(^/))

    local -a all=($dotdirs $dirs $dotfiles $files)

    if (( ${#all} )); then
      (cd "$dir" && command ls -dU $default_opts "${opts[@]}" -- ${all:t})
    else
      command ls -d $default_opts "${opts[@]}" -- "$dir"
    fi
  done
}

# >>> grok installer >>>
export PATH="$HOME/.grok/bin:$PATH"
fpath=(~/.grok/completions/zsh $fpath)
autoload -Uz compinit && compinit -C
# <<< grok installer <<<
