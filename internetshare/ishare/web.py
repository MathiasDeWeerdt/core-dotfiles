"""Web interface for ad-hoc internet sharing."""

from __future__ import annotations

import argparse
import hmac
import secrets
import sys
import webbrowser
from threading import Timer
from urllib.parse import urlsplit

from flask import Flask, jsonify, redirect, render_template, request, session

from . import core

app = Flask(__name__)
app.secret_key = secrets.token_bytes(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict")
ACCESS_TOKEN = secrets.token_urlsafe(32)


@app.before_request
def protect_local_control():
    # This process runs as root. Never expose it as an unauthenticated LAN API,
    # and reject DNS rebinding and cross-site browser requests even on loopback.
    if urlsplit(request.host_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        return fail("Local access only.", 403)
    origin = request.headers.get("Origin")
    if (origin and origin != request.host_url.rstrip("/")) or request.headers.get("Sec-Fetch-Site") == "cross-site":
        return fail("Cross-site requests are not allowed.", 403)
    if request.path == "/login" and request.method == "GET":
        if not hmac.compare_digest(request.args.get("token", ""), ACCESS_TOKEN):
            return fail("Invalid launch token.", 401)
        session.clear()
        session["authenticated"] = True
        return redirect("/")
    if not session.get("authenticated"):
        return fail("Open the launch URL printed by internet-share.", 401)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not request.is_json:
        return fail("JSON content type required.", 415)


@app.after_request
def private_responses(response):
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


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
    if args.host not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("the privileged web interface must bind to loopback")

    if not core.is_root():
        print("Warning: not running as root; start/stop will fail.", file=sys.stderr)

    core.start_monitor()

    host = f"[{args.host}]" if args.host == "::1" else args.host
    url = f"http://{host}:{args.port}/login?token={ACCESS_TOKEN}"
    print(f"Internet Share web UI running at {url}")
    if args.open:
        Timer(1.0, lambda: webbrowser.open(url)).start()

    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
