"""Unit tests for chat message formats and outbound splitting."""

from __future__ import annotations

import unittest

from core.agent_router import AgentRouter
from core.chat_messages import (
    DEFAULT_MESSAGE_FORMAT,
    format_error,
    format_handoff,
    format_processing,
    format_reply,
    is_bot_own_message,
    normalize_message_format,
    split_outbound,
    strip_display_prefix,
)


class MessageFormatUnit(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_message_format(None), DEFAULT_MESSAGE_FORMAT)
        self.assertEqual(normalize_message_format("BLOCK"), "block")
        self.assertEqual(normalize_message_format("nope"), "card")

    def test_each_format_includes_role_and_body(self):
        body = "Scoped magic-link login for mobile."
        for fmt in ("block", "card", "quote", "sections"):
            with self.subTest(fmt=fmt):
                proc = format_processing("pm", fmt)
                self.assertIn("PM", proc)
                self.assertTrue(
                    "working" in proc.lower() or "Working" in proc
                )

                reply = format_reply(
                    "pm",
                    body,
                    fmt=fmt,
                    topic="engineering",
                    task_id="TASK-015",
                    ticket_url="https://ex.example/HOAO-1",
                    status="todo",
                    handoffs=["sa"],
                )
                self.assertIn("PM", reply)
                self.assertIn(body, reply)
                self.assertIn("SA", reply.upper().replace("@", ""))

                err = format_error("qa", "boom", fmt)
                self.assertIn("QA", err)
                self.assertIn("boom", err)

                hand = format_handoff("pm", "sa", "@sa: please draft", depth=1, fmt=fmt)
                self.assertIn("PM", hand)
                self.assertIn("SA", hand)
                self.assertIn("@sa: please draft", hand)

    def test_bot_own_detection_legacy_and_new(self):
        self.assertTrue(is_bot_own_message("**[@PM]**\nhello"))
        self.assertTrue(is_bot_own_message("🔄 **[@PM]** Processing..."))
        self.assertTrue(is_bot_own_message(format_processing("pm", "card")))
        self.assertTrue(is_bot_own_message(format_reply("pm", "hi", fmt="block")))
        self.assertFalse(is_bot_own_message("@PM please scope login"))

    def test_strip_prefix_keeps_mentions(self):
        legacy = "**[@PM]**\n@SA please continue"
        self.assertEqual(strip_display_prefix(legacy), "@SA please continue")

        card = format_handoff("pm", "sa", "@sa: draft the API", depth=1, fmt="card")
        stripped = strip_display_prefix(card)
        self.assertIn("@sa", stripped.lower())

    def test_agent_router_handoff_detect(self):
        self.assertTrue(
            AgentRouter._is_agent_handoff_post(
                "**[@PM → @SA]** (depth:1)\n@sa: hi"
            )
        )
        self.assertTrue(
            AgentRouter._is_agent_handoff_post(
                format_handoff("pm", "sa", "@sa: hi", depth=2, fmt="card")
            )
        )
        self.assertFalse(AgentRouter._is_agent_handoff_post("@PM please help"))


class SplitOutboundUnit(unittest.TestCase):
    def test_under_limit_single_chunk(self):
        chunks = split_outbound("hello world", 100)
        self.assertEqual(chunks, ["hello world"])

    def test_over_limit_multiple_chunks(self):
        text = ("paragraph one about login.\n\n" * 40) + ("word " * 200)
        chunks = split_outbound(text, 1900, role="pm")
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(len(c), 1900)
        self.assertTrue(chunks[0].startswith("paragraph") or "login" in chunks[0])
        self.assertIn("cont.", chunks[1].lower())
        self.assertIn("PM", chunks[1])

    def test_prefers_paragraph_break(self):
        a = "A" * 100
        b = "B" * 100
        text = a + "\n\n" + b
        chunks = split_outbound(text, 120)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(chunks[0].rstrip().endswith("A") or "A" in chunks[0])


if __name__ == "__main__":
    unittest.main()
