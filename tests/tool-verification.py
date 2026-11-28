#!/usr/bin/env python3
"""Exercise fresh-session checks and reversible duplicate cleanup offline."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, script):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / script)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


verify = module("verify_tools", "verify-tools.py")
reconcile = module("reconcile_tools", "reconcile-tools.py")


class Tools(unittest.TestCase):
    def test_symlink_aliases_and_identical_expose_copies_are_not_duplicates(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            for name in ("a", "b", "c"):
                (root / name).mkdir()
            a = root / "a/tool"
            a.write_text("#!/bin/sh\nexit 0\n")
            a.chmod(0o700)
            (root / "b/tool").symlink_to(a)
            c = root / "c/tool"
            c.write_bytes(a.read_bytes())
            c.chmod(0o700)
            candidates = verify.candidates("tool", os.pathsep.join(str(root / n) for n in ("a", "b", "c")))
            self.assertEqual(len(candidates), 2)
            self.assertTrue(verify.equivalent(candidates))
            c.write_text("#!/bin/sh\nexit 1\n")
            self.assertFalse(verify.equivalent(candidates))

    def test_launcher_retirement_requires_replacement_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as work, patch.object(Path, "home", return_value=Path(work)):
            home = Path(work)
            legacy = home / "legacy/tool"
            canonical = home / "managed/tool"
            legacy.parent.mkdir()
            legacy.write_text("legacy launcher")
            backup = home / "backups/private"
            with self.assertRaises(RuntimeError):
                reconcile.retire(legacy, canonical, backup)
            self.assertTrue(legacy.exists())
            canonical.parent.mkdir()
            canonical.write_text("managed launcher")
            canonical.chmod(0o700)
            self.assertTrue(reconcile.retire(legacy, canonical, backup))
            self.assertEqual((backup / "legacy/tool").read_text(), "legacy launcher")
            self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
            self.assertEqual((backup / "legacy/tool").stat().st_mode & 0o777, 0o600)
            self.assertFalse(reconcile.retire(legacy, canonical, backup))

    def test_fresh_shell_diagnostics_never_leak_startup_output(self):
        with tempfile.TemporaryDirectory() as work:
            fake = Path(work) / "zsh"
            fake.write_text('#!/bin/sh\necho "private startup fixture"\necho "private diagnostic fixture" >&2\nexit 1\n')
            fake.chmod(0o700)
            env = dict(os.environ, PATH=work + os.pathsep + os.defpath)
            result = subprocess.run([sys.executable, str(ROOT / "scripts/verify-tools.py")],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("private startup fixture", result.stdout + result.stderr)
            self.assertNotIn("private diagnostic fixture", result.stdout + result.stderr)

    def test_unmanaged_system_launcher_is_backed_up_before_removal(self):
        with tempfile.TemporaryDirectory() as work:
            home = Path(work)
            old, new, backup = home / "old", home / "new", home / "private"
            old.write_text("legacy")
            new.write_text("managed")
            new.chmod(0o700)
            with patch.object(reconcile.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
                with self.assertRaises(RuntimeError):
                    reconcile.retire_system_launcher(old, new, backup)
            self.assertTrue(old.exists())

            def command(args, **kwargs):
                if args[0] == "pacman":
                    return subprocess.CompletedProcess(args, 1)
                self.assertEqual(args, ["sudo", "rm", "--", str(old)])
                self.assertEqual((backup / "system-old").read_text(), "legacy")
                old.unlink()
                return subprocess.CompletedProcess(args, 0)

            with patch.object(reconcile.subprocess, "run", side_effect=command):
                self.assertTrue(reconcile.retire_system_launcher(old, new, backup))
                self.assertFalse(reconcile.retire_system_launcher(old, new, backup))
            self.assertEqual((backup / "system-old").stat().st_mode & 0o777, 0o600)

    def test_npm_commands_cover_inventory_and_installer_invokes_final_checks(self):
        self.assertEqual(set(verify.inventory("npm")), set(verify.NPM))
        for name in ("install.sh", "update.sh"):
            text = (ROOT / name).read_text()
            self.assertIn('scripts/verify-tools.py', text)
            self.assertIn('scripts/reconcile-tools.py', text)
            self.assertIn('scripts/package-policy.sh', text)
        self.assertNotIn('read -rp', (ROOT / "install.sh").read_text())


if __name__ == "__main__":
    unittest.main()
