#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
mkdir -p "$TEST_DIR/bin" "$TEST_DIR/home"
cat > "$TEST_DIR/bin/quickget" <<'STUB'
#!/bin/sh
case "$*" in *--path*) exit 1 ;; esac
printf '%s\n' "$*" >> "$CALLS"
printf 'guest_os="%s"\nram="2G"\n' "$1" > vm.conf
STUB
chmod +x "$TEST_DIR/bin/quickget"
export CALLS="$TEST_DIR/calls"
export HOME="$TEST_DIR/home" VM_DIR="$TEST_DIR/vms" PATH="$TEST_DIR/bin:$PATH"
bash "$ROOT/scripts/quickemu-lab.sh" create > "$TEST_DIR/log"
[[ $(wc -l < "$CALLS") == 4 ]]
find "$VM_DIR" -name '*.conf' -exec sha256sum {} + | sort > "$TEST_DIR/first"
for _ in {1..5}; do
    bash "$ROOT/scripts/quickemu-lab.sh" create > "$TEST_DIR/log"
done
find "$VM_DIR" -name '*.conf' -exec sha256sum {} + | sort > "$TEST_DIR/after"
cmp "$TEST_DIR/first" "$TEST_DIR/after"
[[ $(wc -l < "$CALLS") == 4 ]]
[[ $(rg --no-heading '^ssh_port=' "$VM_DIR" | sort -u | wc -l) == 4 ]]
! rg -q 'port_forwards=' "$VM_DIR"
echo 'quickemu repeat-create tests passed'
