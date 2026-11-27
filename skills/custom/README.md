# Custom skills

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
