"""Agentic OS control plane API (FastAPI)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Repo root on path
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from apps.api.deps import agents_dir, config_path, secrets_env_path, task_map_path
from apps.api.workflows import router as workflows_router
from core.db.seed import seed_database
from core.db import get_db
from core.memory import create_memory_store
from core.workflow import get_pool

app = FastAPI(title="OMC Agentic OS API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workflows_router)


@app.on_event("startup")
def _startup():
    seed_database(get_db(), activate=True)
    get_pool()


def _load_raw_yaml() -> dict:
    path = config_path()
    if not path.exists():
        raise HTTPException(404, f"Config not found: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_raw_yaml(data: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _expand_simple(data: Any) -> Any:
    """Expand ${VAR} from env for read responses."""
    import re

    pat = re.compile(r"\$\{([^}]+)\}")

    def one(v: Any) -> Any:
        if isinstance(v, str):
            return pat.sub(lambda m: os.environ.get(m.group(1), ""), v)
        if isinstance(v, dict):
            return {k: one(x) for k, x in v.items()}
        if isinstance(v, list):
            return [one(x) for x in v]
        return v

    return one(data)


class ConfigUpdate(BaseModel):
    data: dict[str, Any]


class AgentUpdate(BaseModel):
    content: str


class AgentCreate(BaseModel):
    role: str
    content: str = ""
    shared: bool = False


class SecretsUpdate(BaseModel):
    entries: dict[str, str] = Field(default_factory=dict)


@app.get("/api/health")
def health():
    pool = get_pool()
    return {
        "ok": True,
        "service": "agentic-os-api",
        "version": "0.2.0",
        "repo": str(REPO_ROOT),
        "active_workflows": len(pool.runtimes),
    }


@app.get("/api/bridge/status")
def bridge_status():
    # MVP stub — process manager is phase 2
    return {
        "running": False,
        "message": "Bridge process control not wired yet. Run: python bridge.py",
    }


@app.get("/api/config")
def get_config(expand: bool = False):
    raw = _load_raw_yaml()
    return {"path": str(config_path()), "data": _expand_simple(raw) if expand else raw}


@app.put("/api/config")
def put_config(body: ConfigUpdate):
    if not isinstance(body.data, dict):
        raise HTTPException(400, "data must be an object")
    _save_raw_yaml(body.data)
    return {"ok": True, "path": str(config_path())}


@app.get("/api/agents")
def list_agents():
    root = agents_dir()
    roles = []
    for p in sorted(root.glob("*.md")):
        roles.append({"role": p.stem, "path": str(p)})
    shared = []
    shared_dir = root / "_shared"
    if shared_dir.exists():
        for p in sorted(shared_dir.glob("*.md")):
            shared.append({"name": p.stem, "path": str(p)})
    return {"roles": roles, "shared": shared}


@app.get("/api/agents/{role}")
def get_agent(role: str):
    # shared:sdlc → agents/_shared/sdlc.md
    if role.startswith("shared:"):
        name = role.split(":", 1)[1]
        path = agents_dir() / "_shared" / f"{name}.md"
    else:
        path = agents_dir() / f"{role}.md"
    if not path.exists():
        raise HTTPException(404, f"Agent file not found: {role}")
    return {"role": role, "path": str(path), "content": path.read_text(encoding="utf-8")}


@app.put("/api/agents/{role}")
def put_agent(role: str, body: AgentUpdate):
    if role.startswith("shared:"):
        name = role.split(":", 1)[1]
        path = agents_dir() / "_shared" / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        path = agents_dir() / f"{role}.md"
    path.write_text(body.content, encoding="utf-8")
    return {"ok": True, "path": str(path)}


@app.post("/api/agents")
def create_persona(body: AgentCreate):
    role = body.role.strip().lower().replace(" ", "_")
    if not role or role.startswith("shared"):
        raise HTTPException(400, "Invalid role id")
    if body.shared:
        path = agents_dir() / "_shared" / f"{role}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        key = f"shared:{role}"
    else:
        path = agents_dir() / f"{role}.md"
        key = role
    if path.exists():
        raise HTTPException(409, f"Persona already exists: {role}")
    content = body.content.strip() or f"# {role}\n\nYou are @{role}.\n"
    path.write_text(content, encoding="utf-8")
    return {"ok": True, "role": key, "path": str(path)}


@app.delete("/api/agents/{role}")
def delete_persona(role: str):
    if role.startswith("shared:"):
        name = role.split(":", 1)[1]
        path = agents_dir() / "_shared" / f"{name}.md"
    else:
        path = agents_dir() / f"{role}.md"
    if not path.exists():
        raise HTTPException(404, f"Agent file not found: {role}")
    path.unlink()
    return {"ok": True}


@app.get("/api/secrets")
def get_secrets():
    path = secrets_env_path()
    keys = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k = line.split("=", 1)[0].strip()
            keys.append(k)
    return {"path": str(path), "keys": keys, "note": "Values are write-only for safety"}


@app.put("/api/secrets")
def put_secrets(body: SecretsUpdate):
    path = secrets_env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.strip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            existing[k.strip()] = v
    existing.update({k: str(v) for k, v in body.entries.items() if k})
    lines = [f"{k}={v}" for k, v in sorted(existing.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Also export into process env for this API process
    for k, v in body.entries.items():
        if k:
            os.environ[k] = str(v)
    return {"ok": True, "path": str(path), "keys": list(existing.keys())}


@app.get("/api/memory/health")
def memory_health():
    raw = _expand_simple(_load_raw_yaml())
    store = create_memory_store(raw.get("memory"))
    if store is None:
        return {"ok": False, "provider": (raw.get("memory") or {}).get("provider", "none")}
    return {"provider": "obsidian", **store.health()}


@app.get("/api/memory/tasks")
def memory_tasks():
    raw = _expand_simple(_load_raw_yaml())
    store = create_memory_store(raw.get("memory"))
    if store is None:
        return {"tasks": [], "provider": "none"}
    return {"tasks": store.list_tasks(), "provider": "obsidian", "root": str(store.root)}


@app.get("/api/memory/tasks/{task_id}")
def memory_task(task_id: str):
    raw = _expand_simple(_load_raw_yaml())
    store = create_memory_store(raw.get("memory"))
    if store is None:
        raise HTTPException(400, "Memory provider disabled")
    note = store.get_task(task_id)
    if not note:
        raise HTTPException(404, f"Task note not found: {task_id}")
    return note


@app.get("/api/kanban")
def kanban():
    """Read-only board: merge task_map.json + Obsidian task notes."""
    raw = _expand_simple(_load_raw_yaml())
    tickets = raw.get("tickets") or {}
    store_path = task_map_path(tickets.get("store_path"))
    local: dict[str, Any] = {}
    if store_path.exists():
        try:
            local = json.loads(store_path.read_text(encoding="utf-8"))
        except Exception:
            local = {}

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
    ]
    board: dict[str, list] = {c: [] for c in columns}
    board["unknown"] = []

    store = create_memory_store(raw.get("memory"))
    memory_tasks_list = store.list_tasks() if store else []
    by_id = {t["task_id"]: t for t in memory_tasks_list}

    # Prefer Obsidian cards; supplement from task_map
    seen = set()
    for t in memory_tasks_list:
        tid = t["task_id"]
        seen.add(tid)
        status = (t.get("status") or "backlog").lower()
        card = {
            "id": tid,
            "title": t.get("title") or tid,
            "status": status,
            "topic": t.get("topic", ""),
            "assignee": t.get("assignee", ""),
            "backend": t.get("backend", ""),
            "ticket_url": t.get("ticket_url", ""),
            "updated": t.get("updated", ""),
            "source": "obsidian",
        }
        if local.get(tid):
            card["ticket_url"] = card["ticket_url"] or local[tid].get("url", "")
            card["external_id"] = local[tid].get("external_id", "")
        col = status if status in board else "unknown"
        board[col].append(card)

    for key, val in local.items():
        if key.startswith("_") or not isinstance(val, dict):
            continue
        if key in seen:
            continue
        card = {
            "id": key,
            "title": val.get("name") or key,
            "status": "todo",
            "topic": "",
            "assignee": "",
            "backend": "",
            "ticket_url": val.get("url", ""),
            "external_id": val.get("external_id", ""),
            "updated": "",
            "source": "task_map",
        }
        board["todo"].append(card)

    return {"columns": columns + ["unknown"], "board": board, "memory_count": len(by_id)}


def run():
    import uvicorn

    uvicorn.run(
        "apps.api.main:app",
        host=os.environ.get("OMC_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("OMC_API_PORT", "8787")),
        reload=os.environ.get("OMC_API_RELOAD", "0") == "1",
    )


if __name__ == "__main__":
    run()
