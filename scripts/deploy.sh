#!/usr/bin/env bash
# Shared by install.sh and update.sh. Never copies host configs into Git.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
INSTALL_DIR=${EXPOSE_INSTALL_DIR:-/usr/local/bin}

case "${1:-}" in
    --dry-run)
        printf 'Would build expose from %s/expose/src, deploy configs with private backups,\nwire private global memory, and install matching expose tools to %s.\n' "$ROOT" "$INSTALL_DIR"
        if [[ "${DOTFILES_SYNC_ENABLE:-true}" != false ]]; then
            printf 'Would enable reviewed-commit sync and start its user timer when available.\n'
        fi
        if [[ "${SKIP_AGENT_SKILLS:-false}" != true ]]; then
            python3 "$ROOT/scripts/manage-skills.py" --dry-run
        fi
        exit 0 ;;
    '') ;;
    *) printf 'Unknown deployment option: %s\n' "$1" >&2; exit 1 ;;
esac

python3 "$ROOT/scripts/check-secrets.py"
bash "$ROOT/expose/build.sh"
for tool in expose expose-online; do
    bash -n "$ROOT/expose/dist/$tool"
    install -C -m 755 "$ROOT/expose/dist/$tool" "$ROOT/local-bin/.local/bin/$tool"
done
python3 "$ROOT/scripts/deploy-configs.py"

# A user-only target is useful in tests and unprivileged installations.
if [[ "$INSTALL_DIR" == "$HOME/"* ]]; then
    mkdir -p "$INSTALL_DIR"
    privilege=()
else
    privilege=(sudo)
fi
for tool in expose expose-online; do
    target="$INSTALL_DIR/$tool"
    if ! cmp -s "$ROOT/expose/dist/$tool" "$target" || [[ ! -x "$target" ]]; then
        "${privilege[@]}" install -D -C -m 755 "$ROOT/expose/dist/$tool" "$target"
    fi
    cmp -s "$ROOT/expose/dist/$tool" "$target"
    printf 'Verified %s matches repository build.\n' "$target"
done

if command -v go >/dev/null && [[ "${SKIP_CONSOLE_CLIENTS:-false}" != true ]]; then
    make -C "$ROOT/expose" install-console-clients
fi

if [[ "${SKIP_AGENT_SKILLS:-false}" != true ]]; then
    python3 "$ROOT/scripts/manage-skills.py" sync
fi
