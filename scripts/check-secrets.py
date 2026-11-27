#!/usr/bin/env python3
"""Check public files without ever printing matched credential values."""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES = {
    "private-key": re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----\r?\n"),
    "provider-token": re.compile(rb"\b(?:sk-(?:proj-|ant-api\d+-|or-v1-)?[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16}|xox[baprs]-[A-Za-z0-9-]{20,})\b"),
    "literal-credential": re.compile(rb'''(?im)\b(?:[A-Z0-9_]*(?:PASSWORD|PASSWD|API_KEY|AUTH_TOKEN|ACCESS_TOKEN|SECRET_KEY))\s*=\s*["']([^"'\r\n]+)["']'''),
    "unquoted-shell-credential": re.compile(rb'''(?m)(?:^|[ \t])(?:export[ \t]+)?[A-Z0-9_]*(?:PASSWORD|PASSWD|API_KEY|AUTH_TOKEN|ACCESS_TOKEN|SECRET_KEY)=([^\s"'`#;]+)'''),
    "credential-default": re.compile(rb"(?i)\$\{[A-Z0-9_]*(?:PASSWORD|PASSWD|API_KEY|AUTH_TOKEN|SECRET_KEY)(?::-|-)([^}\r\n]+)\}"),
    "credential-dict": re.compile(rb'''(?i)["'](?:wifi_password|password|api_key|secret_key|access_token)["']\s*:\s*["']([^"'\r\n]+)["']'''),
}
PRIVATE_NAMES = re.compile(r"(?:^|/)(?:\.env(?:\..+)?|env|api_key|secrets?\.(?:zsh|sh|json|env)|id_(?:rsa|ed25519|ecdsa)|(?:credentials|auth)\.json)$")


def findings(data, filename=""):
    for name, pattern in RULES.items():
        if name == "unquoted-shell-credential" and filename:
            shell_file = (Path(filename).suffix in (".sh", ".zsh") or
                          Path(filename).name in (".zshrc", ".zshenv", ".profile", ".bashrc", ".bash_profile") or
                          bool(re.match(rb"#![^\n]*\b(?:bash|zsh|sh)\b", data[:200])))
            if not shell_file:
                continue
        for match in pattern.finditer(data):
            if name in ("literal-credential", "unquoted-shell-credential", "credential-default", "credential-dict"):
                value = match[1].strip()
                if (value.startswith((b"$", b"<")) or b"..." in value) or value in (b"password", b"new-password"):
                    continue
                if re.fullmatch(rb"(?:your[_-][a-z0-9_-]+|[a-z0-9_-]+[_-]here)", value, re.IGNORECASE):
                    continue
            yield name, data.count(b"\n", 0, match.start()) + 1


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="scan index contents, including newly added files")
    parser.add_argument("--history", action="store_true", help="scan every blob reachable from any Git ref")
    parser.add_argument("--revision", action="append", default=[], help="also scan this fetched revision with --history")
    args = parser.parse_args()
    if args.revision and not args.history:
        parser.error("--revision requires --history")
    count = total = 0
    if args.history:
        entries = []
        for row in git("rev-list", "--objects", "--all", *args.revision).decode().splitlines():
            oid, _, name = row.partition(" ")
            if name:
                entries.append((oid, name))
        proc = subprocess.Popen(["git", "-C", str(ROOT), "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            for oid, name in entries:
                proc.stdin.write((oid + "\n").encode()); proc.stdin.flush()
                header = proc.stdout.readline().split()
                data = proc.stdout.read(int(header[2])); proc.stdout.read(1)
                if header[1] != b"blob":
                    continue
                total += 1
                if PRIVATE_NAMES.search(name) and not name.endswith(".example"):
                    print(f"{oid[:12]} {name}: private credential filename must not be tracked")
                    count += 1
                for rule, line in findings(data, name):
                    print(f"{oid[:12]} {name}:{line}: {rule} (value redacted)")
                    count += 1
        finally:
            proc.stdin.close(); proc.stdout.close(); proc.wait()
        messages = git("log", "--format=%H%x00%B%x00", "--all", *args.revision).split(b"\0")
        for index in range(0, len(messages) - 1, 2):
            oid, message = messages[index].strip(), messages[index + 1]
            for rule, line in findings(message):
                print(f"{oid.decode()[:12]} commit-message:{line}: {rule} (value redacted)")
                count += 1
    else:
        options = ("--cached",) if args.staged else ("--cached", "--others", "--exclude-standard")
        for raw in git("ls-files", "-z", *options).split(b"\0"):
            if not raw:
                continue
            name = raw.decode()
            if PRIVATE_NAMES.search(name) and not name.endswith(".example"):
                print(f"{name}: private credential filename must not be tracked")
                count += 1
            try:
                data = git("show", ":" + name) if args.staged else (ROOT / name).read_bytes()
            except FileNotFoundError:
                continue
            total += 1
            for rule, line in findings(data, name):
                print(f"{name}:{line}: {rule} (value redacted)")
                count += 1
    print(f"Checked {total} files/blobs; {count} potential credential findings. Values are never printed.")
    return bool(count)


if __name__ == "__main__":
    sys.exit(main())
