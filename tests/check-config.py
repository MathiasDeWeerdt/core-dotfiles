#!/usr/bin/env python3
"""Offline checks against disposable private configuration."""
import hashlib
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Checks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.env = {"HOME": str(self.home), "PATH": os.defpath}
        self.secret = secrets.token_hex(24)

    def write(self, relative, content, mode=0o600):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(content)
        path.chmod(mode)
        return path

    def run_check(self, *args, code=0):
        before = self.snapshot()
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/check-config.py"), *args],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(before, self.snapshot(), "checker changed private configuration")
        self.assertNotIn(self.secret, result.stdout + result.stderr)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result.stdout

    def snapshot(self):
        return {str(p): (p.lstat().st_mode, p.lstat().st_mtime_ns,
                        os.readlink(p) if p.is_symlink() else hashlib.sha256(p.read_bytes()).hexdigest())
                for p in self.home.rglob("*") if p.is_file() or p.is_symlink()}

    def test_missing_optional_and_required(self):
        self.run_check()
        self.run_check("--require", "expose,dehashed,ssh,dsh,shell", code=1)
        self.run_check("--require", self.secret, code=2)
        self.run_check("--" + self.secret, code=2)

    def test_valid_files_empty_environment_precedence_and_permissions(self):
        path = self.write(".config/expose/online.env", 'EXPOSE_AUTH_PASSWORD="' + self.secret + '"\n')
        self.write(".config/dehashed/api_key", self.secret + "\n")
        self.env["DEHASHED_API_KEY"] = ""
        self.run_check("--require", "expose,dehashed")
        self.env["EXPOSE_AUTH_PASSWORD"] = ""
        self.run_check("--require", "expose", code=1)
        del self.env["EXPOSE_AUTH_PASSWORD"]
        path.chmod(0o644)
        self.run_check(code=1)
        path.chmod(0o600)
        path.parent.chmod(0o755)
        self.run_check(code=1)

    def test_no_execution_or_secret_logging(self):
        marker = self.home / "executed"
        self.write(".config/core-dotfiles/secrets.zsh",
                   'export DEEPSEEK_API_KEY="$(touch ' + str(marker) + ')"\n' +
                   'export GITHUB_PERSONAL_ACCESS_TOKEN="' + self.secret + '\n')
        self.run_check()
        self.assertFalse(marker.exists())
        self.run_check("--strict", code=1)

    def test_unused_provider_keys_are_ignored(self):
        ignored = ("COPILOT_PROVIDER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY")
        missing = self.run_check("--strict")
        for name in ignored:
            self.env[name] = self.secret
        declarations = "".join(f'export {name}="$UNUSED"\n' for name in ignored)
        self.write(".config/core-dotfiles/secrets.zsh", declarations)
        self.write(".dsh/.env", declarations)
        present = self.run_check("--strict", "--require", "dsh", code=1)
        self.assertIn("[FAIL] DSH authentication", present)
        self.assertIn("0 warnings.", present)
        for name in ignored:
            self.assertNotIn(name, missing + present)

    def test_symlink_and_repository_override(self):
        path = self.write(".config/dehashed/api_key", self.secret)
        outside = self.write("actual-key", self.secret)
        path.unlink()
        path.symlink_to(outside)
        self.run_check(code=1)
        path.unlink()
        self.env["EXPOSE_ONLINE_CONFIG"] = str(ROOT / "nonexistent-private-config")
        self.run_check(code=1)

    def test_managed_dsh_store_and_native_private_metadata(self):
        self.write(".dsh/.credentials.yaml", self.secret)
        self.write(".ssh/id_fixture", self.secret)
        self.write(".memory.md", self.secret)
        self.run_check("--require", "dsh,ssh")
        (self.home / ".dsh/.credentials.yaml").chmod(0o644)
        self.run_check(code=1)

    def test_dsh_github_token_is_not_model_auth(self):
        self.env["GITHUB_PERSONAL_ACCESS_TOKEN"] = self.secret
        self.run_check("--require", "dsh", code=1)
        self.env["DEEPSEEK_API_KEY"] = self.secret
        self.run_check("--require", "dsh")

    def test_malformed_manifest_values_withheld(self):
        self.write(".config/core-dotfiles/skills.local.json", self.secret)
        self.run_check(code=1)


if __name__ == "__main__":
    unittest.main()
