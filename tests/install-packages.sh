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
        source "$ROOT/scripts/package-policy.sh"
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
            [[ "$*" == 'pacman -Syu --needed --noconfirm --ask=4 '* ]]
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
check 'replace GNU netcat atomically' 0 0 0 false false 0 install
check 'no conflict' 1 0 0 false false 0 install
check 'installation failure is reported' 1 0 1 false false 1 install
check 'dry run makes no changes' 0 0 0 true false 0 ''
check 'skip packages makes no changes' 0 0 0 false true 0 ''

# Execute real AUR transactions against stubs, with stdin closed.
cat > "$TEST_DIR/aur.sh" <<'BASH'
set -eu
source "$ROOT/scripts/package-policy.sh"
DRY_RUN=false
_ERRORS=()
info() { :; }
log() { :; }
warn() { :; }
err() { echo "$*" >&2; }
BASH
sed -n '/^run() {$/,/^}$/p' "$ROOT/install.sh" >> "$TEST_DIR/aur.sh"
cat >> "$TEST_DIR/aur.sh" <<'BASH'
pacman() { [[ "${MISSING:-}" != "$2" ]]; }
yay() {
    [[ " $* " == *' --noconfirm '* ]]
    [[ " $* " == *' --useask '* ]]
    [[ " $* " == *' --ask=4 '* ]]
    [[ " $* " == *' --answeredit None '* ]]
    [[ " $* " == *' --answerupgrade None '* ]]
    [[ " $* " != *' netexec '* ]]
    local target="${!#}"
    echo "$target" >> "$TEST_DIR/aur-calls"
    [[ "${FAILED:-}" != "$target" ]]
}
BASH
sed -n '/^AUR_PKGS=(/,/^log "AUR package attempts complete/p' "$ROOT/install.sh" >> "$TEST_DIR/aur.sh"
echo '(( ${#_ERRORS[@]} == 0 ))' >> "$TEST_DIR/aur.sh"
export ROOT TEST_DIR
for scenario in success build-failure missing-after-success; do
    : > "$TEST_DIR/aur-calls"
    status=0
    case "$scenario" in
        success) FAILED= MISSING= bash "$TEST_DIR/aur.sh" </dev/null || status=$? ;;
        build-failure) FAILED=opencode-bin MISSING= bash "$TEST_DIR/aur.sh" </dev/null || status=$? ;;
        missing-after-success) FAILED= MISSING=opencode-bin bash "$TEST_DIR/aur.sh" </dev/null || status=$? ;;
    esac
    if [[ "$scenario" == success ]]; then [[ "$status" == 0 ]]; else [[ "$status" != 0 ]]; fi
    [[ $(wc -l < "$TEST_DIR/aur-calls") == $(grep -vc '^#\|^$' "$ROOT/packages/aur.txt") ]]
    echo "PASS: AUR $scenario (all transactions attempted without prompts)"
done

# Existing native agent/Bun installs must not gain competing npm copies.
cat > "$TEST_DIR/npm.sh" <<'BASH'
set -eu
PATH=/usr/bin:/bin
DOTFILES="$ROOT"
log() { :; }
info() { :; }
codex() { :; }
copilot() { :; }
pi() { :; }
bun() { :; }
python3() { echo managed-dsh; }
npm() {
    if [[ "$1" == list ]]; then return 1; fi
    [[ "$*" == 'install -g @nestjs/cli' ]]
    echo install-nest
}
BASH
sed -n '/^NPM_GLOBALS=(/,/^# Copilot uses/p' "$ROOT/install.sh" >> "$TEST_DIR/npm.sh"
[[ $(bash "$TEST_DIR/npm.sh") == $'managed-dsh\ninstall-nest' ]]
echo 'PASS: Native agents and Bun do not gain duplicate npm installations'
