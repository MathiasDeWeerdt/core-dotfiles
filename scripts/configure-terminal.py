#!/usr/bin/env python3
"""Select Alacritty in GNOME without changing unrelated desktop preferences."""
import ast
from pathlib import Path
import shlex
import subprocess
import sys


def get(schema, key):
    result = subprocess.run(["gsettings", "get", schema, key], check=True, capture_output=True, text=True)
    return ast.literal_eval(result.stdout.strip().removeprefix("@as "))


def set_value(schema, key, value):
    subprocess.run(["gsettings", "set", schema, key, value], check=True, capture_output=True)


def configure():
    root = "org.gnome.settings-daemon.plugins.media-keys"
    prefix = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"
    managed = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/core-dotfiles-terminal/"
    paths = get(root, "custom-keybindings")
    updated = []
    for path in paths:
        schema = prefix + path
        command = get(schema, "command")
        try:
            words = shlex.split(command)
        except ValueError:
            words = []
        if words and Path(words[0]).name in {"foot", "footclient"}:
            arguments = words[1:]
            while arguments and arguments[0] in {"-m", "--maximized"}:
                arguments.pop(0)
            if arguments and not arguments[0].startswith("-"):
                arguments.insert(0, "-e")
            # Preserve explicit commands and their arguments inside the terminal.
            set_value(schema, "command", shlex.join(["alacritty", *arguments]))
            if get(schema, "binding") in {"<Control><Alt>t", "<Primary><Alt>t"} and path != managed:
                continue
        if path not in updated:
            updated.append(path)
    for key, value in (("name", "Terminal"), ("binding", "<Control><Alt>t"), ("command", "alacritty")):
        set_value(prefix + managed, key, value)
    if managed not in updated:
        updated.append(managed)
    if updated != paths:
        set_value(root, "custom-keybindings", repr(updated))
    set_value("org.gnome.desktop.default-applications.terminal", "exec", "alacritty")
    set_value("org.gnome.desktop.default-applications.terminal", "exec-arg", "")

    schemas = subprocess.run(["gsettings", "list-schemas"], check=True, capture_output=True, text=True).stdout.splitlines()
    nautilus = "com.github.stunkymonkey.nautilus-open-any-terminal"
    if nautilus in schemas:
        set_value(nautilus, "terminal", "alacritty")
        set_value(nautilus, "use-generic-terminal-name", "true")
    favorites = get("org.gnome.shell", "favorite-apps")
    preferred = []
    for entry in favorites:
        entry = "Alacritty.desktop" if entry in {"foot.desktop", "footclient.desktop", "org.codeberg.dnkl.foot.desktop"} else entry
        if entry not in preferred:
            preferred.append(entry)
    if preferred != favorites:
        set_value("org.gnome.shell", "favorite-apps", repr(preferred))
    print("Alacritty selected for GNOME, Ctrl+Alt+T, and the installed Nautilus terminal extension.")


if __name__ == "__main__":
    try:
        configure()
    except (OSError, ValueError, subprocess.SubprocessError):
        print("Could not configure the default terminal; private desktop values withheld.", file=sys.stderr)
        sys.exit(1)
