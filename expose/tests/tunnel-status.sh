#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
source <(sed -n '/^check_tunnel() {$/,/^}$/p' "$ROOT/src/expose-online.sh")

_STOPPED=0 SSH_PID=123 EXPOSE_HEALTH_TOKEN=test-session
DIM='' NC='' GREEN='' YLW=''
sleep() { :; }
kill() { return "${SSH_STATUS:-0}"; }
curl() { printf '%s' "$RESPONSE"; return "${CURL_STATUS:-0}"; }

RESPONSE=test-session
output=$(check_tunnel 2>&1)
[[ "$output" == *'Connected — public URL verified'* ]]

RESPONSE=another-session
output=$(check_tunnel 2>&1)
[[ "$output" == *'Public URL not verified'* ]]
[[ "$output" != *'Connected —'* ]]

CURL_STATUS=28
output=$(check_tunnel 2>&1)
[[ "$output" == *'Public URL not verified'* ]]

SSH_STATUS=1
output=$(check_tunnel 2>&1)
[[ "$output" == *'SSH tunnel disconnected'* ]]
[[ "$output" != *'Connected —'* ]]

echo 'tunnel status tests passed'
