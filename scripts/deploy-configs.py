#!/usr/bin/env python3
"""Deploy public configs; keep existing private files outside the repository."""
import argparse
import os
import pwd
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("zsh", "p10k", "foot", "tmux", "git", "fonts", "local-bin", "flameshot", "systemd")
MEMORY_REF = ("At session start, read ~/.memory.md and, when present, ~/.memory.local.md. "
              "Follow those user preferences subject to repository instructions and explicit current requests. "
              "Keep credentials and private machine/customer context outside public repositories.")


def private_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() == text:
        path.chmod(0o600)
        return
    temp = path.with_name(path.name + ".core-dotfiles.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def outside_repo(path):
    if path.resolve().is_relative_to(ROOT):
        raise RuntimeError(f"Private destination resolves inside public repository: {path}")


def wire_memory(home):
    memory = home / ".memory.md"
    # Older installations stowed this file. Detach that link without importing
    # private content into the public template or following it on future writes.
    if memory.is_symlink():
        text = memory.read_text() if memory.exists() else (ROOT / "memory/.memory.md").read_text()
        memory.unlink()
        private_write(memory, text)
    elif not memory.exists():
        private_write(memory, (ROOT / "memory/.memory.md").read_text())
    else:
        memory.chmod(0o600)
    destinations = {
        Path(os.environ.get("CODEX_HOME", home / ".codex")) / "AGENTS.md": MEMORY_REF,
        Path(os.environ.get("CLAUDE_CONFIG_DIR", home / ".claude")) / "CLAUDE.md": "@~/.memory.md\n\n" + MEMORY_REF,
        Path(os.environ.get("PI_CODING_AGENT_DIR", home / ".pi/agent")) / "AGENTS.md": MEMORY_REF,
        Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "opencode/AGENTS.md": MEMORY_REF,
        Path(os.environ.get("COPILOT_HOME", home / ".copilot")) / "copilot-instructions.md": MEMORY_REF,
    }
    # Codewhale is optional; retain support for existing installations.
    if shutil.which("codewhale") or (home / ".codewhale").exists():
        destinations[home / ".codewhale/instructions.md"] = MEMORY_REF
    for path, reference in destinations.items():
        outside_repo(path)
        current = path.read_text() if path.exists() else ""
        if reference not in current:
            current = current.rstrip() + "\n\n<!-- core-dotfiles: shared private memory -->\n" + reference + "\n"
        private_write(path, current.lstrip())
    print("Preserved private memory and wired global agent instructions.")


def deploy(home):
    backup = home / ".local/state/core-dotfiles/backups" / str(time.time_ns())
    outside_repo(backup)
    unfolds = set()
    conflicts = []
    normalize = []
    # Validate the entire plan before moving any existing user configuration.
    for package in PACKAGES:
        for source in sorted((ROOT / package).rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(ROOT / package)
            target = home / relative
            # Refuse to traverse unrelated directory symlinks. Stow can safely
            # unfold a legacy directory link, without moving any source files.
            parents = []
            for parent in target.parents:
                if parent == home:
                    break
                parents.append(parent)
            for parent in reversed(parents):
                if parent.is_symlink():
                    expected = ROOT / package / parent.relative_to(home)
                    if parent.resolve() != expected.resolve():
                        raise RuntimeError(f"Unmanaged parent symlink: {parent}")
                    unfolds.add(parent)
            if (target.exists() or target.is_symlink()) and target.resolve() == source.resolve():
                if target.is_symlink():
                    normalize.append((target, source))
                continue
            if target.exists() or target.is_symlink():
                if target.is_dir() and not target.is_symlink():
                    raise RuntimeError(f"Expected a file, found directory: {target}")
                conflicts.append((target, relative))
    for parent in sorted(unfolds, key=lambda path: len(path.parts)):
        parent.unlink()
        parent.mkdir()
    for target, source in normalize:
        if target.is_symlink():
            relative_link = os.path.relpath(source, target.parent)
            if os.readlink(target) != relative_link:
                target.unlink()
                target.symlink_to(relative_link)
    for target, relative in conflicts:
        backup.mkdir(parents=True, exist_ok=True, mode=0o700)
        saved = backup / relative
        saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.replace(target, saved)
        print(f"Backed up conflicting config outside repository: {relative}")
    subprocess.run(["stow", "--no-folding", "--stow", "--dir", str(ROOT), "--target", str(home), *PACKAGES], check=True)
    hooks = subprocess.run(["git", "-C", str(ROOT), "config", "--local", "--get", "core.hooksPath"], capture_output=True, text=True)
    if not hooks.stdout.strip():
        subprocess.run(["git", "-C", str(ROOT), "config", "--local", "core.hooksPath", ".githooks"], check=True)
    elif hooks.stdout.strip() != ".githooks":
        print("Existing Git hooks preserved; also run scripts/check-secrets.py before committing.")
    print("Public configs deployed without adopting host files into Git.")


def enable_sync(home):
    if os.environ.get("DOTFILES_SYNC_ENABLE", "true") == "false":
        print("Automatic sync activation skipped (DOTFILES_SYNC_ENABLE=false).")
        return
    units = home / ".config/systemd/user"
    timer = units / "core-dotfiles-sync.timer"
    wanted = units / "timers.target.wants/core-dotfiles-sync.timer"
    wanted.parent.mkdir(parents=True, exist_ok=True)
    if wanted.exists() or wanted.is_symlink():
        if wanted.resolve() != timer.resolve():
            raise RuntimeError("Existing sync timer enablement points at a different unit")
    else:
        wanted.symlink_to("../core-dotfiles-sync.timer")
    # Creating the WantedBy link also enables the timer for an offline home.
    # Never contact the workstation's manager when deploying a disposable home.
    if home.resolve() != Path(pwd.getpwuid(os.getuid()).pw_dir).resolve() or not shutil.which("systemctl"):
        print("Automatic sync enabled; timer starts at the next user login.")
        return
    manager = subprocess.run(["systemctl", "--user", "show", "--property=Version"], capture_output=True)
    if manager.returncode:
        print("Automatic sync enabled; user manager unavailable until login.")
        return
    if os.environ.get("SSH_AUTH_SOCK"):
        subprocess.run(["systemctl", "--user", "import-environment", "SSH_AUTH_SOCK"], check=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "start", "core-dotfiles-sync.timer"], check=True)
    print("Automatic committed-change sync enabled and started.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-only", action="store_true")
    args = parser.parse_args()
    home = Path.home()
    outside_repo(home)
    if not args.memory_only:
        deploy(home)
    wire_memory(home)
    if not args.memory_only:
        enable_sync(home)


if __name__ == "__main__":
    main()
