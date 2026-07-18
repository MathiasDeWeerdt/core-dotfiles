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
# ── Build custom response headers ─────────────────────────────────────────────
_RESP_HDRS=""
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

# ── Serve: text ───────────────────────────────────────────────────────────────
serve_text() {
  local cf
  cf=$(_mktmp /tmp/expose-content.XXXXXX)
  printf '%s' "$1" > "$cf"

  local _socatpf
  _socatpf=$(_mktmp /tmp/expose-socatpid.XXXXXX)

  export EXPOSE_CONTENT="$cf" EXPOSE_LEN="${#1}" EXPOSE_MIME="text/plain; charset=utf-8"
  export EXPOSE_VERBOSE="$VERBOSE" EXPOSE_COUNTER="$_COUNTERFILE"
  export EXPOSE_UPLOAD_HTML="$_UPLOAD_HTML" EXPOSE_UPLOAD_PY="$_UPLOAD_PY" EXPOSE_UPLOAD_DIR="$UPLOAD_DIR"
  export EXPOSE_AUTH="$AUTH" EXPOSE_CATCH="$CATCH" EXPOSE_RESP_CODE="${RESP_CODE:-200}"
  export EXPOSE_RESP_HEADERS="$_RESP_HDRS"
  export EXPOSE_LOGFILE="$_LOGFILE"
  export EXPOSE_ONCE="$ONCE" EXPOSE_SOCAT_PIDFILE="$_socatpf"
  export EXPOSE_ALLOW="$_EXPOSE_ALLOW"
  export EXPOSE_BODY_LIMIT="$BODY_LIMIT"

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
  export EXPOSE_VERBOSE="$VERBOSE" EXPOSE_COUNTER="$_COUNTERFILE"
  export EXPOSE_UPLOAD_HTML="$_UPLOAD_HTML" EXPOSE_UPLOAD_PY="$_UPLOAD_PY" EXPOSE_UPLOAD_DIR="$UPLOAD_DIR"
  export EXPOSE_AUTH="$AUTH" EXPOSE_CATCH="$CATCH" EXPOSE_RESP_CODE="${RESP_CODE:-200}"
  export EXPOSE_RESP_HEADERS="$_RESP_HDRS"
  export EXPOSE_LOGFILE="$_LOGFILE"
  export EXPOSE_ONCE="$ONCE" EXPOSE_SOCAT_PIDFILE="$_socatpf"
  export EXPOSE_ALLOW="$_EXPOSE_ALLOW"
  export EXPOSE_BODY_LIMIT="$BODY_LIMIT"

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
  python3 <<'PYEOF'
@@INJECT:assets/server.py@@
PYEOF
}

# ── Run ───────────────────────────────────────────────────────────────────────
export EXPOSE_MODE="$MODE"
case "$MODE" in
  text)  serve_text "$TARGET" ;;
  catch) serve_text "" ;;
  file)  serve_file "$TARGET" ;;
  dir)   serve_dir ;;
esac
