"""Unit tests for SDLC → Jira/Plane status mapping and sync helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from core.tickets.jira import JiraTracker
from core.tickets.plane import PlaneTracker
from core.tickets.status import SdlcStatus
from core.tickets.status_map import (
    build_plane_status_map,
    build_status_map_from_names,
    pick_jira_transition,
)


class StatusMapUnit(unittest.TestCase):
    def test_short_jira_board_maps_all_sdlc(self):
        names = ["To Do", "In Progress", "In Review", "Done"]
        categories = {
            "To Do": "new",
            "In Progress": "indeterminate",
            "In Review": "indeterminate",
            "Done": "done",
        }
        sm = build_status_map_from_names(names, categories=categories)
        self.assertEqual(sm[SdlcStatus.TODO.value], "To Do")
        self.assertEqual(sm[SdlcStatus.IN_PROGRESS.value], "In Progress")
        self.assertEqual(sm[SdlcStatus.IN_REVIEW.value], "In Review")
        self.assertEqual(sm[SdlcStatus.QA_REVIEW.value], "In Review")
        self.assertEqual(sm[SdlcStatus.READY_TO_DEPLOY.value], "Done")
        self.assertEqual(sm[SdlcStatus.DONE.value], "Done")
        self.assertEqual(len(sm), len(SdlcStatus))

    def test_custom_jira_names_preferred(self):
        names = ["Backlog", "Doing", "QA Review", "Ready to Deploy", "Done"]
        sm = build_status_map_from_names(names)
        self.assertEqual(sm[SdlcStatus.BACKLOG.value], "Backlog")
        self.assertEqual(sm[SdlcStatus.IN_PROGRESS.value], "Doing")
        self.assertEqual(sm[SdlcStatus.QA_REVIEW.value], "QA Review")
        self.assertEqual(sm[SdlcStatus.READY_TO_DEPLOY.value], "Ready to Deploy")

    def test_pick_transition_falls_back(self):
        transitions = [
            {"id": "11", "name": "To Do", "to": {"name": "To Do", "statusCategory": {"key": "new"}}},
            {
                "id": "21",
                "name": "In Progress",
                "to": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}},
            },
            {
                "id": "31",
                "name": "In Review",
                "to": {"name": "In Review", "statusCategory": {"key": "indeterminate"}},
            },
            {"id": "41", "name": "Done", "to": {"name": "Done", "statusCategory": {"key": "done"}}},
        ]
        t = pick_jira_transition(
            transitions,
            SdlcStatus.READY_TO_DEPLOY,
            preferred_target="Ready to Deploy",
        )
        self.assertIsNotNone(t)
        assert t is not None
        self.assertEqual(t["id"], "41")
        self.assertEqual((t.get("to") or {}).get("name"), "Done")

    def test_plane_group_fallback(self):
        states = [
            {"id": "s-backlog", "name": "Backlog", "group": "backlog"},
            {"id": "s-todo", "name": "Todo", "group": "unstarted"},
            {"id": "s-progress", "name": "In Progress", "group": "started"},
            {"id": "s-done", "name": "Done", "group": "completed"},
            {"id": "s-cancel", "name": "Cancelled", "group": "cancelled"},
        ]
        sm = build_plane_status_map(states)
        self.assertEqual(sm[SdlcStatus.BACKLOG.value], "s-backlog")
        self.assertEqual(sm[SdlcStatus.TODO.value], "s-todo")
        self.assertEqual(sm[SdlcStatus.IN_PROGRESS.value], "s-progress")
        self.assertEqual(sm[SdlcStatus.QA_REVIEW.value], "s-progress")
        self.assertEqual(sm[SdlcStatus.DONE.value], "s-done")
        self.assertEqual(sm[SdlcStatus.CANCELLED.value], "s-cancel")


class JiraTrackerSyncUnit(unittest.IsolatedAsyncioTestCase):
    async def test_update_status_uses_fallback_transition(self):
        tracker = JiraTracker(
            "https://ex.atlassian.net",
            "a@b.com",
            "tok",
            "HOAO",
            status_map={"ready_to_deploy": "Ready to Deploy"},
        )
        transitions = {
            "transitions": [
                {
                    "id": "41",
                    "name": "Done",
                    "to": {"name": "Done", "statusCategory": {"key": "done"}},
                },
                {
                    "id": "21",
                    "name": "In Progress",
                    "to": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}},
                },
            ]
        }

        async def fake_request(method, path, data=None):
            if method == "GET":
                return transitions
            self.assertEqual(method, "POST")
            self.assertEqual(data, {"transition": {"id": "41"}})
            return True

        with patch.object(tracker, "_request", side_effect=fake_request):
            ok = await tracker.update_status("HOAO-1", SdlcStatus.READY_TO_DEPLOY)
        self.assertTrue(ok)
        self.assertEqual(tracker.status_map["ready_to_deploy"], "Done")


class PlaneTrackerSyncUnit(unittest.IsolatedAsyncioTestCase):
    async def test_ensure_status_map_and_update(self):
        tracker = PlaneTracker(
            "https://api.plane.so",
            "acme",
            "proj-1",
            api_key="key",
            status_map={},
        )
        states = [
            {"id": "s1", "name": "Backlog", "group": "backlog"},
            {"id": "s2", "name": "In Progress", "group": "started"},
            {"id": "s3", "name": "Done", "group": "completed"},
        ]

        async def fake_request(method, path, data=None):
            if "states" in path:
                return states
            self.assertEqual(method, "PATCH")
            self.assertEqual(data, {"state": tracker.status_map[SdlcStatus.IN_PROGRESS.value]})
            return {"id": "issue-1"}

        with patch.object(tracker, "_request", side_effect=fake_request):
            ok = await tracker.update_status("issue-1", SdlcStatus.IN_PROGRESS)
        self.assertTrue(ok)
        self.assertEqual(tracker.status_map[SdlcStatus.IN_PROGRESS.value], "s2")


if __name__ == "__main__":
    unittest.main()
