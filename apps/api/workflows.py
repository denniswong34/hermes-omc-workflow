"""Workflow / MCP / engines / cron API routes."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from core.cron import get_cron_scheduler
from core.db import get_db, new_id, _json, _now
from core.db import REPO_ROOT
from core.engines import ENGINE_IDS, list_engines
from core.mcp import McpCatalog
from core.memory import build_memory_store
from core.chat_test import test_chat_connection
from core.project import ProjectRepository
from core.tracking_test import test_tracking_connection
from core.tickets.discover import discover_tracking_status_map
from core.tickets.status_map import nonempty_status_map
from core.gateway_guides import gateway_guides_payload
from core.hermes_profiles import (
    HermesProfileError,
    build_hermes_setup_guide,
    sync_workflow_hermes_profiles,
)
from core.secrets import (
    AGENT_GATEWAY_FIELDS,
    PLATFORMS,
    TRACKING_CONNECTION_FIELDS,
    TRACKING_PROVIDERS,
    enrich_agent_gateways,
    enrich_chat_connection,
    enrich_tracking_connection,
    get_workflow_secrets,
    resolve_agent_gateway_credentials,
    resolve_chat_secrets,
    resolve_tracking_secrets,
    save_agent_gateway,
    save_chat_connection,
    save_tracking_connection,
    secret_fields_for_platforms,
    update_workflow_secrets,
)
from core.workflow import get_pool, reload_pool
from core.workflow.repository import ChannelConflictError, WorkflowRepository

router = APIRouter()

PROJECT_HEADER = "X-OMC-Project-Id"


def _repo() -> WorkflowRepository:
    db = get_db()
    repo = WorkflowRepository(db)
    repo.ensure_seeded()
    return repo


def _projects() -> ProjectRepository:
    return ProjectRepository(get_db())


def _resolve_project_id(x_omc_project_id: str | None) -> str:
    try:
        return _projects().require_project_id((x_omc_project_id or "").strip() or None)
    except ValueError as e:
        raise HTTPException(400, str(e))


def _tracking_credentials(
    workflow_id: str,
    provider: str,
    tracking_config: dict | None,
    *,
    connection_id: str = "",
) -> dict[str, str]:
    existing = dict(tracking_config or {})
    nested = dict(existing.get(provider) or {})
    flat = {
        k: v
        for k, v in existing.items()
        if k not in ("provider", "jira", "plane", "label", "status_map")
    }
    credentials: dict[str, str] = {
        **{k: str(v) for k, v in flat.items() if v is not None and k != "status_map"},
        **{k: str(v) for k, v in nested.items() if k != "status_map" and v is not None},
    }
    credentials.update(
        {
            k: v
            for k, v in resolve_tracking_secrets(
                workflow_id, provider, connection_id=connection_id
            ).items()
            if v
        }
    )
    return credentials


def _attach_status_map(
    tracking_config: dict,
    provider: str,
    status_map: dict[str, str],
) -> dict:
    cfg = dict(tracking_config or {})
    nested = dict(cfg.get(provider) or {})
    nested["status_map"] = nonempty_status_map(status_map)
    cfg[provider] = nested
    return cfg


class ActivateBody(BaseModel):
    active: bool


class WorkflowPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    reasoning_engine: Optional[str] = None
    coding_default: Optional[str] = None
    coding_workspace: Optional[str] = None
    memory_provider: Optional[str] = None
    memory_config: Optional[dict[str, Any]] = None
    tracking_provider: Optional[str] = None
    tracking_config: Optional[dict[str, Any]] = None
    routes: Optional[dict[str, list[str]]] = None
    status_authority: Optional[dict[str, list[str]]] = None
    playbooks: Optional[dict[str, list[str]]] = None


class CloneBody(BaseModel):
    name: str
    template_id: str = "tpl-sdlc"


class SaveTemplateBody(BaseModel):
    name: str
    description: str = ""


class AgentPatch(BaseModel):
    display_name: Optional[str] = None
    mention: Optional[str] = None
    kind: Optional[str] = None
    persona_file: Optional[str] = None
    reasoning_engine: Optional[str] = None
    coding_backend: Optional[str] = None
    hermes_profile: Optional[str] = None
    llm_model: Optional[str] = None
    platform_identity: Optional[dict[str, Any]] = None
    tools: Optional[list[str]] = None
    mcp_allowlist: Optional[list[str]] = None


class AgentCreate(BaseModel):
    role_id: str
    display_name: str = ""
    mention: str = ""
    kind: str = "persona"
    persona_file: str = ""
    reasoning_engine: Optional[str] = None
    coding_backend: Optional[str] = None
    hermes_profile: Optional[str] = None
    llm_model: Optional[str] = None
    platform_identity: Optional[dict[str, Any]] = None
    tools: list[str] = Field(default_factory=list)
    mcp_allowlist: list[str] = Field(default_factory=list)
    create_persona_file: bool = True


class AgentGatewayPatch(BaseModel):
    platform: str
    enabled: Optional[bool] = None
    config: dict[str, str] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)
    bot_user_id: Optional[str] = None
    bot_username: Optional[str] = None
    bot_email: Optional[str] = None


class AgentGatewayTestBody(BaseModel):
    platform: Optional[str] = None
    config: dict[str, str] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)


class ChatCreate(BaseModel):
    platform: str = "discord"
    label: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)


class ChatPatch(BaseModel):
    platform: Optional[str] = None
    label: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    secrets: Optional[dict[str, str]] = None


class ChatTestBody(BaseModel):
    """Optional draft credentials from the dialog (unsaved form values)."""
    platform: Optional[str] = None
    config: dict[str, str] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)


class TrackingUpsert(BaseModel):
    provider: str
    label: str = ""
    config: dict[str, str] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)
    # First connection is always activated by the repository; later ones stay inactive unless True
    activate: bool = False


class TrackingPatch(BaseModel):
    label: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    secrets: Optional[dict[str, str]] = None


class TrackingTestBody(BaseModel):
    """Optional draft credentials from the tracking dialog."""
    provider: Optional[str] = None
    config: dict[str, str] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)


class ChannelCreate(BaseModel):
    name: str
    chat_id: Optional[str] = None
    external_id: str = ""
    agents: list[str] = Field(default_factory=list)
    ticket_create_roles: list[str] = Field(default_factory=list)


class ChannelPatch(BaseModel):
    external_id: Optional[str] = None
    agents: Optional[list[str]] = None
    ticket_create_roles: Optional[list[str]] = None
    chat_id: Optional[str] = None


class SecretsUpdate(BaseModel):
    entries: dict[str, str] = Field(default_factory=dict)


class McpAddBody(BaseModel):
    name: str
    description: str = ""
    transport: str = "stdio"
    command: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    docs_url: str = ""


class McpEnableBody(BaseModel):
    catalog_id: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class CronBody(BaseModel):
    name: str
    cron_expr: str
    agent_role: str
    channel_name: str
    prompt: str = ""
    enabled: bool = True


@router.get("/api/workflows")
def list_workflows(
    x_omc_project_id: str | None = Header(default=None, alias=PROJECT_HEADER),
):
    project_id = _resolve_project_id(x_omc_project_id)
    return {"workflows": _repo().list_workflows(project_id=project_id), "project_id": project_id}


@router.get("/api/workflows/active")
def list_active(
    x_omc_project_id: str | None = Header(default=None, alias=PROJECT_HEADER),
):
    project_id = _resolve_project_id(x_omc_project_id)
    workflows = [
        w.to_dict()
        for w in _repo().list_active()
        if w.project_id == project_id
    ]
    return {"workflows": workflows, "project_id": project_id}


def _workflow_payload(workflow_id: str, wf) -> dict[str, Any]:
    data = wf.to_dict()
    data["chats"] = [
        enrich_chat_connection(workflow_id, c) for c in data.get("chats") or []
    ]
    data["agents"] = [
        enrich_agent_gateways(workflow_id, a) for a in data.get("agents") or []
    ]
    trackings = []
    active = None
    for t in data.get("trackings") or []:
        enriched = enrich_tracking_connection(
            workflow_id,
            t.get("provider") or "none",
            t.get("config") or {},
            connection_id=t.get("id") or "",
            is_active=bool(t.get("is_active")),
        )
        # Prefer row label over nested config label
        if t.get("label"):
            enriched["label"] = t["label"]
        trackings.append(enriched)
        if enriched.get("is_active"):
            active = enriched
    data["trackings"] = trackings
    data["tracking"] = active or enrich_tracking_connection(
        workflow_id,
        data.get("tracking_provider") or "none",
        data.get("tracking_config") or {},
    )
    return data


def _get_agent(workflow_id: str, agent_id: str) -> dict[str, Any]:
    wf = _repo().get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    agent = next((a for a in wf.agents if a.id == agent_id), None)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent.to_dict()


@router.get("/api/workflows/{workflow_id}")
def get_workflow(workflow_id: str):
    wf = _repo().get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    return _workflow_payload(workflow_id, wf)


@router.patch("/api/workflows/{workflow_id}")
def patch_workflow(workflow_id: str, body: WorkflowPatch):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "reasoning_engine" in patch and patch["reasoning_engine"] not in ENGINE_IDS:
        raise HTTPException(400, f"Invalid engine. Choose from {ENGINE_IDS}")
    try:
        wf = _repo().update_workflow(workflow_id, patch)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return _workflow_payload(workflow_id, wf)


@router.post("/api/workflows/{workflow_id}/activate")
def activate_workflow(workflow_id: str, body: ActivateBody):
    repo = _repo()
    try:
        wf = repo.set_active(workflow_id, body.active)
    except ChannelConflictError as e:
        raise HTTPException(409, {"message": str(e), "conflicts": e.conflicts})
    except ValueError as e:
        raise HTTPException(400, str(e))
    pool = reload_pool()
    cron = get_cron_scheduler()
    cron.sync_from_workflows([r.workflow for r in pool.runtimes.values()])
    return wf.to_dict()


@router.post("/api/workflows/clone")
def clone_workflow(
    body: CloneBody,
    x_omc_project_id: str | None = Header(default=None, alias=PROJECT_HEADER),
):
    project_id = _resolve_project_id(x_omc_project_id)
    project = _projects().get_project(project_id)
    assert project
    try:
        wf = _repo().clone_from_template(
            body.template_id,
            body.name,
            project_id=project_id,
            coding_workspace=project.get("working_directory") or "",
        )
    except ValueError as e:
        msg = str(e)
        status = 404 if "not found" in msg.lower() else 400
        raise HTTPException(status, msg)
    return wf.to_dict()


@router.post("/api/workflows/{workflow_id}/save-template")
def save_template(workflow_id: str, body: SaveTemplateBody):
    try:
        return _repo().save_as_template(workflow_id, body.name, body.description)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/api/templates")
def list_templates():
    return {"templates": _repo().list_templates()}


@router.patch("/api/workflows/{workflow_id}/agents/{agent_id}")
def patch_agent(workflow_id: str, agent_id: str, body: AgentPatch):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        updated = _repo().update_agent(agent_id, patch)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return enrich_agent_gateways(workflow_id, updated)


@router.post("/api/workflows/{workflow_id}/agents")
def create_agent(workflow_id: str, body: AgentCreate):
    from pathlib import Path

    data = body.model_dump()
    create_file = data.pop("create_persona_file", True)
    if not data.get("persona_file"):
        data["persona_file"] = f"{data['role_id'].strip().lower()}.md"
    persona_path = Path(REPO_ROOT) / "agents" / data["persona_file"]
    if not create_file and data.get("kind") != "coding" and not persona_path.exists():
        raise HTTPException(
            400,
            f"Persona not found: {data['persona_file']}. Create it on the Personas page first.",
        )
    try:
        agent = _repo().add_agent(workflow_id, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if create_file and agent.get("kind") == "persona":
        path = Path(REPO_ROOT) / "agents" / agent["persona_file"]
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"# {agent['display_name']}\n\nYou are @{agent['mention']}.\n",
                encoding="utf-8",
            )
    return agent


@router.delete("/api/workflows/{workflow_id}/agents/{agent_id}")
def delete_agent(workflow_id: str, agent_id: str):
    try:
        _repo().delete_agent(workflow_id, agent_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


@router.post("/api/workflows/{workflow_id}/hermes-profiles/sync")
def sync_hermes_profiles(workflow_id: str):
    """Create/update omc-{role} profiles, write OMC tokens + enable channels, start gateways."""
    if not _repo().get_workflow(workflow_id):
        raise HTTPException(404, "Workflow not found")
    try:
        # Hermes profile gateways own the bot tokens — stop OMC bridge first
        # so Telegram/Discord are not contested by two pollers.
        from apps.api.bridge_proc import stop_bridge

        bridge_stopped = stop_bridge()
        summary = sync_workflow_hermes_profiles(
            _repo(),
            workflow_id,
            start_gateways=True,
            start_on_login=True,
        )
        summary["bridge_stopped"] = bridge_stopped
        return summary
    except HermesProfileError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/api/workflows/{workflow_id}/hermes-profiles/setup-guide")
def hermes_profiles_setup_guide(workflow_id: str):
    """Return CLI setup instructions only (also assigns short profile names)."""
    if not _repo().get_workflow(workflow_id):
        raise HTTPException(404, "Workflow not found")
    try:
        return build_hermes_setup_guide(_repo(), workflow_id, assign_names=True)
    except HermesProfileError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/api/workflows/{workflow_id}/agents/{agent_id}/gateways")
def get_agent_gateways(workflow_id: str, agent_id: str):
    agent = _get_agent(workflow_id, agent_id)
    return enrich_agent_gateways(workflow_id, agent)


@router.patch("/api/workflows/{workflow_id}/agents/{agent_id}/gateways")
def patch_agent_gateways(workflow_id: str, agent_id: str, body: AgentGatewayPatch):
    agent = _get_agent(workflow_id, agent_id)
    identity_updates = {}
    if body.bot_user_id is not None:
        identity_updates["bot_user_id"] = body.bot_user_id
    if body.bot_username is not None:
        identity_updates["bot_username"] = body.bot_username
    if body.bot_email is not None:
        identity_updates["bot_email"] = body.bot_email
    try:
        identity = save_agent_gateway(
            workflow_id,
            agent_id,
            body.platform,
            enabled=body.enabled,
            identity_updates=identity_updates or None,
            config_updates=body.config,
            secret_updates=body.secrets,
            current_identity=agent.get("platform_identity"),
        )
        updated = _repo().update_agent(agent_id, {"platform_identity": identity})
    except ValueError as e:
        raise HTTPException(400, str(e))
    return enrich_agent_gateways(workflow_id, updated)


@router.post("/api/workflows/{workflow_id}/agents/{agent_id}/gateways/{platform}/test")
def test_agent_gateway(
    workflow_id: str,
    agent_id: str,
    platform: str,
    body: AgentGatewayTestBody = AgentGatewayTestBody(),
):
    agent = _get_agent(workflow_id, agent_id)
    plat = (body.platform or platform or "").strip().lower()
    if plat not in PLATFORMS:
        raise HTTPException(400, f"Invalid platform. Choose from {PLATFORMS}")
    stored = resolve_agent_gateway_credentials(
        workflow_id, agent_id, plat, agent.get("platform_identity")
    )
    credentials: dict[str, str] = {**stored}
    for k, v in (body.config or {}).items():
        if v:
            credentials[k] = str(v)
    for k, v in (body.secrets or {}).items():
        if v and not str(v).startswith("(stored"):
            credentials[k] = str(v)
    return test_chat_connection(plat, credentials)


@router.get("/api/platforms")
def platforms():
    from core.secrets import CHAT_CONNECTION_FIELDS

    return {
        "platforms": list(PLATFORMS),
        "connection_fields": CHAT_CONNECTION_FIELDS,
        "gateway_fields": AGENT_GATEWAY_FIELDS,
    }


@router.get("/api/platforms/gateway-guides")
def platform_gateway_guides():
    return gateway_guides_payload()


@router.get("/api/tracking-providers")
def tracking_providers():
    return {
        "providers": list(TRACKING_PROVIDERS),
        "connection_fields": TRACKING_CONNECTION_FIELDS,
    }


def _prepare_tracking_config(
    workflow_id: str,
    provider: str,
    *,
    body_config: dict | None,
    body_secrets: dict | None,
    label: str,
    existing_config: dict | None = None,
    connection_id: str = "",
) -> dict[str, Any]:
    existing = dict(existing_config or {})
    existing_nested = dict(existing.get(provider) or {})
    status_map = existing_nested.get("status_map") or existing.get("status_map")
    body_cfg = dict(body_config or {})
    if isinstance(body_cfg.get("status_map"), dict):
        status_map = body_cfg.pop("status_map")
    prior_config = {
        k: v
        for k, v in existing_nested.items()
        if k not in ("status_map", "api_key", "api_token")
    }
    prior_config.update(body_cfg)

    tracking_config = save_tracking_connection(
        workflow_id,
        provider,
        prior_config,
        body_secrets,
        label=label,
        connection_id=connection_id,
        existing_config=existing,
    )
    if status_map:
        tracking_config = _attach_status_map(tracking_config, provider, status_map)

    creds = _tracking_credentials(
        workflow_id, provider, tracking_config, connection_id=connection_id
    )
    discovered = discover_tracking_status_map(provider, creds)
    if discovered.get("ok") and discovered.get("status_map"):
        tracking_config = _attach_status_map(
            tracking_config,
            provider,
            discovered["status_map"],
        )
    return tracking_config


@router.post("/api/workflows/{workflow_id}/trackings")
def create_tracking(workflow_id: str, body: TrackingUpsert):
    provider = (body.provider or "").strip().lower()
    if provider not in TRACKING_PROVIDERS:
        raise HTTPException(400, f"Invalid provider. Choose from {TRACKING_PROVIDERS}")
    wf = _repo().get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")

    label = (body.label or "").strip() or f"{provider[:1].upper()}{provider[1:]} #1"
    try:
        row = _repo().add_tracking(
            workflow_id,
            {
                "provider": provider,
                "label": label,
                "config": {},
                "is_active": bool(body.activate),
            },
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    tracking_config = _prepare_tracking_config(
        workflow_id,
        provider,
        body_config=body.config,
        body_secrets=body.secrets,
        label=label,
        connection_id=row["id"],
    )
    try:
        _repo().update_tracking(
            workflow_id,
            row["id"],
            {"label": label, "config": tracking_config},
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    wf = _repo().get_workflow(workflow_id)
    return _workflow_payload(workflow_id, wf)


@router.patch("/api/workflows/{workflow_id}/trackings/{tracking_id}")
def patch_tracking(workflow_id: str, tracking_id: str, body: TrackingPatch):
    wf = _repo().get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    current = next((t for t in wf.trackings if t.id == tracking_id), None)
    if not current:
        raise HTTPException(404, "Tracking connection not found")

    label = (
        body.label
        if body.label is not None
        else (current.label or str((current.config or {}).get("label") or ""))
    )
    tracking_config = _prepare_tracking_config(
        workflow_id,
        current.provider,
        body_config=body.config,
        body_secrets=body.secrets,
        label=label,
        existing_config=current.config,
        connection_id=tracking_id,
    )
    try:
        _repo().update_tracking(
            workflow_id,
            tracking_id,
            {"label": label, "config": tracking_config},
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    wf = _repo().get_workflow(workflow_id)
    return _workflow_payload(workflow_id, wf)


@router.delete("/api/workflows/{workflow_id}/trackings/{tracking_id}")
def delete_tracking(workflow_id: str, tracking_id: str):
    try:
        _repo().delete_tracking(workflow_id, tracking_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    wf = _repo().get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    return _workflow_payload(workflow_id, wf)


@router.post("/api/workflows/{workflow_id}/trackings/{tracking_id}/activate")
def activate_tracking(workflow_id: str, tracking_id: str):
    try:
        _repo().set_active_tracking(workflow_id, tracking_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    wf = _repo().get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    return _workflow_payload(workflow_id, wf)


@router.post("/api/workflows/{workflow_id}/trackings/{tracking_id}/test")
def test_tracking_connection_by_id(
    workflow_id: str,
    tracking_id: str,
    body: TrackingTestBody = TrackingTestBody(),
):
    wf = _repo().get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    current = next((t for t in wf.trackings if t.id == tracking_id), None)
    if not current:
        raise HTTPException(404, "Tracking connection not found")
    provider = (body.provider or current.provider or "").strip().lower()
    if provider not in TRACKING_PROVIDERS:
        return {
            "ok": False,
            "platform": provider or "none",
            "message": "Save a Jira or Plane tracking connection before testing",
        }
    credentials = _tracking_credentials(
        workflow_id,
        provider,
        current.config,
        connection_id=tracking_id,
    )
    for k, v in (body.config or {}).items():
        if v and k != "status_map":
            credentials[k] = str(v)
    for k, v in (body.secrets or {}).items():
        if v and not str(v).startswith("(stored"):
            credentials[k] = str(v)
    result = test_tracking_connection(provider, credentials)
    if not result.get("ok"):
        return result
    discovered = discover_tracking_status_map(provider, credentials)
    if discovered.get("ok") and discovered.get("status_map"):
        tracking_config = _attach_status_map(
            dict(current.config or {}),
            provider,
            discovered["status_map"],
        )
        try:
            _repo().update_tracking(
                workflow_id, tracking_id, {"config": tracking_config}
            )
        except ValueError:
            pass
        result = {
            **result,
            "status_map": discovered["status_map"],
            "available_statuses": discovered.get("available") or [],
            "message": f"{result.get('message')} · {discovered.get('message')}",
        }
    return result


@router.put("/api/workflows/{workflow_id}/tracking")
def upsert_tracking(workflow_id: str, body: TrackingUpsert):
    """Legacy: create a new tracking connection (or update the active one)."""
    wf = _repo().get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    active = next((t for t in wf.trackings if t.is_active), None)
    if active and (body.provider or "").strip().lower() == active.provider:
        return patch_tracking(
            workflow_id,
            active.id,
            TrackingPatch(
                label=body.label or None,
                config=body.config or None,
                secrets=body.secrets or None,
            ),
        )
    return create_tracking(workflow_id, body)


@router.delete("/api/workflows/{workflow_id}/tracking")
def clear_tracking(workflow_id: str):
    """Legacy: remove the active tracking connection."""
    wf = _repo().get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    active = next((t for t in wf.trackings if t.is_active), None)
    if active:
        return delete_tracking(workflow_id, active.id)
    try:
        wf = _repo().update_workflow(
            workflow_id,
            {"tracking_provider": "none", "tracking_config": {}},
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    return _workflow_payload(workflow_id, wf)


@router.post("/api/workflows/{workflow_id}/tracking/test")
def test_tracking(workflow_id: str, body: TrackingTestBody = TrackingTestBody()):
    """Probe Jira / Plane credentials and refresh status_map from the live board."""
    wf = _repo().get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    active = next((t for t in wf.trackings if t.is_active), None)
    if active:
        return test_tracking_connection_by_id(workflow_id, active.id, body)

    provider = (body.provider or wf.tracking_provider or "").strip().lower()
    if provider not in TRACKING_PROVIDERS:
        return {
            "ok": False,
            "platform": provider or "none",
            "message": "Save a Jira or Plane tracking connection before testing",
        }

    credentials = _tracking_credentials(workflow_id, provider, wf.tracking_config)
    for k, v in (body.config or {}).items():
        if v and k != "status_map":
            credentials[k] = str(v)
    for k, v in (body.secrets or {}).items():
        if v and not str(v).startswith("(stored"):
            credentials[k] = str(v)

    result = test_tracking_connection(provider, credentials)
    if not result.get("ok"):
        return result

    discovered = discover_tracking_status_map(provider, credentials)
    if discovered.get("ok") and discovered.get("status_map"):
        tracking_config = _attach_status_map(
            dict(wf.tracking_config or {}),
            provider,
            discovered["status_map"],
        )
        try:
            _repo().update_workflow(
                workflow_id,
                {
                    "tracking_provider": provider,
                    "tracking_config": tracking_config,
                },
            )
        except ValueError:
            pass
        result = {
            **result,
            "status_map": discovered["status_map"],
            "available_statuses": discovered.get("available") or [],
            "message": f"{result.get('message')} · {discovered.get('message')}",
        }
    return result


@router.post("/api/workflows/{workflow_id}/tracking/sync-status-map")
def sync_tracking_status_map(workflow_id: str):
    """Re-discover and persist SDLC to board status_map for the active tracker."""
    wf = _repo().get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    active = next((t for t in wf.trackings if t.is_active), None)
    provider = (
        (active.provider if active else wf.tracking_provider) or ""
    ).strip().lower()
    if provider not in TRACKING_PROVIDERS:
        raise HTTPException(400, "No Jira/Plane tracking connection configured")

    cfg = active.config if active else wf.tracking_config
    connection_id = active.id if active else ""
    credentials = _tracking_credentials(
        workflow_id, provider, cfg, connection_id=connection_id
    )
    discovered = discover_tracking_status_map(provider, credentials)
    if not discovered.get("ok"):
        return {
            "ok": False,
            "provider": provider,
            "message": discovered.get("message") or "Status map discovery failed",
        }

    tracking_config = _attach_status_map(
        dict(cfg or {}),
        provider,
        discovered["status_map"],
    )
    if active:
        _repo().update_tracking(
            workflow_id, active.id, {"config": tracking_config}
        )
        wf = _repo().get_workflow(workflow_id)
    else:
        wf = _repo().update_workflow(
            workflow_id,
            {
                "tracking_provider": provider,
                "tracking_config": tracking_config,
            },
        )
    return {
        "ok": True,
        "provider": provider,
        "status_map": discovered["status_map"],
        "available": discovered.get("available") or [],
        "message": discovered.get("message"),
        "workflow": _workflow_payload(workflow_id, wf),
    }


@router.post("/api/workflows/{workflow_id}/chats")
def create_chat(workflow_id: str, body: ChatCreate):
    try:
        chat = _repo().add_chat(
            workflow_id,
            {
                "platform": body.platform,
                "label": body.label,
                "config": body.config or {},
            },
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    config_merge = save_chat_connection(
        workflow_id,
        chat["id"],
        chat["platform"],
        body.config,
        body.secrets,
    )
    if config_merge:
        merged = {**(chat.get("config") or {}), **config_merge}
        chat = _repo().update_chat(workflow_id, chat["id"], {"config": merged})
    return enrich_chat_connection(workflow_id, chat)


@router.patch("/api/workflows/{workflow_id}/chats/{chat_id}")
def patch_chat(workflow_id: str, chat_id: str, body: ChatPatch):
    patch = {k: v for k, v in body.model_dump().items() if v is not None and k != "secrets"}
    try:
        # Load current for platform + existing config
        wf = _repo().get_workflow(workflow_id)
        if not wf:
            raise ValueError("workflow not found")
        current = next((c for c in wf.chats if c.id == chat_id), None)
        if not current:
            raise ValueError("chat not found")
        platform = (patch.get("platform") or current.platform).strip().lower()
        existing_config = dict(current.config or {})
        if body.config:
            existing_config.update(body.config)
        config_from_secrets = save_chat_connection(
            workflow_id,
            chat_id,
            platform,
            body.config,
            body.secrets,
        )
        existing_config.update(config_from_secrets)
        patch["platform"] = platform
        patch["config"] = existing_config
        chat = _repo().update_chat(workflow_id, chat_id, patch)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return enrich_chat_connection(workflow_id, chat)


@router.delete("/api/workflows/{workflow_id}/chats/{chat_id}")
def delete_chat(workflow_id: str, chat_id: str):
    try:
        _repo().delete_chat(workflow_id, chat_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


@router.post("/api/workflows/{workflow_id}/chats/{chat_id}/test")
def test_chat(workflow_id: str, chat_id: str, body: ChatTestBody = ChatTestBody()):
    """Probe Discord / Slack / Telegram / Zulip credentials (stored + draft form values)."""
    wf = _repo().get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    current = next((c for c in wf.chats if c.id == chat_id), None)
    if not current:
        raise HTTPException(404, "Chat not found")
    platform = (body.platform or current.platform or "").strip().lower()
    stored = resolve_chat_secrets(workflow_id, chat_id, platform)
    config = dict(current.config or {})
    config.update({k: v for k, v in (body.config or {}).items() if v})
    # Merge: stored secrets < config fields < draft secrets (non-blank)
    credentials: dict[str, str] = {**stored}
    for k, v in config.items():
        if v:
            credentials[k] = str(v)
    for k, v in (body.secrets or {}).items():
        if v and not str(v).startswith("(stored"):
            credentials[k] = str(v)
    return test_chat_connection(platform, credentials)


@router.post("/api/workflows/{workflow_id}/channels")
def create_channel(workflow_id: str, body: ChannelCreate):
    try:
        return _repo().add_channel(workflow_id, body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/api/workflows/{workflow_id}/channels/{channel_id}")
def delete_channel(workflow_id: str, channel_id: str):
    try:
        _repo().delete_channel(workflow_id, channel_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


@router.get("/api/workflows/{workflow_id}/secrets")
def get_secrets(workflow_id: str):
    wf = _repo().get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    platforms = list({c.platform for c in wf.chats}) or ["discord"]
    meta = get_workflow_secrets(workflow_id)
    return {
        **meta,
        "fields": secret_fields_for_platforms(platforms),
        "platforms": platforms,
    }


@router.put("/api/workflows/{workflow_id}/secrets")
def put_secrets(workflow_id: str, body: SecretsUpdate):
    if not _repo().get_workflow(workflow_id):
        raise HTTPException(404, "Workflow not found")
    return update_workflow_secrets(workflow_id, body.entries)


@router.patch("/api/workflows/{workflow_id}/channels/{channel_id}")
def patch_channel(workflow_id: str, channel_id: str, body: ChannelPatch):
    db = get_db()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM channels WHERE id = ? AND workflow_id = ?",
            (channel_id, workflow_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Channel not found")
        if body.external_id is not None:
            conn.execute(
                "UPDATE channels SET external_id = ? WHERE id = ?",
                (body.external_id, channel_id),
            )
        if body.agents is not None:
            conn.execute(
                "UPDATE channels SET agents_json = ? WHERE id = ?",
                (_json(body.agents), channel_id),
            )
        if body.ticket_create_roles is not None:
            conn.execute(
                "UPDATE channels SET ticket_create_roles_json = ? WHERE id = ?",
                (_json(body.ticket_create_roles), channel_id),
            )
        if body.chat_id is not None:
            conn.execute(
                "UPDATE channels SET chat_id = ? WHERE id = ?",
                (body.chat_id, channel_id),
            )
    wf = _repo().get_workflow(workflow_id)
    assert wf
    ch = next((c for c in wf.channels if c.id == channel_id), None)
    return ch.to_dict() if ch else {}


@router.get("/api/engines")
def engines():
    return {"engines": list_engines()}


@router.get("/api/mcp/catalog")
def mcp_catalog():
    return {"catalog": McpCatalog(get_db()).list_catalog()}


@router.post("/api/mcp/catalog")
def mcp_add(body: McpAddBody):
    return McpCatalog(get_db()).add_custom(
        name=body.name,
        description=body.description,
        transport=body.transport,
        command=body.command,
        env=body.env,
        docs_url=body.docs_url,
    )


@router.post("/api/workflows/{workflow_id}/mcp")
def mcp_enable(workflow_id: str, body: McpEnableBody):
    if not _repo().get_workflow(workflow_id):
        raise HTTPException(404, "Workflow not found")
    return McpCatalog(get_db()).enable_on_workflow(
        workflow_id, body.catalog_id, body.enabled, body.config
    )


@router.get("/api/workflows/{workflow_id}/mcp")
def mcp_list(workflow_id: str):
    return {"servers": McpCatalog(get_db()).workflow_servers(workflow_id, enabled_only=False)}


@router.get("/api/workflows/{workflow_id}/cron")
def list_cron(workflow_id: str):
    wf = _repo().get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    return {"jobs": [j.to_dict() for j in wf.cron_jobs]}


@router.post("/api/workflows/{workflow_id}/cron")
def add_cron(workflow_id: str, body: CronBody):
    if not _repo().get_workflow(workflow_id):
        raise HTTPException(404, "Workflow not found")
    jid = new_id("cron_")
    with get_db().connect() as conn:
        conn.execute(
            "INSERT INTO cron_jobs(id, workflow_id, name, cron_expr, agent_role, channel_name, prompt, enabled) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                jid,
                workflow_id,
                body.name,
                body.cron_expr,
                body.agent_role,
                body.channel_name,
                body.prompt,
                1 if body.enabled else 0,
            ),
        )
    pool = get_pool()
    if workflow_id in pool.runtimes:
        get_cron_scheduler().sync_from_workflows([r.workflow for r in pool.runtimes.values()])
    return {"id": jid, **body.model_dump()}


@router.get("/api/cron")
def cron_all():
    return {"jobs": get_cron_scheduler().list_jobs()}


@router.get("/api/runtime/status")
def runtime_status():
    pool = get_pool()
    return {
        "active_count": len(pool.runtimes),
        "workflows": [
            {"id": wid, "name": rt.workflow.name, "engine": rt.workflow.reasoning_engine}
            for wid, rt in pool.runtimes.items()
        ],
        "channel_index": [
            {"platform": p, "channel_id": c, "workflow_id": wid}
            for (p, c), wid in pool.channel_index.items()
        ],
    }


@router.post("/api/runtime/reload")
def runtime_reload():
    pool = reload_pool()
    get_cron_scheduler().sync_from_workflows([r.workflow for r in pool.runtimes.values()])
    return {"ok": True, "active_count": len(pool.runtimes)}


@router.get("/api/workflows/{workflow_id}/memory/health")
def wf_memory_health(workflow_id: str):
    wf = _repo().get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    cfg = dict(wf.memory_config or {})
    root = cfg.get("root_folder") or "OMC"
    cfg["root_folder"] = f"{root}/{wf.id}"
    store = build_memory_store(wf.memory_provider, cfg)
    if store is None:
        return {"ok": False, "provider": wf.memory_provider, "workflow_id": workflow_id}
    return {"provider": wf.memory_provider, "workflow_id": workflow_id, **store.health()}


@router.get("/api/workflows/{workflow_id}/memory/tasks")
def wf_memory_tasks(workflow_id: str):
    wf = _repo().get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    cfg = dict(wf.memory_config or {})
    root = cfg.get("root_folder") or "OMC"
    cfg["root_folder"] = f"{root}/{wf.id}"
    store = build_memory_store(wf.memory_provider, cfg)
    if store is None:
        return {"tasks": [], "provider": wf.memory_provider}
    return {"tasks": store.list_tasks(), "provider": wf.memory_provider}


@router.get("/api/kanban/v2")
def kanban_v2(workflow_id: Optional[str] = None):
    """Kanban across active workflows (or one selected)."""
    repo = _repo()
    wfs = [repo.get_workflow(workflow_id)] if workflow_id else repo.list_active()
    wfs = [w for w in wfs if w]
    columns = [
        "backlog",
        "todo",
        "in progress",
        "in review",
        "qa review",
        "qa failed",
        "qa verified",
        "ready to deploy",
        "deployed",
        "done",
        "cancelled",
        "unknown",
    ]
    board: dict[str, list] = {c: [] for c in columns}
    for wf in wfs:
        cfg = dict(wf.memory_config or {})
        root = cfg.get("root_folder") or "OMC"
        cfg["root_folder"] = f"{root}/{wf.id}"
        store = build_memory_store(wf.memory_provider, cfg)
        tasks = store.list_tasks() if store else []
        for t in tasks:
            status = (t.get("status") or "backlog").lower()
            card = {
                **t,
                "id": t.get("task_id"),
                "workflow_id": wf.id,
                "workflow_name": wf.name,
            }
            col = status if status in board else "unknown"
            board[col].append(card)
    return {"columns": columns, "board": board}
