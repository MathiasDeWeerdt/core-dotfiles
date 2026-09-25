#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT

# Exercise the real package section without running the rest of the bootstrap.
sed -n '/^run() {$/,/^}$/p' "$ROOT/install.sh" > "$TEST_DIR/packages.sh"
sed -n '/^if \$SKIP_PACKAGES; then$/,/^fi  # SKIP_PACKAGES$/p' \
    "$ROOT/install.sh" | sed '/^fi  # SKIP_PACKAGES$/q' >> "$TEST_DIR/packages.sh"

check() {
    local name="$1" installed="$2" remove_status="$3" install_status="$4"
    local dry_run="$5" skip="$6" expected_status="$7" expected_calls="$8"
    local status=0
    (
        DRY_RUN="$dry_run" SKIP_PACKAGES="$skip"
        _ERRORS=()
        info() { echo "$*"; }
        warn() { echo "$*"; }
        err() { echo "$*"; }
        log() { echo "$*"; }
        pacman() { return "$installed"; }
        sudo() {
            if [[ "$2" == -R ]]; then
                [[ "$*" == 'pacman -R --noconfirm gnu-netcat' ]]
                echo remove >> "$TEST_DIR/calls"
                return "$remove_status"
            fi
            [[ "$*" == 'pacman -Syu --needed --noconfirm '* ]]
            [[ " $* " == *' openbsd-netcat '* ]]
            echo install >> "$TEST_DIR/calls"
            return "$install_status"
        }
        source "$TEST_DIR/packages.sh"
    ) > "$TEST_DIR/output" 2>&1 || status=$?
    [[ "$status" == "$expected_status" ]]
    [[ "$(cat "$TEST_DIR/calls")" == "$expected_calls" ]]
    if (( expected_status != 0 )); then
        ! grep -q 'Official packages installed' "$TEST_DIR/output"
    fi
    : > "$TEST_DIR/calls"
    echo "PASS: $name"
}

: > "$TEST_DIR/calls"
check 'replace GNU netcat' 0 0 0 false false 0 $'remove\ninstall'
check 'no conflict' 1 0 0 false false 0 install
check 'removal failure stops install' 0 1 0 false false 1 remove
check 'installation failure is reported' 1 0 1 false false 1 install
check 'dry run makes no changes' 0 0 0 true false 0 ''
check 'skip packages makes no changes' 0 0 0 false true 0 ''
