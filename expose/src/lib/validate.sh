
# ── Validate ──────────────────────────────────────────────────────────────────
if [[ "$MODE" == "db" ]]; then
  command -v sqlite3 &>/dev/null || die "sqlite3 is required for database browsing"
  [[ -f "$TARGET" ]] || die "Database not found: $TARGET"
  if [[ $DB_SUMMARY -eq 0 ]]; then
    command -v fzf &>/dev/null || die "fzf is required for the database viewer"
    [[ -t 0 && -t 1 ]] || die "Database viewer requires an interactive terminal (use --summary otherwise)"
  fi
else
[[ "$PORT" =~ ^[0-9]+$ ]] && (( PORT >= 1 && PORT <= 65535 )) \
  || die "Invalid port: $PORT (must be 1–65535)"
[[ "$MODE" == "file" && ! -f "$TARGET" ]] && die "File not found: $TARGET"
command -v python3 &>/dev/null || die "python3 is required"
[[ -n "$RESP_CODE" ]] && { [[ "$RESP_CODE" =~ ^[0-9]+$ ]] && (( RESP_CODE >= 100 && RESP_CODE <= 599 )) \
  || die "Invalid status code: $RESP_CODE (must be 100–599)"; }
[[ -n "$AUTH" && "$AUTH" != *:* ]] && die "Invalid auth format: use user:pass"
[[ "$BODY_LIMIT" =~ ^[0-9]+$ ]] || die "Invalid --body-limit: must be a non-negative integer"
if (( ${#RESP_HEADERS[@]} )); then
  for _header in "${RESP_HEADERS[@]}"; do
    [[ "$_header" == *:* ]] || die "Invalid response header: use 'Name: value'"
    [[ "$_header" != *$'\r'* && "$_header" != *$'\n'* ]] \
      || die "Invalid response header: line breaks are not allowed"
  done
fi
[[ -n "$LOGFILE" ]] && { _ldir=$(dirname "$LOGFILE"); [[ -w "$_ldir" ]] || die "Cannot write log to: $LOGFILE"; }
[[ -n "$BIND" && ! "$BIND" =~ ^[0-9a-fA-F.:]+$ ]] && die "Invalid bind address: $BIND"

# ── TLS setup ─────────────────────────────────────────────────────────────────
if [[ $TLS -eq 1 ]]; then
  command -v openssl &>/dev/null || die "openssl is required for --tls  (apt install openssl)"
  _CERTFILE=$(_mktmp /tmp/expose-cert.XXXXXX)
  _KEYFILE=$(_mktmp /tmp/expose-key.XXXXXX)
  log "${D}Generating TLS certificate…${R}"
  openssl req -x509 -newkey rsa:2048 -keyout "$_KEYFILE" -out "$_CERTFILE" \
    -days 1 -nodes -subj "/CN=expose" 2>/dev/null \
    || die "Failed to generate TLS certificate"
fi

# ── Build allow-list string ────────────────────────────────────────────────────
_EXPOSE_ALLOW=""
if (( ${#ALLOWED_NETS[@]} )); then
  _EXPOSE_ALLOW=$(IFS=','; echo "${ALLOWED_NETS[*]}")
fi

# ── Check port in use ────────────────────────────────────────────────────────
_port_pid=""
if [[ "$MODE" != "replay" ]]; then
  _port_pid=$(ss -tlnp "sport = :$PORT" 2>/dev/null \
    | awk 'NR>1{match($0,/pid=([0-9]+)/,a); if(a[1]) print a[1]}' | head -1)
fi
if [[ -n "$_port_pid" ]]; then
  _port_cmd=$(ps -p "$_port_pid" -o comm= 2>/dev/null || echo "unknown")
  printf "%s%sPort %s is already in use%s by %s%s%s (pid %s)\n" \
    "$B" "$YLW" "$PORT" "$R" "$B" "$_port_cmd" "$R" "$_port_pid" >&2
  printf "Kill it? [y/N] " >&2
  _ans=""
  read -r _ans </dev/tty 2>/dev/null \
    || die "Port $PORT is in use — pick another with -p"
  if [[ "$_ans" =~ ^[Yy]$ ]]; then
    kill "$_port_pid" 2>/dev/null
    # wait briefly for port to free
    for _ in 1 2 3 4 5; do
      ss -tln "sport = :$PORT" 2>/dev/null | grep -q ":$PORT" || break
      sleep 0.2
    done
    log "${GRN}Killed ${_port_cmd} (pid ${_port_pid})${R}"
  else
    die "Port $PORT is in use — pick another with -p"
  fi
fi
fi
