# ── Serve ────────────────────────────────────────────────────────────────────
_COUNTERFILE=$(_mktmp /tmp/expose-counter.XXXXXX)
echo 0 > "$_COUNTERFILE"
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
  trap "echo; echo '${GRN}Collected requests:${R} ${_COLLECT_FILE}'; wc -l < '${_COLLECT_FILE}' | xargs printf '${GRN}Total:${R} %s\n'" EXIT
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

_UPLOAD_HTML=$(_mktmp /tmp/expose-upload-html.XXXXXX)
cat > "$_UPLOAD_HTML" << 'UPLOADHTML'
@@INJECT:assets/web/upload.html@@
UPLOADHTML

_UPLOAD_PY=$(_mktmp /tmp/expose-upload-py.XXXXXX)
cat > "$_UPLOAD_PY" << 'UPLOADPY'
@@INJECT:assets/upload.py@@
UPLOADPY

# ── Handler script for socat (text & file modes) ─────────────────────────────
make_handler() {
  local h
  h=$(_mktmp /tmp/expose-handler.XXXXXX)
  cat > "$h" <<'HANDLER'
@@INJECT:assets/handler.sh@@
HANDLER
  chmod +x "$h"
  echo "$h"
}

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
  export EXPOSE_VERBOSE="$VERBOSE" EXPOSE_COUNTER="$_COUNTERFILE"
  export EXPOSE_UPLOAD_HTML="$_UPLOAD_HTML" EXPOSE_UPLOAD_PY="$_UPLOAD_PY" EXPOSE_UPLOAD_DIR="$UPLOAD_DIR"
  export EXPOSE_AUTH="$AUTH" EXPOSE_CATCH="$CATCH" EXPOSE_RESP_CODE="${RESP_CODE:-200}"
  export EXPOSE_RESP_HEADERS="$_RESP_HDRS"
  export EXPOSE_LOGFILE="$_LOGFILE"
  export EXPOSE_ONCE="$ONCE" EXPOSE_SOCAT_PIDFILE="$_socatpf"
  export EXPOSE_ALLOW="$_EXPOSE_ALLOW"
  export EXPOSE_BODY_LIMIT="$BODY_LIMIT"
  export EXPOSE_REDIRECT="$REDIRECT"
  export EXPOSE_DELAY_MS="$DELAY_MS"
  export EXPOSE_PAYLOAD="$PAYLOAD"
  export EXPOSE_COLLECT="$COLLECT"
  export EXPOSE_COLLECT_FILE="$_COLLECT_FILE"
  export EXPOSE_CHAT_FILE="$_CHAT_FILE"
}

# ── Serve: text ───────────────────────────────────────────────────────────────
serve_text() {
  local cf
  cf=$(_mktmp /tmp/expose-content.XXXXXX)
  printf '%s' "$1" > "$cf"

  local _socatpf
  _socatpf=$(_mktmp /tmp/expose-socatpid.XXXXXX)

  export EXPOSE_CONTENT="$cf" EXPOSE_LEN="${#1}" EXPOSE_MIME="text/plain; charset=utf-8"
  _export_common

  local _listen
  if [[ $TLS -eq 1 ]]; then
    _listen="OPENSSL-LISTEN:${PORT},bind=${BIND},reuseaddr,fork,cert=${_CERTFILE},key=${_KEYFILE},verify=0"
  else
    _listen="TCP-LISTEN:${PORT},bind=${BIND},reuseaddr,fork"
  fi

  socat "$_listen" SYSTEM:"$(make_handler)" &
  local _spid=$!
  echo "$_spid" > "$_socatpf"
  wait "$_spid" || true
}

# ── Serve: file ──────────────────────────────────────────────────────────────
serve_file() {
  local fp mime sz
  fp=$(realpath "$1")
  mime=$(file -b --mime-type "$fp" 2>/dev/null || echo "application/octet-stream")
  sz=$(stat -c'%s' "$fp" 2>/dev/null || wc -c < "$fp")

  local _socatpf
  _socatpf=$(_mktmp /tmp/expose-socatpid.XXXXXX)

  export EXPOSE_CONTENT="$fp" EXPOSE_LEN="$sz" EXPOSE_MIME="$mime"
  export EXPOSE_FILENAME="$(basename "$fp")"
  _export_common

  local _listen
  if [[ $TLS -eq 1 ]]; then
    _listen="OPENSSL-LISTEN:${PORT},bind=${BIND},reuseaddr,fork,cert=${_CERTFILE},key=${_KEYFILE},verify=0"
  else
    _listen="TCP-LISTEN:${PORT},bind=${BIND},reuseaddr,fork"
  fi

  socat "$_listen" SYSTEM:"$(make_handler)" &
  local _spid=$!
  echo "$_spid" > "$_socatpf"
  wait "$_spid" || true
}

# ── Serve: directory ──────────────────────────────────────────────────────────
serve_dir() {
  export EXPOSE_PORT="$PORT" EXPOSE_VERBOSE="$VERBOSE"
  export EXPOSE_UPLOAD_DIR="$UPLOAD_DIR" EXPOSE_UPLOAD_HTML="$_UPLOAD_HTML"
  export EXPOSE_AUTH="$AUTH"
  export EXPOSE_LOGFILE="$_LOGFILE"
  export EXPOSE_BIND="$BIND"
  export EXPOSE_ALLOW="$_EXPOSE_ALLOW"
  export EXPOSE_CHAT_FILE="$_CHAT_FILE"
  python3 <<'PYEOF'
@@INJECT:assets/server.py@@
PYEOF
}

# ── Serve: redirect ───────────────────────────────────────────────────────────
serve_redirect() {
  serve_text ""
}

# ── Serve: payload ────────────────────────────────────────────────────────────
serve_payload() {
  local content
  content=$(resolve_payload "$PAYLOAD")
  [[ -z "$content" ]] && die "Unknown payload: $PAYLOAD. Run expose --help for list."
  serve_text "$content"
}

# ── Serve: websocket ──────────────────────────────────────────────────────────
serve_websocket() {
  export EXPOSE_PORT="$PORT" EXPOSE_BIND="$BIND"
  info "WebSocket echo server on ws://${BIND}:${PORT}"
  python3 <<'PYEOF'
@@INJECT:assets/websocket.py@@
PYEOF
}

# ── Replay ────────────────────────────────────────────────────────────────────
do_replay() {
  local logfile="$1"
  [[ -f "$logfile" ]] || die "Log file not found: $logfile"
  python3 <<'PYEOF'
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

# Parse host:port from host header
if ':' in host:
    hostname, port = host.split(':', 1)
    port = int(port)
else:
    hostname = host
    port = 80

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
finally:
    conn.close()
PYEOF
  python3 - "$TARGET"
}

# ── Run ───────────────────────────────────────────────────────────────────────
export EXPOSE_MODE="$MODE"
case "$MODE" in
  text)     serve_text "$TARGET" ;;
  catch)    serve_text "" ;;
  file)     serve_file "$TARGET" ;;
  dir)      serve_dir ;;
  redirect) serve_redirect ;;
  payload)  serve_payload ;;
  websocket) serve_websocket ;;
  replay)   do_replay "$TARGET" ;;
esac