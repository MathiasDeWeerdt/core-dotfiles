"""Core logic for ad-hoc internet sharing.

Everything here is designed to be driven either by the CLI or by the web UI.
The module must be imported from a process that has root privileges.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

CONF_DIR = Path("/etc/internet-share")
CONF_FILE = CONF_DIR / "config.json"
DNSMASQ_CONF = CONF_DIR / "dnsmasq.conf"
RESERVATIONS_FILE = CONF_DIR / "reservations.json"

RUN_DIR = Path("/run/internet-share")
PID_FILE = RUN_DIR / "dnsmasq.pid"
IPFWD_STATE = RUN_DIR / "ip_forward"

LIB_DIR = Path("/var/lib/internet-share")
LEASE_FILE = LIB_DIR / "dnsmasq.leases"

LOG_DIR = Path("/var/log/internet-share")
LOG_FILE = LOG_DIR / "dnsmasq.log"

CHAIN_FWD = "ISHARE-FWD"
CHAIN_NAT = "ISHARE-NAT"

PROFILE_PREFIX = "internet-share"

# Interfaces that only add noise to the picker.
HIDDEN_IFACE_RE = re.compile(r"^(br-|docker|vmnet|veth|virbr|podman)")

LEASE_TIMES = {
    "1 hour": "1h",
    "6 hours": "6h",
    "12 hours": "12h",
    "1 day": "1d",
    "7 days": "7d",
    "Forever": "infinite",
}
LEASE_TIME_VALUES = list(LEASE_TIMES.values())

DEFAULT_CONFIG = {
    "wan": "",
    "lan": "",
    "lan_ip": "10.42.0.1",
    "prefix": 24,
    "dhcp_start": "10.42.0.50",
    "dhcp_end": "10.42.0.200",
    "lease_time": "12h",
    "domain": "jimber.local",
    "dns_servers": [],
    "dhcp_dns": [],
    "wifi_ssid": "jimber",
    "wifi_password": "applebananaorange",
}


class ShareError(Exception):
    """Raised for user-facing problems."""


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def is_root() -> bool:
    return os.geteuid() == 0


def require_root() -> None:
    if not is_root():
        raise ShareError("This action needs root. Run the app with sudo.")


def run(cmd, check=True, timeout=30):
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ShareError(f"{cmd[0]}: command not found") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise ShareError(f"{' '.join(cmd)} failed: {detail}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ShareError(f"{' '.join(cmd)} timed out") from exc


def which(prog: str) -> bool:
    return shutil.which(prog) is not None


def _read_text(path: Path) -> str:
    try:
        return path.read_text()
    except (FileNotFoundError, PermissionError, OSError):
        return ""


def _write_text(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def ensure_dirs() -> None:
    for directory in (CONF_DIR, RUN_DIR, LIB_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# Interfaces
# --------------------------------------------------------------------------- #

def _default_route():
    out = run(["ip", "-j", "route", "show", "default"], check=False).stdout
    try:
        routes = json.loads(out or "[]")
    except json.JSONDecodeError:
        routes = []
    for route in routes:
        if route.get("dst") == "default" and route.get("dev"):
            return route
    return {}


def _is_physical(name: str) -> bool:
    """True for real hardware adapters (PCI/USB), false for virtual links."""
    return (Path("/sys/class/net") / name / "device").exists()


def _iface_kind(name: str) -> str:
    base = Path("/sys/class/net") / name
    if (base / "wireless").exists() or (base / "phy80211").exists():
        return "wifi"
    if (base / "bridge").exists():
        return "bridge"
    if name.startswith(("tun", "tap", "wg")) or name in {"jimber"}:
        return "tunnel"
    try:
        # ARPHRD_ETHER == 1 covers both wired Ethernet and Wi-Fi drivers.
        if (base / "type").read_text().strip() == "1":
            return "ethernet"
    except OSError:
        pass
    return "other"


def is_wifi(name: str) -> bool:
    base = Path("/sys/class/net") / name
    return (base / "wireless").exists() or (base / "phy80211").exists()


def wifi_supports_ap(name: str) -> bool | None:
    """True/False if AP mode is known, None when it cannot be determined."""
    phy = _read_text(Path("/sys/class/net") / name / "phy80211" / "name").strip()
    if not phy or not which("iw"):
        return None
    out = run(["iw", "phy", phy, "info"], check=False).stdout
    for line in out.splitlines():
        if line.strip() in ("* AP", "AP"):
            return True
    return False if "Supported interface modes" in out else None


def list_interfaces():
    """Return a list of usable network interfaces with details."""
    out = run(["ip", "-j", "addr"]).stdout
    try:
        items = json.loads(out or "[]")
    except json.JSONDecodeError:
        items = []

    default_dev = _default_route().get("dev")

    interfaces = []
    for item in items:
        name = item.get("ifname", "")
        if name == "lo":
            continue
        if HIDDEN_IFACE_RE.match(name):
            continue
        if not _is_physical(name):
            continue

        addrs = []
        for info in item.get("addr_info", []):
            if info.get("family") == "inet":
                addrs.append(f"{info['local']}/{info['prefixlen']}")

        base = Path("/sys/class/net") / name
        try:
            carrier = (base / "carrier").read_text().strip() == "1"
        except OSError:
            carrier = None
        up = "UP" in item.get("flags", [])

        interfaces.append(
            {
                "name": name,
                "kind": _iface_kind(name),
                "state": item.get("operstate", "UNKNOWN").lower(),
                "up": up,
                "carrier": carrier,
                "addresses": addrs,
                "mac": item.get("address", ""),
                "mtu": item.get("mtu"),
                "is_default": name == default_dev,
            }
        )

    interfaces.sort(key=lambda i: (not i["is_default"], i["name"]))
    return interfaces


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONF_FILE.exists():
        try:
            cfg.update(json.loads(CONF_FILE.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_config(cfg: dict) -> None:
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    # Contains the Wi-Fi password, so keep it private.
    _write_text(CONF_FILE, json.dumps(cfg, indent=2) + "\n", mode=0o600)


def system_dns() -> list[str]:
    """Return the system's upstream DNS servers (non-loopback)."""
    for path in ("/run/systemd/resolve/resolv.conf", "/etc/resolv.conf"):
        servers = []
        for line in _read_text(Path(path)).splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and parts[0] == "nameserver":
                ip = parts[1]
                try:
                    address = ipaddress.ip_address(ip)
                except ValueError:
                    continue
                if address.is_loopback:
                    continue
                if ip not in servers:
                    servers.append(ip)
        if servers:
            return servers
    return []


def effective_config() -> dict:
    """Config for display, with DNS defaults filled from the system."""
    cfg = load_config()
    if not cfg.get("dns_servers"):
        cfg["dns_servers"] = system_dns()
    if not cfg.get("dhcp_dns"):
        cfg["dhcp_dns"] = system_dns()
    return cfg


def network_cidr(cfg: dict) -> str:
    net = ipaddress.ip_network(f"{cfg['lan_ip']}/{cfg['prefix']}", strict=False)
    return str(net)


def validate_config(cfg: dict) -> dict:
    """Normalise and validate a configuration dict, raising ShareError."""
    clean = dict(DEFAULT_CONFIG)
    clean.update({k: v for k, v in cfg.items() if k in DEFAULT_CONFIG})

    wan = str(clean.get("wan", "")).strip()
    lan = str(clean.get("lan", "")).strip()
    if not wan or not lan:
        raise ShareError("Pick both an internet (WAN) and a devices (LAN) interface.")
    if wan == lan:
        raise ShareError("The WAN and LAN interfaces must be different.")
    for name in (wan, lan):
        if not (Path("/sys/class/net") / name).exists():
            raise ShareError(f"Interface {name} does not exist.")

    try:
        prefix = int(clean.get("prefix", 24))
    except (TypeError, ValueError):
        raise ShareError("Invalid subnet prefix.")
    if not 8 <= prefix <= 30:
        raise ShareError("Subnet size must be between /8 and /30.")

    try:
        net = ipaddress.ip_network(f"{clean['lan_ip']}/{prefix}", strict=False)
        lan_ip = ipaddress.ip_address(str(clean["lan_ip"]))
        start = ipaddress.ip_address(str(clean["dhcp_start"]))
        end = ipaddress.ip_address(str(clean["dhcp_end"]))
    except ValueError as exc:
        raise ShareError(f"Invalid IP address: {exc}") from exc

    for ip in (lan_ip, start, end):
        if ip not in net:
            raise ShareError(f"{ip} is not inside the LAN network {net}.")
    if lan_ip == net.network_address:
        raise ShareError("The gateway address cannot be the network address.")
    if start > end:
        raise ShareError("The DHCP range start must be before the end.")
    if lan_ip in (start, end) or (int(start) <= int(lan_ip) <= int(end)):
        raise ShareError("The DHCP range must not include the gateway address.")

    lease_time = str(clean.get("lease_time", "12h")).strip() or "12h"
    if lease_time not in LEASE_TIME_VALUES and not re.fullmatch(r"\d+[smhdw]?", lease_time):
        raise ShareError("Invalid lease time.")

    dns_servers = clean.get("dns_servers") or []
    if isinstance(dns_servers, str):
        dns_servers = [s.strip() for s in dns_servers.split(",") if s.strip()]
    for server in dns_servers:
        try:
            ipaddress.ip_address(server)
        except ValueError as exc:
            raise ShareError(f"Invalid DNS server {server}") from exc

    dhcp_dns = clean.get("dhcp_dns") or []
    if isinstance(dhcp_dns, str):
        dhcp_dns = [s.strip() for s in dhcp_dns.split(",") if s.strip()]
    for server in dhcp_dns:
        try:
            ipaddress.ip_address(server)
        except ValueError as exc:
            raise ShareError(f"Invalid client DNS {server}") from exc

    wifi_ssid = str(clean.get("wifi_ssid") or "").strip()
    wifi_password = str(clean.get("wifi_password") or "")
    if is_wifi(lan):
        wifi_ssid = wifi_ssid or "jimber"
        if len(wifi_ssid) > 32:
            raise ShareError("Wi-Fi name must be 32 characters or fewer.")
        if not 8 <= len(wifi_password) <= 63:
            raise ShareError("Wi-Fi password must be 8–63 characters.")
        if wifi_supports_ap(lan) is False:
            raise ShareError(f"{lan} does not support access-point (AP) mode.")

    clean.update(
        {
            "wan": wan,
            "lan": lan,
            "lan_ip": str(lan_ip),
            "prefix": prefix,
            "dhcp_start": str(start),
            "dhcp_end": str(end),
            "lease_time": lease_time,
            "domain": re.sub(r"[^A-Za-z0-9.-]", "", str(clean.get("domain", "lan"))) or "lan",
            "dns_servers": dns_servers,
            "dhcp_dns": dhcp_dns,
            "wifi_ssid": wifi_ssid,
            "wifi_password": wifi_password,
        }
    )
    return clean


def suggest_config(wan: str | None = None, lan: str | None = None) -> dict:
    """Pick sensible defaults for the given interfaces."""
    cfg = load_config()

    interfaces = list_interfaces()
    names = {i["name"] for i in interfaces}

    if not wan:
        default_dev = next((i["name"] for i in interfaces if i["is_default"]), None)
        wan = default_dev or cfg.get("wan") or ""
    if not lan:
        candidates = [
            i["name"]
            for i in interfaces
            if i["name"] != wan and i["kind"] in ("ethernet", "wifi")
        ]
        lan = (candidates[0] if candidates else "") or cfg.get("lan") or ""

    if wan and wan not in names:
        wan = ""
    if lan and lan not in names:
        lan = ""

    cfg["wan"] = wan
    cfg["lan"] = lan

    if not cfg.get("lan_ip") or cfg.get("lan_ip") == DEFAULT_CONFIG["lan_ip"]:
        cfg["lan_ip"] = _pick_lan_ip(interfaces, exclude={wan, lan})
        cfg["dhcp_start"] = str(ipaddress.ip_address(cfg["lan_ip"]) + 49)
        cfg["dhcp_end"] = str(ipaddress.ip_address(cfg["lan_ip"]) + 199)

    return cfg


def _pick_lan_ip(interfaces, exclude=None) -> str:
    """Avoid clashing with existing networks."""
    exclude = exclude or set()
    used = set()
    for iface in interfaces:
        if iface["name"] in exclude:
            continue
        for addr in iface["addresses"]:
            try:
                used.add(ipaddress.ip_network(addr, strict=False))
            except ValueError:
                pass
    for candidate in ("10.42.0.1", "10.43.0.1", "192.168.50.1", "10.99.0.1"):
        net = ipaddress.ip_network(f"{candidate}/24", strict=False)
        if not any(net.overlaps(other) for other in used if other.version == 4):
            return candidate
    return "10.42.0.1"


# --------------------------------------------------------------------------- #
# NetworkManager profile
# --------------------------------------------------------------------------- #

def profile_name(lan: str) -> str:
    return f"{PROFILE_PREFIX}-{lan}"


def _profile_active(name: str) -> bool:
    out = run(["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"], check=False).stdout
    return name in out.splitlines()


def _profile_exists(name: str) -> bool:
    rc = run(["nmcli", "connection", "show", name], check=False).returncode
    return rc == 0


def _share_profiles() -> list[str]:
    out = run(["nmcli", "-t", "-f", "NAME", "connection", "show"], check=False).stdout
    return [line for line in out.splitlines() if line.startswith(f"{PROFILE_PREFIX}-")]


def remove_stale_profiles(keep: str | None = None) -> None:
    """Tear down internet-share profiles other than *keep*.

    Every profile we create puts the same LAN address (e.g. 10.42.0.1/24) on
    its interface. A leftover profile from a previous run therefore keeps a
    second route to the LAN subnet, and if that interface has a lower metric
    (sooner or later, or is simply down) the kernel picks it for replies to
    clients. Return traffic then leaves a dead link and is dropped, which
    looks exactly like "DHCP works but there is no internet/DNS/ICMP".
    """
    for name in _share_profiles():
        if name == keep:
            continue
        run(["nmcli", "connection", "down", name], check=False)
        run(["nmcli", "connection", "delete", name], check=False)


def _ensure_profile(cfg: dict) -> str:
    name = profile_name(cfg["lan"])
    address = f"{cfg['lan_ip']}/{cfg['prefix']}"
    wifi = is_wifi(cfg["lan"])
    wanted_type = "802-11-wireless" if wifi else "802-3-ethernet"

    if _profile_exists(name):
        current_type = run(
            ["nmcli", "-g", "connection.type", "connection", "show", name], check=False
        ).stdout.strip()
        if current_type and current_type != wanted_type:
            # The link changed between wired and wireless; rebuild the profile.
            run(["nmcli", "connection", "delete", name], check=False)

    wireless = []
    if wifi:
        wireless = [
            "802-11-wireless.mode", "ap",
            "802-11-wireless.ssid", cfg["wifi_ssid"],
            "802-11-wireless-security.key-mgmt", "wpa-psk",
            "802-11-wireless-security.psk", cfg["wifi_password"],
        ]

    common = [
        "connection.interface-name", cfg["lan"],
        "connection.autoconnect", "no",
        "ipv4.method", "manual",
        "ipv4.addresses", address,
        "ipv4.gateway", "",
        "ipv4.dns", "",
        "ipv4.routes", "",
        "ipv4.never-default", "yes",
        "ipv6.method", "disabled",
    ]

    if _profile_exists(name):
        run(["nmcli", "connection", "modify", name] + wireless + common)
    else:
        run(
            [
                "nmcli", "connection", "add",
                "type", "wifi" if wifi else "ethernet",
                "ifname", cfg["lan"],
                "con-name", name,
            ] + wireless + common
        )
    return name


# --------------------------------------------------------------------------- #
# Firewall / forwarding
# --------------------------------------------------------------------------- #

def _iptables(*args, table: str | None = None, check: bool = False):
    cmd = ["iptables"]
    if table:
        cmd += ["-t", table]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _chain_exists(chain: str, table: str | None = None) -> bool:
    return _iptables("-n", "-L", chain, table=table).returncode == 0


def install_firewall(cfg: dict) -> None:
    net = network_cidr(cfg)
    lan, wan = cfg["lan"], cfg["wan"]

    if not _chain_exists(CHAIN_FWD):
        _iptables("-N", CHAIN_FWD)
    for parent in ("FORWARD",):
        while _iptables("-C", parent, "-j", CHAIN_FWD).returncode != 0:
            _iptables("-I", parent, "1", "-j", CHAIN_FWD)
    _iptables("-F", CHAIN_FWD)
    _iptables("-A", CHAIN_FWD, "-i", lan, "-o", wan, "-s", net, "-j", "ACCEPT")
    _iptables("-A", CHAIN_FWD, "-i", wan, "-o", lan, "-d", net,
              "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT")

    if not _chain_exists(CHAIN_NAT, table="nat"):
        _iptables("-N", CHAIN_NAT, table="nat")
    while _iptables("-C", "POSTROUTING", "-j", CHAIN_NAT, table="nat").returncode != 0:
        _iptables("-I", "POSTROUTING", "1", "-j", CHAIN_NAT, table="nat")
    _iptables("-F", CHAIN_NAT, table="nat")
    _iptables("-A", CHAIN_NAT, "-o", wan, "-s", net, "-j", "MASQUERADE", table="nat")


def remove_firewall() -> None:
    for chain, parent, table in (
        (CHAIN_FWD, "FORWARD", None),
        (CHAIN_NAT, "POSTROUTING", "nat"),
    ):
        if not _chain_exists(chain, table=table):
            continue
        while _iptables("-C", parent, "-j", chain, table=table).returncode == 0:
            _iptables("-D", parent, "-j", chain, table=table)
        _iptables("-F", chain, table=table)
        _iptables("-X", chain, table=table)


def _enable_forwarding() -> None:
    current = _read_text(Path("/proc/sys/net/ipv4/ip_forward")).strip() or "0"
    if not IPFWD_STATE.exists():
        _write_text(IPFWD_STATE, current + "\n")
    _write_text(Path("/proc/sys/net/ipv4/ip_forward"), "1\n")


def _restore_forwarding() -> None:
    if IPFWD_STATE.exists():
        value = _read_text(IPFWD_STATE).strip() or "0"
        _write_text(Path("/proc/sys/net/ipv4/ip_forward"), value + "\n")
        try:
            IPFWD_STATE.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# dnsmasq (DHCP / DNS for the LAN)
# --------------------------------------------------------------------------- #

def load_reservations() -> list[dict]:
    if RESERVATIONS_FILE.exists():
        try:
            data = json.loads(RESERVATIONS_FILE.read_text())
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_reservations(items: list[dict]) -> None:
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    _write_text(RESERVATIONS_FILE, json.dumps(items, indent=2) + "\n")


def _dnsmasq_config_text(cfg: dict) -> str:
    net = ipaddress.ip_network(f"{cfg['lan_ip']}/{cfg['prefix']}", strict=False)
    lines = [
        "# Generated by internet-share - do not edit by hand.",
        f"interface={cfg['lan']}",
        "bind-dynamic",
        "dhcp-authoritative",
        "log-dhcp",
        f"log-facility={LOG_FILE}",
        f"pid-file={PID_FILE}",
        f"dhcp-leasefile={LEASE_FILE}",
        f"domain={cfg['domain']}",
        f"dhcp-range={cfg['dhcp_start']},{cfg['dhcp_end']},{cfg['lease_time']}",
        f"dhcp-option=option:router,{cfg['lan_ip']}",
        "dhcp-option=option:dns-server," + ",".join(cfg.get("dhcp_dns") or [cfg["lan_ip"]]),
        f"dhcp-option=option:domain-name,{cfg['domain']}",
    ]

    if cfg.get("dns_servers"):
        lines.append("no-resolv")
        for server in cfg["dns_servers"]:
            lines.append(f"server={server}")
    else:
        resolved = Path("/run/systemd/resolve/resolv.conf")
        lines.append(f"resolv-file={resolved if resolved.exists() else '/etc/resolv.conf'}")

    for item in load_reservations():
        mac = item.get("mac", "")
        ip = item.get("ip", "")
        host = item.get("hostname", "") or ""
        if not mac or not ip:
            continue
        entry = f"dhcp-host={mac},{ip}"
        if host:
            entry += f",{host}"
        if ipaddress.ip_address(ip) not in net:
            continue
        lines.append(entry)

    return "\n".join(lines) + "\n"


def _dnsmasq_pid():
    pid = _read_text(PID_FILE).strip()
    if pid.isdigit():
        return int(pid)
    return None


def dnsmasq_running() -> bool:
    pid = _dnsmasq_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _start_dnsmasq() -> None:
    _stop_dnsmasq()
    run(["dnsmasq", f"--conf-file={DNSMASQ_CONF}"])


def _stop_dnsmasq() -> None:
    pid = _dnsmasq_pid()
    if pid is not None:
        try:
            os.kill(pid, signal.SIGTERM)
            for _ in range(20):
                try:
                    os.kill(pid, 0)
                except OSError:
                    break
                time.sleep(0.05)
        except OSError:
            pass
    if PID_FILE.exists():
        try:
            PID_FILE.unlink()
        except OSError:
            pass


def _reload_dnsmasq() -> None:
    pid = _dnsmasq_pid()
    if pid is not None:
        try:
            os.kill(pid, signal.SIGHUP)
            return
        except OSError:
            pass


def write_dhcp_config(cfg: dict) -> None:
    DNSMASQ_CONF.parent.mkdir(parents=True, exist_ok=True)
    _write_text(DNSMASQ_CONF, _dnsmasq_config_text(cfg))


def restart_dhcp(cfg: dict) -> None:
    ensure_dirs()
    write_dhcp_config(cfg)
    result = run(["dnsmasq", "--test", f"--conf-file={DNSMASQ_CONF}"], check=False)
    if result.returncode != 0:
        raise ShareError(f"DHCP config invalid: {(result.stderr or result.stdout).strip()}")
    _start_dnsmasq()


# --------------------------------------------------------------------------- #
# Leases
# --------------------------------------------------------------------------- #

def list_leases() -> list[dict]:
    now = time.time()
    reservations = {(r.get("mac") or "").lower(): r for r in load_reservations()}
    leases = []
    for line in _read_text(LEASE_FILE).splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            expiry = int(parts[0])
        except ValueError:
            continue
        mac = parts[1]
        ip = parts[2]
        hostname = parts[3] if parts[3] != "*" else ""
        client_id = parts[4] if len(parts) > 4 else ""
        remaining = None if expiry == 0 else int(expiry - now)
        leases.append(
            {
                "expiry": expiry,
                "expires_in": remaining,
                "mac": mac,
                "ip": ip,
                "hostname": hostname,
                "client_id": client_id,
                "active": expiry == 0 or expiry > now,
                "reserved": mac.lower() in reservations,
            }
        )
    leases.sort(key=lambda l: ipaddress.ip_address(l["ip"]))
    return leases


def delete_lease(ip: str | None = None, mac: str | None = None) -> bool:
    if not LEASE_FILE.exists():
        return False
    kept, removed = [], False
    for line in LEASE_FILE.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 4 and (
            (ip and parts[2] == ip) or (mac and parts[1].lower() == mac.lower())
        ):
            removed = True
            continue
        kept.append(line)
    if removed:
        _write_text(LEASE_FILE, "\n".join(kept) + ("\n" if kept else ""))
        _reload_dnsmasq()
    return removed


_PROBE_TTL = 8.0
_probe_cache: dict[str, tuple[float, bool]] = {}

_monitor_started = False
_monitor_lock = threading.Lock()


def _probe_one(ip: str, lan: str, timeout: float = 1.0) -> bool:
    """True if a host answers on the LAN segment.

    Uses a single ARP request (``arping``) which bypasses the kernel
    neighbour cache, so a device that just disappeared is detected within
    the timeout instead of after the ARP state machine gives up.
    """
    wait = max(1, int(round(timeout)))
    if is_root() and which("arping"):
        result = subprocess.run(
            ["arping", "-q", "-c", "1", "-w", str(wait), "-I", lan, ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 1,
            check=False,
        )
        return result.returncode == 0

    # Fallback: ping to force a neighbour lookup, then inspect its state.
    if which("ping"):
        subprocess.run(
            ["ping", "-n", "-q", "-c", "1", "-W", str(wait), "-I", lan, ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 1,
            check=False,
        )
    out = run(["ip", "-j", "neigh", "show", ip, "dev", lan], check=False).stdout
    try:
        entries = json.loads(out or "[]")
    except json.JSONDecodeError:
        entries = []
    for entry in entries:
        states = entry.get("state") or []
        if entry.get("lladdr") and not any(s in ("FAILED", "INCOMPLETE") for s in states):
            return True
    return False


def _probe_many(ips: list[str], lan: str) -> list[tuple[str, bool]]:
    if not ips:
        return []
    workers = max(1, min(32, len(ips)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda ip: (ip, _probe_one(ip, lan)), ips))
    return results


def leases_with_status() -> list[dict]:
    """Leases annotated with an ``online`` flag (probed and cached)."""
    cfg = load_config()
    lan = cfg.get("lan")
    leases = list_leases()
    if not lan or not leases:
        return leases

    now = time.time()
    # Probe anything we have never seen, and refresh stale entries when the
    # background monitor is not running (e.g. one-shot CLI usage).
    pending = [
        lease["ip"]
        for lease in leases
        if lease["ip"] not in _probe_cache
        or (not _monitor_started and now - _probe_cache[lease["ip"]][0] > _PROBE_TTL)
    ]
    if pending:
        for ip, online in _probe_many(pending, lan):
            _probe_cache[ip] = (now, online)

    for lease in leases:
        cached = _probe_cache.get(lease["ip"])
        lease["online"] = bool(cached[1]) if cached else None
    return leases


def start_monitor(interval: float = 1.0) -> None:
    """Continuously probe leased hosts so the UI updates instantly."""
    global _monitor_started
    with _monitor_lock:
        if _monitor_started:
            return
        _monitor_started = True
    threading.Thread(target=_monitor_loop, args=(interval,), daemon=True).start()


def _monitor_loop(interval: float) -> None:
    while True:
        try:
            if is_active():
                cfg = load_config()
                lan = cfg.get("lan")
                ips = [lease["ip"] for lease in list_leases()]
                if lan and ips:
                    now = time.time()
                    for ip, online in _probe_many(ips, lan):
                        _probe_cache[ip] = (now, online)
        except Exception:
            pass
        time.sleep(interval)


def add_reservation(mac: str, ip: str, hostname: str = "") -> list[dict]:
    try:
        mac = mac.strip().lower()
        ip = str(ipaddress.ip_address(ip.strip()))
    except ValueError as exc:
        raise ShareError(f"Invalid reservation: {exc}") from exc
    if not re.fullmatch(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", mac):
        raise ShareError("Enter a valid MAC address (aa:bb:cc:dd:ee:ff).")

    items = [r for r in load_reservations() if r.get("mac", "").lower() != mac]
    items.append({"mac": mac, "ip": ip, "hostname": hostname.strip()})
    items.sort(key=lambda r: ipaddress.ip_address(r["ip"]))
    save_reservations(items)
    if is_active():
        restart_dhcp(load_config())
    return items


def remove_reservation(mac: str) -> list[dict]:
    items = [r for r in load_reservations() if r.get("mac", "").lower() != mac.lower()]
    save_reservations(items)
    if is_active():
        restart_dhcp(load_config())
    return items


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #

def check_dependencies() -> None:
    for prog in ("nmcli", "dnsmasq", "iptables", "ip"):
        if not which(prog):
            raise ShareError(f"{prog} is required but was not found in PATH.")


def is_active() -> bool:
    cfg = load_config()
    lan = cfg.get("lan")
    if not lan:
        return False
    return _profile_active(profile_name(lan)) and dnsmasq_running()


def start(cfg: dict | None = None) -> dict:
    require_root()
    check_dependencies()
    ensure_dirs()

    cfg = validate_config(cfg or load_config())

    route = _default_route()
    if route.get("dev") != cfg["wan"]:
        # WAN is selectable, but warn only if there is no connectivity at all
        if not route:
            raise ShareError("No default internet route found. Are you online?")

    start_time = time.time()
    name = _ensure_profile(cfg)
    remove_stale_profiles(keep=name)
    run(["nmcli", "connection", "down", name], check=False)
    run(["nmcli", "connection", "up", name, "ifname", cfg["lan"]])
    _enable_forwarding()
    install_firewall(cfg)
    restart_dhcp(cfg)
    save_config(cfg)
    try:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        _write_text(RUN_DIR / "started", f"{int(start_time)}\n")
    except OSError:
        pass
    return status()


def stop() -> dict:
    require_root()

    _stop_dnsmasq()
    remove_firewall()
    _restore_forwarding()
    remove_stale_profiles()

    for path in (RUN_DIR / "started", PID_FILE):
        try:
            path.unlink()
        except OSError:
            pass

    return status()


def status() -> dict:
    cfg = effective_config()
    active = is_active()
    started_at = None
    try:
        started_at = int(_read_text(RUN_DIR / "started").strip())
    except (ValueError, OSError):
        started_at = None

    leases = leases_with_status() if active else []
    net = None
    if cfg.get("lan_ip"):
        try:
            net = network_cidr(cfg)
        except ValueError:
            net = None

    return {
        "active": active,
        "config": cfg,
        "network": net,
        "leases": leases,
        "reservations": load_reservations(),
        "started_at": started_at,
        "dnsmasq_running": dnsmasq_running(),
    }
