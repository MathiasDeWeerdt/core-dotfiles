#!/usr/bin/env bash
# Upstream's pipx flow, isolated from Arch's rolling Python ABI.
set -euo pipefail
if [[ "${1:-}" == --dry-run ]]; then
    printf 'Would install/update upstream NetExec through pipx using uv-managed Python 3.12.\n'
    exit 0
fi
[[ $# == 0 ]] || { printf 'Usage: install-netexec.sh [--dry-run]\n' >&2; exit 2; }
command -v uv >/dev/null || { printf 'Install the official uv package first.\n' >&2; exit 1; }
command -v pipx >/dev/null || { printf 'Install python-pipx first.\n' >&2; exit 1; }
STATE_DIR=${XDG_STATE_HOME:-$HOME/.local/state}/core-dotfiles
umask 077
mkdir -p "$STATE_DIR"
exec 9> "$STATE_DIR/netexec-install.lock"
flock 9
SOURCE=https://github.com/Pennyw0rth/NetExec
REVISION=$(git ls-remote "$SOURCE" refs/heads/main | cut -f1)
[[ "$REVISION" =~ ^[0-9a-f]{40}$ ]] || { printf 'Could not resolve upstream NetExec main.\n' >&2; exit 1; }
uv python install 3.12
PYTHON_BIN=$(uv python find --managed-python 3.12)
SPEC="git+$SOURCE@$REVISION"
VENV_ROOT=$(pipx environment --value PIPX_LOCAL_VENVS)
BIN_DIR=$(pipx environment --value PIPX_BIN_DIR)
if "$PYTHON_BIN" - "$VENV_ROOT/netexec/pipx_metadata.json" "$SPEC" "$BIN_DIR" <<'PY'
import json, pathlib, sys
try:
    path = pathlib.Path(sys.argv[1])
    data = json.loads(path.read_text())
    matches = (data.get('main_package', {}).get('package_or_url') == sys.argv[2]
               and data.get('python_version', '').startswith('Python 3.12.')
               and (path.parent / 'bin/nxc').is_file()
               and all((pathlib.Path(sys.argv[3]) / name).resolve() == (path.parent / 'bin' / name).resolve()
                       and (pathlib.Path(sys.argv[3]) / name).is_file()
                       for name in ('nxc', 'nxcdb', 'NetExec', 'netexec')))
except (OSError, ValueError):
    matches = False
sys.exit(0 if matches else 1)
PY
then
    printf 'NetExec already matches upstream commit %.12s on Python 3.12.\n' "$REVISION"
else
    pipx install --force --python "$PYTHON_BIN" "$SPEC"
    # --force updates an existing venv but intentionally keeps its interpreter.
    # Reinstall is required exactly once when migrating Arch's rolling Python.
    if [[ "$("$VENV_ROOT/netexec/bin/python" --version)" != Python\ 3.12.* ]]; then
        pipx reinstall --python "$PYTHON_BIN" netexec
    fi
fi
# Only retire the old package after the new isolated installation succeeds.
if pacman -Q netexec >/dev/null 2>&1; then
    sudo pacman -R --noconfirm netexec
fi
