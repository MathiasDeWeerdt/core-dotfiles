#!/usr/bin/env bash
# expose-online — expose a local server through singlecore.dev
set -euo pipefail

# Local utility commands do not need a public tunnel and must keep control of
# the terminal.
if [[ "${1:-}" == "db" ]]; then
  exec expose "$@"
fi

# ── Config ────────────────────────────────────────────────────────────────────
TUNNEL_HOST="${TUNNEL_HOST:-213.118.201.119}"
TUNNEL_PORT="${TUNNEL_PORT:-47865}"
TUNNEL_USER="${TUNNEL_USER:-root}"
TUNNEL_RPORT="${TUNNEL_RPORT:-9090}"
TUNNEL_LPORT="${TUNNEL_LPORT:-9090}"

GREEN=$'\033[0;32m'
CYAN=$'\033[0;36m'
YLW=$'\033[1;33m'
BOLD=$'\033[1m'
DIM=$'\033[2m'
NC=$'\033[0m'

if [[ ! -t 2 ]]; then
  GREEN="" CYAN="" YLW="" BOLD="" DIM="" NC=""
fi

# ── State ─────────────────────────────────────────────────────────────────────
_STOPPED=0
SSH_PID=""
EXPOSE_PID=""

cleanup() {
  [[ $_STOPPED -eq 1 ]] && return
  _STOPPED=1
  printf '\n%sStopping tunnel…%s\n' "$DIM" "$NC" >&2
  [[ -n "$SSH_PID" ]] && kill "$SSH_PID" 2>/dev/null || true
  [[ -n "$EXPOSE_PID" ]] && kill "$EXPOSE_PID" 2>/dev/null || true
  [[ -n "$SSH_PID" ]] && wait "$SSH_PID" 2>/dev/null || true
  [[ -n "$EXPOSE_PID" ]] && wait "$EXPOSE_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

free_remote_port() {
  ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new \
    -p "$TUNNEL_PORT" "${TUNNEL_USER}@${TUNNEL_HOST}" \
    "fuser -k ${TUNNEL_RPORT}/tcp >/dev/null 2>&1; true" \
    >/dev/null 2>&1 || true
}

start_tunnel() {
  ssh -n \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=2 \
    -o ExitOnForwardFailure=yes \
    -o StrictHostKeyChecking=accept-new \
    -o ConnectTimeout=10 \
    -N -R "*:${TUNNEL_RPORT}:localhost:${TUNNEL_LPORT}" \
    -p "$TUNNEL_PORT" \
    "${TUNNEL_USER}@${TUNNEL_HOST}" &
  SSH_PID=$!
}

local_ip() {
  local address
  address=$(ip route get 1 2>/dev/null \
    | awk '{for (i=1; i<=NF; i++) if ($i=="src") {print $(i+1); exit}}')
  if [[ -z "$address" ]]; then
    address=$(hostname -I 2>/dev/null | awk '{print $1}')
  fi
  printf '%s\n' "${address:-127.0.0.1}"
}

# ── Free the local port ───────────────────────────────────────────────────────
_local_pid=$(ss -tlnp "sport = :${TUNNEL_LPORT}" 2>/dev/null \
  | awk 'NR>1{match($0,/pid=([0-9]+)/,a); if(a[1]) print a[1]}' | head -1)
if [[ -n "$_local_pid" ]]; then
  printf '%sReplacing existing listener on :%s%s\n' \
    "$DIM" "$TUNNEL_LPORT" "$NC" >&2
  kill "$_local_pid" 2>/dev/null || true
  for _ in {1..20}; do
    ss -tln "sport = :${TUNNEL_LPORT}" 2>/dev/null | awk 'NR > 1 { found=1 } END { exit !found }' \
      || break
    sleep 0.1
  done
fi

# ── Start expose ──────────────────────────────────────────────────────────────
EXPOSE_NO_BANNER=1 expose --bind 0.0.0.0 -p "$TUNNEL_LPORT" "$@" &
EXPOSE_PID=$!
sleep 0.5

if ! kill -0 "$EXPOSE_PID" 2>/dev/null; then
  printf '%sexpose failed to start%s\n' "$YLW" "$NC" >&2
  exit 1
fi

# ── Start tunnel ──────────────────────────────────────────────────────────────
free_remote_port
start_tunnel
sleep 0.3

if ! kill -0 "$SSH_PID" 2>/dev/null; then
  wait "$SSH_PID" 2>/dev/null || true
  printf '%sSSH tunnel failed to start%s\n' "$YLW" "$NC" >&2
  exit 1
fi

printf '\n%s%sExpose online%s\n' "$BOLD" "$GREEN" "$NC" >&2
printf '  %-7s %shttps://singlecore.dev%s\n' "Public" "$CYAN" "$NC" >&2
printf '  %-7s http://127.0.0.1:%s\n' "Local" "$TUNNEL_LPORT" >&2
printf '  %-7s http://%s:%s\n' "Network" "$(local_ip)" "$TUNNEL_LPORT" >&2
printf '  %-7s %s:%s %s(via SSH :%s)%s\n\n' \
  "Tunnel" "$TUNNEL_HOST" "$TUNNEL_RPORT" "$DIM" "$TUNNEL_PORT" "$NC" >&2

while [[ $_STOPPED -eq 0 ]]; do
  wait "$SSH_PID" 2>/dev/null || true
  [[ $_STOPPED -eq 1 ]] && break

  if ! kill -0 "$EXPOSE_PID" 2>/dev/null; then
    printf '%sexpose stopped unexpectedly%s\n' "$YLW" "$NC" >&2
    exit 1
  fi

  printf '%sTunnel dropped; reconnecting in 3 seconds…%s\n' "$YLW" "$NC" >&2
  sleep 3
  free_remote_port
  start_tunnel
done
