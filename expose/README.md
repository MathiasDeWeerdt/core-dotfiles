# expose

Serve text, files, or directories over HTTP from your terminal — a single-file
bash tool for quick sharing on a LAN, webhook catching, and pentest payloads.

Think `python3 -m http.server` combined with a request inspector: one command
gives you a web server with persistent request logging, file uploads (drag &
drop web UI), and built-in reverse-shell payloads.

**Version:** 2.0 · **Default port:** 9090 · **License:** personal toolkit

## Features

- **Serve anything** — a text string, a single file, stdin, or the current directory
- **Request inspection** — one-line or verbose logging (all headers, reverse DNS, parsed User-Agent)
- **Request catcher** (`--catch`) — dump full headers + body, webhook-tester style
- **Uploads** — every mode serves a drag & drop upload page; received files land in `~/Downloads/expose`
- **Themes** — dark + light UI; follows your OS theme automatically, manual override in the header
- **Device fingerprinting** — `/me` shows what the visitor's browser leaks: GPU, canvas fingerprint, timezone, screen, CPU/memory, storage APIs… plus a stable SHA-256 visitor id and copy-as-JSON
- **Smart request viewer** — request bodies are auto-decoded (JSON pretty-print, JWT header+payload, form-urlencoded) and credential-looking bodies are flagged with a red `creds` chip
- **CLI one-liners** — copy-ready commands per OS (Linux/macOS/Windows) for uploading files, posting to chat, and downloading shared content: curl, wget, nc, socat, python (stdlib + requests), httpie, PowerShell, certutil, bitsadmin
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
| `python3`  | HTTP serving, uploads, and request logging |
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
echo "secret" | expose -                # serve stdin
expose --catch                          # webhook catcher (dumps bodies)
expose --payload powershell-reverse     # serve a reverse-shell one-liner
expose --redirect https://evil.com      # 302 redirect everything
```

Stop with `Ctrl+C`. The startup banner shows the local and network URLs.

## Options

| Option | Description |
|--------|-------------|
| `-p, --port <port>` | Listen port (default: 9090) |
| `--bind <addr>` | Bind to a specific interface (default: 0.0.0.0) |
| `-m, --more` | Verbose logging: all headers, reverse DNS, parsed UA |
| `--catch` | Request catcher — dump full headers + body (implies `--more`) |
| `--code <N>` | HTTP status code for responses (100–599, default: 200) |
| `--header "K: V"` | Add a response header (repeatable) |
| `--cors` | Add permissive CORS headers |
| `--redirect <url>` | 302 redirect all requests to the URL |
| `--payload <name>` | Serve a built-in payload (see below) |
| `--collect` | Collect requests to a JSONL log, printed on exit |
| `--delay <ms>` | Artificial response delay in milliseconds |
| `-h, --help` | Show help |

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
| `POST /upload` | Multipart upload — saves to `~/Downloads/expose` |
| `GET /upload/files` | JSON list of received files |
| `GET /upload/files/<name>` | Download a received file |
| `DELETE /upload/files/<name>` | Delete a received file |
| `GET /me` | Echo the client's request info + client-side device fingerprint (HTML, or JSON with `Accept: application/json`) |
| `GET /log?since=<n>` | JSON request log (last 500 entries; `since` filters by entry number) |
| `POST /log/clear` | Clear the request log |
| `GET /meta` | JSON metadata about the current mode |
| `GET /content` | The served text/file payload (not in directory mode) |
| `GET`/`POST /chat` | Mini chat shared between visitors of the upload page |

Directory mode additionally serves the full file tree under `/` and a JSON
listing API at `/ls[/path]`.

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

## Development

The binary is generated — edit `src/` and rebuild with `make build`; never edit
`dist/expose` directly. Run `make test` for the integration suite. See
[AGENTS.md](AGENTS.md) for the architecture, build system, and contribution
conventions.
