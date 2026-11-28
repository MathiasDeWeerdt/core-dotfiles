# Core Dotfiles

One-command terminal environment for **CachyOS / Arch Linux** (GNOME + Wayland).

```bash
git clone https://github.com/MathiasDeWeerdt/core-dotfiles ~/Documents/core-dotfiles
cd ~/Documents/core-dotfiles && ./install.sh
```

> **First time?** Defaults are your current user, hostname, and checkout.
> Optionally copy `env.example` to ignored `env` to override these. The installer
> accepts managed package replacements automatically; `--dry-run` previews
> without changes. Sudo authentication still uses the normal system prompt.

## What gets installed

### Shell & Terminal
- **Alacritty** — GPU-accelerated terminal (MesloLGS NF, 14px, maximized)
- **Zsh** — Oh My Zsh + Powerlevel10k (lean prompt, instant)
- **Tmux** — multiplexer with 8 plugins, `C-a` prefix, dev session, command palette

Alacritty is selected through GNOME defaults, Ctrl+Alt+T, Nautilus, and
`~/.config/xdg-terminals.list`. Legacy terminal shortcuts and dock entries are
migrated while unrelated settings are preserved. Previous terminal configs are
backed up privately; full install/update removes the old terminal package after
Alacritty is installed. Clipboard Indicator's paste shortcut remains supported.

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

### 5 coding agents
[See AGENTS.md](AGENTS.md) for installation and private configuration conventions.

| Agent | Install | Vendor |
|-------|---------|--------|
| `dsh web` (`@deepseek-ai/dsh`) | isolated user npm prefix | DeepSeek |
| `codex` (`@openai/codex`) | npm global | OpenAI |
| `claude-code` | AUR | Anthropic |
| `opencode` | AUR | OpenCode |
| `pi` (`@earendil-works/pi-coding-agent`) | npm global | Earendil |

An existing native installation of a coding agent or Bun is reused rather than
adding a competing npm installation. Those native installations keep their own
update mechanism. Missing tools are installed through the listed managed channel.

DeepSeek Harness uses the [official Linux npm package](https://github.com/deepseek-ai/deepseek-harness).
Run `dsh web` for its local browser UI (default `127.0.0.1:3080`). Installation
does not start a server. This is a developer preview and can have breaking changes.
The full installer/updater resolves npm `latest` and installs into
`~/.local/share/core-dotfiles/dsh`, skipping an already installed matching version.
Node.js >=24.9 is required. To update only DSH, run
`python3 scripts/install-dsh.py`. Config-only deployment installs its launcher;
the runtime still needs this command or the full installer.
Configure providers through Models in the UI. DSH's private credential store is
`${DSH_HOME:-~/.dsh}/.credentials.yaml`; keep it outside Git with mode `0600`.
DSH shares managed skills under `~/.agents/skills/` and reads private global
instructions from `~/.dsh/AGENTS.md`. Codewhale is no longer managed; existing
private Codewhale data is preserved.

### Agent skills

Installation and updates manage selected skills through the official Skills CLI.
Impeccable follows its latest stable skill release. Public custom skills live in
`skills/custom/<name>/SKILL.md`; private skills stay outside Git and can be listed
in private `~/.config/core-dotfiles/skills.local.json`. Existing unlisted skills
are preserved, and local edits to managed skills block replacement.

Use `dotfiles-skills check` to check versions and `dotfiles-skills sync` to update.
See [skills/README.md](skills/README.md) for sources, discovery paths, backups, and
custom-skill setup. Config-only deployment also refreshes skills; set
`SKIP_AGENT_SKILLS=true` to skip that step. Full bootstrap installs the required
Node.js; config-only installs need Node.js >=22.20 and npx already available.

The custom DeHashed skill is included with its stdlib client and references.
Its API key, account state, cache, budget ledger, and exported breach data stay
outside Git. Configure each device privately with
`python3 ~/.agents/skills/dehashed/scripts/dehashed.py init` when needed;
installation neither copies credentials nor performs DeHashed API calls.

The [mail](skills/custom/mail/SKILL.md) and [5sim](skills/custom/5sim/SKILL.md)
skills include their command-line helpers. Each device uses its own credentials.
If a device already has OpenCode copies, see the [migration steps](skills/custom/README.md#migrate-an-existing-opencode-copy).

The [security-tooling skill](skills/custom/security-tooling/SKILL.md) checks local
tool syntax and reviews supplied security evidence. Full bootstrap installs its
analysis tools. Each device builds its own help cache on first use.
See the [Pi migration notes](skills/custom/README.md#migrate-an-existing-pi-copy) for an existing local copy.

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
| `Ctrl+Alt+T` | Terminal (alacritty) |
| `Ctrl+Shift+A` | Screenshot (flameshot) |
| `Ctrl+F9` | Open Clipboard Indicator (extension default) |

The full installer uses Clipboard Indicator for text and image history. On systems
with Clipboard History installed, its replacement is accepted automatically.
GNOME may need a new login to load a newly installed extension.

### Custom tooling
- `expose` — serve files/dirs over HTTP with request inspection; password-protected operator UI, browser consoles, SOCKS proxy, and inbound callbacks (full source in `expose/`)
- `expose-online` — publish `expose` through `singlecore.dev` with an authenticated session and a resilient SSH tunnel
- `flameshot-gui` — screenshot → clipboard in one shot
- Nautilus right-click → **Open in Terminal** opens Alacritty (via `nautilus-open-any-terminal`)

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
├── alacritty/    → ~/.config/alacritty/, xdg-terminals.list
├── tmux/         → ~/.tmux.conf, dev-session, command-palette
├── git/          → ~/.gitconfig           (template)
├── fonts/        → ~/.local/share/fonts/  (MesloLGS NF ×4)
├── local-bin/    → ~/.local/bin/          (expose, burpsuitepro, flameshot-gui)
├── flameshot/    → ~/.config/flameshot/
│
├── expose/       → Full source for the expose HTTP tool
├── systemd/      → Default committed sync; optional update-check user timer
├── scripts/      → Deployment, credential checks, GNOME settings, VM manager
├── skills/       → Managed skill sources and public custom skills
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
./update.sh --configs-only      # Redeploy local configs/tools and refresh skills
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

The full installer has no bootstrap yes/no confirmation (`--yes` remains accepted
for compatibility). Pacman/yay accept conflicting-package replacements, including
OpenCode beta → managed OpenCode and GNU netcat → OpenBSD netcat. Signature and
dependency checks remain enabled. AUR packages run as separate transactions, so a
failed build does not hold back other tools. Failures remain visible in the final
summary and produce a nonzero exit status.

NetExec uses the [upstream pipx flow](https://www.netexec.wiki/getting-started/installation/installation-on-unix)
with uv-managed Python 3.12, independently of Arch's system Python. Its upstream
main branch is resolved to a full commit; unchanged installs are skipped. This
avoids the obsolete Certipy dependency reference in the old AUR release. The old
AUR NetExec package is removed only after the isolated replacement succeeds.

At the end, installer and updater reconcile known duplicate launchers, then run
`python3 scripts/verify-tools.py` in a fresh interactive Zsh login. It checks
managed package presence, executable commands, startup errors, and competing
executables on PATH. Startup output is captured privately in memory and never
forwarded. Non-CLI packages (fonts, themes, libraries) have no command to check.
Versioned Python/Node/JDK/Rust toolchains and identical expose copies are expected.
This checks discoverability, not GUI launch, network access, or service health.
Known legacy OpenCode, Claude, and pipx launchers are moved to private backups only
after their managed replacement exists. The unmanaged system Burp Pro wrapper is
also backed up and retired in favor of the repository's stowed launcher; its
optional JAR remains untouched. A standalone pipx Impacket installation
is removed when the managed Arch package exists; isolated dependencies inside
other tools are preserved. Native authentication and application data stay private.

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

### Checking private configuration

Keep credentials outside this checkout, including ignored files: shell exports
belong in `~/.config/core-dotfiles/secrets.zsh`, the expose password in
`~/.config/expose/online.env`, and the DeHashed key in `~/.config/dehashed/api_key`.
Use mode `0700` for private config directories and `0600` for their files.
Codex and Claude Code use their native logins. The shell credential check
covers `DEEPSEEK_API_KEY` and `GITHUB_PERSONAL_ACCESS_TOKEN`.

```bash
./check.sh                          # Read-only local presence/permission check
./check.sh --require expose,dehashed,ssh,dsh
./check.sh --strict                 # Warnings also cause failure
```

Missing optional credentials are skipped; an unsafe existing file fails even
when optional. `--require shell` requires a nonempty private secrets file, not
every provider key. Exit codes are 0 for success, 1 for failures (or strict
warnings), and 2 for invalid arguments. Values and private paths are never
printed. The checker does not source config, change permissions, contact APIs,
or validate logins. It recognizes simple literal shell assignments; computed
values need manual review. SSH checks metadata and agent-socket presence, not
loaded keys or remote authorization. DSH's managed store is checked for safe
permissions and nonempty file size; its provider records are not parsed.

## Local verification

```bash
bash tests/install-packages.sh
python3 tests/deployment.py       # 100 deployments in a disposable home
bash tests/online-config.sh
bash tests/quickemu.sh
python3 tests/gnome.py
python3 tests/secret-checks.py
python3 tests/sync.py             # Disposable local Git remotes; no network
python3 tests/skills.py           # Skill ownership, updates, rollback, 100 repeats
python3 tests/mail-5sim.py        # Offline mailbox and SMS order tests
node --test tests/security-tooling.mjs  # Offline help cache and evidence checks
python3 tests/dehashed.py         # Offline key handling and evidence isolation
python3 tests/check-config.py     # Read-only checks, permissions, no secret output
python3 tests/dsh.py              # Isolated official package installation/updates
python3 tests/netexec-install.py  # Python migration and unchanged-commit handling
python3 tests/tool-verification.py # Fresh login checks and duplicate cleanup
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
enabling them. To enable journal-only checks after reviewing the setup:

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

Perform complete system upgrades, read Arch news, and handle required
interventions. The installer/updater accept managed package replacements
automatically. Do not run unattended `pacman` or
AUR upgrades at boot. Running shell sessions remain on their existing server
build until you choose to restart it; they do not migrate across restarts.

## Automatic sync across devices

Use the same tracked branch on every device (`main` is recommended; `dev_new`
also contains this setup). After reviewing and committing a change, `dotfiles-sync` pushes it through
the secret-checking hook. On another device it fetches and fast-forwards a clean
checkout. It never creates commits, stashes edits, merges divergent branches,
force-pushes, installs packages, runs sudo, or restarts expose. Conflicts and local
edits stop synchronization and write a journal entry without desktop notifications.
Fetched history is checked for credentials before it can reach linked configs.

```bash
./install.sh --configs-only
dotfiles-sync                     # Optional immediate foreground run
journalctl --user -u core-dotfiles-sync.service
```

Both full installation and config-only deployment enable the sync timer by
default. It starts immediately when the user manager is available, otherwise at
the next login. Repeated deployment keeps one timer enabled. The installed command
finds its own checkout, including custom clone locations; `DOTFILES_DIR` overrides it.

The timer runs after login and every five minutes. It does not create commits.
An unchanged checkout creates no commit and pushes nothing. A working SSH key/agent with
GitHub write access is required on each device; authentication never prompts in
the background. Zsh imports its unlocked agent socket into the user service
environment. If login starts a different agent, open a terminal and unlock your
GitHub key; the next timer run retries. No key or password is copied into Git.
Run `git add` and `git commit` yourself after reviewing edits.
To pause syncing: `systemctl --user disable --now core-dotfiles-sync.timer`.
To deploy without activating it, use `DOTFILES_SYNC_ENABLE=false ./install.sh`
(or the same prefix with `--configs-only` / `./update.sh`). This preserves an
already enabled timer; disable it explicitly when you want to pause syncing.
The journal-only update-check timer above is an alternative; it can remain
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
