#!/usr/bin/env python3
"""Exercise synchronization against disposable local Git repositories."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.env = dict(os.environ, HOME=str(self.base), XDG_STATE_HOME=str(self.base / "state"),
                        GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, DOTFILES_SYNC_NOTIFY="0")
        self.remote = self.base / "remote.git"
        self.a = self.base / "a"
        self.b = self.base / "b"
        self.git(self.base, "init", "--bare", str(self.remote))
        self.git(self.base, "clone", str(self.remote), str(self.a))
        self.identity(self.a)
        self.git(self.a, "checkout", "-b", "sync-test")
        (self.a / "scripts").mkdir()
        (self.a / ".githooks").mkdir()
        shutil.copy(ROOT / "scripts/check-secrets.py", self.a / "scripts")
        shutil.copy(ROOT / ".githooks/pre-push", self.a / ".githooks")
        (self.a / "config").write_text("initial\n")
        self.commit(self.a)
        self.git(self.a, "push", "-u", "origin", "sync-test")
        self.git(self.base, "clone", "--branch", "sync-test", str(self.remote), str(self.b))
        self.identity(self.b)
        for repo in (self.a, self.b):
            self.git(repo, "config", "core.hooksPath", ".githooks")

    def identity(self, repo):
        self.git(repo, "config", "user.name", "Sync Test")
        self.git(repo, "config", "user.email", "sync@example.invalid")

    def git(self, repo, *args):
        return subprocess.check_output(["git", "-C", str(repo), *args], env=self.env, stderr=subprocess.DEVNULL).decode().strip()

    def commit(self, repo):
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-m", "Test config change")

    def sync(self, repo, success=True):
        result = subprocess.run([str(ROOT / "local-bin/.local/bin/dotfiles-sync")], cwd=self.base,
                                env=dict(self.env, DOTFILES_DIR=str(repo)), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0 if success else 1, result.stdout + result.stderr)
        return result

    def test_push_pull_and_repeat(self):
        (self.a / "config").write_text("reviewed edit\n")
        self.commit(self.a)
        self.sync(self.a)
        self.sync(self.b)
        self.assertEqual((self.b / "config").read_text(), "reviewed edit\n")
        head = self.git(self.b, "rev-parse", "HEAD")
        self.sync(self.a)
        self.sync(self.b)
        self.assertEqual(head, self.git(self.b, "rev-parse", "HEAD"))

    def test_dirty_checkout_is_preserved(self):
        (self.a / "config").write_text("unreviewed\n")
        head = self.git(self.a, "rev-parse", "HEAD")
        self.sync(self.a, False)
        self.assertEqual(head, self.git(self.a, "rev-parse", "HEAD"))
        self.assertEqual((self.a / "config").read_text(), "unreviewed\n")

    def test_divergence_stops_without_merge(self):
        for repo, content in ((self.a, "device one"), (self.b, "device two")):
            (repo / "config").write_text(content)
            self.commit(repo)
        self.sync(self.a)
        before = self.git(self.b, "rev-parse", "HEAD")
        self.sync(self.b, False)
        self.assertEqual(before, self.git(self.b, "rev-parse", "HEAD"))

    def test_secret_commit_never_pushed(self):
        before = self.git(self.remote, "rev-parse", "refs/heads/sync-test")
        (self.a / "config").write_text("DEPLOY_" + "PASSWORD" + chr(61) + repr("synthetic-test-value") + "\n")
        self.commit(self.a)
        self.sync(self.a, False)
        self.assertEqual(before, self.git(self.remote, "rev-parse", "refs/heads/sync-test"))

    def test_secret_incoming_never_applied(self):
        (self.a / "config").write_text("DEPLOY_" + "PASSWORD" + chr(61) + repr("synthetic-test-value") + "\n")
        self.commit(self.a)
        # Model an upstream commit made on a device that lacks our hook.
        self.git(self.a, "-c", "core.hooksPath=/dev/null", "push")
        before = self.git(self.b, "rev-parse", "HEAD")
        self.sync(self.b, False)
        self.assertEqual(before, self.git(self.b, "rev-parse", "HEAD"))

    def test_missing_hook_or_pending_operation_stops(self):
        self.git(self.a, "config", "core.hooksPath", "/dev/null")
        self.sync(self.a, False)
        self.git(self.a, "config", "core.hooksPath", ".githooks")
        (self.a / ".git/rebase-merge").mkdir()
        self.sync(self.a, False)


if __name__ == "__main__":
    unittest.main()
