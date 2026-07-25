"""Unit tests for chat connection probes (mocked HTTP)."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from core.chat_test import test_chat_connection, test_discord, test_slack, test_telegram, test_zulip


class _FakeResp:
    def __init__(self, status: int, payload):
        self.status = status
        self._raw = json.dumps(payload).encode() if not isinstance(payload, bytes) else payload

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _patch_urlopen(status: int, payload: dict):
    return patch(
        "core.chat_test.urllib.request.urlopen",
        return_value=_FakeResp(status, payload),
    )


class ChatTestUnit(unittest.TestCase):
    def test_missing_credentials(self):
        self.assertFalse(test_chat_connection("discord", {})["ok"])
        self.assertFalse(test_chat_connection("slack", {})["ok"])
        self.assertFalse(test_chat_connection("telegram", {})["ok"])
        self.assertFalse(test_chat_connection("zulip", {})["ok"])
        self.assertIn("Unsupported", test_chat_connection("foo", {})["message"])

    def test_discord_ok(self):
        with _patch_urlopen(200, {"id": "1", "username": "omc-bot"}):
            r = test_discord("tok")
        self.assertTrue(r["ok"])
        self.assertIn("omc-bot", r["message"])

    def test_discord_strips_bot_prefix(self):
        with _patch_urlopen(200, {"id": "1", "username": "x"}):
            r = test_discord("Bot abc")
        self.assertTrue(r["ok"])

    def test_slack_ok(self):
        with _patch_urlopen(200, {"ok": True, "user": "bot", "team": "Acme"}):
            r = test_slack("xoxb-1", "xapp-1")
        self.assertTrue(r["ok"])
        self.assertIn("Acme", r["message"])

    def test_slack_bad_app_token(self):
        with _patch_urlopen(200, {"ok": True, "user": "bot", "team": "Acme"}):
            r = test_slack("xoxb-1", "bad")
        self.assertFalse(r["ok"])
        self.assertIn("xapp-", r["message"])

    def test_telegram_ok(self):
        with _patch_urlopen(200, {"ok": True, "result": {"username": "omc_bot", "id": 9}}):
            r = test_telegram("123:ABC")
        self.assertTrue(r["ok"])
        self.assertIn("omc_bot", r["message"])

    def test_zulip_ok(self):
        with _patch_urlopen(200, {"result": "success", "full_name": "OMC Bot", "email": "b@x.com"}):
            r = test_zulip("chat.example.com", "b@x.com", "key")
        self.assertTrue(r["ok"])
        self.assertIn("OMC Bot", r["message"])

    def test_dispatcher(self):
        with _patch_urlopen(200, {"id": "1", "username": "d"}):
            self.assertTrue(test_chat_connection("discord", {"DISCORD_BOT_TOKEN": "t"})["ok"])
        with _patch_urlopen(200, {"ok": True, "user": "u", "team": "t"}):
            self.assertTrue(
                test_chat_connection("slack", {"SLACK_BOT_TOKEN": "xoxb"})["ok"]
            )
        with _patch_urlopen(200, {"ok": True, "result": {"username": "tg"}}):
            self.assertTrue(
                test_chat_connection("telegram", {"TELEGRAM_BOT_TOKEN": "1:a"})["ok"]
            )
        with _patch_urlopen(200, {"full_name": "Z"}):
            self.assertTrue(
                test_chat_connection(
                    "zulip",
                    {
                        "ZULIP_SITE": "https://z.example",
                        "ZULIP_EMAIL": "a@b.c",
                        "ZULIP_API_KEY": "k",
                    },
                )["ok"]
            )


if __name__ == "__main__":
    unittest.main()
