"""Tests for Hermes profile naming + sync (tokens, allow-all, aliases)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.db import Database
from core.db.seed import seed_database
from core.hermes_profiles import (
    apply_agent_gateways_to_profile,
    build_hermes_setup_guide,
    create_profile_from_default,
    default_agent_profile_name,
    ensure_profile_alias,
    profile_dir,
    sync_workflow_hermes_profiles,
    upsert_env_values,
    wrapper_script_path,
)
from core.project import ProjectRepository
from core.secrets import save_agent_gateway
from core.workflow.repository import WorkflowRepository


class HermesProfileSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db_path = root / "omc.db"
        self.secrets_dir = root / "secrets"
        self.secrets_dir.mkdir()
        self.hermes_home = root / "hermes-home"
        self.hermes_home.mkdir()
        (self.hermes_home / "config.yaml").write_text(
            "gateway:\n  strict: false\n", encoding="utf-8"
        )
        (self.hermes_home / ".env").write_text(
            "# default\nSHARED_KEY=from-default\nDISCORD_BOT_TOKEN=default-dead-token\n",
            encoding="utf-8",
        )
        (self.hermes_home / "SOUL.md").write_text("# Soul\n", encoding="utf-8")
        (self.hermes_home / "skills").mkdir()
        self.wrapper_dir = root / "local-bin"
        self.wrapper_dir.mkdir()

        os.environ["OMC_DB_PATH"] = str(self.db_path)
        os.environ["OMC_SECRETS_DIR"] = str(self.secrets_dir)
        os.environ["OMC_HERMES_HOME"] = str(self.hermes_home)

        self.db = Database(self.db_path)
        self.db.init_schema()
        seed_database(self.db, activate=False)
        self.repo = WorkflowRepository(self.db)
        projects = ProjectRepository(self.db)
        proj = projects.create_project("HP", working_directory=str(root))
        self.wf = self.repo.clone_from_template(
            "tpl-sdlc", "WF Profiles", project_id=proj["id"]
        )

        self._wrapper_patch = patch(
            "core.hermes_profiles.wrapper_bin_dir", return_value=self.wrapper_dir
        )
        self._wrapper_patch.start()

    def tearDown(self):
        self._wrapper_patch.stop()
        self.tmp.cleanup()
        for key in (
            "OMC_DB_PATH",
            "OMC_SECRETS_DIR",
            "OMC_HERMES_HOME",
            "OMC_HERMES_BIN",
        ):
            os.environ.pop(key, None)

    def test_default_agent_profile_name_is_short(self):
        self.assertEqual(default_agent_profile_name("wf_abc123", "pm"), "omc-pm")
        self.assertEqual(default_agent_profile_name("", "sa"), "omc-sa")

    def test_upsert_env_preserves_comments(self):
        path = Path(self.tmp.name) / "sample.env"
        path.write_text("# keep me\nFOO=1\nBAR=2\n", encoding="utf-8")
        changed = upsert_env_values(path, {"FOO": "9", "BAZ": "3"})
        text = path.read_text(encoding="utf-8")
        self.assertIn("# keep me", text)
        self.assertIn("FOO=9", text)
        self.assertIn("BAZ=3", text)
        self.assertIn("FOO", changed)
        self.assertIn("BAZ", changed)

    def test_ensure_profile_alias_writes_wrapper(self):
        with patch("core.hermes_profiles._which_hermes", return_value=None):
            result = ensure_profile_alias("omc-qa")
        self.assertEqual(result["action"], "created")
        path = wrapper_script_path("omc-qa")
        self.assertTrue(path.is_file())
        self.assertIn("hermes -p omc-qa", path.read_text(encoding="utf-8"))

    def test_apply_gateways_writes_tokens_and_allow_all(self):
        with patch("core.hermes_profiles._which_hermes", return_value=None):
            create_profile_from_default("omc-pm")
        ag = next(a for a in self.wf.agents if a.role_id == "pm")
        identity = save_agent_gateway(
            self.wf.id,
            ag.id,
            "discord",
            enabled=True,
            secret_updates={"DISCORD_BOT_TOKEN": "agent-pm-discord-token"},
            current_identity=ag.platform_identity,
        )
        applied = apply_agent_gateways_to_profile(
            "omc-pm", self.wf.id, ag.id, identity
        )
        self.assertEqual(applied, ["discord"])
        env = (profile_dir("omc-pm") / ".env").read_text(encoding="utf-8")
        self.assertIn("DISCORD_BOT_TOKEN=agent-pm-discord-token", env)
        self.assertNotIn("DISCORD_BOT_TOKEN=default-dead-token", env)
        self.assertIn("DISCORD_ALLOW_ALL_USERS=true", env)
        self.assertIn("GATEWAY_ALLOW_ALL_USERS=true", env)
        self.assertTrue(wrapper_script_path("omc-pm").is_file())
        import yaml

        cfg = yaml.safe_load(
            (profile_dir("omc-pm") / "config.yaml").read_text(encoding="utf-8")
        )
        self.assertTrue(cfg["platforms"]["discord"]["enabled"])

    def test_setup_guide_assigns_short_names_and_commands(self):
        guide = build_hermes_setup_guide(self.repo, self.wf.id)
        self.assertTrue(guide["ok"])
        self.assertIn(
            "hermes profile create omc-pm --clone-from default", guide["script"]
        )
        self.assertIn("hermes profile alias omc-pm", guide["script"])
        self.assertIn("DISCORD_ALLOW_ALL_USERS=true", guide["script"])
        self.assertIn("--start-on-login", guide["script"])

    def test_sync_copies_persona_into_soul_and_description(self):
        agents_dir = Path(self.tmp.name) / "agents"
        (agents_dir / "_shared").mkdir(parents=True)
        (agents_dir / "_shared" / "sdlc.md").write_text(
            "# SDLC\nshared-sdlc", encoding="utf-8"
        )
        (agents_dir / "_shared" / "handoff.md").write_text(
            "# Handoff\nshared-handoff", encoding="utf-8"
        )
        (agents_dir / "pm.md").write_text(
            "# You are the PM Agent\nPortal PM persona body.",
            encoding="utf-8",
        )
        self.db.set_setting("agents_dir", str(agents_dir))

        with patch("core.hermes_profiles._which_hermes", return_value=None), patch(
            "core.hermes_profiles.set_hermes_profile_description",
            return_value={"action": "updated", "description": "OMC Product Manager"},
        ) as describe:
            summary = sync_workflow_hermes_profiles(
                self.repo, self.wf.id, start_gateways=False
            )

        pm = next(r for r in summary["results"] if r["role_id"] == "pm")
        soul = (profile_dir("omc-pm") / "SOUL.md").read_text(encoding="utf-8")
        self.assertIn("Portal PM persona body", soul)
        self.assertIn("shared-sdlc", soul)
        self.assertIn("OMC Agent Portal", soul)
        self.assertRegex(soul, r"@[Pp][Mm]")
        self.assertTrue(pm["persona"]["soul_changed"])
        describe.assert_called()
        pm_calls = [
            c
            for c in describe.call_args_list
            if (c.args and c.args[0] == "omc-pm")
            or c.kwargs.get("profile_name") == "omc-pm"
        ]
        self.assertTrue(pm_calls, "expected describe(omc-pm, ...)")
        self.assertEqual(pm_calls[0].args[1], "OMC Product Manager")

    def test_sync_workflow_applies_tokens_and_starts_gateway(self):
        ag = next(a for a in self.wf.agents if a.role_id == "pm")
        identity = save_agent_gateway(
            self.wf.id,
            ag.id,
            "discord",
            enabled=True,
            secret_updates={"DISCORD_BOT_TOKEN": "agent-pm-discord-token"},
            current_identity=ag.platform_identity,
        )
        self.repo.update_agent(ag.id, {"platform_identity": identity})

        with patch("core.hermes_profiles._which_hermes", return_value=None), patch(
            "core.hermes_profiles.start_hermes_gateway",
            return_value={"status": "restarted", "profile": "omc-pm", "pids": [1]},
        ) as start_gw, patch(
            "core.hermes_profiles.set_hermes_profile_description",
            return_value={"action": "updated", "description": "OMC Product Manager"},
        ):
            # Provide minimal persona files so SOUL sync does not fail
            agents_dir = Path(self.tmp.name) / "agents2"
            (agents_dir / "_shared").mkdir(parents=True)
            (agents_dir / "pm.md").write_text("# PM\npm-body", encoding="utf-8")
            for role in (
                "sa",
                "coder",
                "qa",
                "devops",
                "marketing",
                "standup",
                "hermes",
                "claude",
                "cursor",
                "opencode",
                "codex",
            ):
                # coding aliases reuse coder.md via ROLE_FILES
                pass
            (agents_dir / "sa.md").write_text("# SA\n", encoding="utf-8")
            (agents_dir / "coder.md").write_text("# Coder\n", encoding="utf-8")
            (agents_dir / "qa.md").write_text("# QA\n", encoding="utf-8")
            (agents_dir / "devops.md").write_text("# DevOps\n", encoding="utf-8")
            (agents_dir / "marketing.md").write_text("# Marketing\n", encoding="utf-8")
            (agents_dir / "standup.md").write_text("# Standup\n", encoding="utf-8")
            self.db.set_setting("agents_dir", str(agents_dir))
            summary = sync_workflow_hermes_profiles(self.repo, self.wf.id)

        self.assertTrue(summary["ok"])
        self.assertGreaterEqual(summary["gateways_started"], 1)
        start_gw.assert_called()
        kwargs = start_gw.call_args.kwargs
        self.assertTrue(kwargs.get("force_restart"))
        self.assertTrue(kwargs.get("start_on_login"))

        env = (profile_dir("omc-pm") / ".env").read_text(encoding="utf-8")
        self.assertIn("DISCORD_BOT_TOKEN=agent-pm-discord-token", env)
        self.assertIn("GATEWAY_ALLOW_ALL_USERS=true", env)

        import yaml

        cfg = yaml.safe_load(
            (profile_dir("omc-pm") / "config.yaml").read_text(encoding="utf-8")
        )
        self.assertTrue(cfg["platforms"]["discord"]["enabled"])
        self.assertIn("discord", summary.get("platforms_enabled") or [])

        pm = next(r for r in summary["results"] if r["role_id"] == "pm")
        self.assertEqual(pm["hermes_profile"], "omc-pm")
        self.assertEqual(pm["platforms_enabled"], ["discord"])
        self.assertEqual(pm["gateway"]["status"], "restarted")
        self.assertIsNotNone(pm.get("alias"))
        self.assertIn(pm["alias"]["action"], ("created", "exists"))
        self.assertTrue(wrapper_script_path("omc-pm").is_file())
        self.assertIn("pm-body", (profile_dir("omc-pm") / "SOUL.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
