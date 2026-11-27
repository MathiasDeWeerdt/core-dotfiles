#!/usr/bin/env python3
"""Check local secret locations and permissions without executing configs or logging values."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY",
             "GITHUB_PERSONAL_ACCESS_TOKEN", "COPILOT_PROVIDER_API_KEY")
GROUPS = {"expose", "dehashed", "shell", "ssh", "dsh"}


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, "Invalid arguments. Use --help; never pass secret values on this command line.\n")


class Checker:
    def __init__(self, required):
        self.required = required
        self.failures = 0
        self.warnings = 0
        self.home = Path.home()
        self.config = Path(os.environ.get("XDG_CONFIG_HOME", str(self.home / ".config")))

    def report(self, status, label, message):
        # Labels are fixed program strings, never configuration contents/values.
        print(f"[{status}] {label}: {message}")
        self.failures += status == "FAIL"
        self.warnings += status == "WARN"

    def inside_repo(self, path):
        return path.absolute().is_relative_to(ROOT) or path.resolve().is_relative_to(ROOT)

    def inspect(self, path, label, *, directory=False, contents=True, maximum=1024 * 1024):
        """Return (present, safe, data). Inspect existing paths even if optional."""
        if self.inside_repo(path):
            self.report("FAIL", label, "private configuration must be outside this public repository")
            return True, False, b""
        try:
            info = path.lstat()
        except FileNotFoundError:
            return False, True, b""
        except OSError:
            self.report("FAIL", label, "cannot inspect file metadata")
            return True, False, b""
        if stat.S_ISLNK(info.st_mode):
            self.report("FAIL", label, "symlink detected; use a real private file/directory")
            return True, False, b""
        valid_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        expected = 0o700 if directory else 0o600
        if not valid_type:
            self.report("FAIL", label, "not a regular " + ("directory" if directory else "file"))
            return True, False, b""
        if info.st_uid != os.getuid():
            self.report("FAIL", label, "must be owned by the current user")
            return True, False, b""
        if stat.S_IMODE(info.st_mode) != expected:
            self.report("FAIL", label, f"permissions {stat.S_IMODE(info.st_mode):04o}; expected {expected:04o}")
            return True, False, b""
        # Private leaf permissions do not prevent a writable parent replacing it.
        for parent in path.parents:
            parent_info = parent.stat()
            sticky_root = parent_info.st_uid == 0 and parent_info.st_mode & stat.S_ISVTX
            if parent_info.st_uid not in (os.getuid(), 0) or parent_info.st_mode & 0o022 and not sticky_root:
                self.report("FAIL", label, "parent directory has unsafe ownership or write permissions")
                return True, False, b""
            if parent == self.home:
                break
        if directory:
            self.report("OK", label, "owned by you; mode 0700")
            return True, True, b""
        if not contents:
            self.report("OK", label, "owned by you; mode 0600; contents not inspected")
            return True, True, b""
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                actual = os.fstat(stream.fileno())
                if (actual.st_ino, actual.st_dev, actual.st_uid, actual.st_mode) != (info.st_ino, info.st_dev, info.st_uid, info.st_mode):
                    self.report("FAIL", label, "file changed while checking; retry")
                    return True, False, b""
                data = stream.read(maximum + 1)
            if len(data) > maximum:
                self.report("FAIL", label, "file exceeds the configuration size limit")
                return True, False, b""
        except OSError:
            self.report("FAIL", label, "cannot safely read the private file")
            return True, False, b""
        self.report("OK", label, "owned by you; mode 0600")
        return True, True, data

    def assignments(self, data, names, label):
        """Read simple literal declarations only; never expand shell expressions."""
        known, dynamic = {}, set()
        try:
            text = data.decode("utf-8")
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("export "):
                    line = line[7:].lstrip()
                if not re.match(r"^[A-Z_][A-Z0-9_]*=", line):
                    continue
                words = shlex.split(line, comments=True, posix=True)
                for word in words:
                    name, separator, value = word.partition("=")
                    if separator and name in names:
                        if any(symbol in value for symbol in ("$", "`", ";")):
                            known.pop(name, None)
                            dynamic.add(name)
                        else:
                            known[name] = bool(value.strip())
                            dynamic.discard(name)
        except (ValueError, UnicodeError):
            self.report("WARN", label, "could not parse simple assignments; contents were not executed or printed")
        return known, dynamic

    def credential(self, group, label, name, known=None, dynamic=None, *, empty_environment_wins=False):
        known, dynamic = known or {}, dynamic or set()
        if os.environ.get(name, "").strip() or empty_environment_wins and name in os.environ:
            present = bool(os.environ[name].strip())
            source = "environment"
        else:
            present = known.get(name, False)
            source = "private file"
            if name in dynamic:
                self.report("FAIL" if group in self.required else "WARN", label,
                            "computed shell value cannot be confirmed without executing config")
                return
        if present:
            self.report("OK", label, "nonempty value present in " + source + "; not authenticated")
        else:
            self.report("FAIL" if group in self.required else "SKIP", label,
                        "missing or empty; needed only when using this feature")

    def run(self):
        for path, label in ((self.home / ".config/core-dotfiles", "Core private config directory"),
                            (self.config / "expose", "Expose private config directory"),
                            (self.home / ".config/dehashed", "DeHashed private config directory"),
                            (self.home / ".ssh", "SSH directory")):
            self.inspect(path, label, directory=True)

        secret_file = self.home / ".config/core-dotfiles/secrets.zsh"
        present, safe, data = self.inspect(secret_file, "Shell secrets file")
        known, dynamic = self.assignments(data, PROVIDERS, "Shell secrets file") if present and safe else ({}, set())
        if not present:
            self.report("FAIL" if "shell" in self.required else "SKIP", "Shell secrets file", "not present; native agent login may be used instead")
        for name in PROVIDERS:
            # No single provider is mandatory: OAuth/native login is an alternative.
            self.credential("provider", name, name, known, dynamic)
        if "shell" in self.required and present and safe and not data.strip():
            self.report("FAIL", "Shell secrets file", "file is empty")

        online = Path(os.environ.get("EXPOSE_ONLINE_CONFIG", str(self.config / "expose/online.env")))
        present, safe, data = self.inspect(online, "Expose private config")
        known, dynamic = self.assignments(data, {"EXPOSE_AUTH_PASSWORD"}, "Expose private config") if present and safe else ({}, set())
        self.credential("expose", "Expose operator password", "EXPOSE_AUTH_PASSWORD", known, dynamic, empty_environment_wins=True)

        key = self.home / ".config/dehashed/api_key"
        present, safe, data = self.inspect(key, "DeHashed key file")
        if present and safe and data.strip():
            try:
                valid = all(33 <= ord(char) <= 126 for char in data.decode("utf-8").strip())
            except UnicodeError:
                valid = False
            if not valid:
                self.report("FAIL", "DeHashed key file", "must contain one ASCII key without whitespace")
        self.credential("dehashed", "DeHashed API key", "DEHASHED_API_KEY", {"DEHASHED_API_KEY": bool(safe and data.strip())})

        ssh = self.home / ".ssh"
        keys = sorted(p for p in ssh.glob("id_*") if not p.name.endswith(".pub")) if ssh.is_dir() and not ssh.is_symlink() else []
        usable = False
        for index, path in enumerate(keys, 1):
            present, safe, _ = self.inspect(path, f"SSH identity {index}", contents=False)
            usable |= present and safe and path.stat().st_size > 0
        agent = os.environ.get("SSH_AUTH_SOCK")
        if agent:
            try:
                info = Path(agent).stat()
                socket_ok = stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid()
            except OSError:
                socket_ok = False
            self.report("INFO" if socket_ok else "WARN", "SSH agent", "socket available; loaded identities not checked" if socket_ok else "socket unavailable or not owned by you")
        else:
            socket_ok = False
        if usable or socket_ok:
            self.report("INFO", "SSH authentication", "local identity/agent found; remote authorization and passphrase unlock are not checked")
        else:
            self.report("FAIL" if "ssh" in self.required else "SKIP", "SSH authentication", "no default identity/agent found; custom SSH configuration or HTTPS login may be used")

        for path, label in ((self.home / ".config/core-dotfiles/update.env", "Sync service environment"),
                            (self.home / ".config/core-dotfiles/tmux-projects", "Private tmux projects"),
                            (self.home / ".memory.md", "Private agent memory"),
                            (self.home / ".memory.local.md", "Machine-specific agent memory")):
            self.inspect(path, label, contents=False)
        private_manifest = self.config / "core-dotfiles/skills.local.json"
        present, safe, data = self.inspect(private_manifest, "Private skill manifest")
        if present and safe:
            try:
                value = json.loads(data)
                if not isinstance(value, dict) or not isinstance(value.get("skills", []), list):
                    raise ValueError()
            except (ValueError, UnicodeError):
                self.report("FAIL", "Private skill manifest", "invalid JSON/skills list; contents withheld")

        dsh_home = Path(os.environ.get("DSH_HOME", str(self.home / ".dsh")))
        self.inspect(dsh_home, "DSH private directory", directory=True)
        store, safe, _ = self.inspect(dsh_home / ".credentials.yaml", "DSH managed credentials", contents=False)
        store_present = store and safe and (dsh_home / ".credentials.yaml").stat().st_size > 0
        present, env_safe, data = self.inspect(dsh_home / ".env", "DSH fallback environment")
        known, dynamic = self.assignments(data, PROVIDERS, "DSH fallback environment") if present and env_safe else ({}, set())
        model_providers = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY"}
        env_present = any(os.environ.get(name, "").strip() or known.get(name, False) for name in model_providers)
        if store_present:
            self.report("INFO", "DSH authentication", "managed store present; provider entries and login validity are not inspected")
        elif env_present:
            self.report("OK", "DSH authentication", "provider environment declaration present; not authenticated")
        elif dynamic & model_providers:
            self.report("FAIL" if "dsh" in self.required else "WARN", "DSH authentication", "computed provider declarations cannot be confirmed without executing config")
        else:
            self.report("FAIL" if "dsh" in self.required else "SKIP", "DSH authentication", "no managed credentials or provider environment found; configure Models in dsh web")


def main():
    parser = SafeParser(description=__doc__)
    parser.add_argument("--require", action="append", default=[], metavar="GROUPS",
                        help="require comma-separated expose,dehashed,shell,ssh,dsh; repeatable")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures too")
    args = parser.parse_args()
    required = {name for option in args.require for name in option.split(",")}
    if not required <= GROUPS:
        parser.error("unknown group")
    checker = Checker(required)
    checker.run()
    print(f"\n{checker.failures} failures; {checker.warnings} warnings. No secrets printed; no config executed; no network checks.")
    return int(bool(checker.failures or args.strict and checker.warnings))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError):
        print("[FAIL] Local check could not finish safely; private values and OS error details withheld.", file=sys.stderr)
        sys.exit(1)
