#!/usr/bin/env python3
"""Verify that commit checks scan staged bytes and never expose values."""
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SecretChecks(unittest.TestCase):
    def test_index_and_worktree_are_checked_independently(self):
        with tempfile.TemporaryDirectory(prefix="core-dotfiles-secrets-") as directory:
            repo = Path(directory)
            (repo / "scripts").mkdir()
            scanner = repo / "scripts/check-secrets.py"
            shutil.copyfile(ROOT / "scripts/check-secrets.py", scanner)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            source = repo / ".zshrc"
            source.write_text('export API_KEY="$EXTERNAL_KEY"\n')
            subprocess.run(["git", "-C", str(repo), "add", ".zshrc"], check=True)
            # A synthetic test token exists only in this disposable repository.
            token = "sk-proj-" + secrets.token_hex(32)
            source.write_text('export API_KEY="' + token + '"\n')
            source.chmod(0o600)

            def check(staged):
                result = subprocess.run([sys.executable, str(scanner), *(["--staged"] if staged else [])], capture_output=True, text=True)
                if token in result.stdout + result.stderr:
                    self.fail("The scanner exposed a credential value")
                return result.returncode

            self.assertNotEqual(check(False), 0)
            self.assertEqual(check(True), 0)
            subprocess.run(["git", "-C", str(repo), "add", ".zshrc"], check=True)
            source.write_text('export API_KEY="$EXTERNAL_KEY"\n')
            self.assertEqual(check(False), 0)
            self.assertNotEqual(check(True), 0)


if __name__ == "__main__":
    unittest.main()
