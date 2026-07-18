
# ── Validate ──────────────────────────────────────────────────────────────────
[[ "$PORT" =~ ^[0-9]+$ ]] && (( PORT >= 1 && PORT <= 65535 )) \
  || die "Invalid port: $PORT (must be 1–65535)"
[[ "$MODE" == "file" && ! -f "$TARGET" ]] && die "File not found: $TARGET"
[[ "$MODE" != "dir" ]] && ! command -v socat &>/dev/null \
  && die "socat is required  (apt install socat)"
[[ "$MODE" == "dir" ]] && ! command -v python3 &>/dev/null \
  && die "python3 is required for directory serving"
[[ -n "$RESP_CODE" ]] && { [[ "$RESP_CODE" =~ ^[0-9]+$ ]] && (( RESP_CODE >= 100 && RESP_CODE <= 599 )) \
  || die "Invalid status code: $RESP_CODE (must be 100–599)"; }
[[ -n "$AUTH" && "$AUTH" != *:* ]] && die "Invalid auth format: use user:pass"
[[ "$BODY_LIMIT" =~ ^[0-9]+$ ]] || die "Invalid --body-limit: must be a non-negative integer"
[[ $CATCH -eq 1 && "$MODE" == "dir" ]] && die "--catch is not supported with directory mode"
[[ $ONCE -eq 1 && "$MODE" == "dir" ]] && die "--once is not supported with directory mode"
[[ $TLS -eq 1 && "$MODE" == "dir" ]] && die "--tls is not yet supported with directory mode"
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
_port_pid=$(ss -tlnp "sport = :$PORT" 2>/dev/null \
  | awk 'NR>1{match($0,/pid=([0-9]+)/,a); if(a[1]) print a[1]}' | head -1)
if [[ -n "$_port_pid" ]]; then
  _port_cmd=$(ps -p "$_port_pid" -o comm= 2>/dev/null || echo "unknown")
  printf "%s%sPort %s is already in use%s by %s%s%s (pid %s)\n" \
    "$B" "$YLW" "$PORT" "$R" "$B" "$_port_cmd" "$R" "$_port_pid" >&2
  printf "Kill it? [y/N] " >&2
  read -r _ans </dev/tty
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

