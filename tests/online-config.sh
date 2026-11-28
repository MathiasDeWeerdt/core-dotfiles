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
# A pasted repair must work even if the configured path contains shell syntax.
config="$TEST_DIR/"'test file '"'"'$(false).env'
mv -- "$TEST_DIR/private.env" "$config"
chmod 644 -- "$config"
if EXPOSE_ONLINE_CONFIG="$config" bash "$TEST_DIR/config.sh" >"$TEST_DIR/out" 2>&1; then
    echo 'World-readable configuration was accepted' >&2; exit 1
fi
grep -q 'mode 0600' "$TEST_DIR/out"
repair=$(tail -n 1 "$TEST_DIR/out")
[[ "$repair" == '  chmod 600 -- '* ]]
bash -c "$repair"
[[ $(stat -c %a -- "$config") == 600 ]]
EXPOSE_ONLINE_CONFIG="$config" bash "$TEST_DIR/config.sh"

# Simulate foreign ownership without privileges. Check chown's arguments and
# execute the printed chmod on the fixture only.
chmod 644 -- "$config"
if EXPOSE_ONLINE_CONFIG="$config" bash -c '
    stat() { printf "%s:644\n" "$((EUID + 1))"; }
    source "$1"
' _ "$TEST_DIR/config.sh" >"$TEST_DIR/out" 2>&1; then
    echo 'Foreign-owned configuration was accepted' >&2; exit 1
fi
repair=$(tail -n 1 "$TEST_DIR/out")
[[ "$repair" == '  sudo chown '* ]]
EXPOSE_ONLINE_CONFIG="$config" bash -c '
    sudo() { [[ $# == 4 && $1 == chown && $2 == -- && $3 == "$EUID" && $4 == "$EXPOSE_ONLINE_CONFIG" ]]; }
    eval "$1"
' _ "$repair"
[[ $(stat -c %a -- "$config") == 600 ]]

ln -s -- "$config" "$TEST_DIR/link"
for path in "$TEST_DIR/link" "$TEST_DIR/home"; do
    if EXPOSE_ONLINE_CONFIG="$path" bash "$TEST_DIR/config.sh" >"$TEST_DIR/out" 2>&1; then
        echo 'Non-regular configuration was accepted' >&2; exit 1
    fi
    grep -q 'regular config file' "$TEST_DIR/out"
    if grep -Eq 'chmod|chown' "$TEST_DIR/out"; then exit 1; fi
done
echo 'online config tests passed'
