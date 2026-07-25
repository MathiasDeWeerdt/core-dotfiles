# AGENTS.md — expose

Guidance for coding agents working on this repository. For user-facing docs see
[README.md](README.md). More conventions live in
[.github/instructions/](.github/instructions/) (`project-structure`,
`bash-security-toolkit`) — follow them.

## What this is

`expose` (v1.3) is a single-file bash CLI that serves text, files, or
directories over HTTP(S) on a LAN: quick sharing, webhook catching, request
inspection, and pentest payloads. All development happens in `src/`; the
executable `dist/expose` is **build output — never edit it directly**.

## Architecture

### Build

`build.sh` concatenates sources in a fixed order into one self-contained bash
script (`dist/expose`, ~100 KB), resolving asset-injection markers with inline
Python:

```
shebang + set -uo pipefail
src/globals.sh     → variables/defaults (VERSION, PORT, MODE, …)
src/lib/colors.sh  → terminal color detection (no color when stderr isn't a tty)
src/lib/helpers.sh → log, die, _mktmp, cleanup, INT/TERM/EXIT traps
src/lib/usage.sh   → usage() heredoc
src/lib/args.sh    → top-level while/case argument parsing (not a function!)
src/lib/validate.sh→ input validation, TLS cert generation, port-in-use prompt
src/lib/banner.sh  → startup banner + mode_label()
src/lib/serve.sh   → serve_text/file/dir/redirect/payload/websocket, do_replay
```

Injection markers (resolved by `build.sh` via `str.replace`, verbatim,
no escaping needed):

- `@@INJECT:assets/<path>@@` inside heredocs in `serve.sh` — embeds
  `handler.sh`, `upload.py`, `server.py`, `websocket.py`, `payloads.sh`,
  `web/upload.html`
- `@@CSS@@` / `@@JS@@` inside `src/assets/web/upload.html` — inlines the
  stylesheet and client JS into a single HTML page

### Runtime dispatch

`args.sh` sets `MODE` (text | file | dir | stdin→text | catch | redirect |
payload | websocket | replay); `serve.sh`'s final `case` dispatches:

- **text / file / catch / redirect / payload** → `socat TCP-LISTEN:...,fork`
  (or `OPENSSL-LISTEN` with `--tls`) running `src/assets/handler.sh` (POSIX sh)
  via `SYSTEM:` per connection. Payload mode resolves a template from
  `src/assets/payloads.sh` then serves it as text.
- **dir** → `python3 src/assets/server.py` — `http.server` subclass serving the
  cwd, with JSON APIs (`/ls`, `/log`, `/meta`, …).
- **websocket** → `python3 src/assets/websocket.py` — dependency-free echo
  server (raw socket, manual frame parsing).
- **replay** → inline Python in `serve.sh` (`do_replay`).

### The env-var contract

The parent process passes all configuration to `handler.sh` through `EXPOSE_*`
environment variables, exported by `_export_common()` in `serve.sh`
(`EXPOSE_CONTENT`, `EXPOSE_LEN`, `EXPOSE_MIME`, `EXPOSE_AUTH`, `EXPOSE_ALLOW`,
`EXPOSE_LOGFILE`, `EXPOSE_COUNTER`, `EXPOSE_ONCE`, …). `server.py` and
`upload.py` read the same convention. **When adding an option: add the global
in `globals.sh`, parse it in `args.sh`, validate in `validate.sh`, show it in
`banner.sh` and `usage.sh`, export it in `_export_common()`, consume it in the
handler.**

### Shared HTTP surface

`handler.sh` (socat modes) and `server.py` (dir mode) implement the same
built-in routes: `/` + `/upload` (upload UI), `POST /upload` (multipart →
`~/Downloads/expose`, via `upload.py` in socat modes), `/upload/files[/<name>]`,
`/me`, `/log?since=n` + `/log/clear`, `/meta`, `/chat`, plus `/content` (socat
modes only). Keep both implementations in sync when touching routes. The
request log is JSON, capped at 500 entries; chat is capped at 200 messages.

## Conventions

- Bash: `#!/usr/bin/env bash` + `set -uo pipefail` (no `-e`; errors handled
  manually via `die`). `handler.sh` is **POSIX sh** — it runs under socat.
- Section headers: `# ── Name ───…` (Unicode box-drawing).
- Globals/env `UPPER_SNAKE`, locals `lower_snake` (`local` keyword).
- Temp files only via `_mktmp` (registers for cleanup on EXIT).
- `make build` → `dist/expose`; install target `/usr/local/bin/expose`;
  `dist/` is gitignored and never committed.
- `old_expose` is the legacy v1.1 monolith kept for reference only — not part
  of the build; don't modify it.

## Testing a change

```bash
make build
./dist/expose -p 18090 "hi" &        # then curl it
curl -s localhost:18090/content
curl -s -F "files=@/etc/hostname" localhost:18090/upload
kill %1
```

Note the port-in-use check in `validate.sh` prompts on `/dev/tty` — always use a
free test port and a non-interactive shell.

## Known issues (as of v1.3)

- `serve_websocket()` calls `info`, which doesn't exist (only `log`/`die`) —
  prints "command not found" before the Python server starts.
- `do_replay()` in `serve.sh` is broken: the heredoc feeds the first `python3`
  without argv (`IndexError` on `sys.argv[1]`), and the follow-up
  `python3 - "$TARGET"` receives no script. Verified failing on v1.3.
- `mode_label()` in `banner.sh` only covers text/catch/file/dir — the Mode
  line is blank for redirect/payload/websocket/replay.
- The `--collect` EXIT trap in `serve.sh` replaces the `cleanup` EXIT trap
  from `helpers.sh`, so cleanup is skipped on plain exit (INT/TERM still fine).

Fix these deliberately if asked; don't "drive-by" repair them while doing
unrelated work.
