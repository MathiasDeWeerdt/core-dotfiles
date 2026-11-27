#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin" "$WORK/checkout/.git"
cat > "$WORK/bin/git" <<'STUB'
#!/bin/sh
shift 2
case "$1" in
    symbolic-ref) echo test-branch ;;
    config) case "$3" in *.remote) echo origin ;; *.merge) echo refs/heads/test-branch ;; esac ;;
    rev-parse) echo 1111111111111111111111111111111111111111 ;;
    ls-remote)
        [ "$REMOTE_STATUS" = 0 ] || exit 1
        printf '%s\trefs/heads/test-branch\n' "$REMOTE_HEAD" ;;
    *) echo 'Unexpected Git mutation' >&2; exit 99 ;;
esac
STUB
cat > "$WORK/bin/notify-send" <<'STUB'
#!/bin/sh
echo notification >> "$CALLS"
STUB
chmod +x "$WORK/bin/"*
export PATH="$WORK/bin:$PATH" DOTFILES_DIR="$WORK/checkout" CALLS="$WORK/calls"
export REMOTE_STATUS=0 REMOTE_HEAD=1111111111111111111111111111111111111111
bash "$ROOT/local-bin/.local/bin/dotfiles-check-updates" > "$WORK/output"
[[ ! -e "$CALLS" ]]
export REMOTE_HEAD=2222222222222222222222222222222222222222
bash "$ROOT/local-bin/.local/bin/dotfiles-check-updates" > "$WORK/output"
[[ $(wc -l < "$CALLS") == 1 ]]
export REMOTE_STATUS=1
if bash "$ROOT/local-bin/.local/bin/dotfiles-check-updates" > "$WORK/output" 2>&1; then
    echo 'Network failure was hidden' >&2; exit 1
fi
[[ $(wc -l < "$CALLS") == 1 ]]
echo 'Read-only update-check tests passed'
