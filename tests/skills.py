#!/usr/bin/env python3
"""Test skill ownership, update policy, and repeated installs without networking."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("skill_manager", ROOT / "scripts/manage-skills.py")
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


class Skills(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.home = self.base / "home"
        self.home.mkdir()
        (self.repo / "skills/custom").mkdir(parents=True)
        self.manifest = {"version": 1, "cli_version": "1.9.1",
                         "agents": ["codex", "claude-code", "opencode", "github-copilot", "pi"], "skills": []}
        self.write_manifest()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(manager, "ROOT", self.repo).start()
        mock.patch.dict(os.environ, {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config"),
                                    "XDG_STATE_HOME": str(self.home / ".state"),
                                    "CLAUDE_CONFIG_DIR": str(self.home / ".claude")}).start()
        mock.patch.object(manager.shutil, "which", return_value="/fake/npx").start()
        self.installer = mock.patch.object(manager, "run_cli", side_effect=self.fake_install).start()
        self.runtime = mock.patch.object(manager, "require_cli_runtime").start()
        self.source = self.custom("example-workflow")
        self.failure = False

    def write_manifest(self):
        (self.repo / "skills/manifest.json").write_text(json.dumps(self.manifest))

    def custom(self, name):
        source = self.repo / "skills/custom" / name
        source.mkdir()
        (source / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Test workflow.\n---\nOriginal instructions.\n")
        return source

    @property
    def canonical(self):
        return self.home / ".agents/skills" / manager.skill_name(self.source)

    @property
    def storage(self):
        return self.home / ".state/core-dotfiles/skills"

    def fake_install(self, command, home, env):
        self.assertEqual(env["DISABLE_TELEMETRY"], "1")
        self.assertEqual(env["npm_config_ignore_scripts"], "true")
        self.assertIn("skills@1.9.1", command)
        self.assertIn("--global", command)
        name = manager.skill_name(self.source)
        target = self.home / ".agents/skills" / name
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.source, target)
        for path in manager.destinations(home, name, self.manifest["agents"]):
            if path == target:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.is_symlink():
                path.symlink_to(target)
        return subprocess.CompletedProcess(command, 1 if self.failure else 0, b"{}", b"fixture error" if self.failure else b"")

    def run_manager(self, *args):
        with mock.patch("sys.argv", ["manage-skills", *args]), contextlib.redirect_stdout(io.StringIO()):
            return manager.main()

    def test_100_runs_install_once_preserve_state_and_native_links(self):
        self.run_manager()
        state_path = self.storage / "installed.json"
        stamp = state_path.stat().st_mtime_ns
        for _ in range(99):
            self.run_manager()
        self.assertEqual(self.installer.call_count, 1)
        self.assertEqual(stamp, state_path.stat().st_mtime_ns)
        self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)
        for path in manager.destinations(self.home, "example-workflow", self.manifest["agents"]):
            self.assertEqual(path.resolve(), self.canonical.resolve())

    def test_custom_update_backs_up_prior_content(self):
        self.run_manager()
        original = (self.canonical / "SKILL.md").read_text()
        (self.source / "reference.txt").write_text("New committed instructions")
        self.run_manager()
        self.assertEqual(self.installer.call_count, 2)
        saved = list((self.storage / "backups").glob("*/example-workflow/SKILL.md"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_text(), original)

    def test_local_edits_and_unmanaged_skills_are_preserved(self):
        self.run_manager()
        (self.canonical / "SKILL.md").write_text("User's local changes")
        with self.assertRaises(manager.SkillError):
            self.run_manager()
        self.assertEqual((self.canonical / "SKILL.md").read_text(), "User's local changes")
        (self.storage / "installed.json").unlink()
        with self.assertRaises(manager.SkillError):
            self.run_manager()
        self.assertEqual(self.installer.call_count, 1)

    def test_foreign_native_copy_blocks_install(self):
        own = self.home / ".claude/skills/example-workflow"
        own.mkdir(parents=True)
        (own / "SKILL.md").write_text("Existing user skill")
        with self.assertRaises(manager.SkillError):
            self.run_manager()
        self.installer.assert_not_called()
        self.assertEqual((own / "SKILL.md").read_text(), "Existing user skill")

    def test_explicit_named_adoption_backs_up_an_existing_custom_skill(self):
        self.canonical.mkdir(parents=True)
        (self.canonical / "SKILL.md").write_text("Original private user instructions")
        with self.assertRaises(manager.SkillError):
            self.run_manager()
        self.run_manager("sync", "--adopt", "example-workflow")
        saved = list((self.storage / "backups").glob("*/example-workflow/SKILL.md"))
        self.assertEqual(saved[0].read_text(), "Original private user instructions")
        (self.canonical / "SKILL.md").write_text("Further user edits")
        with self.assertRaises(manager.SkillError):
            self.run_manager("sync", "--adopt", "example-workflow")

    def test_failure_restores_prior_skill_and_removes_first_install_debris(self):
        self.failure = True
        with self.assertRaises(manager.SkillError):
            self.run_manager()
        self.assertFalse(self.canonical.exists())
        self.failure = False
        self.run_manager()
        original = manager.digest(self.canonical)
        (self.source / "reference.txt").write_text("Updated source")
        self.failure = True
        with self.assertRaises(manager.SkillError):
            self.run_manager()
        self.assertEqual(manager.digest(self.canonical), original)
        saved_count = len(list((self.storage / "backups").glob("*/example-workflow/SKILL.md")))
        with self.assertRaises(manager.SkillError):
            self.run_manager()
        self.assertEqual(len(list((self.storage / "backups").glob("*/example-workflow/SKILL.md"))), saved_count)
        self.assertEqual((self.storage / "last-error.json").stat().st_mode & 0o777, 0o600)

    def test_dry_run_has_no_installs_network_or_state_writes(self):
        with mock.patch.object(manager, "github", side_effect=AssertionError("Unexpected network")):
            self.run_manager("--dry-run")
        self.installer.assert_not_called()
        self.assertFalse(self.storage.exists())

    def test_symlinks_and_duplicate_private_names_are_rejected(self):
        (self.source / "outside").symlink_to(self.home)
        with self.assertRaises(manager.SkillError):
            self.run_manager()
        (self.source / "outside").unlink()
        private = self.home / ".config/core-dotfiles/skills.local.json"
        private.parent.mkdir(parents=True)
        private.write_text(json.dumps({"skills": [{"name": "example-workflow", "type": "local", "path": str(self.home)}]}))
        with self.assertRaises(manager.SkillError):
            self.run_manager()
        self.installer.assert_not_called()

    def test_private_custom_skills_stay_outside_public_repo(self):
        self.source.rename(self.home / "private-workflow")
        self.source = self.home / "private-workflow"
        private = self.home / ".config/core-dotfiles/skills.local.json"
        private.parent.mkdir(parents=True)
        private.write_text(json.dumps({"skills": [{"name": "example-workflow", "type": "local", "path": str(self.source)}]}))
        self.run_manager()
        self.assertTrue((self.canonical / "SKILL.md").is_file())
        self.assertFalse((self.repo / "skills/custom/example-workflow").exists())

    def test_latest_release_ignores_other_packages_and_prereleases(self):
        releases = [
            {"tag_name": "skill-v1.0.0", "published_at": "2026-01-01", "draft": False, "prerelease": False},
            {"tag_name": "skill-v2.0.0", "published_at": "2026-02-01", "draft": False, "prerelease": False},
            {"tag_name": "engine-v9.0.0", "published_at": "2026-03-01", "draft": False, "prerelease": False},
            {"tag_name": "skill-v3.0.0", "published_at": "2026-04-01", "draft": False, "prerelease": True},
        ]
        with mock.patch.object(manager, "github", side_effect=[releases, {"sha": "a" * 40}]) as github:
            resolved = manager.resolve({"type": "github", "repo": "example/skills", "path": "skill", "release_prefix": "skill-v"})
        self.assertEqual(resolved["release"], "skill-v2.0.0")
        self.assertIn("/tree/" + "a" * 40 + "/skill", resolved["source"])
        self.assertIn("skill-v2.0.0", github.call_args.args[0])

    def test_legacy_cli_install_is_backed_up_before_adoption(self):
        self.source.rename(self.base / "upstream")
        self.source = self.base / "upstream"
        self.manifest["skills"] = [{"name": "example-workflow", "type": "github", "repo": "example/skills", "path": "skill", "ref": "main"}]
        self.write_manifest()
        self.canonical.mkdir(parents=True)
        (self.canonical / "SKILL.md").write_text("Older customized instructions")
        lock = self.home / ".agents/.skill-lock.json"
        lock.write_text(json.dumps({"skills": {"example-workflow": {"source": "example/skills", "skillPath": "skill/SKILL.md"}}}))
        with mock.patch.object(manager, "resolve", return_value={"revision": "a" * 40, "source": "upstream", "release": "main"}):
            self.run_manager()
        saved = list((self.storage / "backups").glob("*/example-workflow/SKILL.md"))
        self.assertEqual(saved[0].read_text(), "Older customized instructions")


if __name__ == "__main__":
    unittest.main()
