#!/usr/bin/env python3
"""Manage explicitly selected global skills through the official Skills CLI."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
AGENTS = {"codex", "claude-code", "opencode", "github-copilot", "pi"}


class SkillError(Exception):
    pass


def outside_repo(path):
    if path.resolve().is_relative_to(ROOT):
        raise SkillError("Installed skill state and backups must stay outside the public repository")


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def private_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def digest(directory):
    if directory.is_symlink() or not directory.is_dir():
        raise SkillError("Skill root must be a real directory")
    result = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if any(part in (".git", "__pycache__", "__pypackages__") for part in relative.parts):
            continue
        if path.is_symlink():
            raise SkillError("Skill source contains a symlink; use self-contained skill files")
        if path.is_file():
            result.update(str(relative).encode() + b"\0")
            result.update(str(path.stat().st_mode & 0o111).encode() + b"\0")
            result.update(hashlib.sha256(path.read_bytes()).digest())
    return result.hexdigest()


def skill_name(directory):
    text = (directory / "SKILL.md").read_text()
    frontmatter = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
    if not frontmatter:
        raise SkillError("SKILL.md needs YAML frontmatter with name and description")
    match = re.search(r"^name:\s*['\"]?([a-z0-9-]+)['\"]?\s*$", frontmatter[1], re.M)
    if not match or not re.search(r"^description:\s*\S", frontmatter[1], re.M):
        raise SkillError("SKILL.md needs a valid name and description")
    return match[1]


def load_manifest():
    manifest = read_json(ROOT / "skills/manifest.json")
    if manifest.get("version") != 1 or not re.fullmatch(r"\d+\.\d+\.\d+", manifest.get("cli_version", "")):
        raise SkillError("Unsupported skill manifest or CLI version")
    agents = manifest.get("agents", [])
    if not agents or len(set(agents)) != len(agents) or not set(agents) <= AGENTS:
        raise SkillError("Manifest must select supported, unique agents")
    entries = []
    for item in manifest.get("skills", []):
        entries.append((dict(item), False))
    for directory in sorted((ROOT / "skills/custom").iterdir()):
        if directory.is_dir() and (directory / "SKILL.md").is_file():
            entries.append(({"name": skill_name(directory), "type": "local", "path": str(directory)}, False))
    private = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "core-dotfiles/skills.local.json"
    outside_repo(private)
    for item in read_json(private, {}).get("skills", []):
        entries.append((dict(item), True))
    seen = set()
    for item, private_source in entries:
        name = item.get("name", "")
        if not NAME.fullmatch(name) or len(name) > 64 or name in seen:
            raise SkillError("Skill names must be unique lowercase names of at most 64 characters")
        seen.add(name)
        if item.get("type") == "github":
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", item.get("repo", "")):
                raise SkillError("GitHub sources require owner/repository, without credentials")
            path = Path(item.get("path", ""))
            if not item.get("path") or path.is_absolute() or ".." in path.parts:
                raise SkillError("GitHub skill paths must stay inside their repository")
            if bool(item.get("ref")) == bool(item.get("release_prefix")):
                raise SkillError("Choose either ref or release_prefix for each GitHub skill")
        elif item.get("type") == "local":
            source = Path(item["path"]).expanduser()
            source = (ROOT / source).resolve() if not source.is_absolute() else source.resolve()
            if not private_source and not source.is_relative_to(ROOT / "skills/custom"):
                raise SkillError("Public custom skills must live under skills/custom")
            if private_source:
                outside_repo(source)
            if skill_name(source) != name:
                raise SkillError("Custom skill name must match SKILL.md frontmatter")
            digest(source)  # Refuse symlinks before the installer follows them.
            item["path"] = str(source)
        else:
            raise SkillError("Skill type must be github or local")
    return manifest, [item for item, _ in entries]


def github(endpoint):
    request = urllib.request.Request("https://api.github.com/repos/" + endpoint,
                                     headers={"Accept": "application/vnd.github+json", "User-Agent": "core-dotfiles-skills"})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.load(response)
    except (urllib.error.URLError, OSError):
        # Let gh use its own credentials; never extract tokens into this process.
        if shutil.which("gh"):
            result = subprocess.run(["gh", "api", "repos/" + endpoint], capture_output=True, timeout=35)
            if result.returncode == 0:
                return json.loads(result.stdout)
        raise SkillError("Could not resolve GitHub skill source; nothing was installed") from None


def resolve(item):
    if item["type"] == "local":
        return {"revision": digest(Path(item["path"])), "source": item["path"], "release": "custom"}
    ref = item.get("ref")
    if not ref:
        releases = github(item["repo"] + "/releases?per_page=100")
        releases = [r for r in releases if not r.get("draft") and not r.get("prerelease")
                    and r["tag_name"].startswith(item["release_prefix"])]
        if not releases:
            raise SkillError("No stable release matches the configured skill release prefix")
        ref = max(releases, key=lambda r: r["published_at"])["tag_name"]
    commit = github(item["repo"] + "/commits/" + urllib.parse.quote(ref, safe=""))["sha"]
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise SkillError("GitHub returned an invalid commit")
    return {"revision": commit, "release": ref,
            "source": f"https://github.com/{item['repo']}/tree/{commit}/{item['path']}"}


def destinations(home, name, agents):
    roots = {
        "codex": home / ".agents/skills", "pi": home / ".agents/skills",
        "opencode": home / ".agents/skills", "github-copilot": home / ".agents/skills",
        "claude-code": Path(os.environ.get("CLAUDE_CONFIG_DIR", home / ".claude")) / "skills",
    }
    return list(dict.fromkeys(roots[agent] / name for agent in agents))


def run_cli(command, home, env):
    process = subprocess.Popen(command, cwd=home, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=240)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise SkillError("Skills CLI timed out; its installer subprocesses were stopped") from None
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def require_cli_runtime():
    if not shutil.which("npx") or not shutil.which("node"):
        raise SkillError("Node.js >=22.20 and npx are required; run the full installer or set SKIP_AGENT_SKILLS=true")
    result = subprocess.run(["node", "--version"], capture_output=True, timeout=10)
    match = re.fullmatch(rb"v(\d+)\.(\d+)\.(\d+)\s*", result.stdout)
    if result.returncode or not match or tuple(map(int, match.groups())) < (22, 20, 0):
        raise SkillError("The pinned Skills CLI requires Node.js >=22.20; update Node before installing skills")


def sync_one(item, target, manifest, state, state_path, storage):
    home = Path.home()
    canonical = home / ".agents/skills" / item["name"]
    outside_repo(canonical)
    if canonical.is_symlink():
        raise SkillError("Existing canonical skill is a symlink; preserve it before changing skill ownership")
    if item["type"] == "local":
        source_path = Path(item["path"]).resolve()
        if source_path.is_relative_to(canonical.resolve()) or canonical.resolve().is_relative_to(source_path):
            raise SkillError("Keep custom source folders separate from installed skills to avoid copying onto themselves")
    paths = destinations(home, item["name"], manifest["agents"])
    # Preserve older agent-specific installs even when the pinned CLI now uses
    # shared global discovery. Distinct copies can shadow the managed package.
    legacy_paths = [home / ".codex/skills" / item["name"], home / ".copilot/skills" / item["name"],
                    Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "opencode/skills" / item["name"],
                    home / ".pi/agent/skills" / item["name"]]
    missing_paths = [path for path in paths if not path.exists() and not path.is_symlink()]
    for path in [*paths, *legacy_paths]:
        outside_repo(path)
        if path != canonical and (path.exists() or path.is_symlink()) and path.resolve() != canonical.resolve():
            raise SkillError("An agent has its own skill at this name; preserve or rename it before installing")
    previous = state["skills"].get(item["name"])
    if previous:
        if previous["identity"] != item:
            raise SkillError("Managed source changed; choose a distinct skill name instead of replacing another source")
        if canonical.exists() and digest(canonical) != previous["digest"]:
            raise SkillError("Installed skill has local edits; preserve them as a custom skill before updating")
    elif canonical.exists() or canonical.is_symlink():
        legacy = read_json(home / ".agents/.skill-lock.json", {}).get("skills", {}).get(item["name"], {})
        same_source = (item["type"] == "github" and legacy.get("source") == item["repo"]
                       and legacy.get("skillPath", "").removesuffix("/SKILL.md") == item["path"])
        if not same_source and (item["type"] != "local" or digest(canonical) != target["revision"]):
            raise SkillError("An unmanaged skill already exists; it was left untouched")
    links_ready = all(path.exists() and path.resolve() == canonical.resolve() for path in paths)
    if previous and canonical.exists() and previous["revision"] == target["revision"] and links_ready and previous.get("agents") == manifest["agents"]:
        print(item["name"] + ": already current (" + target["release"] + ")")
        return
    require_cli_runtime()
    saved = None
    if canonical.exists():
        original_digest = digest(canonical)
        saved = storage / "backups" / original_digest / item["name"]
        outside_repo(saved)
        saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not saved.exists():
            shutil.copytree(canonical, saved)
        elif digest(saved) != original_digest:
            raise SkillError("Private skill backup changed; preserve it before retrying this installation")
    env = dict(os.environ, DISABLE_TELEMETRY="1", DO_NOT_TRACK="1", npm_config_ignore_scripts="true",
               GIT_TERMINAL_PROMPT="0", CI="1")
    command = ["npx", "--yes", "--package", "skills@" + manifest["cli_version"], "--", "skills", "add",
               target["source"], "--global", "--yes", "--skill", item["name"], "--agent", *manifest["agents"], "--json"]
    cli_lock_path = home / ".agents/.skill-lock.json"
    cli_before = read_json(cli_lock_path, {}).get("skills", {}).get(item["name"])
    try:
        result = run_cli(command, home, env)
        private_json(storage / "last-install.json", {"returncode": result.returncode,
                                                     "stdout": result.stdout.decode(errors="replace"),
                                                     "stderr": result.stderr.decode(errors="replace")})
        if result.returncode:
            private_json(storage / "last-error.json", {"stdout": result.stdout.decode(errors="replace"),
                                                       "stderr": result.stderr.decode(errors="replace")})
        if result.returncode or not (canonical / "SKILL.md").is_file() or skill_name(canonical) != item["name"]:
            raise SkillError("Skills CLI installation failed; previous skill restored when available")
        if not all(path.exists() and path.resolve() == canonical.resolve() for path in paths):
            raise SkillError("Skills CLI did not establish the expected agent discovery paths")
        installed_digest = digest(canonical)
    except (OSError, subprocess.TimeoutExpired, SkillError):
        for path in missing_paths:
            if path != canonical and path.is_symlink() and path.resolve() == canonical.resolve():
                path.unlink()
        if canonical.is_symlink():
            canonical.unlink()
        elif canonical.exists():
            shutil.rmtree(canonical)
        if saved:
            shutil.copytree(saved, canonical)
        if cli_lock_path.exists():
            cli_lock = read_json(cli_lock_path)
            cli_entries = cli_lock.setdefault("skills", {})
            if cli_before is None:
                cli_entries.pop(item["name"], None)
            else:
                cli_entries[item["name"]] = cli_before
            private_json(cli_lock_path, cli_lock)
        raise SkillError("Skills CLI could not finish; any prior skill was restored and its backup kept privately") from None
    if cli_lock_path.exists():
        cli_lock_path.chmod(0o600)
    state["skills"][item["name"]] = dict(target, identity=item, digest=installed_digest, agents=manifest["agents"])
    private_json(state_path, state)
    print(item["name"] + ": installed " + target["release"] + " through Skills CLI")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("sync", "check"), default="sync")
    parser.add_argument("--dry-run", action="store_true", help="preview without network or writes")
    args = parser.parse_args()
    manifest, entries = load_manifest()
    if args.dry_run:
        for item in entries:
            print("Would check/install managed skill: " + item["name"] + " (" + item["type"] + ")")
        return 0
    storage = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "core-dotfiles/skills"
    outside_repo(storage)
    state_path = storage / "installed.json"
    outside_repo(state_path)
    state = read_json(state_path, {"version": 1, "skills": {}})
    if args.command == "check":
        for item in entries:
            target = resolve(item)
            previous = state["skills"].get(item["name"], {})
            current = previous.get("revision") == target["revision"]
            canonical = Path.home() / ".agents/skills" / item["name"]
            status = "current" if current and canonical.exists() else "install/update available"
            if previous and previous["identity"] != item:
                status = "managed source changed; update blocked"
            elif previous and canonical.exists() and digest(canonical) != previous["digest"]:
                status = "local edits; update blocked"
            elif current and not all(p.exists() and p.resolve() == canonical.resolve()
                                     for p in destinations(Path.home(), item["name"], manifest["agents"])):
                status = "agent discovery links need repair"
            print(item["name"] + ": " + status + " (" + target["release"] + ")")
        return 0
    os.umask(0o077)
    storage.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (storage / "install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read_json(state_path, {"version": 1, "skills": {}})
        for item in entries:
            sync_one(item, resolve(item), manifest, state, state_path, storage)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (SkillError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        # Do not relay command output, URLs, local source contents, or token values.
        message = str(error) if isinstance(error, SkillError) else "Skill setup failed; existing private skill state was preserved"
        print(message, file=sys.stderr)
        sys.exit(1)
