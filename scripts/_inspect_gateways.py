"""One-shot inspect of OMC agents / hermes profiles / gateways."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.db import get_db
from core.project.repository import ProjectRepository
from core.secrets import enrich_agent_gateways, read_env_file, workflow_secrets_path
from core.workflow.repository import WorkflowRepository


def main() -> None:
    db = get_db()
    db.init_schema()
    repo = WorkflowRepository(db)
    repo.ensure_seeded()
    projs = ProjectRepository(db)
    print("ACTIVE_PROJECT", projs.get_active_project_id())
    for p in projs.list_projects():
        print("PROJECT", p["id"], p["name"], p.get("working_directory"))
    for w in repo.list_workflows():
        print(
            "WF",
            w["id"],
            w["name"],
            "active=",
            w.get("is_active"),
            "project=",
            w.get("project_id"),
        )
        wf = repo.get_workflow(w["id"])
        if not wf:
            continue
        secrets = read_env_file(workflow_secrets_path(wf.id))
        agent_keys = sorted(k for k in secrets if k.startswith("AGENT_"))
        print("  agent_secret_keys", agent_keys[:20] or "-")
        print(
            "  has_global_discord",
            bool(secrets.get("DISCORD_BOT_TOKEN")),
            "has_global_telegram",
            bool(secrets.get("TELEGRAM_BOT_TOKEN")),
        )
        for ag in wf.agents:
            e = enrich_agent_gateways(wf.id, ag.to_dict())
            gws = {
                p: {"en": g.get("enabled"), "cfg": g.get("configured")}
                for p, g in (e.get("gateways") or {}).items()
                if g.get("enabled") or g.get("configured")
            }
            print(
                f"  AGENT role={ag.role_id} id={ag.id} "
                f"profile={ag.hermes_profile!r} model={ag.llm_model!r} "
                f"gateways={gws or '-'}"
            )
        for ch in wf.chats:
            print(f"  CHAT platform={ch.platform} label={ch.label} id={ch.id}")
        for ch in wf.channels:
            print(
                f"  CHANNEL {ch.name} platform={ch.platform} "
                f"ext={ch.external_id!r}"
            )


if __name__ == "__main__":
    main()
