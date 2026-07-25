# AGENTS.md — expose

Guidance for coding agents working on this repository. For user-facing docs see
[README.md](README.md). More conventions live in
[.github/instructions/](.github/instructions/) (`project-structure`,
`bash-security-toolkit`) — follow them.

## What this is

`expose` (v2.0) is a single-file bash CLI that serves text, files, or
directories over HTTP(S) on a LAN: quick sharing, webhook catching, request
inspection, and pentest payloads. All development happens in `src/`; the
executable `dist/expose` is **build output — never edit it directly**.

## Architecture

### Build

`build.sh` concatenates sources in a fixed order into one self-contained bash
script (`dist/expose`, ~100 KB), resolves asset-injection markers with inline
Python, and copies `src/expose-online.sh` to `dist/expose-online`:

```
shebang + set -uo pipefail
src/globals.sh     → variables/defaults (VERSION, PORT, MODE, …)
src/lib/colors.sh  → terminal color detection (no color when stderr isn't a tty)
src/lib/helpers.sh → log, die, _mktmp, cleanup, INT/TERM/EXIT traps
src/lib/usage.sh   → usage() heredoc
src/lib/args.sh    → top-level while/case argument parsing (not a function!)
src/lib/validate.sh→ input validation, TLS cert generation, port-in-use prompt
src/lib/database.sh→ read-only SQLite/fzf request-history browser
src/lib/banner.sh  → startup banner + mode_label()
src/lib/serve.sh   → serve_text/file/dir/redirect/payload/websocket, do_replay
```

Injection markers (resolved by `build.sh` via `str.replace`, verbatim,
no escaping needed):

- `@@INJECT:assets/<path>@@` inside heredocs in `serve.sh` — embeds
  `server.py`, `websocket.py`, `payloads.sh`, `web/upload.html`,
  `web/me.html`, `web/logo.svg`, and `web/fp.js`
- `@@CSS@@` / `@@JS@@` / `@@FPJS@@` inside `src/assets/web/upload.html` — inlines
  the stylesheet, client JS, and fingerprint script into a single HTML page
- `web/fp.js` is also inlined into `/me` at runtime via the `EXPOSE_FP_JS` env
  var (tempfile path exported by `serve.sh`). It collects browser/device
  signals on every page and reports them to `POST /fp`, which appends to the
  `fingerprints` table in `EXPOSE_DB` (`/fp` is on the internal-API skip-list)

### Runtime dispatch

`args.sh` sets `MODE` (text | file | dir | stdin→text | catch | redirect |
payload | websocket | replay); `serve.sh`'s final `case` dispatches:

- **text / file / dir / catch / redirect / payload** → the unified
  `src/assets/server.py` backend, embedded into the generated executable and
  run with Python's threaded HTTP server. Payload mode resolves a template
  from `src/assets/payloads.sh` and exposes it as content.
- **websocket** → `python3 src/assets/websocket.py` — dependency-free echo
  server (raw socket, manual frame parsing).
- **replay** → inline Python in `serve.sh` (`do_replay`).

### The env-var contract

The parent process passes all configuration to `server.py` through `EXPOSE_*`
environment variables, exported by `_export_common()` in `serve.sh`
(`EXPOSE_CONTENT`, `EXPOSE_LEN`, `EXPOSE_MIME`, `EXPOSE_AUTH`, `EXPOSE_ALLOW`,
`EXPOSE_LOGFILE`, `EXPOSE_COUNTER`, `EXPOSE_ONCE`, `EXPOSE_DB`,
`EXPOSE_FP_JS`, …).
`EXPOSE_DB` points at `~/.expose/requests.db` — a persistent SQLite request
log (schema created at startup in `serve.sh`, WAL mode, inserts happen in the
same code paths as the JSON log, so the internal-API skip-list applies). **When adding an option: add the global
in `globals.sh`, parse it in `args.sh`, validate in `validate.sh`, show it in
`banner.sh` and `usage.sh`, export it in `_export_common()`, consume it in the
handler.**

### Shared HTTP surface

`server.py` implements the shared built-in routes: `/` + `/upload` (upload
UI), `POST /upload` (multipart → `~/Downloads/expose`),
`/upload/files[/<name>]`, `/me`, `/log?since=n` + `/log/clear`, `/meta`,
`/chat`, plus `/content` outside directory mode. The request log is JSON,
capped at 500 entries; chat is capped at 200 messages.

## Conventions

- Bash: `#!/usr/bin/env bash` + `set -uo pipefail` (no `-e`; errors handled
  manually via `die`).
- Section headers: `# ── Name ───…` (Unicode box-drawing).
- Globals/env `UPPER_SNAKE`, locals `lower_snake` (`local` keyword).
- Temp files only via `_mktmp` (registers for cleanup on EXIT).
- `make build` → `dist/expose` and `dist/expose-online`; install target
  `/usr/local/bin`;
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

## Architecture note

- WebSocket mode remains a separate, dependency-free socket server rather than
  part of the HTTP backend.
