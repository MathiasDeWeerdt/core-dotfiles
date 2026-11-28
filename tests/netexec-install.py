#!/usr/bin/env python3
"""Exercise the real NetExec installer without downloads or tool execution."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Installer(unittest.TestCase):
    def test_latest_commit_idempotence_failure_and_python_migration(self):
        with tempfile.TemporaryDirectory() as work:
            home = Path(work)
            binaries = home / "bin"
            binaries.mkdir()
            stub = binaries / "stub"
            stub.write_text("#!" + sys.executable + "\n" + '''import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
home = pathlib.Path(os.environ['HOME'])
root = home / 'venvs'
metadata = root / 'netexec/pipx_metadata.json'
if name == 'git':
    print(os.environ.get('REVISION', 'a' * 40) + '\\trefs/heads/main')
elif name == 'uv':
    if args[1] == 'find': print(sys.executable)
elif name == 'pacman':
    sys.exit(1)
elif name == 'pipx':
    if args[0] == 'environment':
        print(root if args[-1] == 'PIPX_LOCAL_VENVS' else home / 'apps')
    else:
        with (home / 'calls').open('a') as f: f.write(args[0] + '\\n')
        if os.environ.get('FAIL_INSTALL'): sys.exit(1)
        spec = args[-1] if args[0] == 'install' else json.loads(metadata.read_text())['main_package']['package_or_url']
        version = 'Python 3.12.11' if args[0] == 'reinstall' or not os.environ.get('OLD_PYTHON') else 'Python 3.14.10'
        metadata.parent.mkdir(parents=True, exist_ok=True)
        (metadata.parent / 'bin').mkdir(exist_ok=True)
        (home / 'apps').mkdir(exist_ok=True)
        for app in ('nxc', 'nxcdb', 'NetExec', 'netexec'):
            target = metadata.parent / 'bin' / app
            target.write_text('fixture')
            link = home / 'apps' / app
            if not link.is_symlink(): link.symlink_to(target)
        python = metadata.parent / 'bin/python'
        python.write_text('#!/bin/sh\\necho "' + version + '"\\n')
        python.chmod(0o700)
        metadata.write_text(json.dumps({'main_package': {'package_or_url': spec}, 'python_version': version}))
''')
            stub.chmod(0o700)
            for name in ("git", "uv", "pipx", "pacman"):
                (binaries / name).symlink_to(stub)
            env = {"HOME": work, "PATH": str(binaries) + os.pathsep + os.defpath, "OLD_PYTHON": "1"}

            def run(code=0):
                result = subprocess.run(["bash", str(ROOT / "scripts/install-netexec.sh")],
                                        env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)

            run()
            self.assertEqual((home / "calls").read_text(), "install\nreinstall\n")
            run()
            self.assertEqual((home / "calls").read_text(), "install\nreinstall\n")
            env["REVISION"] = "b" * 40
            del env["OLD_PYTHON"]
            run()
            self.assertEqual((home / "calls").read_text(), "install\nreinstall\ninstall\n")
            env["REVISION"] = "c" * 40
            env["FAIL_INSTALL"] = "1"
            run(1)
            self.assertEqual(json.loads((home / "venvs/netexec/pipx_metadata.json").read_text())["main_package"]["package_or_url"],
                             "git+https://github.com/Pennyw0rth/NetExec@" + "b" * 40)


if __name__ == "__main__":
    unittest.main()
