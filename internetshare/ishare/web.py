"""Web interface for ad-hoc internet sharing."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from threading import Timer

from flask import Flask, jsonify, render_template, request

from . import core

app = Flask(__name__)


def ok(payload=None):
    data = {"ok": True}
    if payload:
        data.update(payload)
    return jsonify(data)


def fail(message: str, code: int = 400):
    return jsonify({"ok": False, "error": message}), code


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/interfaces")
def api_interfaces():
    return ok({"interfaces": core.list_interfaces()})


@app.get("/api/suggest")
def api_suggest():
    interfaces = core.list_interfaces()
    default_dev = next((i["name"] for i in interfaces if i["is_default"]), None)
    lan_candidates = [
        i["name"] for i in interfaces if i["name"] != default_dev and i["kind"] in ("ethernet", "wifi")
    ]
    return ok({"wan": default_dev, "lan": lan_candidates[0] if lan_candidates else None})


@app.get("/api/state")
def api_state():
    return ok(
        {
            "state": core.status(),
            "interfaces": core.list_interfaces(),
            "root": core.is_root(),
        }
    )


@app.get("/api/leases")
def api_leases():
    return ok({"leases": core.leases_with_status()})


@app.post("/api/start")
def api_start():
    try:
        cfg = core.validate_config(request.get_json(force=True, silent=True) or {})
        state = core.start(cfg)
        return ok({"state": state, "interfaces": core.list_interfaces()})
    except core.ShareError as exc:
        return fail(str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        return fail(f"Unexpected error: {exc}", 500)


@app.post("/api/stop")
def api_stop():
    try:
        state = core.stop()
        return ok({"state": state, "interfaces": core.list_interfaces()})
    except core.ShareError as exc:
        return fail(str(exc))
    except Exception as exc:  # pragma: no cover
        return fail(f"Unexpected error: {exc}", 500)


@app.post("/api/config")
def api_config():
    """Save settings, applying them live when sharing is active."""
    try:
        cfg = core.validate_config(request.get_json(force=True, silent=True) or {})
        if core.is_active():
            state = core.start(cfg)
        else:
            core.save_config(cfg)
            state = core.status()
        return ok({"state": state, "interfaces": core.list_interfaces()})
    except core.ShareError as exc:
        return fail(str(exc))
    except Exception as exc:  # pragma: no cover
        return fail(f"Unexpected error: {exc}", 500)


@app.post("/api/lease/delete")
def api_lease_delete():
    try:
        data = request.get_json(force=True, silent=True) or {}
        removed = core.delete_lease(ip=data.get("ip"), mac=data.get("mac"))
        if not removed:
            return fail("Lease not found.")
        return ok({"leases": core.list_leases()})
    except core.ShareError as exc:
        return fail(str(exc))


@app.get("/api/reservations")
def api_reservations():
    return ok({"reservations": core.load_reservations()})


@app.post("/api/reservations")
def api_reservation_add():
    try:
        data = request.get_json(force=True, silent=True) or {}
        items = core.add_reservation(
            mac=data.get("mac", ""),
            ip=data.get("ip", ""),
            hostname=data.get("hostname", ""),
        )
        return ok({"reservations": items, "leases": core.list_leases()})
    except core.ShareError as exc:
        return fail(str(exc))


@app.delete("/api/reservations/<mac>")
def api_reservation_remove(mac: str):
    try:
        items = core.remove_reservation(mac)
        return ok({"reservations": items, "leases": core.list_leases()})
    except core.ShareError as exc:
        return fail(str(exc))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Internet sharing web UI")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="port (default 8080)")
    parser.add_argument("--open", action="store_true", help="open a browser window")
    args = parser.parse_args(argv)

    if not core.is_root():
        print("Warning: not running as root; start/stop will fail.", file=sys.stderr)

    core.start_monitor()

    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.port}"
    print(f"Internet Share web UI running at {url}")
    if args.open:
        Timer(1.0, lambda: webbrowser.open(url)).start()

    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
