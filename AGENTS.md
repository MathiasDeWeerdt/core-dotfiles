# Repository instructions

Read `~/.memory.md` and `~/.memory.local.md` when present. Repository instructions
and explicit user requests take precedence over general preferences.

This is a **public** dotfiles repository. Never introduce passwords, API tokens,
private keys, customer details, or private machine/network context. Do not copy
live shell configs or global agent memory into the repo. Keep credentials under
`~/.config/core-dotfiles/` or `~/.config/expose/`, outside Git, with mode `0600`.
Never use Stow `--adopt`: it can replace public configs with credential-bearing
host files. Do not print sensitive values in command output or review reports.

Preserve unrelated user edits. Never commit, rewrite Git history, or force-push
without explicit authorization. Run `python3 scripts/check-secrets.py` before
sharing changes. `--staged` checks index contents; `--history` checks all reachable
Git history and reports locations without values. Follow `expose/AGENTS.md` for
that tool's build and runtime conventions. Edit its sources, then rebuild.

## Installation and validation

- `./install.sh --dry-run`: read-only bootstrap preview.
- `./install.sh --configs-only`: deploy public configs, private memory references,
  and matching `/usr/local/bin/expose` and `expose-online` builds.
- `./update.sh`: update packages/runtimes/plugins, then use the same deployment.
- Existing private `~/.memory.md` is preserved, never stowed. `memory/.memory.md`
  is a public starter template used only when no private memory exists.
- `./check.sh` checks private credential presence and permissions without sourcing
  configuration, printing values, changing files, or authenticating to services.
  Use `--require expose,dehashed,ssh,dsh` to require those feature credentials.
- Conflicting configs are backed up outside Git under
  `~/.local/state/core-dotfiles/backups/`.
- Full bootstrap accepts package conflicts/replacements automatically. Reuse the
  shared `scripts/package-policy.sh`; `--noconfirm` alone rejects some conflicts.
  Keep package signatures and dependency validation enabled. Never pipe `yes`
  indiscriminately into package managers or run bootstrap to test its logic.
- NetExec uses upstream pipx with uv-managed Python 3.12, not the old AUR build.
  Full install/update ends with known-duplicate reconciliation and fresh Zsh CLI
  verification. Test these with `tests/netexec-install.py` and
  `tests/tool-verification.py` using disposable homes.

Validation: `bash tests/install-packages.sh`, `python3 tests/deployment.py`,
`python3 tests/internetshare.py` (system Flask package required), and
`make -C expose console-clients test`. The deployment test repeats real deployment
100 times in a disposable home. Never test bootstrap by reconfiguring the host.

## Coding agents

| Agent | Command | Installation |
|-------|---------|--------------|
| Codex | `codex` | npm: `@openai/codex` |
| Claude Code | `claude` | AUR: `claude-code` |
| OpenCode | `opencode` | AUR: `opencode-bin` |
| GitHub Copilot CLI | `copilot` | npm: `@github/copilot` |
| Pi | `pi` | npm: `@earendil-works/pi-coding-agent` |
| DeepSeek Harness | `dsh web` | official npm: `@deepseek-ai/dsh`, isolated user prefix |

Use each tool's native login or private configuration. Never add API keys here.
The retired `github/gh-copilot` extension is not the standalone Copilot CLI.
Provider configuration differs between agents; consult their current docs.

## Global instruction files

Deployment preserves custom instructions and adds one shared memory reference:

| Harness | Default user-global file |
|---------|--------------------------|
| Codex | `~/.codex/AGENTS.md` |
| Claude Code | `~/.claude/CLAUDE.md` (native memory import) |
| OpenCode | `~/.config/opencode/AGENTS.md` |
| Pi | `~/.pi/agent/AGENTS.md` |
| Copilot CLI | `~/.copilot/copilot-instructions.md` |
| DeepSeek Harness | `~/.dsh/AGENTS.md` (`DSH_HOME` respected) |

Standard harness directory overrides are respected. These private files and
harness-generated project memories are never synchronized back into this repo.
Edit global preferences in `~/.memory.md`; retain machine/customer details in
private memory. Project-specific instructions remain in each project's own files.

## Device synchronization

`dotfiles-sync` and its enabled-by-default user timer synchronize explicit, reviewed commits
on the configured upstream branch. They stop on dirty or diverged checkouts and
scan local and fetched history. Never add automatic commits, bypass secret hooks,
auto-stash, force-push, or run privileged package upgrades in this workflow.
Sync changes stowed configs immediately; installing rebuilt expose tools remains
an explicit `./update.sh --configs-only` operation. Test changes with
`python3 tests/sync.py` against disposable local remotes.
Deployment enables the timer for next login and starts it when the real user's
manager is available; never contact that manager from disposable-home tests.
`DOTFILES_SYNC_ENABLE=false` skips activation without disabling an existing timer.

After the authorized historical secret cleanup, other devices need fresh clones.
Never merge their old history back into cleaned branches. Private backups of old
history must remain outside this public repository with restricted permissions.

## Managed agent skills

Read `skills/README.md`. `skills/manifest.json` lists explicit upstream sources and
pins the official Skills CLI; GitHub refs/releases resolve to full commits before
installation. Public custom skills belong under `skills/custom/<name>/SKILL.md`.
Private custom sources belong in the private per-user skills.local.json manifest,
never imported into Git. Never copy global skill directories, built-in skills,
private skill state, or credential files into this public repository.

Deployment refreshes managed skills unless SKIP_AGENT_SKILLS=true. Local edits to
managed installs and conflicting user skills block replacement; preserve them as
separate custom skills. Existing matching Skills CLI installs can be adopted only
with a private backup. Use `python3 tests/skills.py` for isolated tests; deployment
tests must set SKIP_AGENT_SKILLS=true and never fetch into the workstation home.
The Git sync timer does not execute skill updates. Do not run newly fetched skill
scripts, hooks, or project initialization as an installation side effect.
