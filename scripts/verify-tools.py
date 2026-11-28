#!/usr/bin/env python3
"""Verify managed command availability and shadowing in a fresh Zsh login."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MARKER = "CORE_DOTFILES_TOOL_REPORT="
# Multiple installed interpreters/JDKs are deliberate, not duplicate tool installs.
VERSIONED = {"python", "python-pip", "jdk8-openjdk", "jdk11-openjdk",
             "jdk17-openjdk", "jdk21-openjdk", "jdk-openjdk"}
EXTRA = ("node", "npm", "npx", "rustc", "cargo", "rustup", "bunx", "qemu-system-x86_64", "nxc", "nxcdb",
         "donpapi", "mitm6", "expose", "expose-online", "dotfiles-sync", "dotfiles-skills")
NPM = {"@deepseek-ai/dsh": "dsh", "@openai/codex": "codex",
       "@earendil-works/pi-coding-agent": "pi", "bun": "bun", "@nestjs/cli": "nest"}


def inventory(name):
    return [line.strip() for line in (ROOT / "packages" / (name + ".txt")).read_text().splitlines()
            if line.strip() and not line.startswith("#")]


def candidates(command, path):
    paths = []
    for directory in path.split(os.pathsep):
        if not directory:
            continue
        candidate = Path(directory) / command
        if candidate.is_file() and os.access(candidate, os.X_OK):
            resolved = candidate.resolve()
            if resolved not in paths:
                paths.append(resolved)
    return paths


def equivalent(paths):
    # expose deliberately has identical user and system installations.
    if len(paths) < 2:
        return True
    sizes = {path.stat().st_size for path in paths}
    return len(sizes) == 1 and len({hashlib.sha256(path.read_bytes()).digest() for path in paths}) == 1


def inspect():
    issues, notes = [], []
    installed = subprocess.run(["pacman", "-Qq"], capture_output=True, text=True, check=True).stdout.splitlines()
    installed = set(installed)
    packages = inventory("pacman") + inventory("aur")
    for package in packages:
        if package not in installed:
            issues.append("missing managed package: " + package)
    if "netexec" in installed:
        issues.append("duplicate NetExec channel: remove the old AUR package after pipx installation")
    for legacy, wanted in (("opencode-beta", "opencode-bin"),
                           ("gnome-shell-extension-clipboard-history", "gnome-shell-extension-clipboard-indicator"),
                           ("gnu-netcat", "openbsd-netcat")):
        if legacy in installed:
            issues.append("legacy conflicting package: " + legacy + " (managed replacement: " + wanted + ")")

    available = [p for p in packages if p in installed]
    owned = (subprocess.run(["pacman", "-Ql", *available], capture_output=True, text=True, check=True).stdout
             if available else "")
    commands = {name: "runtime" for name in EXTRA}
    commands.update({NPM[p]: p for p in inventory("npm")})
    commands.update({path.name: "dotfiles" for path in (ROOT / "local-bin/.local/bin").iterdir()
                     if path.is_file() and os.access(path, os.X_OK)})
    for line in owned.splitlines():
        package, _, filename = line.partition(" ")
        path = Path(filename)
        if path.parent in (Path("/usr/bin"), Path("/usr/sbin")) and path.is_file() and os.access(path, os.X_OK):
            commands[path.name] = package
        elif "/docker/cli-plugins/" in filename and path.is_file() and not os.access(path, os.X_OK):
            issues.append("Docker CLI plugin is not executable: " + path.name)
    if os.environ.get("CORE_DOTFILES_NVM_AVAILABLE") != "1":
        issues.append("nvm function is unavailable in the fresh shell")

    checked = 0
    for command, owner in sorted(commands.items()):
        paths = candidates(command, os.environ.get("PATH", ""))
        if not paths:
            issues.append("command unavailable in fresh login: " + command)
            continue
        checked += 1
        if command in {"node", "npm", "npx", "corepack", "rustc", "cargo", "rustdoc", "rustfmt", "cargo-fmt", "cargo-clippy", "clippy-driver"} or owner in VERSIONED:
            continue
        if not equivalent(paths):
            issues.append("competing executables on PATH: " + command + " (" + str(len(paths)) + " distinct installations)")
    notes.append(str(checked) + " managed commands available in a fresh Zsh login")
    return {"issues": issues, "notes": notes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inside-login", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.inside_login:
        print(MARKER + json.dumps(inspect()))
        return 0
    zsh = shutil.which("zsh")
    if not zsh:
        print("[FAIL] zsh is missing; cannot verify a fresh login")
        return 1
    env = {key: value for key, value in os.environ.items()
           if key in {"HOME", "USER", "LOGNAME", "TERM", "DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR",
                      "DBUS_SESSION_BUS_ADDRESS", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"}}
    env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/bin:/bin"
    env["POWERLEVEL9K_INSTANT_PROMPT"] = "off"
    command = "(( $+functions[nvm] )) && export CORE_DOTFILES_NVM_AVAILABLE=1; exec " + shlex.join(
        [sys.executable, "-B", str(Path(__file__).resolve()), "--inside-login"])
    try:
        result = subprocess.run([zsh, "-lic", command], env=env, capture_output=True, text=True, timeout=120)
        # Startup scripts can print private data. Never forward their raw output.
        reports = [line[len(MARKER):] for line in result.stdout.splitlines() if line.startswith(MARKER)]
        if result.returncode or len(reports) != 1:
            raise ValueError()
        report = json.loads(reports[0])
        if re.search(r"command not found|no such file or directory|parse error", result.stderr, re.IGNORECASE):
            report["issues"].append("fresh shell reported startup errors; diagnostic values withheld")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        print("[FAIL] Fresh-shell verification could not finish; startup output withheld")
        return 1
    for note in report["notes"]:
        print("[OK] " + note)
    for issue in report["issues"]:
        print("[FAIL] " + issue)
    print(str(len(report["issues"])) + " tool availability/duplication issues")
    return int(bool(report["issues"]))


if __name__ == "__main__":
    sys.exit(main())
