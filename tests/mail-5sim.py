#!/usr/bin/env python3
"""Exercise the skill helpers with local mail and 5SIM fixtures."""
from contextlib import redirect_stdout
from email.message import EmailMessage
from io import StringIO
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

CUSTOM = Path(__file__).resolve().parents[1] / "skills/custom"
MAIL = CUSTOM / "mail/scripts/mailctl"
SIM = CUSTOM / "5sim/scripts/5simctl"


class Mail(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        config = self.base / "mail/config.json"
        config.parent.mkdir()
        secret = self.base / "password"
        secret.write_text("fixture")
        secret.chmod(0o600)
        self.sender = "mail@example.org"
        config.write_text(json.dumps({"imap_host": "imap.example.org", "username": self.sender,
                                      "from": self.sender, "password_file": str(secret)}))
        self.main = runpy.run_path(str(MAIL))["main"]
        self.enterContext(patch.dict(os.environ, XDG_CONFIG_HOME=temp.name))
        self.imap = self.enterContext(patch("imaplib.IMAP4_SSL"))
        self.box = self.imap.return_value.__enter__.return_value
        self.box.select.return_value = ("OK", [])
        message = EmailMessage()
        message["From"] = self.sender
        message["Subject"] = "Test"
        message.set_content("Own mailbox")
        message.add_alternative('<a href="https://example.org/action">Open</a>', subtype="html")
        self.box.uid.side_effect = lambda op, *args: (
            ("OK", [b"42"]) if op == "SEARCH" else ("OK", [(b"42", message.as_bytes())])
        )
        self.msmtp = self.enterContext(patch("subprocess.run"))

    def command(self, *args):
        output = StringIO()
        with patch.object(sys, "argv", ["mailctl", *args]), redirect_stdout(output):
            self.main()
        return output.getvalue()

    def test_reads_are_scoped_and_do_not_mark_mail_as_seen(self):
        self.assertEqual(json.loads(self.command("list", "--json"))[0]["uid"], "42")
        self.assertEqual(json.loads(self.command("read", "42", "--json"))["body"], "Own mailbox")
        self.assertIn("Test", self.command("search", "mailbox", "--body"))
        self.assertEqual(self.command("links", "42").strip(), "https://example.org/action")
        self.assertEqual(self.command("latest-link", "--match", "action").strip(), "https://example.org/action")
        self.box.select.assert_called_with('"INBOX"', readonly=True)
        for call in self.box.uid.call_args_list:
            if call.args[0] == "FETCH":
                self.assertIn("BODY.PEEK[", call.args[2])

    def test_wait_only_reports_new_uid(self):
        self.box.uid.side_effect = [("OK", [b"42"]), ("OK", [b"42 43"]), ("OK", [(b"", b"Subject: New\r\n\r\n")])]
        with patch("time.sleep"):
            self.assertTrue(self.command("wait").startswith("NEW 43"))

    def test_send_only_to_configured_address(self):
        with self.assertRaises(ValueError):
            self.command("send", "another@example.org", "subject", "body")
        self.msmtp.assert_not_called()
        self.assertEqual(self.command("send", self.sender, "subject", "body").strip(), "sent")
        self.assertEqual(self.msmtp.call_args.args[0], ["msmtp", "--", self.sender])
        self.imap.assert_not_called()

    def test_refuses_exposed_password(self):
        (self.base / "password").chmod(0o644)
        with self.assertRaises(ValueError):
            self.command("list")
        self.imap.assert_not_called()


FAKE_CURL = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
from urllib.parse import urlsplit
home = Path(os.environ['HOME'])
url = urlsplit(sys.argv[-1])
assert url.scheme == 'https' and url.netloc == '5sim.net'
if url.path.startswith('/v1/user/'):
    assert '@-' in sys.argv and sys.stdin.readline().strip().endswith(' fixture')
with (home / 'requests').open('a') as f:
    print(url.path + '?' + url.query, file=f)
data = json.loads((home / 'responses').read_text())[url.path]
if data is None:
    sys.exit(28)
print(json.dumps(data))
"""


class FiveSim(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.env = {"HOME": temp.name, "PATH": temp.name + os.pathsep + os.defpath}
        (self.home / "curl").write_text(FAKE_CURL)
        (self.home / "curl").chmod(0o700)
        self.token = self.home / ".config/5sim/token"
        self.token.parent.mkdir(parents=True)
        self.token.write_text("fixture")
        self.token.chmod(0o600)
        self.state = self.home / ".local/state/5sim"
        self.order = "/v1/user/buy/activation/england/any/sample"
        self.responses = {
            "/v1/guest/prices": {"sample": {"england": {"op": {"cost": 0.2, "count": 3}},
                                            "france": {"op": {"cost": 0.1, "count": 0}}}},
            "/v1/user/profile": {"balance": 1},
            "/v1/user/orders": {"Data": [], "Total": 0},
            self.order: {"id": 7, "phone": "fixture", "status": "PENDING", "price": 0.2},
        }

    def command(self, *args, success=True):
        (self.home / "responses").write_text(json.dumps(self.responses))
        result = subprocess.run([SIM, *args], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode == 0, success, result.stderr)
        return result.stdout

    def requests(self):
        return (self.home / "requests").read_text().splitlines()

    def test_public_catalog_needs_no_credentials(self):
        self.token.unlink()
        rows = json.loads(self.command("prices", "sample", "--json"))
        self.assertEqual([row["country"] for row in rows], ["england"])
        self.assertEqual(len(self.requests()), 1)

    def test_preview_and_capped_purchase(self):
        self.command("buy", "sample", "--max-price", "0.25", "--dry-run")
        self.assertFalse(self.state.exists())
        self.assertFalse(any("buy/" in path for path in self.requests()))
        self.command("buy", "sample", "--max-price", "0.25", "--operator", "op", success=False)
        self.command("buy", "sample", "--max-price", "0.15", success=False)
        self.assertIn("ORDER id=7", self.command("buy", "sample", "--max-price", "0.25"))
        purchases = [p for p in self.requests() if "buy/" in p]
        self.assertEqual(purchases, [self.order + "?maxPrice=0.25"])
        self.assertEqual((self.state / "attempts.jsonl").stat().st_mode & 0o777, 0o600)

    def test_force_still_checks_for_open_orders(self):
        self.responses["/v1/user/orders"] = {"Data": [{"status": "RECEIVED", "id": 8}], "Total": 1}
        self.command("buy", "sample", "--force", success=False)
        self.assertFalse(any("buy/" in path for path in self.requests()))

    def test_failed_dispatch_counts_and_legacy_log_is_respected(self):
        self.responses[self.order] = None
        for _ in range(2):
            self.command("buy", "sample", "--max-price", "0.25", success=False)
        self.assertEqual(sum("buy/" in p for p in self.requests()), 1)
        row = {"ts": int(time.time()) - 300, "outcome": "bought", "product": "sample"}
        (self.state / "attempts.jsonl").write_text((json.dumps(row) + "\n") * 3)
        self.command("buy", "sample", success=False)
        self.assertEqual(sum("buy/" in p for p in self.requests()), 1)

    def test_check_wait_and_settlement(self):
        self.responses["/v1/user/check/7"] = {"id": 7, "status": "RECEIVED", "sms": [{"code": "fixture"}]}
        self.assertIn("CODE fixture", self.command("check", "7"))
        self.assertEqual(self.command("wait", "7", "--code-only").strip(), "fixture")
        for action, status in (("finish", "FINISHED"), ("cancel", "CANCELED"), ("ban", "BANNED")):
            self.responses["/v1/user/" + action + "/7"] = {"id": 7, "status": status, "price": 0.2}
            self.assertIn(status, self.command(action, "7"))
        self.responses["/v1/user/check/7"] = None
        self.command("check", "7", success=False)


if __name__ == "__main__":
    unittest.main()
