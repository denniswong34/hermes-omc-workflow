"""Smoke tests for Agentic OS multi-workflow redesign."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

# Isolate DB
_tmp = tempfile.mkdtemp(prefix="omc-test-")
os.environ["OMC_DB_PATH"] = str(Path(_tmp) / "test.db")

from core.db import get_db
from core.db.seed import seed_database
from core.engines import get_engine, list_engines
from core.mcp import McpCatalog
from core.memory import build_memory_store
from core.project import ProjectRepository
from core.workflow import WorkflowRuntimePool, reload_pool
from core.workflow.repository import ChannelConflictError, WorkflowRepository


class RedesignSmokeTest(unittest.TestCase):
    def setUp(self):
        self.db = get_db(os.environ["OMC_DB_PATH"])
        seed_database(self.db, activate=True)
        self.projects = ProjectRepository(self.db)
        self.repo = WorkflowRepository(self.db)
        if not self.projects.list_projects():
            self.project = self.projects.create_project(
                name="Test Project",
                working_directory="/tmp/omc-test",
            )
        else:
            self.project = self.projects.get_active_project()
        assert self.project
        if not self.repo.list_workflows(project_id=self.project["id"]):
            self.repo.clone_from_template(
                "tpl-sdlc",
                "SDLC Company",
                project_id=self.project["id"],
                coding_workspace=self.project.get("working_directory") or "",
            )
            # Activate for pool tests
            wfs = self.repo.list_workflows(project_id=self.project["id"])
            self.repo.set_active(wfs[0]["id"], True)

    def test_seed_sdlc_template(self):
        tpls = self.repo.list_templates()
        self.assertTrue(any(t["id"] == "tpl-sdlc" for t in tpls))
        wfs = self.repo.list_workflows(project_id=self.project["id"])
        self.assertGreaterEqual(len(wfs), 1)

    def test_clone_and_dual_activate_conflict(self):
        a = self.repo.list_workflows(project_id=self.project["id"])[0]
        # Set channel on first
        wf_a = self.repo.get_workflow(a["id"])
        assert wf_a
        ch = wf_a.channels[0]
        self.repo.update_channel_external_id(ch.id, "CH_SHARED_1")
        self.repo.set_active(a["id"], True)

        b = self.repo.clone_from_template(
            "tpl-sdlc", "Second Co", project_id=self.project["id"]
        )
        wf_b = self.repo.get_workflow(b.id)
        assert wf_b
        self.repo.update_channel_external_id(wf_b.channels[0].id, "CH_SHARED_1")
        # Same platform discord + same external id → conflict
        with self.assertRaises(ChannelConflictError):
            self.repo.set_active(b.id, True)

        # Different channel → ok
        self.repo.update_channel_external_id(wf_b.channels[0].id, "CH_OTHER")
        self.repo.set_active(b.id, True)
        actives = self.repo.list_active()
        self.assertGreaterEqual(len(actives), 2)

    def test_engines(self):
        ids = {e["id"] for e in list_engines()}
        self.assertEqual(ids, {"hermes", "claude", "cursor", "opencode", "codex"})
        eng = get_engine("hermes")
        self.assertEqual(eng.id, "hermes")

    def test_hermes_memory_namespace(self):
        mem_root = Path(_tmp) / "mem"
        store = build_memory_store(
            "hermes", {"path": str(mem_root), "root_folder": "OMC/wf_test"}
        )
        self.assertIsNotNone(store)
        assert store
        store.upsert_task("TASK-001", title="Hello", status="todo")
        tasks = store.list_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["task_id"], "TASK-001")

    def test_mcp_enable(self):
        wf = self.repo.list_workflows(project_id=self.project["id"])[0]
        cat = McpCatalog(self.db)
        catalog = cat.list_catalog()
        self.assertGreaterEqual(len(catalog), 1)
        cat.enable_on_workflow(wf["id"], catalog[0]["id"], True)
        servers = cat.workflow_servers(wf["id"])
        self.assertEqual(len(servers), 1)

    def test_pool_reload(self):
        pool = WorkflowRuntimePool(repo=self.repo)
        pool.reload()
        self.assertGreaterEqual(len(pool.runtimes), 1)


if __name__ == "__main__":
    unittest.main()
