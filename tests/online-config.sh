#!/usr/bin/env bash
# Check credentials and help handling with a stub expose; never start a tunnel.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
mkdir -p "$TEST_DIR/bin" "$TEST_DIR/home"
cp "$ROOT/expose/src/expose-online.sh" "$TEST_DIR/bin/expose-online"
cat > "$TEST_DIR/bin/expose" <<'STUB'
#!/bin/sh
printf 'local help reached\n'
STUB
chmod +x "$TEST_DIR/bin/expose" "$TEST_DIR/bin/expose-online"
env -u EXPOSE_AUTH_PASSWORD HOME="$TEST_DIR/home" "$TEST_DIR/bin/expose-online" --help | grep -q 'local help reached'
if env -u EXPOSE_AUTH_PASSWORD HOME="$TEST_DIR/home" "$TEST_DIR/bin/expose-online" >"$TEST_DIR/out" 2>&1; then
    echo 'Missing password was accepted' >&2; exit 1
fi
grep -q 'set EXPOSE_AUTH_PASSWORD' "$TEST_DIR/out"
# Extract only credential setup; the rest of the wrapper cannot open sockets.
sed -n '/^ONLINE_CONFIG=/,/^export EXPOSE_AUTH_PASSWORD$/p' "$ROOT/expose/src/expose-online.sh" > "$TEST_DIR/config.sh"
umask 077
EXPOSE_AUTH_PASSWORD=$(cat /proc/sys/kernel/random/uuid)
export EXPOSE_AUTH_PASSWORD
printf 'EXPOSE_AUTH_PASSWORD=%s\n' "$EXPOSE_AUTH_PASSWORD" > "$TEST_DIR/private.env"
EXPOSE_ONLINE_CONFIG="$TEST_DIR/private.env" bash -c 'unset EXPOSE_AUTH_PASSWORD; source "$1"; [[ -n "$EXPOSE_AUTH_PASSWORD" ]]' _ "$TEST_DIR/config.sh"
if EXPOSE_AUTH_PASSWORD='' EXPOSE_ONLINE_CONFIG="$TEST_DIR/private.env" bash "$TEST_DIR/config.sh" >"$TEST_DIR/out" 2>&1; then
    echo 'Explicit empty password was accepted' >&2; exit 1
fi
chmod 644 "$TEST_DIR/private.env"
if EXPOSE_ONLINE_CONFIG="$TEST_DIR/private.env" bash "$TEST_DIR/config.sh" >"$TEST_DIR/out" 2>&1; then
    echo 'World-readable configuration was accepted' >&2; exit 1
fi
grep -q 'mode 0600' "$TEST_DIR/out"
echo 'online config tests passed'
