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
    def test_repeat_configuration_preserves_other_shortcuts(self):
        with tempfile.TemporaryDirectory(prefix="core-dotfiles-gnome-") as directory:
            base = Path(directory)
            home = base / "home"
            home.mkdir()
            binaries = base / "bin"
            binaries.mkdir()
            state = base / "settings.json"
            key = "org.gnome.settings-daemon.plugins.media-keys custom-keybindings"
            state.write_text(json.dumps({key: "['/unrelated/shortcut/']"}))
            stub = binaries / "gsettings"
            stub.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
path = Path(os.environ['SETTINGS_STORE'])
data = json.loads(path.read_text())
key = ' '.join(sys.argv[2:4])
if sys.argv[1] == 'get':
    print(data[key])
else:
    data[key] = sys.argv[4]
    path.write_text(json.dumps(data, sort_keys=True))
''')
            stub.chmod(0o755)
            power = binaries / "powerprofilesctl"
            power.write_text("#!/bin/sh\nprintf 'balanced\\n'\n")
            power.chmod(0o755)
            env = dict(os.environ, HOME=str(home), SETTINGS_STORE=str(state), PATH=str(binaries) + os.pathsep + os.environ["PATH"])
            first = None
            for _ in range(3):
                process = subprocess.run(["bash", str(ROOT / "scripts/gnome-settings.sh")], env=env, capture_output=True, text=True)
                self.assertEqual(process.returncode, 0, process.stderr)
                current = state.read_bytes()
                first = current if first is None else first
                self.assertEqual(current, first)
            shortcuts = json.loads(state.read_text())[key]
            self.assertIn("/unrelated/shortcut/", shortcuts)
            self.assertEqual(shortcuts.count("core-dotfiles-terminal/"), 1)
            self.assertEqual(shortcuts.count("core-dotfiles-screenshot/"), 1)


if __name__ == "__main__":
    unittest.main()
