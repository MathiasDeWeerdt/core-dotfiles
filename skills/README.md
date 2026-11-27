# Managed agent skills

`./install.sh`, `./install.sh --configs-only`, and `./update.sh` check and install
the explicitly managed skills. `./update.sh --configs-only` also refreshes skills.
`SKIP_AGENT_SKILLS=true` skips this step. Dry runs perform no network requests or
writes. Full installation supplies Node.js through nvm; config-only installation
needs Node.js >=22.20 and `npx` already available.

```bash
dotfiles-skills check       # Resolve upstream versions without installing
dotfiles-skills sync        # Install or update managed skills
dotfiles-skills --dry-run   # Preview without network or writes
```

## Upstream skills

[manifest.json](manifest.json) lists trusted sources, selected agents, and a pinned
version of Vercel's official [Skills CLI](https://github.com/vercel-labs/skills).
Only listed skills are installed. GitHub sources choose either `ref` (branch, tag,
or full commit) or `release_prefix` (latest non-draft, non-prerelease matching tag).
The selected ref is resolved to a full commit before installation. This downloads
current skill content into user storage; upstream files are not vendored into this
public repository. Changing an existing managed source is blocked; use a distinct
skill name for a different source.

Impeccable follows stable `skill-v*` releases, independently of its engine
releases. This uses its documented [shared-skill install flow](https://impeccable.style/docs/).
Its tailored installer/plugin is a separate flow with additional native
integrations; this setup installs the shared skill, references, and launchers.
The launcher manages its checksum-verified engine when the skill is actually used.
No Impeccable commands, detector hooks, or project initialization run at install.

The pinned CLI installs shared files under `~/.agents/skills/`. Codex, Pi,
OpenCode, and Copilot use its shared global discovery flow; the CLI deliberately
avoids redundant agent-specific copies. Claude Code gets its native global
discovery link, respecting `CLAUDE_CONFIG_DIR`. Private manifest/state paths
respect XDG overrides. Codewhale
has no configured skill integration here; do not invent an unsupported loader.
Reload your agent after an update; newly installed skills are available next turn.

## Custom skills

Public skills under `custom/<name>/SKILL.md` are discovered automatically and use
the same supported installation flow. See [custom/README.md](custom/README.md).
The package must be self-contained; symlinks are rejected rather than followed
into private files. Existing unlisted user skills and built-in/system skills are
left alone.

Private skills can be registered in `~/.config/core-dotfiles/skills.local.json`
(or the equivalent under `XDG_CONFIG_HOME`), kept outside Git:

```json
{
  "skills": [
    {"name": "private-workflow", "type": "local", "path": "/absolute/private/skill-folder"}
  ]
}
```

The referenced folder needs matching SKILL.md frontmatter. Its contents stay
outside the public repo. Names must be unique across public and private sources.
Keep source folders separate from installed `~/.agents/skills/` packages; a source
that contains its own destination or would copy onto itself is rejected.
Private GitHub sources can also be listed here; Git/gh handle authentication
through their normal private credentials. Never embed credentials in a URL.

## Ownership, updates, and recovery

Per-machine revision records, content hashes, and backups live under private
`~/.local/state/core-dotfiles/skills/` (`XDG_STATE_HOME` is respected). An unchanged
revision with intact agent links does not reinstall or rewrite files. A managed
skill with local edits blocks replacement: save those edits as a distinct custom
skill instead of modifying an upstream package in place.

An existing Skills CLI installation from the same GitHub source can be adopted.
Its previous directory is backed up privately before replacement, including any
local edits made before adoption. Unrecognized existing skills, unrelated agent
copies, and foreign symlinks are preserved and block a conflicting installation.
Backups never enter this repository. Removing an entry does not delete an
installed skill automatically; use the Skills CLI's removal command deliberately.

Use `dotfiles-skills` to update managed packages. Its CLI lock entry records the
resolved commit; it is not a floating upstream ref. Updating or editing a managed
package through another installer changes its recorded content and will block the
next managed refresh. Backups are addressed by content hash, so retrying a failed
update does not create duplicate copies of the same prior content.

CLI lifecycle scripts and telemetry are disabled. The source allowlist is a trust
decision: skills contain instructions and can include scripts an agent may run
later. Secret checks do not prove upstream code safe. The Git sync timer only
synchronizes reviewed dotfiles commits; it does not run skill updates in the
background. Run the installer/updater or `dotfiles-skills sync` to refresh them.
