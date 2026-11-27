#!/usr/bin/env python3
"""Test DSH package management without network or npm execution."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("install_dsh", ROOT / "scripts/install-dsh.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class DSH(unittest.TestCase):
    def test_install_skip_and_update(self):
        with tempfile.TemporaryDirectory() as work:
            home = Path(work)
            prefix = home / ".local/share/core-dotfiles/dsh"
            version = ["1.2.3"]
            installs = []

            def registry(request, **kwargs):
                self.assertEqual(request.full_url, "https://registry.npmjs.org/@deepseek-ai%2fdsh/latest")
                return io.BytesIO(json.dumps({"name": installer.PACKAGE, "version": version[0]}).encode())

            def command(args, **kwargs):
                if args == ["node", "--version"]:
                    return subprocess.CompletedProcess(args, 0, b"v24.9.0\n")
                self.assertEqual(args[:5], ["npm", "install", "--global", "--prefix", str(prefix)])
                self.assertEqual(args[-1], installer.PACKAGE + "@" + version[0])
                installs.append(args)
                package = prefix / "lib/node_modules/@deepseek-ai/dsh/package.json"
                package.parent.mkdir(parents=True, exist_ok=True)
                package.write_text(json.dumps({"name": installer.PACKAGE, "version": version[0]}))
                binary = prefix / "bin/dsh"
                binary.parent.mkdir(exist_ok=True)
                binary.write_text("#!/bin/sh\nexit 0\n")
                binary.chmod(0o700)
                return subprocess.CompletedProcess(args, 0)

            old_mask = os.umask(0o077)
            self.addCleanup(os.umask, old_mask)
            with patch.object(Path, "home", return_value=home), patch.object(sys, "argv", ["install-dsh"]), \
                 patch.object(installer.shutil, "which", return_value="fixture"), \
                 patch.object(installer.urllib.request, "urlopen", side_effect=registry), \
                 patch.object(installer.subprocess, "run", side_effect=command), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(installer.main(), 0)
                for _ in range(99):
                    self.assertEqual(installer.main(), 0)
                self.assertEqual(len(installs), 1)
                version[0] = "1.2.4-rc.1"
                self.assertEqual(installer.main(), 0)
                self.assertEqual(len(installs), 2)
                self.assertEqual(prefix.stat().st_mode & 0o777, 0o700)
                self.assertEqual((prefix / "install.log").stat().st_mode & 0o777, 0o600)

    def test_dry_run_and_old_node(self):
        with patch.object(sys, "argv", ["install-dsh", "--dry-run"]), \
             patch.object(installer.urllib.request, "urlopen", side_effect=AssertionError("network")), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.main(), 0)
        with patch.object(sys, "argv", ["install-dsh"]), \
             patch.object(installer.shutil, "which", return_value="fixture"), \
             patch.object(installer.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"v22.0.0\n")):
            with self.assertRaisesRegex(RuntimeError, "Node.js"):
                installer.main()

    def test_launcher_forwards_arguments(self):
        with tempfile.TemporaryDirectory() as work:
            binary = Path(work) / ".local/share/core-dotfiles/dsh/bin/dsh"
            binary.parent.mkdir(parents=True)
            binary.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            binary.chmod(0o700)
            result = subprocess.run(["bash", str(ROOT / "local-bin/.local/bin/dsh"), "web", "--no-open"],
                                    env={"HOME": work, "PATH": os.defpath}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "web\n--no-open\n")


if __name__ == "__main__":
    unittest.main()
