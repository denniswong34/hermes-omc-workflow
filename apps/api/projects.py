"""Project CRUD + active project API routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from core.db import get_db
from core.project import ProjectRepository

router = APIRouter()

PROJECT_HEADER = "X-OMC-Project-Id"


def _repo() -> ProjectRepository:
    return ProjectRepository(get_db())


class ProjectCreate(BaseModel):
    name: str
    working_directory: str = ""
    github_repo: str = ""
    github_username: str = ""
    github_pat: Optional[str] = None
    make_active: bool = True


class ProjectPatch(BaseModel):
    name: Optional[str] = None
    working_directory: Optional[str] = None
    github_repo: Optional[str] = None
    github_username: Optional[str] = None
    github_pat: Optional[str] = None


class ActiveBody(BaseModel):
    project_id: str = Field(..., min_length=1)


def resolve_project_id(
    x_omc_project_id: str | None = Header(default=None, alias=PROJECT_HEADER),
) -> str:
    """Resolve project from header or active setting; 400 if none."""
    try:
        return _repo().require_project_id((x_omc_project_id or "").strip() or None)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/api/projects")
def list_projects():
    return {"projects": _repo().list_projects()}


@router.post("/api/projects")
def create_project(body: ProjectCreate):
    try:
        return _repo().create_project(
            name=body.name,
            working_directory=body.working_directory,
            github_repo=body.github_repo,
            github_username=body.github_username,
            github_pat=body.github_pat,
            make_active=body.make_active,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/api/projects/active")
def get_active_project():
    proj = _repo().get_active_project()
    return {"project": proj}


@router.put("/api/projects/active")
def set_active_project(body: ActiveBody):
    try:
        return _repo().set_active_project_id(body.project_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/api/projects/{project_id}")
def get_project(project_id: str):
    proj = _repo().get_project(project_id)
    if not proj:
        raise HTTPException(404, "Project not found")
    return proj


@router.patch("/api/projects/{project_id}")
def patch_project(project_id: str, body: ProjectPatch):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        return _repo().update_project(project_id, **patch)
    except ValueError as e:
        msg = str(e)
        status = 404 if "not found" in msg.lower() else 400
        raise HTTPException(status, msg)


@router.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
    try:
        _repo().delete_project(project_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True, "id": project_id}
