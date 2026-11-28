# Custom skills

| Skill | Purpose |
| --- | --- |
| [mail](mail/SKILL.md) | Read a private IMAP inbox and send test mail to your own address. |
| [5sim](5sim/SKILL.md) | Compare SMS activation prices and manage an order. |
| [dehashed](dehashed/SKILL.md) | Query DeHashed with a private API key and credit budget. |
| [security-tooling](security-tooling/SKILL.md) | Verify installed tool syntax and review supplied security evidence. |

Create `skills/custom/<name>/SKILL.md` with Agent Skills YAML frontmatter:

```markdown
---
name: example-workflow
description: Explain when an agent should use this workflow.
---

Write the instructions here. Put optional scripts and references beside this file.
```

The folder and frontmatter name should match. Install with `dotfiles-skills sync`
or the normal installer/updater. The Skills CLI validates and copies the skill to
the shared global directory and links supported agent discovery paths. Repeated
deployment skips unchanged content. Runtime scripts are not executed at install.

These files are **public**. Keep passwords, tokens, private keys, customer context,
and machine-specific instructions outside this repo. Existing private/global
skills are not automatically imported. For private custom skills, use the private
manifest described in [the skill management guide](../README.md).

### Migrate an existing OpenCode copy

If OpenCode already has its own `mail` or `5sim` directory, review the managed
version above before switching. The skill manager stops on a conflicting
agent-specific copy. Move the old skill instructions to a private backup,
then run the normal sync. The bundled helpers can read the existing private
service configs.

```sh
(
set -e
old="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/skills"
backups="${XDG_STATE_HOME:-$HOME/.local/state}/core-dotfiles/backups"
mkdir -p -m 700 "$backups"
backup=$(mktemp -d "$backups/opencode-skills.XXXXXXXX")
for name in mail 5sim; do
  if [ -d "$old/$name" ] && [ ! -L "$old/$name" ]; then
    mv -- "$old/$name" "$backup/"
  fi
done
dotfiles-skills sync
)
```

### Migrate an existing Pi copy

A standalone `~/.pi/agent/skills/security-tooling` directory will block managed
installation. After reviewing the shared skill, move the standalone directory
to a private backup outside Pi's discovery path and run `dotfiles-skills sync`.
Pi can then discover the shared version under `~/.agents/skills/`. The full
installer installs its tool packages. Config-only deployment installs the skill.
