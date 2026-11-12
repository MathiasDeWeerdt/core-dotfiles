#!/bin/sh
# Ad-hoc internet sharing - launcher.
#
#   ./internet-share.sh              # open the web interface (default)
#   ./internet-share.sh web --port 9000 --open
#   ./internet-share.sh up --wan wlan0 --lan enp0s31f6
#   ./internet-share.sh down
#   ./internet-share.sh status
#   ./internet-share.sh leases
#
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PYTHONPATH="${HERE}${PYTHONPATH:+:$PYTHONPATH}"

if [ "$(id -u)" -ne 0 ]; then
    exec sudo --preserve-env=PYTHONPATH,DISPLAY,WAYLAND_DISPLAY,XDG_RUNTIME_DIR \
        python3 -m ishare.cli "$@"
fi

exec python3 -m ishare.cli "$@"
