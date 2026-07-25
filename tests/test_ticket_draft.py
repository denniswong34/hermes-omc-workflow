"""Unit tests for ticket drafting and ADF/HTML formatting."""

from __future__ import annotations

import unittest

from core.tickets.draft import draft_ticket, format_agent_comment
from core.tickets.formatting import plain_to_adf, plain_to_html


class TicketDraftUnit(unittest.TestCase):
    def test_feature_not_raw_copy(self):
        msg = (
            "@PM Create/track Jira task for SDLC-E2E-20260725-1625: "
            "one-line scope for passwordless magic-link login. Then @SA."
        )
        d = draft_ticket(msg, topic="engineering", role="pm", author="Boss")
        self.assertNotIn("@PM", d.title)
        self.assertNotIn("SDLC-E2E", d.title)
        self.assertNotEqual(d.title.strip().lower(), msg.strip().lower())
        self.assertNotEqual(d.description.strip(), d.title.strip())
        self.assertIn("## Requirements", d.description)
        self.assertIn("## Acceptance criteria", d.description)
        self.assertIn(msg.strip()[:40], d.description)  # verbatim only in context quote
        self.assertTrue(d.title.lower().startswith("implement") or "magic" in d.title.lower())

    def test_bug_repro_sections(self):
        msg = "@SA Triage: user never received magic-link email."
        d = draft_ticket(msg, topic="support", role="sa")
        self.assertEqual(d.kind, "bug")
        self.assertIn("## Steps to reproduce", d.description)
        self.assertIn("## Evidence / attachments", d.description)
        self.assertNotEqual(d.description, d.title)

    def test_agent_comment_format(self):
        c = format_agent_comment(
            role="qa",
            topic="engineering",
            body="Status: qa review\nTwo test cases ready.",
            status="qa review",
            task_id="TASK-012",
        )
        self.assertIn("[QA · #engineering] · TASK-012", c)
        self.assertIn("Status → qa review", c)
        self.assertIn("Two test cases ready", c)


class FormattingUnit(unittest.TestCase):
    def test_adf_headings_and_bullets(self):
        adf = plain_to_adf("## Overview\nHello\n- one\n- two")
        types = [b["type"] for b in adf["content"]]
        self.assertIn("heading", types)
        self.assertIn("bulletList", types)
        self.assertIn("paragraph", types)

    def test_html_basic(self):
        html = plain_to_html("## Overview\nDo the thing\n- a\n- b")
        self.assertIn("<h3>Overview</h3>", html)
        self.assertIn("<li>a</li>", html)


if __name__ == "__main__":
    unittest.main()
