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
    def test_api_key_files_are_rejected_even_without_a_known_token_format(self):
        with tempfile.TemporaryDirectory(prefix="core-dotfiles-key-file-") as directory:
            repo = Path(directory)
            (repo / "scripts").mkdir()
            scanner = repo / "scripts/check-secrets.py"
            shutil.copyfile(ROOT / "scripts/check-secrets.py", scanner)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            value = secrets.token_hex(24)
            (repo / "api_key").write_text(value)
            subprocess.run(["git", "-C", str(repo), "add", "api_key"], check=True)
            result = subprocess.run([sys.executable, str(scanner), "--staged"], capture_output=True, text=True)
            if value in result.stdout + result.stderr:
                self.fail("The scanner exposed a credential file's contents")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("private credential filename", result.stdout)

    def test_unquoted_shell_credentials_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="core-dotfiles-unquoted-check-") as directory:
            repo = Path(directory)
            (repo / "scripts").mkdir()
            scanner = repo / "scripts/check-secrets.py"
            shutil.copyfile(ROOT / "scripts/check-secrets.py", scanner)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            token = secrets.token_hex(24)
            source = repo / ".zshrc"
            source.write_text("export EXAMPLE_" + "PASSWORD" + chr(61) + token + "\n")
            subprocess.run(["git", "-C", str(repo), "add", ".zshrc"], check=True)
            result = subprocess.run([sys.executable, str(scanner), "--staged"], capture_output=True, text=True)
            if token in result.stdout + result.stderr:
                self.fail("The scanner exposed an unquoted credential")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unquoted-shell-credential", result.stdout)

    def test_commit_messages_are_checked_without_revealing_values(self):
        with tempfile.TemporaryDirectory(prefix="core-dotfiles-message-check-") as directory:
            repo = Path(directory)
            (repo / "scripts").mkdir()
            scanner = repo / "scripts/check-secrets.py"
            shutil.copyfile(ROOT / "scripts/check-secrets.py", scanner)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            token = "sk-proj-" + secrets.token_hex(32)
            commit = subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test",
                                     "-c", "user.email=test@example.invalid", "commit", "-qm",
                                     "Synthetic leaked credential: " + token], capture_output=True)
            self.assertEqual(commit.returncode, 0, "Could not create temporary test commit")
            result = subprocess.run([sys.executable, str(scanner), "--history"], capture_output=True, text=True)
            if token in result.stdout + result.stderr:
                self.fail("The scanner exposed a commit-message credential")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("commit-message", result.stdout)

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
