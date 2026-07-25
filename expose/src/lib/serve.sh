# ── Serve ────────────────────────────────────────────────────────────────────
# ── Request log file ──────────────────────────────────────────────────────────
if [[ -n "$LOGFILE" ]]; then
  _LOGFILE="$LOGFILE"
  echo '[]' > "$_LOGFILE" || die "Cannot write to log file: $LOGFILE"
else
  _LOGFILE=$(_mktmp /tmp/expose-log.XXXXXX)
  echo '[]' > "$_LOGFILE"
fi
# ── Collect file (JSONL) ──────────────────────────────────────────────────────
if [[ $COLLECT -eq 1 ]]; then
  if [[ -n "$LOGFILE" ]]; then
    _COLLECT_FILE="${LOGFILE%.json}.jsonl"
  else
    _COLLECT_FILE=$(_mktmp /tmp/expose-collect.XXXXXX)
  fi
  : > "$_COLLECT_FILE"
  print_collected() {
    echo
    printf '%sCollected requests:%s %s\n' "$GRN" "$R" "$_COLLECT_FILE"
    printf '%sTotal:%s %s\n' "$GRN" "$R" "$(wc -l < "$_COLLECT_FILE")"
  }
  trap 'print_collected; cleanup' EXIT
fi

# ── Chat file ──
_CHAT_FILE=$(_mktmp /tmp/expose-chat.XXXXXX)
echo "[]" > "$_CHAT_FILE"

# ── Build custom response headers ─────────────────────────────────────────────
_RESP_HDRS=""
if [[ $CORS -eq 1 ]]; then
  _RESP_HDRS+="Access-Control-Allow-Origin: *"$'\r\n'
  _RESP_HDRS+="Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS"$'\r\n'
  _RESP_HDRS+="Access-Control-Allow-Headers: *"$'\r\n'
  _RESP_HDRS+="Access-Control-Max-Age: 86400"$'\r\n'
fi
if (( ${#RESP_HEADERS[@]} )); then
  for _h in "${RESP_HEADERS[@]}"; do
    _RESP_HDRS+="${_h}"$'\r\n'
  done
fi
# ── Upload support ────────────────────────────────────────────────────────────
UPLOAD_DIR="${HOME}/Downloads/expose"
mkdir -p "$UPLOAD_DIR"

# ── Persistent SQLite request log (~/.expose/requests.db) ────────────────────
_DB_DIR="${HOME}/.expose"
_DB="${_DB_DIR}/requests.db"
if command -v python3 &>/dev/null && mkdir -p "$_DB_DIR" 2>/dev/null; then
  python3 - "$_DB" <<'PYDB' 2>/dev/null
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
con.execute("""create table if not exists requests(
  id integer primary key autoincrement,
  ts real, time text, method text, path text,
  ip text, port text, ua text, host text,
  content_type text, content_len text, mode text)""")
con.execute("""create table if not exists fingerprints(
  id integer primary key autoincrement,
  ts real, time text,
  ip text, port text, ua text,
  page text, visitor_id text, data text)""")
con.execute("pragma journal_mode=WAL")
con.commit(); con.close()
PYDB
fi

_UPLOAD_HTML=$(_mktmp /tmp/expose-upload-html.XXXXXX)
cat > "$_UPLOAD_HTML" << 'UPLOADHTML'
@@INJECT:assets/web/upload.html@@
UPLOADHTML

_FP_JS=$(_mktmp /tmp/expose-fp-js.XXXXXX)
cat > "$_FP_JS" << 'FPJS'
@@INJECT:assets/web/fp.js@@
FPJS

_ME_HTML=$(_mktmp /tmp/expose-me-html.XXXXXX)
cat > "$_ME_HTML" << 'MEHTML'
@@INJECT:assets/web/me.html@@
MEHTML

_LOGO_SVG=$(_mktmp /tmp/expose-logo-svg.XXXXXX)
cat > "$_LOGO_SVG" << 'LOGOSVG'
@@INJECT:assets/web/logo.svg@@
LOGOSVG

# ── Payload resolver ──────────────────────────────────────────────────────────
resolve_payload() {
  local name="$1"
  bash -c "$(cat <<'PAYLOAD_SRC'
@@INJECT:assets/payloads.sh@@
PAYLOAD_SRC
)" -- "$name"
}

# ── Common exports ────────────────────────────────────────────────────────────
_export_common() {
  export EXPOSE_PORT="$PORT" EXPOSE_BIND="$BIND" EXPOSE_VERBOSE="$VERBOSE"
  export EXPOSE_UPLOAD_HTML="$_UPLOAD_HTML" EXPOSE_UPLOAD_DIR="$UPLOAD_DIR"
  export EXPOSE_AUTH="$AUTH" EXPOSE_CATCH="$CATCH" EXPOSE_RESP_CODE="${RESP_CODE:-200}"
  export EXPOSE_RESP_HEADERS="$_RESP_HDRS"
  export EXPOSE_LOGFILE="$_LOGFILE"
  export EXPOSE_ONCE="$ONCE"
  export EXPOSE_ALLOW="$_EXPOSE_ALLOW"
  export EXPOSE_BODY_LIMIT="$BODY_LIMIT"
  export EXPOSE_REDIRECT="$REDIRECT"
  export EXPOSE_DELAY_MS="$DELAY_MS"
  export EXPOSE_PAYLOAD="$PAYLOAD"
  export EXPOSE_COLLECT="$COLLECT"
  export EXPOSE_COLLECT_FILE="$_COLLECT_FILE"
  export EXPOSE_CHAT_FILE="$_CHAT_FILE"
  export EXPOSE_FP_JS="$_FP_JS"
  export EXPOSE_ME_HTML="$_ME_HTML"
  export EXPOSE_LOGO_SVG="$_LOGO_SVG"
  export EXPOSE_DB="$_DB"
  export EXPOSE_TLS="$TLS" EXPOSE_CERTFILE="${_CERTFILE:-}" EXPOSE_KEYFILE="${_KEYFILE:-}"
}

# ── Unified HTTP backend ──────────────────────────────────────────────────────
serve_http() {
  _export_common
  python3 <<'PYEOF'
@@INJECT:assets/server.py@@
PYEOF
}

# ── Serve: websocket ──────────────────────────────────────────────────────────
serve_websocket() {
  export EXPOSE_PORT="$PORT" EXPOSE_BIND="$BIND"
  log "WebSocket echo server on ws://${BIND}:${PORT}"
  python3 <<'PYEOF'
@@INJECT:assets/websocket.py@@
PYEOF
}

# ── Replay ────────────────────────────────────────────────────────────────────
do_replay() {
  local logfile="$1"
  [[ -f "$logfile" ]] || die "Log file not found: $logfile"
  python3 - "$logfile" <<'PYEOF'
import sys, json, http.client, urllib.parse

logfile = sys.argv[1]

with open(logfile) as f:
    log = json.load(f)

if not log:
    print("No requests in log")
    sys.exit(1)

# Replay the last request
entry = log[-1]
method = entry.get('method', 'GET')
path = entry.get('path', '/')
host = entry.get('host', 'localhost')

# Parse host and optional port, including bracketed IPv6 addresses.
destination = urllib.parse.urlsplit("//" + host)
hostname = destination.hostname or "localhost"
port = destination.port or 80

print(f"Replaying {method} {path} -> {hostname}:{port}")

conn = http.client.HTTPConnection(hostname, port, timeout=10)
headers = {}
if entry.get('ua'):
    headers['User-Agent'] = entry['ua']
if entry.get('accept'):
    headers['Accept'] = entry['accept']
if entry.get('content_type'):
    headers['Content-Type'] = entry['content_type']

body = entry.get('body', '') if entry.get('body') else None
try:
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    print(f"Response: {resp.status} {resp.reason}")
    print(resp.read().decode('utf-8', 'replace')[:2000])
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
finally:
    conn.close()
PYEOF
}

# ── Run ───────────────────────────────────────────────────────────────────────
export EXPOSE_MODE="$MODE"
case "$MODE" in
  text|catch|redirect|dir)
    if [[ "$MODE" == "text" ]]; then
      _CONTENT_FILE=$(_mktmp /tmp/expose-content.XXXXXX)
      printf '%s' "$TARGET" > "$_CONTENT_FILE"
      export EXPOSE_CONTENT="$_CONTENT_FILE" EXPOSE_LEN="${#TARGET}" EXPOSE_MIME="text/plain; charset=utf-8"
    fi
    serve_http
    ;;
  file)
    _CONTENT_FILE=$(realpath "$TARGET")
    export EXPOSE_CONTENT="$_CONTENT_FILE"
    export EXPOSE_LEN="$(stat -c'%s' "$_CONTENT_FILE" 2>/dev/null || wc -c < "$_CONTENT_FILE")"
    export EXPOSE_MIME="$(file -b --mime-type "$_CONTENT_FILE" 2>/dev/null || echo "application/octet-stream")"
    export EXPOSE_FILENAME="$(basename "$_CONTENT_FILE")"
    serve_http
    ;;
  payload)
    _PAYLOAD_CONTENT=$(resolve_payload "$PAYLOAD") \
      || die "Unknown payload: $PAYLOAD. Run expose --help for list."
    _CONTENT_FILE=$(_mktmp /tmp/expose-content.XXXXXX)
    printf '%s' "$_PAYLOAD_CONTENT" > "$_CONTENT_FILE"
    export EXPOSE_CONTENT="$_CONTENT_FILE" EXPOSE_LEN="${#_PAYLOAD_CONTENT}" EXPOSE_MIME="text/plain; charset=utf-8"
    serve_http
    ;;
  websocket) serve_websocket ;;
  replay)   do_replay "$TARGET" ;;
esac
