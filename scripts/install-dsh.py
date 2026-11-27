#!/usr/bin/env python3
"""Install/update the official DSH npm package in a user-owned prefix."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "@deepseek-ai/dsh"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        print("Would install/update official @deepseek-ai/dsh in a user-owned prefix; no server starts.")
        return 0
    prefix = Path.home() / ".local/share/core-dotfiles/dsh"
    if prefix.resolve().is_relative_to(ROOT):
        raise RuntimeError("DSH package storage must be outside the public repository")
    if not shutil.which("node") or not shutil.which("npm"):
        raise RuntimeError("DSH needs Node.js >=24.9 and npm; run the full installer first")
    node = subprocess.run(["node", "--version"], capture_output=True, timeout=10)
    match = re.fullmatch(rb"v(\d+)\.(\d+)\.(\d+)\s*", node.stdout)
    if node.returncode or not match or tuple(map(int, match.groups())) < (24, 9, 0):
        raise RuntimeError("DSH requires Node.js >=24.9")
    request = urllib.request.Request("https://registry.npmjs.org/@deepseek-ai%2fdsh/latest",
                                     headers={"User-Agent": "core-dotfiles-dsh"})
    with urllib.request.urlopen(request, timeout=30) as response:
        metadata = json.load(response)
    version = metadata.get("version", "")
    if metadata.get("name") != PACKAGE or not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", version):
        raise RuntimeError("Invalid official DSH package metadata")
    os.umask(0o077)
    prefix.mkdir(parents=True, exist_ok=True, mode=0o700)
    installed = prefix / "lib/node_modules/@deepseek-ai/dsh/package.json"
    executable = prefix / "bin/dsh"
    with (prefix / ".install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = json.loads(installed.read_text()) if installed.exists() else {}
        if current.get("name") == PACKAGE and current.get("version") == version and executable.is_file() and os.access(executable, os.X_OK):
            print("DSH " + version + " already installed in the managed user prefix.")
            return 0
        # npm verifies the registry package's integrity. No application start or
        # model configuration is performed; DSH_HOME and credentials stay private.
        with (prefix / "install.log").open("w") as log:
            result = subprocess.run(["npm", "install", "--global", "--prefix", str(prefix),
                                     "--registry=https://registry.npmjs.org", "--no-audit", "--no-fund", PACKAGE + "@" + version],
                                    stdout=log, stderr=subprocess.STDOUT, timeout=600)
        if result.returncode:
            raise RuntimeError("DSH installation failed; inspect its private install.log")
        current = json.loads(installed.read_text())
        if current.get("name") != PACKAGE or current.get("version") != version or not executable.is_file() or not os.access(executable, os.X_OK):
            raise RuntimeError("DSH installation verification failed")
        print("Installed official DSH " + version + "; launch with dsh web when ready.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except Exception:
        print("DSH setup failed; diagnostic values withheld. Existing DSH credentials were not changed.", file=sys.stderr)
        sys.exit(1)
