"""Handoff concurrency: standby filtering + per-role supersede."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from adapters.base import Message
from core.agent_router import AgentRouter, is_standby_handoff
from core.coding import CodingRegistry


def _router() -> AgentRouter:
    adapter = MagicMock()
    adapter.send_message = AsyncMock(side_effect=lambda *a, **k: "ack-1")
    adapter.edit_message = AsyncMock(return_value=True)
    coding = MagicMock(spec=CodingRegistry)
    coding.is_coding_mention = MagicMock(return_value=False)
    coding.get_hermes = MagicMock()
    return AgentRouter(
        adapter=adapter,
        topics={
            "engineering": {
                "channel_id": "ch-eng",
                "agents": ["pm", "sa", "coder", "qa", "devops"],
                "ticket_create_roles": ["pm"],
            }
        },
        topic_by_channel_id={"ch-eng": "engineering"},
        agent_prompts={
            "pm": "pm",
            "sa": "sa",
            "coder": "coder",
            "qa": "qa",
            "devops": "devops",
        },
        agent_routes={
            "pm": ["sa", "coder", "devops"],
            "sa": ["coder", "qa", "pm"],
            "coder": ["qa", "sa"],
            "qa": ["devops", "coder"],
            "devops": ["pm"],
        },
        channel_names={"ch-eng": "engineering"},
        coding=coding,
        message_format="block",
    )


class StandbyHandoffTests(unittest.TestCase):
    def test_detects_wait_phrases(self):
        self.assertTrue(is_standby_handoff("wait for spec from @SA before starting"))
        self.assertTrue(is_standby_handoff("Waiting on @SA for the spec"))
        self.assertTrue(is_standby_handoff("stand by until SA finishes"))
        self.assertFalse(
            is_standby_handoff(
                "TASK-012 — spec above. Implement magic-link login per this spec."
            )
        )

    def test_select_drops_standby_and_keeps_linear_first(self):
        r = _router()
        selected = r._select_handoffs(
            "pm",
            [
                ("sa", "Write the API spec for TASK-012"),
                ("coder", "wait for SA before starting implementation"),
            ],
        )
        self.assertEqual(selected, [("sa", "Write the API spec for TASK-012")])

    def test_sa_may_fan_out_coder_and_qa(self):
        r = _router()
        selected = r._select_handoffs(
            "sa",
            [
                ("coder", "Implement per spec above"),
                ("qa", "Prepare test cases from AC"),
            ],
        )
        self.assertEqual(len(selected), 2)


class ConcurrentMentionTests(unittest.TestCase):
    def test_standby_discord_mention_ignored(self):
        r = _router()
        r._invoke_role = AsyncMock(return_value="should not run")
        msg = Message(
            id="m1",
            channel_id="ch-eng",
            author_id="bot-pm",
            author_name="OMC Dennis PM",
            content="@coder: wait for spec from @SA before starting",
            is_bot=True,
        )
        asyncio.run(r.handle_message(msg))
        r._invoke_role.assert_not_called()

    def test_newer_mention_supersedes_queued_turn(self):
        r = _router()
        order: list[str] = []
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_then_fast(*, role, prompt, topic_key):
            order.append(f"start:{role}:{prompt[:20]}")
            if "WAIT" in prompt:
                started.set()
                await release.wait()
                order.append("finish:wait")
                return "Understood. Waiting on @SA."
            order.append("finish:real")
            return "Implemented magic_link_login stub per SA spec."

        r._invoke_role = AsyncMock(side_effect=slow_then_fast)

        async def scenario():
            wait_msg = Message(
                id="m-wait",
                channel_id="ch-eng",
                author_id="agent:pm",
                author_name="@pm",
                content="@coder: WAIT for SA spec",
                is_bot=True,
            )
            # Bypass standby filter to exercise supersede path only
            t_wait = asyncio.create_task(
                r._run_agent_turn(
                    msg=wait_msg,
                    topic=r.topics["engineering"],
                    topic_key="engineering",
                    role="coder",
                    content="WAIT for SA spec",
                    depth=1,
                )
            )
            await started.wait()
            real_msg = Message(
                id="m-real",
                channel_id="ch-eng",
                author_id="agent:sa",
                author_name="@sa",
                content="@coder: Implement per SA spec above",
                is_bot=True,
            )
            t_real = asyncio.create_task(
                r._run_agent_turn(
                    msg=real_msg,
                    topic=r.topics["engineering"],
                    topic_key="engineering",
                    role="coder",
                    content="Implement per SA spec above",
                    depth=2,
                )
            )
            # Let the real turn bump epoch while wait holds the gate
            await asyncio.sleep(0.05)
            release.set()
            await asyncio.gather(t_wait, t_real)

        asyncio.run(scenario())
        # Wait turn ran Hermes, then saw a newer epoch and dropped its reply.
        self.assertIn("finish:wait", order)
        self.assertIn("finish:real", order)
        edits = [str(c.args[2]) for c in r.adapter.edit_message.await_args_list]
        self.assertTrue(
            any("Superseded" in e for e in edits),
            f"expected superseded edit, got {edits!r}",
        )
        self.assertTrue(
            any("Implemented" in e or "magic_link" in e.lower() for e in edits),
            f"expected real reply edit, got {edits!r}",
        )

    def test_pm_multi_handoff_does_not_fire_coder_wait(self):
        r = _router()
        invoked: list[str] = []

        async def capture(*, role, prompt, topic_key):
            invoked.append(role)
            if role == "pm":
                return (
                    "Created TASK-012.\n"
                    "@sa: Write the full API spec for TASK-012.\n"
                    "@coder: wait for SA before starting.\n"
                )
            if role == "sa":
                return (
                    "Spec complete.\n"
                    "@coder: TASK-012 — implement magic-link per spec above.\n"
                )
            return f"{role} done — stub implemented."

        r._invoke_role = AsyncMock(side_effect=capture)
        msg = Message(
            id="m-pm",
            channel_id="ch-eng",
            author_id="human-1",
            author_name="denniswong34",
            content="@PM create magic-link task and hand to SA",
            is_bot=False,
        )
        asyncio.run(r.handle_message(msg))
        self.assertEqual(invoked.count("pm"), 1)
        self.assertEqual(invoked.count("sa"), 1)
        self.assertEqual(invoked.count("coder"), 1)
        # Coder should have been invoked from SA's actionable handoff only.
        coder_prompts = [
            c.kwargs["prompt"]
            for c in r._invoke_role.await_args_list
            if c.kwargs.get("role") == "coder"
        ]
        self.assertEqual(len(coder_prompts), 1)
        self.assertIn("implement magic-link", coder_prompts[0].lower())
        self.assertNotIn("wait for SA", coder_prompts[0].lower())


if __name__ == "__main__":
    unittest.main()
