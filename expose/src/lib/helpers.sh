# ── Helpers ─────────────────────────────────────────────────────────────────
get_local_ip() {
  local addr
  addr=$(command ip route get 1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1);exit}}')
  [[ -n "$addr" ]] && { echo "$addr"; return; }
  addr=$(hostname -I 2>/dev/null | awk '{print $1}')
  [[ -n "$addr" ]] && { echo "$addr"; return; }
  echo "127.0.0.1"
}

log()  { printf "%s%s%s  %s\n" "$D" "$(date '+%H:%M:%S')" "$R" "$*" >&2; }
die()  { printf "%s%serror:%s %s\n" "$B" "$RED" "$R" "$*" >&2; exit 1; }

_mktmp() { local f; f=$(mktemp "$1"); _TMPFILES+=("$f"); echo "$f"; }

cleanup() {
  [[ -n "$_CLEANUP_DONE" ]] && return; _CLEANUP_DONE=1
  if [[ "${EXPOSE_NO_BANNER:-0}" != "1" ]]; then
    echo >&2
    log "${YLW}Shutting down…${R}"
  fi
  for f in "${_TMPFILES[@]+"${_TMPFILES[@]}"}"; do rm -f "$f" 2>/dev/null; done
  if [[ "${EXPOSE_NO_BANNER:-0}" != "1" ]]; then
    log "${GRN}Stopped.${R}"
  fi
}

trap 'cleanup; exit 0' INT TERM
trap cleanup EXIT

# ── Usage ─────────────────────────────────────────────────────────────────────
