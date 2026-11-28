#!/usr/bin/env python3
"""Run desktop configuration against a fake settings store, never D-Bus."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Desktop(unittest.TestCase):
    def test_repeat_configuration_preserves_other_shortcuts_and_extensions(self):
        with tempfile.TemporaryDirectory(prefix="core-dotfiles-gnome-") as directory:
            base = Path(directory)
            home = base / "home"
            home.mkdir()
            binaries = base / "bin"
            binaries.mkdir()
            state = base / "settings.json"
            key = "org.gnome.settings-daemon.plugins.media-keys custom-keybindings"
            enabled = "org.gnome.shell enabled-extensions"
            disabled = "org.gnome.shell disabled-extensions"
            indicator = "clipboard-indicator@tudmotu.com"
            legacy = "/legacy/terminal/"
            shortcut_schema = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"
            initial = {
                key: repr(["/unrelated/shortcut/", legacy, "/legacy/command/"]),
                shortcut_schema + "/unrelated/shortcut/ command": "echo preserved",
                shortcut_schema + legacy + " command": "foot -m",
                shortcut_schema + legacy + " binding": "<Control><Alt>t",
                shortcut_schema + "/legacy/command/ command": "foot -m -e printf 'hello world'",
                shortcut_schema + "/legacy/command/ binding": "<Control><Alt>y",
                "org.gnome.shell favorite-apps": "['unrelated.desktop', 'foot.desktop', 'Alacritty.desktop']",
                enabled: "['unrelated-enabled', 'clipboard-history@alexsaveau.dev']",
                disabled: repr([indicator, "unrelated-disabled"]),
            }
            state.write_text(json.dumps(initial))
            stub = binaries / "gsettings"
            stub.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
path = Path(os.environ['SETTINGS_STORE'])
data = json.loads(path.read_text())
if sys.argv[1] == 'list-schemas':
    print('com.github.stunkymonkey.nautilus-open-any-terminal')
    sys.exit(0)
key = ' '.join(sys.argv[2:4])
if sys.argv[1] == 'get':
    print(repr(data[key]) if sys.argv[3] in ('command', 'binding') else data[key])
else:
    data[key] = sys.argv[4]
    path.write_text(json.dumps(data, sort_keys=True))
''')
            stub.chmod(0o755)
            power = binaries / "powerprofilesctl"
            power.write_text("#!/bin/sh\nprintf 'balanced\\n'\n")
            power.chmod(0o755)
            pacman = binaries / "pacman"
            pacman.write_text(
                '#!/bin/sh\n'
                '[ "$*" = "-Q gnome-shell-extension-clipboard-indicator" ] && [ "$HAS_INDICATOR" = yes ]\n'
            )
            pacman.chmod(0o755)
            env = dict(os.environ, HOME=str(home), SETTINGS_STORE=str(state), PATH=str(binaries) + os.pathsep + os.environ["PATH"])
            script = ["bash", str(ROOT / "scripts/gnome-settings.sh")]
            subprocess.run(script, env=dict(env, HAS_INDICATOR="no"), check=True, capture_output=True)
            without_indicator = json.loads(state.read_text())
            self.assertEqual(without_indicator[enabled], initial[enabled])
            self.assertEqual(without_indicator[disabled], initial[disabled])
            first = None
            for _ in range(3):
                process = subprocess.run(script, env=dict(env, HAS_INDICATOR="yes"), capture_output=True, text=True)
                self.assertEqual(process.returncode, 0, process.stderr)
                current = state.read_bytes()
                first = current if first is None else first
                self.assertEqual(current, first)
            configured = json.loads(state.read_text())
            self.assertEqual(configured[enabled], repr(["unrelated-enabled", indicator]))
            self.assertEqual(configured[disabled], "['unrelated-disabled']")
            shortcuts = configured[key]
            self.assertIn("/unrelated/shortcut/", shortcuts)
            self.assertEqual(shortcuts.count("core-dotfiles-terminal/"), 1)
            self.assertEqual(shortcuts.count("core-dotfiles-screenshot/"), 1)
            self.assertNotIn(legacy, shortcuts)
            self.assertIn("/legacy/command/", shortcuts)
            self.assertEqual(configured[shortcut_schema + "/legacy/command/ command"], "alacritty -e printf 'hello world'")
            self.assertEqual(configured[shortcut_schema + "/unrelated/shortcut/ command"], "echo preserved")
            self.assertEqual(configured["org.gnome.desktop.default-applications.terminal exec"], "alacritty")
            self.assertEqual(configured["com.github.stunkymonkey.nautilus-open-any-terminal terminal"], "alacritty")
            self.assertEqual(configured["org.gnome.shell favorite-apps"], "['unrelated.desktop', 'Alacritty.desktop']")


if __name__ == "__main__":
    unittest.main()
