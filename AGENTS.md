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
- Conflicting configs are backed up outside Git under
  `~/.local/state/core-dotfiles/backups/`.

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
| Codewhale | `codewhale` | npm: `codewhale` (optional global wiring when installed) |

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
| Codewhale | `~/.codewhale/instructions.md` when installed |

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
