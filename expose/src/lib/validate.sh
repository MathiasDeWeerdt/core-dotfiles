
# ── Validate ──────────────────────────────────────────────────────────────────
[[ "$PORT" =~ ^[0-9]+$ ]] && (( PORT >= 1 && PORT <= 65535 )) \
  || die "Invalid port: $PORT (must be 1–65535)"
[[ "$MODE" == "file" && ! -f "$TARGET" ]] && die "File not found: $TARGET"
command -v python3 &>/dev/null || die "python3 is required"
[[ -n "$RESP_CODE" ]] && { [[ "$RESP_CODE" =~ ^[0-9]+$ ]] && (( RESP_CODE >= 100 && RESP_CODE <= 599 )) \
  || die "Invalid status code: $RESP_CODE (must be 100–599)"; }
if (( ${#RESP_HEADERS[@]} )); then
  for _header in "${RESP_HEADERS[@]}"; do
    [[ "$_header" == *:* ]] || die "Invalid response header: use 'Name: value'"
    [[ "$_header" != *$'\r'* && "$_header" != *$'\n'* ]] \
      || die "Invalid response header: line breaks are not allowed"
  done
fi
[[ -n "$BIND" && ! "$BIND" =~ ^[0-9a-fA-F.:]+$ ]] && die "Invalid bind address: $BIND"

# ── Check port in use ────────────────────────────────────────────────────────
_port_pid=$(ss -tlnp "sport = :$PORT" 2>/dev/null \
  | awk 'NR>1{match($0,/pid=([0-9]+)/,a); if(a[1]) print a[1]}' | head -1)
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
