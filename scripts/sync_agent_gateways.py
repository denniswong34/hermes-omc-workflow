"""Sync OMC agent Hermes profiles + Discord/Telegram gateways.

Usage:
  python scripts/sync_agent_gateways.py                 # ensure profiles only
  python scripts/sync_agent_gateways.py --discord-map mapping.json
  python scripts/sync_agent_gateways.py --telegram-map mapping.json

mapping.json example:
  { "pm": "<token>", "sa": "<token>" }
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.chat_test import test_chat_connection
from core.db import get_db
from core.secrets import (
    enrich_agent_gateways,
    save_agent_gateway,
)
from core.workflow.repository import WorkflowRepository

PERSONA_ROLES = ("pm", "sa", "coder", "qa", "devops", "marketing", "standup")
WF_ID = "wf_bd77e2aed1b8"


def ensure_profiles(repo: WorkflowRepository, wf_id: str) -> None:
    wf = repo.get_workflow(wf_id)
    assert wf
    for ag in wf.agents:
        expected = f"omc-{ag.role_id}"
        patch = {}
        if (ag.hermes_profile or "").strip() != expected:
            patch["hermes_profile"] = expected
        if patch:
            repo.update_agent(ag.id, patch)
            print(f"profile synced {ag.role_id} -> {expected}")
        else:
            print(f"profile ok {ag.role_id} -> {expected}")


def apply_platform_tokens(
    repo: WorkflowRepository,
    wf_id: str,
    platform: str,
    role_to_token: dict[str, str],
    *,
    test: bool = True,
) -> None:
    wf = repo.get_workflow(wf_id)
    assert wf
    by_role = {a.role_id: a for a in wf.agents}
    secret_key = {
        "discord": "DISCORD_BOT_TOKEN",
        "telegram": "TELEGRAM_BOT_TOKEN",
    }[platform]

    for role, token in role_to_token.items():
        role = role.lower().strip()
        token = (token or "").strip()
        if not token:
            continue
        ag = by_role.get(role)
        if not ag:
            print(f"SKIP unknown role {role}")
            continue
        identity = save_agent_gateway(
            wf_id,
            ag.id,
            platform,
            enabled=True,
            secret_updates={secret_key: token},
            current_identity=ag.platform_identity,
        )
        repo.update_agent(ag.id, {"platform_identity": identity})
        print(f"gateway saved {role}/{platform} agent={ag.id}")
        if test:
            creds = {secret_key: token}
            result = test_chat_connection(platform, creds)
            print(f"  test: ok={result.get('ok')} msg={result.get('message')}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", default=WF_ID)
    ap.add_argument("--discord-map", type=Path)
    ap.add_argument("--telegram-map", type=Path)
    ap.add_argument("--no-test", action="store_true")
    args = ap.parse_args()

    db = get_db()
    db.init_schema()
    repo = WorkflowRepository(db)
    repo.ensure_seeded()

    ensure_profiles(repo, args.workflow)

    if args.discord_map:
        mapping = json.loads(args.discord_map.read_text(encoding="utf-8"))
        apply_platform_tokens(
            repo, args.workflow, "discord", mapping, test=not args.no_test
        )
    if args.telegram_map:
        mapping = json.loads(args.telegram_map.read_text(encoding="utf-8"))
        apply_platform_tokens(
            repo, args.workflow, "telegram", mapping, test=not args.no_test
        )

    wf = repo.get_workflow(args.workflow)
    assert wf
    print("--- status ---")
    for ag in wf.agents:
        if ag.role_id not in PERSONA_ROLES and ag.kind != "persona":
            continue
        e = enrich_agent_gateways(wf.id, ag.to_dict())
        g = e.get("gateways") or {}
        disc = g.get("discord") or {}
        tele = g.get("telegram") or {}
        print(
            f"{ag.role_id}: profile={ag.hermes_profile} "
            f"discord(en={disc.get('enabled')},cfg={disc.get('configured')}) "
            f"telegram(en={tele.get('enabled')},cfg={tele.get('configured')})"
        )


if __name__ == "__main__":
    main()
