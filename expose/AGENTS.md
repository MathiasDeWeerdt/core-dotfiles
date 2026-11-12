# AGENTS.md — expose

Guidance for coding agents working on this repository. For user-facing docs see
[README.md](README.md). More conventions live in
[.github/instructions/](.github/instructions/) (`project-structure`,
`bash-security-toolkit`) — follow them.

## What this is

`expose` (v2.0) is a single-file bash CLI that serves text, files, or
directories over HTTP on a LAN: quick sharing, webhook catching, request
inspection, and pentest payloads. All development happens in `src/`; the
executable `dist/expose` is **build output — never edit it directly**.

## Architecture

### Build

`build.sh` concatenates sources in a fixed order into one self-contained bash
script (`dist/expose`, ~700 KB), resolves asset-injection markers with inline
Python, and copies `src/expose-online.sh` to `dist/expose-online`:

```
shebang + set -uo pipefail
src/globals.sh     → variables/defaults (VERSION, PORT, MODE, …)
src/lib/colors.sh  → terminal color detection (no color when stderr isn't a tty)
src/lib/helpers.sh → log, die, _mktmp, cleanup, INT/TERM/EXIT traps
src/lib/usage.sh   → usage() heredoc
src/lib/args.sh    → top-level while/case argument parsing (not a function!)
src/lib/validate.sh→ input validation and port-in-use prompt
src/lib/banner.sh  → startup banner + mode_label()
src/lib/serve.sh   → serve text/file/dir/redirect/payload modes
```

Injection markers (resolved by `build.sh` via `str.replace`, verbatim,
no escaping needed):

- `@@INJECT:assets/<path>@@` inside heredocs in `serve.sh` — embeds
  `server.py`, `consoles.py`, `winenum.ps1`, `payloads.sh`, `web/upload.html`,
  `web/me.html`, `web/logo.svg`, and `web/fp.js`
- `@@CSS@@` / `@@JS@@` / `@@TERM_CSS@@` / `@@TERM_JS@@` / `@@FIT_JS@@` /
  `@@CONSOLE_JS@@` / `@@FPJS@@` inside `src/assets/web/upload.html` — inlines
  the stylesheet, client scripts, terminal vendor code, console UI, and
  fingerprint script into a single HTML page
- `web/fp.js` is also inlined into `/me` at runtime via the `EXPOSE_FP_JS` env
  var (tempfile path exported by `serve.sh`). It collects browser/device
  signals for display in the browser.

### Runtime dispatch

`args.sh` sets `MODE` (text | file | dir | stdin→text | catch | redirect |
payload); `serve.sh`'s final `case` dispatches:

- **text / file / dir / catch / redirect / payload** → the unified
  `src/assets/server.py` backend, embedded into the generated executable and
  run with Python's threaded HTTP server. Payload mode resolves a template
  from `src/assets/payloads.sh` and exposes it as content.

### The env-var contract

The parent process passes all configuration to `server.py` through `EXPOSE_*`
environment variables, exported by `_export_common()` in `serve.sh`
(`EXPOSE_CONTENT`, `EXPOSE_LEN`, `EXPOSE_MIME`, `EXPOSE_LOGFILE`,
`EXPOSE_FP_JS`, …). `EXPOSE_LOGFILE` points at
`~/.expose/requests.json`, a persistent JSON request log capped at 500 entries.
`EXPOSE_PROXY` (for example `127.0.0.1:1080`) starts the SOCKS5 listener in the
same Python process; it only works when `EXPOSE_CONSOLES=1`.
`EXPOSE_AUTH_PASSWORD` enables the login gate. Connector routes (`/lin`,
`/mac`, `/win`, `/console/client/*`, `/console/register`, `/console/agent/*`)
and `/.expose-health` are exempt because they require tickets or bearer
tokens; all other routes need the session cookie. `expose-online` sets the
password by default. New routes are protected by default — only extend the
exemption list for traffic that authenticates itself with a ticket or token.
**When adding an option: add the global
in `globals.sh`, parse it in `args.sh`, validate in `validate.sh`, show it in
`banner.sh` and `usage.sh`, export it in `_export_common()`, consume it in the
handler.**

### Shared HTTP surface

`server.py` implements the shared built-in routes: `/` + `/upload` (upload
dashboard with sidebar navigation and live overview), `POST /upload`
(multipart → `~/Downloads/expose`),
`/upload/files[/<name>]`, `/me`, `/log?since=n` + `/log/clear`, `/meta`,
`/chat`, plus `/content` outside directory mode. The request log is JSON,
capped at 500 entries; chat is capped at 200 messages.

`src/assets/consoles.py` holds the console relay, the SOCKS5 proxy, and the
Windows enumeration ticket/upload bridge. Console sessions long-poll
`/console/agent/<id>/input`; proxy streams use
`/console/agent/<id>/net` plus per-stream `status`, `data`, and `close`
endpoints. Inbound callbacks add `listen`/`unlisten` events, a connector
`/callback/<id>/state` report, and `/net/<id>/inbound` for accepted connections.
The Go connector (`src/connector/`) dials targets or accepts callback
connections from the endpoint and pumps bytes over those HTTP endpoints. Keep
per-session queues bounded.

`winenum.ps1` is served at `/console/winenum.ps1?ticket=…`. The ticket comes
from the authenticated `/console/winenum/ticket` route, lasts one hour, and is
also accepted by `POST /upload?ticket=…` so the endpoint can upload its report
without a browser session. Third-party tools are staged by the operator in
`EXPOSE_TOOLS_DIR` (default `~/.local/share/expose/tools`), listed at
`GET /console/tools`, downloaded at `/console/tool/<name>?ticket=…`, and run by
`toolrunner.ps1` (winPEAS, Seatbelt, PrivescCheck, SharpHound). Keep ticket
values out of logs; the logger redacts `ticket=…`. Tool uploads bypass the
64 KB console body cache and stream to disk.

### Reconnection

Do not turn a network error into a session close.

- The connector retries terminal input/output and network relay requests with
  exponential backoff (1 s → 60 s) until the context ends. Only 401/403/410 or a
  dead PTY are fatal.
- `ConsoleService` keeps sessions for 24 hours and does not flip `connected` on
  inactivity. `stale` is presentation-only. Explicit `exit`, `close`, or
  `remove` set `connected=False`.
- Registration is idempotent for ten minutes when the connector supplies a
  nonce; keep this behavior so a lost registration response can be retried.
- `expose-online` retries the SSH tunnel forever with backoff and binds the
  reverse port to `127.0.0.1` by default.

### Operator output
`server.py` prints event lines, not every request:

- `internal_path()` hides UI polling and ticket routes from stderr and the JSON
  log; keep new polling routes there.
- `unique_hit()` deduplicates external hits for 60 seconds.
- `event()` formats `time  ip  KIND  message`. Login, connector, SOCKS, and
  callback transitions use it.
- Real client IPs come from `X-Real-IP`, then the last `X-Forwarded-For`
  entry, only when the peer is loopback. Keep the JSON log's `peer` field for
  tunnel debugging.

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
