# Core Dotfiles

One-command terminal environment for **CachyOS / Arch Linux** (GNOME + Wayland).

```bash
git clone https://github.com/MathiasDeWeerdt/core-dotfiles ~/Documents/core-dotfiles
cd ~/Documents/core-dotfiles && ./install.sh
```

> **First time?** Copy `env.example` to `env` and set your hostname/user. The
> script will ask for confirmation before changing anything. Use `--dry-run` to
> preview.

## What gets installed

### Shell & Terminal
- **Foot** — native Wayland terminal (MesloLGS NF, 14px)
- **Zsh** — Oh My Zsh + Powerlevel10k (lean prompt, instant)
- **Tmux** — multiplexer with 8 plugins, `C-a` prefix, dev session, command palette

### 16 Zsh plugins
`git` `fzf` `fzf-tab` `docker` `docker-compose` `npm` `nvm` `dotnet` `node`
`ssh` `tmux` `zsh-syntax-highlighting` `zsh-autosuggestions` `magic-enter`
`encode64` `extract`

### 60+ CLI tools
| Category | Tools |
|----------|-------|
| Shell | `fzf` `fd` `ripgrep` `jq` `zoxide` `keychain` `stow` |
| Monitoring | `htop` `fastfetch` `ncdu` `lm_sensors` |
| Editing | `vim` `nano` `tree` |
| Networking | `nmap` `smbclient` `openbsd-netcat` `aria2` `rsync` `curl` `wget` |
| Security | `metasploit` `bettercap` `aircrack-ng` `hashcat` `impacket` `proxychains-ng` `netexec` `binwalk` `ufw` `gufw` |
| Transfer | `flameshot` `xclip` `wl-clipboard` |
| Browsers | `chromium` `firefox` `google-chrome` |

### 5 CLI coding agents
[See AGENTS.md](AGENTS.md) for configuration and API keys.

| Agent | Install | Vendor |
|-------|---------|--------|
| `codewhale` | npm global | CodeWhale |
| `codex` (`@openai/codex`) | npm global | OpenAI |
| `claude-code` | AUR | Anthropic |
| `opencode` | AUR | OpenCode |
| `copilot` | gh extension | GitHub |

### Dev runtimes
| Runtime | Manager | Versions |
|---------|---------|----------|
| Node.js | nvm | LTS |
| Go | pacman | Latest |
| Rust | rustup | Stable |
| Python | pacman | Latest + pipx |
| .NET | pacman | Latest SDK |
| Java | archlinux-java | JDK 8, 11, 17, 21, 26 |
| Bun | npm global | Latest |

### Infrastructure
- **Docker** — Engine + buildx + compose, user in `docker` group
- **QEMU** — full stack with `virt-manager` GUI + `quickemu`
- **Firewall** — `ufw` enabled (deny incoming, allow outgoing) + `gufw` GUI

### Virtual machines
Run `./scripts/quickemu-lab.sh create` to provision:
- Ubuntu 26.04 desktop, Ubuntu 24.04 desktop
- Windows 11, macOS Tahoe

All thin-provisioned qcow2, user-mode NAT networking (stable across WiFi/Ethernet switches).

### GNOME shortcuts
| Keys | Action |
|------|--------|
| `Ctrl+Alt+T` | Terminal (foot -m) |
| `Ctrl+Shift+A` | Screenshot (flameshot) |

### Custom tooling
- `expose` — serve files/dirs over HTTP with request inspection (full source in `expose/`)
- `flameshot-gui` — screenshot → clipboard in one shot
- `killport <port>` — kill whatever's listening on a port
- `dev` — launch pre-configured tmux dev session

## Structure

```
core-dotfiles/
├── install.sh                   # Bootstrap (610 lines, 11 steps)
├── update.sh                    # Upgrade everything in one shot
├── env.example                  # Copy to env, customize
├── README.md
├── AGENTS.md                    # Coding agent setup & API keys
│
├── zsh/          → ~/.zshrc, .zshenv
├── p10k/         → ~/.p10k.zsh           (1,713 lines)
├── foot/         → ~/.config/foot/
├── tmux/         → ~/.tmux.conf, dev-session, command-palette
├── git/          → ~/.gitconfig           (template)
├── fonts/        → ~/.local/share/fonts/  (MesloLGS NF ×4)
├── local-bin/    → ~/.local/bin/          (expose, burpsuitepro, flameshot-gui)
├── flameshot/    → ~/.config/flameshot/
│
├── expose/       → Full source for the expose HTTP tool
├── scripts/      → quickemu-lab.sh (VM fleet manager)
└── packages/     → pacman.txt, aur.txt, npm.txt
```

Uses **GNU Stow** — each directory symlinks into `$HOME`. Rerun anytime.

## Usage

```bash
./install.sh                    # Full bootstrap
./install.sh --help             # Show flags
./install.sh --dry-run          # Preview only
./install.sh --skip-packages    # Re-deploy configs, skip package installs

./update.sh                     # Upgrade everything to latest
```

Configuration lives in `env` (copy from `env.example`):
```bash
TARGET_USER="mathias"
DESIRED_HOSTNAME="bytebadger"
DOTFILES_DIR="$HOME/Documents/core-dotfiles"
SSH_KEY_TYPE="ed25519"
```

## Requirements

- CachyOS / Arch Linux (or EndeavourOS, Manjaro, ArcoLinux, Garuda, Artix)
- GNOME desktop (Wayland)
- `base-devel` (for AUR packages via yay)

## Post-install

- **Prompt**: `p10k configure`
- **Docker**: log out and back in for group membership
- **API keys**: see [AGENTS.md](AGENTS.md)
- **VMs**: `./scripts/quickemu-lab.sh create`
- **Burp Suite**: community edition via AUR, launcher at `~/.local/bin/burpsuitepro`
- **Updates**: `./update.sh` keeps everything current
