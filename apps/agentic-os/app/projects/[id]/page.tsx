"use client";

import { FormEvent, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { apiDelete, apiGet, apiPatch } from "@/lib/api";
import { useProject, type Project } from "@/lib/project-context";

export default function ProjectDetailPage() {
  const params = useParams();
  const id = String(params?.id || "");
  const router = useRouter();
  const { refresh, switchProject, activeProject } = useProject();
  const [project, setProject] = useState<Project | null>(null);
  const [name, setName] = useState("");
  const [workingDirectory, setWorkingDirectory] = useState("");
  const [githubRepo, setGithubRepo] = useState("");
  const [githubUsername, setGithubUsername] = useState("");
  const [githubPat, setGithubPat] = useState("");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [saving, setSaving] = useState(false);

  async function load() {
    const p = await apiGet<Project>(`/api/projects/${id}`);
    setProject(p);
    setName(p.name);
    setWorkingDirectory(p.working_directory || "");
    setGithubRepo(p.github_repo || "");
    setGithubUsername(p.github_username || "");
    setGithubPat("");
  }

  useEffect(() => {
    if (!id) return;
    load().catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [id]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setMsg("");
    setSaving(true);
    try {
      const body: Record<string, string> = {
        name,
        working_directory: workingDirectory,
        github_repo: githubRepo,
        github_username: githubUsername,
      };
      if (githubPat.trim()) body.github_pat = githubPat.trim();
      const updated = await apiPatch<Project>(`/api/projects/${id}`, body);
      setProject(updated);
      setGithubPat("");
      await refresh();
      setMsg("Saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function onDelete() {
    if (!confirm(`Delete project "${project?.name}" and all its workflows?`)) return;
    setError("");
    try {
      await apiDelete(`/api/projects/${id}`);
      await refresh();
      const list = await apiGet<{ projects: Project[] }>("/api/projects");
      if (list.projects.length === 0) {
        router.replace("/projects/new");
      } else {
        await switchProject(list.projects[0].id);
        router.replace("/projects");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  if (!project && !error) {
    return (
      <div>
        <h1>Project</h1>
        <p className="muted">Loading…</p>
      </div>
    );
  }

  return (
    <div>
      <h1>{project?.name || "Project"}</h1>
      <p className="muted">
        {activeProject?.id === id ? "This is the active project." : "Not active — switch from the nav."}
      </p>
      {error && <div className="panel error">{error}</div>}
      {msg && <div className="panel">{msg}</div>}

      <form className="panel" onSubmit={onSubmit}>
        <label className="field">
          <span>Project name *</span>
          <input required value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="field">
          <span>Working directory</span>
          <input
            value={workingDirectory}
            onChange={(e) => setWorkingDirectory(e.target.value)}
            placeholder="E:\\git\\my-app"
          />
        </label>
        <label className="field">
          <span>GitHub repository</span>
          <input
            value={githubRepo}
            onChange={(e) => setGithubRepo(e.target.value)}
            placeholder="owner/repo"
          />
        </label>
        <label className="field">
          <span>GitHub username</span>
          <input
            value={githubUsername}
            onChange={(e) => setGithubUsername(e.target.value)}
            autoComplete="username"
          />
        </label>
        <label className="field">
          <span>GitHub PAT {project?.has_pat ? "(configured — leave blank to keep)" : ""}</span>
          <input
            type="password"
            value={githubPat}
            onChange={(e) => setGithubPat(e.target.value)}
            placeholder={project?.has_pat ? "(stored)" : "ghp_…"}
            autoComplete="new-password"
          />
        </label>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
          <button type="submit" disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
          {activeProject?.id !== id && (
            <button
              type="button"
              onClick={() =>
                switchProject(id).then(() =>
                  window.dispatchEvent(new CustomEvent("omc-project-changed", { detail: id }))
                )
              }
            >
              Make active
            </button>
          )}
          <button type="button" className="btn-danger" onClick={onDelete}>
            Delete project
          </button>
        </div>
      </form>
    </div>
  );
}
