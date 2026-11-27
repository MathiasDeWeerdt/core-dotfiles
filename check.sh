#!/usr/bin/env bash
# Read-only local credential/configuration checks. Never source secret files.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
exec python3 -B "$ROOT/scripts/check-config.py" "$@"
