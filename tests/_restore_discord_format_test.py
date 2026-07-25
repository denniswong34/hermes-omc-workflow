"""Restore Discord wiring and set message_format for format e2e test."""

from __future__ import annotations

import json
from pathlib import Path

from core.db import get_db
from core.db.seed import SDLC_CHANNELS
from core.secrets import (
    read_env_file,
    save_chat_connection,
    update_workflow_secrets,
    workflow_secrets_path,
)
from core.workflow.repository import WorkflowRepository

WF = "wf_bd77e2aed1b8"
CHAT = "ch_f0f07570b5b6"
OLD = "wf_bea284cf7353"

CHANNEL_IDS = {
    "engineering": "1530436643662594179",
    "product": "1530436585022160968",
    "support": "1530436828098724011",
    "standup": "1530436787485278228",
    "marketing": "1528310499773648968",
}


def main() -> None:
    repo = WorkflowRepository(get_db())
    wf = repo.get_workflow(WF)
    if not wf:
        raise SystemExit(f"workflow {WF} missing")

    old_env = read_env_file(workflow_secrets_path(OLD))
    token = ""
    for k, v in old_env.items():
        if k.endswith("DISCORD_BOT_TOKEN") and v:
            token = v
            break
    token = token or old_env.get("DISCORD_BOT_TOKEN", "")
    if not token:
        hermes = Path.home() / ".hermes" / ".env"
        if hermes.exists():
            for line in hermes.read_text(encoding="utf-8").splitlines():
                if line.startswith("DISCORD_BOT_TOKEN="):
                    token = line.split("=", 1)[1].strip()
    if not token:
        raise SystemExit("No DISCORD_BOT_TOKEN found")

    update_workflow_secrets(
        WF,
        {
            "DISCORD_BOT_TOKEN": token,
            f"CHAT_{CHAT}_DISCORD_BOT_TOKEN": token,
        },
    )
    if old_env.get("JIRA_API_TOKEN"):
        update_workflow_secrets(WF, {"JIRA_API_TOKEN": old_env["JIRA_API_TOKEN"]})

    cfg = save_chat_connection(
        WF, CHAT, "discord", {"message_format": "block"}, {}
    )
    merged = {**(wf.chats[0].config or {}), **cfg, "message_format": "block"}
    repo.update_chat(WF, CHAT, {"config": merged})

    defaults = {c["name"]: c for c in SDLC_CHANNELS}
    with repo.db.connect() as conn:
        for ch in list(repo.get_workflow(WF).channels):
            d = defaults.get(ch.name, {})
            agents = list(d.get("agents") or ch.agents or [])
            roles = list(d.get("ticket_create_roles") or ch.ticket_create_roles or [])
            ext = CHANNEL_IDS.get(ch.name, ch.external_id or "")
            conn.execute(
                "UPDATE channels SET external_id = ?, agents_json = ?, ticket_create_roles_json = ? WHERE id = ?",
                (ext, json.dumps(agents), json.dumps(roles), ch.id),
            )

    wf = repo.get_workflow(WF)
    print("message_format", (wf.chats[0].config or {}).get("message_format"))
    for ch in wf.channels:
        print(f"#{ch.name} {ch.external_id} agents={ch.agents}")
    print("token_len", len(token))


if __name__ == "__main__":
    main()
