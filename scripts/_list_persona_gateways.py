from core.db import get_db
from core.workflow.repository import WorkflowRepository
from core.secrets import enrich_agent_gateways

db = get_db()
repo = WorkflowRepository(db)
repo.ensure_seeded()
wf = repo.get_workflow("wf_bd77e2aed1b8")
roles = ["pm", "sa", "coder", "qa", "devops", "marketing", "standup"]
for ag in wf.agents:
    if ag.role_id not in roles:
        continue
    e = enrich_agent_gateways(wf.id, ag.to_dict())
    d = e["gateways"]["discord"]
    t = e["gateways"]["telegram"]
    print(
        f"{ag.role_id}\tid={ag.id}\t"
        f"discord={d['configured']}\ttelegram={t['configured']}"
    )
