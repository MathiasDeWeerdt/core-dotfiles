#!/usr/bin/env python3
"""Retire known duplicate tool launchers after managed replacements exist."""
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def retire(path, canonical, backup):
    if not (path.exists() or path.is_symlink()):
        return False
    if not canonical.is_file() or not os.access(canonical, os.X_OK):
        raise RuntimeError("Managed replacement is not ready; legacy launcher preserved")
    # Same canonical file through two symlinks is not a competing installation.
    if path.resolve() == canonical.resolve():
        return False
    if path.is_dir() and not path.is_symlink():
        raise RuntimeError("Unexpected launcher directory; preserved")
    relative = path.relative_to(Path.home())
    backup.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = backup / relative
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Move only the launcher; preserve private auth, preferences and app data.
    shutil.move(str(path), str(destination))
    if not destination.is_symlink():
        destination.chmod(0o600)
    print("Retired duplicate launcher: " + path.name + " (private backup saved)")
    return True


def retire_system_launcher(path, canonical, backup):
    if not (path.exists() or path.is_symlink()):
        return False
    if not canonical.is_file() or not os.access(canonical, os.X_OK):
        raise RuntimeError("Managed launcher is not ready; system launcher preserved")
    if path.resolve() == canonical.resolve():
        return False
    if subprocess.run(["pacman", "-Qo", str(path)], capture_output=True).returncode == 0:
        raise RuntimeError("System launcher belongs to a package; preserved")
    backup.mkdir(parents=True, exist_ok=True, mode=0o700)
    saved = backup / ("system-" + path.name)
    if path.is_symlink():
        saved.symlink_to(os.readlink(path))
    else:
        fd = os.open(saved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as output, path.open("rb") as source:
            shutil.copyfileobj(source, output)
    subprocess.run(["sudo", "rm", "--", str(path)], check=True)
    print("Retired duplicate system launcher: " + path.name + " (private backup saved)")
    return True


def main():
    home = Path.home()
    backup = home / ".local/state/core-dotfiles/backups" / ("tool-launchers-" + str(time.time_ns()))
    if backup.resolve().is_relative_to(ROOT):
        raise RuntimeError("Private backups must stay outside the public repository")
    for package, command, paths in (
        ("opencode-bin", "opencode", (home / ".opencode/bin/opencode", home / ".local/bin/opencode")),
        ("claude-code", "claude", (home / ".local/bin/claude",)),
        ("python-pipx", "pipx", (home / ".local/bin/pipx",)),
    ):
        if subprocess.run(["pacman", "-Q", package], capture_output=True).returncode == 0:
            for path in paths:
                retire(path, Path("/usr/bin") / command, backup)
    # This legacy manual launcher competes with the repository's stowed wrapper.
    retire_system_launcher(Path("/usr/local/bin/burpsuitepro"), home / ".local/bin/burpsuitepro", backup)
    if subprocess.run(["pacman", "-Q", "impacket"], capture_output=True).returncode == 0:
        # Let pipx remove its own standalone duplicate. Per-tool dependency
        # environments (NetExec, Certipy, etc.) remain isolated and intact.
        import json
        pipx = "/usr/bin/pipx"
        result = subprocess.run([pipx, "list", "--json"], capture_output=True, text=True, check=True)
        if "impacket" in json.loads(result.stdout).get("venvs", {}):
            subprocess.run([pipx, "uninstall", "impacket"], check=True)
            print("Removed standalone pipx Impacket duplicate; Arch package retained")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        raise SystemExit("Tool reconciliation failed; private diagnostic values withheld")
