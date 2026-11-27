#!/usr/bin/env python3
"""Exercise real deployment with disposable homes, never the workstation."""
import hashlib
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def snapshot(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            result[str(path.relative_to(root))] = ("link", os.readlink(path))
        elif path.is_file():
            result[str(path.relative_to(root))] = ("file", hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mode & 0o777)
    return result


class Deployment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="core-dotfiles-deployment-")
        cls.base = Path(cls.temp.name)
        cls.repo = cls.base / "repo"
        cls.repo.mkdir()
        for entry in ROOT.iterdir():
            if entry.name in {".git", ".venv", "env"}:
                continue
            target = cls.repo / entry.name
            if entry.is_dir():
                shutil.copytree(entry, target, ignore=shutil.ignore_patterns(".venv", "__pycache__", "dist"))
            elif entry.is_file():
                shutil.copy2(entry, target)
        subprocess.run(["git", "init", "-q", str(cls.repo)], check=True)
        subprocess.run(["git", "-C", str(cls.repo), "add", "."], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def environment(self, home):
        env = dict(os.environ, HOME=str(home), USER="fixture-user", DESIRED_HOSTNAME="fixture-host", SKIP_CONSOLE_CLIENTS="true")
        for key in ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "PI_CODING_AGENT_DIR", "XDG_CONFIG_HOME", "COPILOT_HOME", "DOTFILES_DIR", "DOTFILES_SYNC_ENABLE"):
            env.pop(key, None)
        return env

    def run_script(self, *args, env):
        process = subprocess.run(args, cwd=self.repo, env=env, capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
        return process

    def test_100_deployments_preserve_configs_and_private_memory(self):
        home = self.base / "repeat-home"
        home.mkdir()
        env = self.environment(home)
        (home / ".memory.md").write_text("Private current workstation context\n")
        (home / ".zshrc").write_text("Existing local configuration\n")
        (home / ".pi/agent").mkdir(parents=True)
        (home / ".pi/agent/AGENTS.md").write_text("Custom Pi instructions\n")
        # A legacy Stow directory link must never cause source files to move.
        (home / ".config").mkdir()
        (home / ".config/foot").symlink_to(self.repo / "foot/.config/foot", target_is_directory=True)
        source_before = snapshot(self.repo / "foot")
        script = str(self.repo / "scripts/deploy-configs.py")
        self.run_script("python3", script, env=env)
        after_first = snapshot(home)
        for _ in range(99):
            self.run_script("python3", script, env=env)
        self.assertEqual(snapshot(home), after_first)
        self.assertEqual(snapshot(self.repo / "foot"), source_before)
        self.assertEqual((home / ".memory.md").read_text(), "Private current workstation context\n")
        self.assertIn("Custom Pi instructions", (home / ".pi/agent/AGENTS.md").read_text())
        self.assertEqual((home / ".pi/agent/AGENTS.md").read_text().count("<!-- core-dotfiles:"), 1)
        self.assertEqual((home / ".memory.md").stat().st_mode & 0o777, 0o600)
        backups = list((home / ".local/state/core-dotfiles/backups").rglob(".zshrc"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "Existing local configuration\n")
        enabled = home / ".config/systemd/user/timers.target.wants/core-dotfiles-sync.timer"
        self.assertTrue(enabled.is_symlink())
        self.assertEqual(enabled.resolve(), (self.repo / "systemd/.config/systemd/user/core-dotfiles-sync.timer").resolve())

    def test_sync_activation_can_be_skipped(self):
        home = self.base / "sync-opt-out-home"
        home.mkdir()
        env = self.environment(home)
        env["DOTFILES_SYNC_ENABLE"] = "false"
        self.run_script("python3", str(self.repo / "scripts/deploy-configs.py"), env=env)
        enabled = home / ".config/systemd/user/timers.target.wants/core-dotfiles-sync.timer"
        self.assertFalse(enabled.is_symlink())
        self.assertTrue((home / ".config/systemd/user/core-dotfiles-sync.timer").is_symlink())

    def test_dry_runs_do_not_execute_mutating_commands(self):
        home = self.base / "dry-home"
        home.mkdir()
        env = self.environment(home)
        spies = self.base / "spies"
        spies.mkdir()
        for name in ("sudo", "pacman", "yay", "ssh", "ssh-keygen", "hostnamectl", "systemctl", "curl", "npm", "git", "stow"):
            path = spies / name
            path.write_text("#!/bin/sh\nprintf 'Forbidden command in dry run' >&2\nexit 99\n")
            path.chmod(0o755)
        env["PATH"] = str(spies) + os.pathsep + env["PATH"]
        before = snapshot(home)
        source_before = snapshot(self.repo)
        for script in ("install.sh", "update.sh"):
            self.run_script("bash", str(self.repo / script), "--dry-run", env=env)
            self.run_script("bash", str(self.repo / script), "--dry-run", "--configs-only", env=env)
        self.assertEqual(snapshot(home), before)
        self.assertEqual(snapshot(self.repo), source_before)

    def test_system_install_target_is_updated_and_matches_source(self):
        home = self.base / "install-home"
        home.mkdir()
        env = self.environment(home)
        target = home / "system-bin"
        target.mkdir()
        env["EXPOSE_INSTALL_DIR"] = str(target)
        (target / "expose-online").write_text("obsolete\n")
        script = str(self.repo / "scripts/deploy.sh")
        self.run_script("bash", script, env=env)
        for tool in ("expose", "expose-online"):
            self.assertEqual((target / tool).read_bytes(), (self.repo / "expose/dist" / tool).read_bytes())
        before = snapshot(home)
        self.run_script("bash", script, env=env)
        self.assertEqual(snapshot(home), before)

    def test_existing_memory_symlink_is_detached(self):
        home = self.base / "memory-home"
        home.mkdir()
        env = self.environment(home)
        source = self.repo / "memory/.memory.md"
        text = source.read_text()
        (home / ".memory.md").symlink_to(source)
        self.run_script("python3", str(self.repo / "scripts/deploy-configs.py"), "--memory-only", env=env)
        self.assertFalse((home / ".memory.md").is_symlink())
        self.assertEqual((home / ".memory.md").read_text(), text)
        self.assertEqual(source.read_text(), text)

    def test_failed_build_preserves_last_good_output(self):
        env = self.environment(self.base)
        build = str(self.repo / "expose/build.sh")
        self.run_script("bash", build, env=env)
        output = self.repo / "expose/dist/expose"
        previous = output.read_bytes()
        source = self.repo / "expose/src/assets/server.py"
        saved = source.with_suffix(".saved")
        source.rename(saved)
        try:
            process = subprocess.run(["bash", build], cwd=self.repo, env=env, capture_output=True)
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(output.read_bytes(), previous)
        finally:
            saved.rename(source)

    def test_explicit_environment_overrides_local_config(self):
        home = self.base / "override-home"
        home.mkdir()
        env = self.environment(home)
        env["TARGET_USER"] = "explicit-user"
        config = self.repo / "env"
        config.write_text('TARGET_USER="local-user"\nDESIRED_HOSTNAME="local-host"\n')
        try:
            process = self.run_script("bash", str(self.repo / "install.sh"), "--dry-run", env=env)
            self.assertIn("Target user: explicit-user; hostname: fixture-host", process.stdout)
        finally:
            config.unlink()

    def test_invalid_plan_keeps_all_existing_files(self):
        home = self.base / "invalid-home"
        home.mkdir()
        (home / ".zshrc").write_text("Keep this configuration\n")
        (home / ".config").mkdir()
        foreign = self.base / "foreign-config"
        foreign.mkdir()
        (home / ".config/foot").symlink_to(foreign)
        before = snapshot(home)
        process = subprocess.run(["python3", str(self.repo / "scripts/deploy-configs.py")], env=self.environment(home), capture_output=True)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(snapshot(home), before)

    def test_package_inventories_match_installer(self):
        installer = (ROOT / "install.sh").read_text()
        for variable, filename in (("PACMAN_PKGS", "pacman"), ("AUR_PKGS", "aur"), ("NPM_GLOBALS", "npm")):
            body = re.search(r'^'+variable+r'=\((.*?)^\)', installer, re.M | re.S)[1]
            installed = shlex.split(body, comments=True)
            inventory = shlex.split((ROOT / "packages" / (filename + ".txt")).read_text(), comments=True)
            self.assertEqual(sorted(installed), sorted(inventory))


if __name__ == "__main__":
    unittest.main(verbosity=2)
