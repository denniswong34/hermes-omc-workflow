"""Project repository — CRUD + active project helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from core.db import Database, _now, new_id
from core.secrets import (
    delete_project_secrets,
    get_project_secrets_meta,
    update_project_secrets,
)


ACTIVE_PROJECT_KEY = "active_project_id"


@dataclass
class ProjectRecord:
    id: str
    name: str
    working_directory: str
    github_repo: str
    github_username: str
    created_at: str
    updated_at: str

    def to_dict(self, *, has_pat: bool | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "working_directory": self.working_directory,
            "github_repo": self.github_repo,
            "github_username": self.github_username,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if has_pat is not None:
            out["has_pat"] = has_pat
        return out


class ProjectRepository:
    def __init__(self, db: Database):
        self.db = db

    def list_projects(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY name COLLATE NOCASE"
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            rec = self._row_to_record(r)
            meta = get_project_secrets_meta(rec.id)
            out.append(rec.to_dict(has_pat=meta["has_pat"]))
        return out

    def get_project(self, project_id: str) -> Optional[dict[str, Any]]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        if not row:
            return None
        rec = self._row_to_record(row)
        meta = get_project_secrets_meta(rec.id)
        return rec.to_dict(has_pat=meta["has_pat"])

    def create_project(
        self,
        name: str,
        working_directory: str = "",
        github_repo: str = "",
        github_username: str = "",
        github_pat: str | None = None,
        *,
        make_active: bool = True,
    ) -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise ValueError("name is required")
        pid = new_id("proj_")
        now = _now()
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO projects(id, name, working_directory, github_repo, github_username, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    pid,
                    name,
                    (working_directory or "").strip(),
                    (github_repo or "").strip(),
                    (github_username or "").strip(),
                    now,
                    now,
                ),
            )
        secret_entries: dict[str, str] = {}
        if github_username:
            secret_entries["GITHUB_USERNAME"] = github_username.strip()
        if github_pat:
            secret_entries["GITHUB_PAT"] = str(github_pat)
        if secret_entries:
            update_project_secrets(pid, secret_entries)
        if make_active or not self.get_active_project_id():
            self.set_active_project_id(pid)
        proj = self.get_project(pid)
        assert proj
        return proj

    def update_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        working_directory: str | None = None,
        github_repo: str | None = None,
        github_username: str | None = None,
        github_pat: str | None = None,
    ) -> dict[str, Any]:
        existing = self.get_project(project_id)
        if not existing:
            raise ValueError(f"Project not found: {project_id}")

        cols: list[str] = []
        vals: list[Any] = []
        if name is not None:
            n = name.strip()
            if not n:
                raise ValueError("name is required")
            cols.append("name = ?")
            vals.append(n)
        if working_directory is not None:
            cols.append("working_directory = ?")
            vals.append(working_directory.strip())
        if github_repo is not None:
            cols.append("github_repo = ?")
            vals.append(github_repo.strip())
        if github_username is not None:
            cols.append("github_username = ?")
            vals.append(github_username.strip())

        secret_entries: dict[str, str] = {}
        if github_username is not None and github_username.strip():
            secret_entries["GITHUB_USERNAME"] = github_username.strip()
        if github_pat is not None and str(github_pat).strip():
            secret_entries["GITHUB_PAT"] = str(github_pat).strip()

        if cols:
            cols.append("updated_at = ?")
            vals.append(_now())
            vals.append(project_id)
            with self.db.connect() as conn:
                conn.execute(
                    f"UPDATE projects SET {', '.join(cols)} WHERE id = ?",
                    vals,
                )
        if secret_entries:
            update_project_secrets(project_id, secret_entries)

        proj = self.get_project(project_id)
        assert proj
        return proj

    def delete_project(self, project_id: str) -> None:
        with self.db.connect() as conn:
            cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            if cur.rowcount == 0:
                raise ValueError(f"Project not found: {project_id}")
        delete_project_secrets(project_id)
        active = self.get_active_project_id()
        if active == project_id:
            nxt = self.list_projects()
            if nxt:
                self.set_active_project_id(nxt[0]["id"])
            else:
                self.db.set_setting(ACTIVE_PROJECT_KEY, "")

    def get_active_project_id(self) -> str:
        return (self.db.get_setting(ACTIVE_PROJECT_KEY, "") or "").strip()

    def set_active_project_id(self, project_id: str) -> dict[str, Any]:
        proj = self.get_project(project_id)
        if not proj:
            raise ValueError(f"Project not found: {project_id}")
        self.db.set_setting(ACTIVE_PROJECT_KEY, project_id)
        return proj

    def get_active_project(self) -> Optional[dict[str, Any]]:
        pid = self.get_active_project_id()
        if not pid:
            projects = self.list_projects()
            if not projects:
                return None
            self.set_active_project_id(projects[0]["id"])
            return projects[0]
        proj = self.get_project(pid)
        if proj:
            return proj
        projects = self.list_projects()
        if not projects:
            self.db.set_setting(ACTIVE_PROJECT_KEY, "")
            return None
        self.set_active_project_id(projects[0]["id"])
        return projects[0]

    def require_project_id(self, project_id: str | None = None) -> str:
        """Resolve explicit or active project; raise if none exist."""
        projects = self.list_projects()
        if not projects:
            raise ValueError("Create a project first")
        if project_id:
            if not self.get_project(project_id):
                raise ValueError(f"Project not found: {project_id}")
            return project_id
        active = self.get_active_project()
        if not active:
            raise ValueError("Create a project first")
        return active["id"]

    @staticmethod
    def _row_to_record(row: Any) -> ProjectRecord:
        return ProjectRecord(
            id=row["id"],
            name=row["name"],
            working_directory=row["working_directory"] or "",
            github_repo=row["github_repo"] or "",
            github_username=row["github_username"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
