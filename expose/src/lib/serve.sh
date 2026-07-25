# ── Serve ────────────────────────────────────────────────────────────────────
# ── Persistent request log ────────────────────────────────────────────────────
_LOG_DIR="${HOME}/.expose"
_LOGFILE="${_LOG_DIR}/requests.json"
mkdir -p "$_LOG_DIR" || die "Cannot create log directory: $_LOG_DIR"
[[ -f "$_LOGFILE" ]] || echo '[]' > "$_LOGFILE" \
  || die "Cannot write request log: $_LOGFILE"
# ── Collect file (JSONL) ──────────────────────────────────────────────────────
if [[ $COLLECT -eq 1 ]]; then
  _COLLECT_FILE=$(_mktmp /tmp/expose-collect.XXXXXX)
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
  export EXPOSE_CATCH="$CATCH" EXPOSE_RESP_CODE="${RESP_CODE:-200}"
  export EXPOSE_RESP_HEADERS="$_RESP_HDRS"
  export EXPOSE_LOGFILE="$_LOGFILE"
  export EXPOSE_REDIRECT="$REDIRECT"
  export EXPOSE_DELAY_MS="$DELAY_MS"
  export EXPOSE_PAYLOAD="$PAYLOAD"
  export EXPOSE_COLLECT="$COLLECT"
  export EXPOSE_COLLECT_FILE="$_COLLECT_FILE"
  export EXPOSE_CHAT_FILE="$_CHAT_FILE"
  export EXPOSE_FP_JS="$_FP_JS"
  export EXPOSE_ME_HTML="$_ME_HTML"
  export EXPOSE_LOGO_SVG="$_LOGO_SVG"
}

# ── Unified HTTP backend ──────────────────────────────────────────────────────
serve_http() {
  _export_common
  python3 <<'PYEOF'
@@INJECT:assets/server.py@@
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
esac
