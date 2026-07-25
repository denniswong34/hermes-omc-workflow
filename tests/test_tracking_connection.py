"""Unit tests for tracking connection probes (mocked HTTP)."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from core.tracking_test import test_jira, test_plane, test_tracking_connection


class _FakeResp:
    def __init__(self, status: int, payload):
        self.status = status
        self._raw = json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TrackingTestUnit(unittest.TestCase):
    def test_missing(self):
        self.assertFalse(test_tracking_connection("jira", {})["ok"])
        self.assertFalse(test_tracking_connection("plane", {})["ok"])
        self.assertIn("Unsupported", test_tracking_connection("x", {})["message"])

    def test_jira_ok(self):
        calls = [
            _FakeResp(200, {"accountId": "a1", "displayName": "Bot", "emailAddress": "b@x.com"}),
            _FakeResp(200, {"id": "10000", "key": "OMC", "name": "OMC Project"}),
        ]

        def side_effect(*args, **kwargs):
            return calls.pop(0)

        with patch("core.chat_test.urllib.request.urlopen", side_effect=side_effect):
            r = test_jira("https://ex.atlassian.net", "b@x.com", "tok", "OMC")
        self.assertTrue(r["ok"])
        self.assertIn("OMC", r["message"])

    def test_plane_ok(self):
        calls = [
            _FakeResp(200, {"name": "Acme", "slug": "acme"}),
            _FakeResp(200, {"name": "Main", "id": "proj-1"}),
        ]

        def side_effect(*args, **kwargs):
            return calls.pop(0)

        with patch("core.chat_test.urllib.request.urlopen", side_effect=side_effect):
            r = test_plane("https://api.plane.so", "acme", "proj-1", "key")
        self.assertTrue(r["ok"])
        self.assertIn("Acme", r["message"])


if __name__ == "__main__":
    unittest.main()
