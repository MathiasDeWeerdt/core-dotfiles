# Core Dotfiles

One-command terminal environment for **CachyOS / Arch Linux** (GNOME + Wayland).

```bash
git clone https://github.com/MathiasDeWeerdt/core-dotfiles ~/Documents/core-dotfiles
cd ~/Documents/core-dotfiles && ./install.sh
```

> **First time?** Defaults are your current user, hostname, and checkout.
> Optionally copy `env.example` to ignored `env` to override these. The installer
> asks for confirmation; `--dry-run` previews without changes.

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
| GitHub | `gh` |
| Monitoring | `htop` `fastfetch` `ncdu` `lm_sensors` |
| Editing | `vim` `nano` `tree` |
| Networking | `nmap` `smbclient` `openbsd-netcat` `aria2` `rsync` `curl` `wget` |
| Security | `metasploit` `bettercap` `aircrack-ng` `hashcat` `impacket` `proxychains-ng` `netexec` `binwalk` `ufw` `gufw` |
| Transfer | `flameshot` `xclip` `wl-clipboard` |
| Browsers | `chromium` `firefox` `google-chrome` |

### 6 CLI coding agents
[See AGENTS.md](AGENTS.md) for installation and private configuration conventions.

| Agent | Install | Vendor |
|-------|---------|--------|
| `codewhale` | npm global | CodeWhale |
| `codex` (`@openai/codex`) | npm global | OpenAI |
| `claude-code` | AUR | Anthropic |
| `opencode` | AUR | OpenCode |
| `copilot` (`@github/copilot`) | npm global | GitHub |
| `pi` (`@earendil-works/pi-coding-agent`) | npm global | Earendil |

### Dev runtimes
| Runtime | Manager | Versions |
|---------|---------|----------|
| Node.js | nvm | LTS |
| Go | pacman | Latest |
| Rust | rustup | Stable |
| Python | pacman | Latest + pipx |
| .NET | pacman | Latest SDK |
| Java | archlinux-java | JDK 8, 11, 17, 21, latest |
| Bun | npm global | Latest |

### Infrastructure
- **Docker** — Engine + buildx + compose, user in `docker` group
- **QEMU** — full stack with `virt-manager` GUI + `quickemu`
- **Firewall** — `ufw` enabled (deny incoming, allow outgoing) + `gufw` GUI
- **Preload** — adaptive readahead daemon for faster app startup

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
- `expose` — serve files/dirs over HTTP with request inspection; password-protected operator UI, browser consoles, SOCKS proxy, and inbound callbacks (full source in `expose/`)
- `expose-online` — publish `expose` through `singlecore.dev` with an authenticated session and a resilient SSH tunnel
- `flameshot-gui` — screenshot → clipboard in one shot
- Nautilus right-click → **Open in Terminal** opens foot (via `nautilus-open-any-terminal`)

### Global agent memory
A single `~/.memory.md` feeds identity, preferences, and development philosophy
into all coding agents (Claude Code via `@import`, Codex/Pi/OpenCode via global
`AGENTS.md`). Existing private memory and harness-specific instructions are preserved.
`memory/.memory.md` is only a public starter template. It is copied once, never stowed
or overwritten on reruns. Private context can also live in `~/.memory.local.md`.

## Structure

```
core-dotfiles/
├── install.sh                   # Bootstrap with a read-only preview
├── update.sh                    # Upgrade everything in one shot
├── env.example                  # Copy to env, customize
├── README.md
├── AGENTS.md                    # Repository rules & coding agent setup
├── memory/        → Public starter template; private ~/.memory.md is preserved
│
├── zsh/          → ~/.zshrc, .zshenv
├── p10k/         → ~/.p10k.zsh
├── foot/         → ~/.config/foot/
├── tmux/         → ~/.tmux.conf, dev-session, command-palette
├── git/          → ~/.gitconfig           (template)
├── fonts/        → ~/.local/share/fonts/  (MesloLGS NF ×4)
├── local-bin/    → ~/.local/bin/          (expose, burpsuitepro, flameshot-gui)
├── flameshot/    → ~/.config/flameshot/
│
├── expose/       → Full source for the expose HTTP tool
├── systemd/      → Opt-in update-check and committed-sync user timers
├── scripts/      → Deployment, credential checks, GNOME settings, VM manager
├── tests/        → Isolated deployment, security, and sync checks
└── packages/     → pacman.txt, aur.txt, npm.txt
```

Uses **GNU Stow** to link public configs into `$HOME`. Conflicting files are backed up under `~/.local/state/core-dotfiles/backups/`; host files are never adopted into Git.

## Usage

```bash
./install.sh                    # Full bootstrap
./install.sh --help             # Show flags
./install.sh --dry-run          # Preview only
./install.sh --skip-packages    # Skip pacman/AUR; other setup still runs
./install.sh --configs-only     # Configs, private memory wiring, expose tools only

./update.sh                     # Upgrade packages/runtimes/plugins and redeploy
./update.sh --configs-only      # Redeploy current local sources without pulling
./update.sh --dry-run           # Preview without changes
```

Optional bootstrap overrides live in ignored `env` (copy from `env.example`):
```bash
TARGET_USER="$USER"
DESIRED_HOSTNAME="$(hostname)"
DOTFILES_DIR="$HOME/Documents/core-dotfiles"
SSH_KEY_TYPE="ed25519"
```

## Requirements

- CachyOS / Arch Linux (or EndeavourOS, Manjaro, ArcoLinux, Garuda; systemd required)
- GNOME desktop (Wayland)
- `base-devel` (for AUR packages via yay)

## Post-install

- **Prompt**: `p10k configure`
- **Docker**: log out and back in for group membership
- **API keys**: native login or private shell configuration; see [AGENTS.md](AGENTS.md)
- **VMs**: `./scripts/quickemu-lab.sh create`
- **Burp Suite**: community edition via AUR, launcher at `~/.local/bin/burpsuitepro`
- **Updates**: `./update.sh` keeps everything current

## Safe updates and credentials

`expose` and `expose-online` are built from `expose/src/`. Both installer and
updater verify and install matching scripts to `/usr/local/bin`, including when
an older system copy shadows `~/.local/bin`. Console connectors are rebuilt when
Go is available. Use `EXPOSE_INSTALL_DIR` to select a different installation directory.

`expose-online` has no built-in password. Keep its private shell configuration at
`~/.config/expose/online.env`, owned by your user with permissions `0600`.
Set `EXPOSE_AUTH_PASSWORD` there or in the calling environment. The environment
wins; an empty password is rejected. Never put the configuration in this repo.

No passwords, API tokens, private keys, customer context, or runtime captures
belong in this public repository. `.gitignore`, the local Git hooks, and CI
provide complementary checks. Run `python3 scripts/check-secrets.py` before
sharing; `--staged` checks the Git index and `--history` checks all reachable
history. Detection is a safeguard, not a guarantee. Historical credentials must
be rotated; deleting them from the current checkout does not remove old commits.

The privileged `internetshare` web UI binds to loopback and prints a temporary
launch URL. Open that URL to authenticate; cross-site requests are rejected.

## Local verification

```bash
bash tests/install-packages.sh
python3 tests/deployment.py       # 100 deployments in a disposable home
bash tests/online-config.sh
bash tests/quickemu.sh
python3 tests/gnome.py
python3 tests/secret-checks.py
python3 tests/sync.py             # Disposable local Git remotes; no network
python3 tests/internetshare.py    # requires the system python-flask package
make -C expose console-clients test
(cd expose/src/connector && go test ./... && go vet ./...)
```

Repeated deployment preserves private memory, custom agent instructions, and
existing backups. Dry runs do not write files, download software, or run sudo.
The full bootstrap still intentionally configures system services and desktop
settings. Updates require internet access and fail visibly when a step fails.

## Existing shell sessions

While `expose-online` runs, use `expose sessions` and `expose attach` in another
terminal. Ctrl+] detaches without stopping the shell or SOCKS relay. Ctrl+C
interrupts the remote command; `exit` and Ctrl+D end the shell. Use
`expose invite linux|mac|win` to enroll an authorized endpoint and
`expose proxychains COMMAND` to select the local instance's SOCKS configuration.
Remote CLI login uses `expose login --url https://YOUR-HOST`; credentials stay
in private user storage. See [expose/README.md](expose/README.md) for details and
the isolated `./expose/playground.sh test` / `up` / `attach` playground.

## Login and daily update checks (opt-in)

The installer deploys `core-dotfiles-update-check.service` and `.timer` without
enabling them. To enable notifications after reviewing the setup:

```bash
./install.sh --configs-only
systemctl --user daemon-reload
systemctl --user enable --now core-dotfiles-update-check.timer
```

The timer checks the tracked upstream after login and daily, with a randomized
delay. It never pulls code, installs packages, runs sudo, or restarts services or
shells. An optional private `~/.config/core-dotfiles/update.env` can override
`DOTFILES_DIR`. Apply reviewed updates with `./update.sh`; resolve local changes
first. Each laptop/desktop keeps its own SSH keys and private expose credentials.

Keep full Arch/AUR upgrades interactive: perform complete system upgrades, read
Arch news, and handle required interventions. Do not run unattended `pacman` or
AUR upgrades at boot. Running shell sessions remain on their existing server
build until you choose to restart it; they do not migrate across restarts.

## Automatic sync across devices

Use the same tracked branch on every device (`main` is recommended; `dev_new`
also contains this setup). After reviewing and committing a change, `dotfiles-sync` pushes it through
the secret-checking hook. On another device it fetches and fast-forwards a clean
checkout. It never creates commits, stashes edits, merges divergent branches,
force-pushes, installs packages, runs sudo, or restarts expose. Conflicts and local
edits stop synchronization and produce a desktop notification and journal entry.
Fetched history is checked for credentials before it can reach linked configs.

```bash
./install.sh --configs-only
dotfiles-sync                     # Review a foreground run first
systemctl --user daemon-reload
systemctl --user enable --now core-dotfiles-sync.timer
journalctl --user -u core-dotfiles-sync.service
```

The timer runs after login and every five minutes. A working SSH key/agent with
GitHub write access is required on each device; authentication never prompts in
the background. Run `git add` and `git commit` yourself after reviewing edits.
To pause syncing: `systemctl --user disable --now core-dotfiles-sync.timer`.
The notification-only update-check timer above is an alternative; it can remain
disabled when sync is enabled. Both support private `update.env` / `DOTFILES_DIR`.

Fast-forwarding immediately changes files linked by Stow. This trusts commits on
the selected upstream branch. It does not rebuild `/usr/local/bin/expose` or Go
connectors: review incoming changes, then run `./update.sh --configs-only`.
Use `./update.sh` separately for full system upgrades. Private memory, keys,
passwords, and machine-specific configuration stay local to each device.

The security cleanup rewrites old history. Existing devices must save uncommitted
work privately and clone the cleaned repository again; do not merge or push their
old history into the cleaned branches. Credentials once published remain exposed
even after cleanup and must be rotated. GitHub may retain cached commits and pull
request references; see [GitHub's removal guidance](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).

## Private tmux projects

`dev` reuses the existing `dev` session and creates missing sessions with an
OpenCode home window and a CLI window. Add optional project directories, one per
line, to private `~/.config/core-dotfiles/tmux-projects` (mode `0600`). Empty lines,
comments, duplicate paths, and unavailable directories are skipped. Project paths
and customer names do not belong in this public repository. `dev-session --boot`
creates the session without attaching; rerunning it preserves existing windows.
