#!/usr/bin/env python3
"""Verify the privileged UI without running networking commands."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "internetshare"))
from ishare import web


class LocalControl(unittest.TestCase):
    def setUp(self):
        self.client = web.app.test_client()

    def login(self):
        result = self.client.get("/login", query_string={"token": web.ACCESS_TOKEN})
        self.assertEqual(result.status_code, 302)
        self.assertIn("HttpOnly", result.headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", result.headers["Set-Cookie"])

    def test_unauthenticated_control_is_rejected(self):
        with patch.object(web.core, "stop") as stop:
            self.assertEqual(self.client.post("/api/stop", json={}).status_code, 401)
            stop.assert_not_called()

    def test_authenticated_control(self):
        self.login()
        with patch.object(web.core, "stop", return_value={}) as stop, patch.object(web.core, "list_interfaces", return_value=[]):
            self.assertEqual(self.client.post("/api/stop", json={}).status_code, 200)
            stop.assert_called_once()

    def test_cross_site_and_form_posts_are_rejected(self):
        self.login()
        with patch.object(web.core, "stop") as stop:
            self.assertEqual(self.client.post("/api/stop", json={}, headers={"Origin": "https://example.invalid"}).status_code, 403)
            self.assertEqual(self.client.post("/api/stop", data="{}", content_type="text/plain").status_code, 415)
            self.assertEqual(self.client.post("/api/stop", json={}, headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
            stop.assert_not_called()

    def test_dns_rebinding_and_nonlocal_bind_are_rejected(self):
        self.assertEqual(self.client.get("/", base_url="http://example.invalid").status_code, 403)
        with patch.object(web.core, "start_monitor") as monitor:
            with self.assertRaises(SystemExit):
                web.main(["--host", "0.0.0.0"])
            monitor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
