---
description: "Use when writing, editing, or reviewing bash/sh scripts in this security toolkit. Covers strict mode, validation, error handling, color output, section headers, and cleanup patterns."
applyTo: "src/**/*.sh, build.sh"
---

# Bash Security Toolkit Guidelines

## Script Header

Start with strict mode (no `-e` — we handle errors manually):

```bash
#!/usr/bin/env bash
set -uo pipefail
```

## Section Comments

Use Unicode box-drawing for visual separation:

```bash
# ── Section Name ────────────────────────────────────────────────────────────
```

## Naming Conventions

| Type | Style | Example |
|------|-------|---------|
| Global/env vars | `UPPER_SNAKE` | `VERSION`, `TARGET`, `RESP_CODE` |
| Local vars | `lower_snake` | `local addr`, `local mime` |
| Internal vars | `_PREFIX` | `_TMPFILES`, `_CLEANUP_DONE` |
| Functions | `lower_snake` | `get_local_ip()`, `mode_label()` |

## Color Output

Auto-detect terminal capabilities:

```bash
if [[ -t 2 ]]; then
  B=$'\e[1m' D=$'\e[2m' R=$'\e[0m' U=$'\e[4m'
  RED=$'\e[31m' GRN=$'\e[32m' YLW=$'\e[33m' BLU=$'\e[34m' CYN=$'\e[36m'
else
  B="" D="" R="" U="" RED="" GRN="" YLW="" BLU="" CYN=""
fi
```

## Standard Helpers

```bash
log()  { printf "%s%s%s  %s\n" "$D" "$(date '+%H:%M:%S')" "$R" "$*" >&2; }
die()  { printf "%s%serror:%s %s\n" "$B" "$RED" "$R" "$*" >&2; exit 1; }
```

## Input Validation

Validate early, fail fast with `die()`:

```bash
[[ "$PORT" =~ ^[0-9]+$ ]] && (( PORT >= 1 && PORT <= 65535 )) \
  || die "Invalid port: $PORT (must be 1–65535)"
[[ -n "$BIND" && ! "$BIND" =~ ^[0-9a-fA-F.:]+$ ]] && die "Invalid bind address: $BIND"
```

## Cleanup & Temp Files

Track temp files; cleanup on exit:

```bash
_TMPFILES=()
_mktmp() { local f; f=$(mktemp "$1"); _TMPFILES+=("$f"); echo "$f"; }

cleanup() {
  [[ -n "$_CLEANUP_DONE" ]] && return; _CLEANUP_DONE=1
  for f in "${_TMPFILES[@]+"${_TMPFILES[@]}"}"; do rm -f "$f" 2>/dev/null; done
}
trap 'cleanup; exit 0' INT TERM
trap cleanup EXIT
```

## Usage Function

Include:
- Tool name + version in bold
- USAGE section with modes
- OPTIONS with defaults
- EXAMPLES section

```bash
usage() {
  cat >&2 <<EOF
${B}toolname${R} v${VERSION}  —  short description

${B}USAGE${R}
    toolname [opts] ${CYN}<arg>${R}

${B}OPTIONS${R}
    -p, --port ${CYN}<port>${R}   Listen port (default: ${PORT})

${B}EXAMPLES${R}
    toolname "hello"
    toolname -p 9000 -f ./file.txt
EOF
}
```

## Testing Patterns

1. **Validate all inputs** before any action
2. **Check dependencies** with `command -v <cmd> &>/dev/null`
3. **Resource checks** (port in use, file exists) with interactive prompts
4. **Graceful degradation** with fallback methods (see `get_local_ip`)

## Security Considerations

- Always quote variables: `"$var"` not `$var`
- Validate external input (ports, filenames, auth strings)
- Use `[[ ]]` over `[ ]` for conditionals
- Redirect errors to stderr: `>&2`
- Clean up sensitive temp files on exit

## Operator and credential boundaries

Operator subcommands dispatch before normal server parsing. Preserve original
stdin across the embedded Python heredoc so `proxychains COMMAND` receives the
caller's input. Detach must restore terminal settings without terminating the
connector, proxy streams, or server. Never log tickets, session cookies, bearer
tokens, operator keys, or password values, including in verbose output.

Private instance descriptors and proxy configuration use owner-only directories
and atomic mode-0600 files. Console operator actions always authenticate, even
when ordinary file sharing is public. Connector tokens authorize only their own
agent session; enrollment tickets never authorize operator actions. Remote CLI
and connector origins require verified HTTPS. SOCKS listeners are loopback-only.

Build output uses atomic replacement and explicit mode 0755; preserve the last
good build on failure and avoid rewriting unchanged files. Build temporary files
are managed by build.sh's own cleanup trap rather than runtime helpers.
