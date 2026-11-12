"""Command line interface for internet-share."""

from __future__ import annotations

import argparse
import sys

from . import core


def _build_config(args) -> dict:
    cfg = core.load_config()
    if getattr(args, "wan", None):
        cfg["wan"] = args.wan
    if getattr(args, "lan", None):
        cfg["lan"] = args.lan
    if getattr(args, "gateway", None):
        cfg["lan_ip"] = args.gateway
    if getattr(args, "prefix", None):
        cfg["prefix"] = args.prefix
    if getattr(args, "range", None):
        start, _, end = args.range.partition(",")
        if not end:
            raise core.ShareError("--range expects START,END (e.g. 10.42.0.50,10.42.0.200)")
        cfg["dhcp_start"] = start.strip()
        cfg["dhcp_end"] = end.strip()
    if getattr(args, "lease", None):
        cfg["lease_time"] = args.lease
    if getattr(args, "domain", None):
        cfg["domain"] = args.domain
    if getattr(args, "dns", None):
        cfg["dns_servers"] = [s.strip() for s in args.dns.split(",") if s.strip()]
    if getattr(args, "dhcp_dns", None):
        cfg["dhcp_dns"] = [s.strip() for s in args.dhcp_dns.split(",") if s.strip()]
    if getattr(args, "wifi_ssid", None):
        cfg["wifi_ssid"] = args.wifi_ssid
    if getattr(args, "wifi_password", None):
        cfg["wifi_password"] = args.wifi_password
    return cfg


def cmd_up(args) -> int:
    cfg = core.suggest_config(args.wan, args.lan)
    cfg.update({k: v for k, v in _build_config(args).items() if v not in (None, "")})
    state = core.start(cfg)
    print(f"Internet sharing is active: {state['config']['wan']} -> {state['config']['lan']}")
    print(f"Network {state['network']}, DHCP {state['config']['dhcp_start']} - {state['config']['dhcp_end']}")
    return 0


def cmd_down(_args) -> int:
    core.stop()
    print("Internet sharing stopped.")
    return 0


def cmd_status(_args) -> int:
    state = core.status()
    if state["active"]:
        cfg = state["config"]
        print(f"Active: {cfg['wan']} -> {cfg['lan']} ({state['network']})")
        print(f"DHCP {cfg['dhcp_start']} - {cfg['dhcp_end']}, {len(state['leases'])} lease(s)")
    else:
        print("Inactive.")
    return 0


def cmd_leases(_args) -> int:
    leases = core.list_leases()
    if not leases:
        print("No leases.")
        return 0
    for lease in leases:
        host = lease["hostname"] or "-"
        print(f"{lease['ip']:<16} {lease['mac']:<18} {host}")
    return 0


def cmd_web(args) -> int:
    from . import web

    argv = ["--host", args.host, "--port", str(args.port)]
    if args.open:
        argv.append("--open")
    web.main(argv)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="internet-share", description="Ad-hoc internet sharing")
    sub = parser.add_subparsers(dest="command")

    p_web = sub.add_parser("web", help="launch the web interface (default)")
    p_web.add_argument("--host", default="127.0.0.1")
    p_web.add_argument("--port", type=int, default=8080)
    p_web.add_argument("--open", action="store_true")
    p_web.set_defaults(func=cmd_web)

    p_up = sub.add_parser("up", help="start sharing")
    p_up.add_argument("--wan")
    p_up.add_argument("--lan")
    p_up.add_argument("--gateway")
    p_up.add_argument("--prefix", type=int)
    p_up.add_argument("--range", help="START,END")
    p_up.add_argument("--lease", help="e.g. 12h, 1d, infinite")
    p_up.add_argument("--domain")
    p_up.add_argument("--dns", help="comma separated upstream DNS servers")
    p_up.add_argument("--dhcp-dns", help="comma separated DNS handed to clients")
    p_up.add_argument("--wifi-ssid", help="SSID when the LAN interface is Wi-Fi")
    p_up.add_argument("--wifi-password", help="WPA password when the LAN interface is Wi-Fi")
    p_up.set_defaults(func=cmd_up)

    sub.add_parser("down", help="stop sharing").set_defaults(func=cmd_down)
    sub.add_parser("status", help="show status").set_defaults(func=cmd_status)
    sub.add_parser("leases", help="list DHCP leases").set_defaults(func=cmd_leases)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        args = parser.parse_args(["web"])

    try:
        return args.func(args)
    except core.ShareError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
