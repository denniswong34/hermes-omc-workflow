"""Per-agent Hermes profiles + chat gateway identities."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from adapters.base import Message
from adapters.hub import ChatAdapterHub
from core.agent_router import AgentRouter
from core.db import Database
from core.db.seed import seed_database
from core.secrets import (
    agent_secret_key,
    enrich_agent_gateways,
    resolve_agent_gateway_credentials,
    save_agent_gateway,
)
from core.workflow.repository import WorkflowRepository


class AgentIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "omc.db"
        self.secrets_dir = Path(self.tmp.name) / "secrets"
        self.secrets_dir.mkdir()
        os.environ["OMC_DB_PATH"] = str(self.db_path)
        os.environ["OMC_SECRETS_DIR"] = str(self.secrets_dir)
        self.db = Database(self.db_path)
        self.db.init_schema()
        seed_database(self.db, activate=False)
        self.repo = WorkflowRepository(self.db)
        # Create a project + clone template
        from core.project import ProjectRepository

        projects = ProjectRepository(self.db)
        proj = projects.create_project("Test", working_directory=str(self.tmp.name))
        self.wf = self.repo.clone_from_template(
            "tpl-sdlc", "WF Identity", project_id=proj["id"]
        )

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("OMC_DB_PATH", None)
        os.environ.pop("OMC_SECRETS_DIR", None)

    def test_clone_seeds_hermes_profile(self):
        agents = self.wf.agents
        self.assertTrue(agents)
        for ag in agents:
            self.assertTrue(ag.hermes_profile)
            self.assertEqual(ag.hermes_profile, f"omc-{ag.role_id}")

    def test_agent_gateway_secrets_namespaced(self):
        ag = self.wf.agents[0]
        identity = save_agent_gateway(
            self.wf.id,
            ag.id,
            "discord",
            enabled=True,
            secret_updates={"DISCORD_BOT_TOKEN": "discord-test-token"},
            current_identity=ag.platform_identity,
        )
        self.repo.update_agent(ag.id, {"platform_identity": identity})
        scoped = agent_secret_key(ag.id, "DISCORD_BOT_TOKEN")
        from core.secrets import read_env_file, workflow_secrets_path

        data = read_env_file(workflow_secrets_path(self.wf.id))
        self.assertEqual(data.get(scoped), "discord-test-token")
        # Must NOT mirror to unscoped global (multi-bot coexistence)
        self.assertNotEqual(data.get("DISCORD_BOT_TOKEN"), "discord-test-token")

        creds = resolve_agent_gateway_credentials(
            self.wf.id, ag.id, "discord", identity
        )
        self.assertEqual(creds["DISCORD_BOT_TOKEN"], "discord-test-token")

        enriched = enrich_agent_gateways(
            self.wf.id, self.repo.get_workflow(self.wf.id).agents[0].to_dict()
        )
        self.assertTrue(enriched["gateways"]["discord"]["stored_secrets"]["DISCORD_BOT_TOKEN"])
        self.assertTrue(enriched["gateways"]["discord"]["enabled"])

    def test_session_key_uses_hermes_profile(self):
        from core.workflow import WorkflowRuntime

        wf = self.repo.get_workflow(self.wf.id)
        assert wf
        ag = next(a for a in wf.agents if a.role_id == "pm")
        self.repo.update_agent(ag.id, {"hermes_profile": "profile-pm-custom"})
        wf = self.repo.get_workflow(self.wf.id)
        rt = WorkflowRuntime(
            workflow=wf,
            memory=None,
            tickets=MagicMock(),
            agents_dir=Path("."),
        )
        self.assertEqual(rt.session_key("hermes", "product", "pm"), "profile-pm-custom")

    def test_hub_send_as_and_two_telegram_clients(self):
        hub = ChatAdapterHub()

        class StubAdapter:
            def __init__(self, name):
                self.name = name
                self.agent_id = ""
                self.role_id = ""
                self.bot_user_id = ""
                self.sent = []
                self._handler = None

            async def start(self):
                return None

            async def stop(self):
                return None

            async def send_message(self, channel_id, content):
                self.sent.append((channel_id, content))
                return "1"

            async def edit_message(self, *a, **k):
                return True

            async def send_typing(self, channel_id):
                return None

            def on_message(self, handler):
                self._handler = handler

        a1 = StubAdapter("pm")
        a2 = StubAdapter("sa")
        hub.register("telegram", a1, agent_id="ag_pm", workflow_id=self.wf.id, role_id="pm")
        hub.register("telegram", a2, agent_id="ag_sa", workflow_id=self.wf.id, role_id="sa")
        self.assertEqual(len([k for k in hub.adapters if k.startswith("telegram")]), 2)

        async def _run():
            await hub.send_as("ag_sa", "telegram", "chat1", "hello from sa")
            await hub.send_as("ag_pm", "telegram", "chat1", "hello from pm")

        asyncio.run(_run())
        self.assertEqual(a2.sent[-1][1], "hello from sa")
        self.assertEqual(a1.sent[-1][1], "hello from pm")

    def test_dm_routes_to_target_role(self):
        adapter = MagicMock()
        adapter.send_message = AsyncMock(return_value="ack1")
        adapter.edit_message = AsyncMock(return_value=True)

        coding = MagicMock()
        coding.is_coding_mention.return_value = False
        hermes = MagicMock()
        hermes.run = AsyncMock(return_value="DM reply ok")
        coding.get_hermes.return_value = hermes

        router = AgentRouter(
            adapter=adapter,
            topics={},
            topic_by_channel_id={},
            agent_prompts={"pm": "You are PM"},
            agent_routes={},
            channel_names={},
            coding=coding,
            workflow_id=self.wf.id,
            agent_meta={
                "pm": {
                    "id": "ag_pm",
                    "hermes_profile": "omc-profile-pm",
                    "llm_model": "test-model",
                }
            },
        )

        msg = Message(
            id="m1",
            channel_id="999",
            author_id="u1",
            author_name="user",
            content="help me",
            is_dm=True,
            target_role="pm",
            bot_mentioned=True,
            platform="telegram",
            bot_user_id="bot1",
            agent_id="ag_pm",
        )
        asyncio.run(router.handle_message(msg))
        hermes.run.assert_awaited()
        kwargs = hermes.run.await_args.kwargs
        self.assertEqual(kwargs.get("session_key"), "omc-profile-pm")
        self.assertEqual(kwargs.get("profile"), "omc-profile-pm")
        self.assertEqual(kwargs.get("model"), "test-model")

    def test_gateway_guides_api_shape(self):
        from core.gateway_guides import gateway_guides_payload, render_gateway_setup_markdown

        payload = gateway_guides_payload()
        self.assertIn("discord", payload["guides"])
        self.assertIn("telegram", payload["guides"])
        self.assertIn("slack", payload["guides"])
        self.assertIn("zulip", payload["guides"])
        md = render_gateway_setup_markdown()
        self.assertIn("Discord bot gateway", md)
        self.assertIn("BotFather", md)


if __name__ == "__main__":
    unittest.main()
