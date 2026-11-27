#!/usr/bin/env python3
"""Offline credential and evidence isolation checks for the custom skill."""
import argparse
import contextlib
import email.message
import importlib.util
import io
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error
import urllib.request
import urllib.response

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "skills/custom/dehashed/scripts/dehashed.py"


class Dehashed(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self.home.mkdir()
        self.repo = Path(self.temp.name) / "repo"
        (self.repo / ".git").mkdir(parents=True)
        self.environment = mock.patch.dict(os.environ, {
            "HOME": str(self.home), "DEHASHED_API_KEY": "", "DEHASHED_CONTACT_EMAIL": "",
            "DEHASHED_CACHE_DIR": str(self.home / ".cache/dehashed"),
            "DEHASHED_MAX_CREDITS": "0", "DEHASHED_DAILY_MAX_CREDITS": "10",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        spec = importlib.util.spec_from_file_location("dehashed_offline_test", CLIENT)
        self.client = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.client
        self.addCleanup(sys.modules.pop, spec.name)
        spec.loader.exec_module(self.client)
        self.network_patch = mock.patch.object(self.client.HTTP, "open", side_effect=RuntimeError("Unexpected network"))
        self.network = self.network_patch.start()
        self.addCleanup(self.network_patch.stop)
        self.token = secrets.token_hex(24)

    def key_file(self, mode=0o600):
        path = Path(self.client.KEY_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.token + "\n")
        path.chmod(mode)
        return path

    def test_key_stays_private_and_environment_takes_precedence(self):
        path = self.key_file()
        self.assertEqual(self.client.load_key(), self.token)
        other = secrets.token_hex(24)
        with mock.patch.dict(os.environ, {"DEHASHED_API_KEY": other}):
            self.assertEqual(self.client.load_key(), other)
        self.assertEqual(path.read_text().strip(), self.token)
        self.network.assert_not_called()

    def test_public_or_symlinked_key_is_rejected(self):
        path = self.key_file(0o644)
        with self.assertRaises(self.client.UsageError):
            self.client.load_key()
        path.unlink()
        target = self.home / "private-value"
        target.write_text(self.token)
        target.chmod(0o600)
        path.symlink_to(target)
        with self.assertRaises(OSError):
            self.client.load_key()

    def test_key_init_is_private_and_does_not_print_the_key(self):
        output = io.StringIO()
        with mock.patch.dict(os.environ, {"DEHASHED_API_KEY": self.token}), contextlib.redirect_stdout(output):
            self.client.cmd_init(argparse.Namespace(from_env=True, force=False))
        path = Path(self.client.KEY_FILE)
        self.assertEqual(path.read_text().strip(), self.token)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        if self.token in output.getvalue():
            self.fail("Initialization exposed a credential")
        self.network.assert_not_called()

    def test_sensitive_files_are_mode_600_from_creation(self):
        target = self.home / "evidence.json"
        previous = os.umask(0)
        try:
            with self.client.private_output(str(target)) as stream:
                self.assertEqual(stat.S_IMODE(os.fstat(stream.fileno()).st_mode), 0o600)
                stream.write("private evidence")
        finally:
            os.umask(previous)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.home.glob(".dehashed-*")), [])

    def test_git_skill_and_symlink_destinations_are_blocked(self):
        alias = self.home / "alias"
        alias.symlink_to(self.repo, target_is_directory=True)
        for path in (self.repo / "result.json", alias / "result.json", CLIENT.parent.parent / "result.json"):
            with self.assertRaises(self.client.UsageError):
                self.client.write_private(str(path), "private evidence")
        self.assertFalse((self.repo / "result.json").exists())
        self.network.assert_not_called()

    def test_bad_output_is_rejected_before_authentication_or_spending(self):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors), mock.patch.object(self.client, "cmd_lookup") as lookup:
            result = self.client.main(["domain", "example.com", "--out", str(self.repo / "result.json"), "--max-credits", "1"])
        self.assertEqual(result, 2)
        self.assertIn("outside Git", errors.getvalue())
        lookup.assert_not_called()
        self.network.assert_not_called()
        self.assertFalse(Path(self.client.LEDGER_FILE).exists())

    def test_all_export_formats_use_private_files(self):
        value = secrets.token_hex(12)
        payload = {"entries": [{"email": ["user@example.com"], "password": [value]}], "meta": {}}
        for fmt in ("json", "csv", "ndjson"):
            path = self.home / ("result." + fmt)
            self.client._write_payload(payload, str(path), fmt)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(self.client.UsageError):
                self.client._write_payload(payload, str(self.repo / path.name), fmt)

    def test_only_api_https_origin_is_accepted(self):
        with mock.patch.dict(os.environ, {"DEHASHED_API_KEY": self.token}):
            for url in ("http://api.dehashed.com/v2/info/user", "https://example.invalid/", "https://api.dehashed.com.example.invalid/"):
                with self.assertRaises(self.client.UsageError):
                    self.client.request("GET", url, sleep=False)
        self.network.assert_not_called()

    def test_redirects_cannot_forward_authentication(self):
        calls = []

        class FixtureHTTPS(urllib.request.HTTPSHandler):
            def https_open(self, request):
                calls.append(request.full_url)
                headers = email.message.Message()
                headers["Location"] = "https://example.invalid/"
                response = urllib.response.addinfourl(io.BytesIO(b""), headers, request.full_url, 302)
                response.msg = "Found"
                return response

        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), FixtureHTTPS(), self.client.NoRedirect())
        request = urllib.request.Request(self.client.API + "/v2/info/user", headers={"Dehashed-Api-Key": self.token})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            opener.open(request)
        caught.exception.close()
        self.assertEqual(calls, [self.client.API + "/v2/info/user"])
        self.network.assert_not_called()

    def test_reflected_api_key_is_redacted(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = json.dumps({"echo": self.token}).encode()
        self.network.side_effect = None
        self.network.return_value = response
        with mock.patch.dict(os.environ, {"DEHASHED_API_KEY": self.token}):
            code, body = self.client.request("GET", self.client.API + "/v2/info/user", sleep=False)
        self.assertEqual(code, 200)
        self.assertEqual(body["echo"], "<redacted>")
        self.assertEqual(self.network.call_count, 1)

    def test_budget_defaults_are_preserved_without_live_calls(self):
        self.assertEqual(self.client.DEFAULT_MAX_CREDITS, 0)
        self.assertEqual(self.client.DAILY_MAX_CREDITS, 10)
        self.network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
