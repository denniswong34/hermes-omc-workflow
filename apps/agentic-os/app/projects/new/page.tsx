"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { apiPost } from "@/lib/api";
import { useProject, type Project } from "@/lib/project-context";

export default function NewProjectPage() {
  const router = useRouter();
  const { refresh, switchProject, projects } = useProject();
  const [name, setName] = useState("");
  const [workingDirectory, setWorkingDirectory] = useState("");
  const [githubRepo, setGithubRepo] = useState("");
  const [githubUsername, setGithubUsername] = useState("");
  const [githubPat, setGithubPat] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      const created = await apiPost<Project>("/api/projects", {
        name,
        working_directory: workingDirectory,
        github_repo: githubRepo,
        github_username: githubUsername,
        github_pat: githubPat || undefined,
        make_active: true,
      });
      await refresh();
      await switchProject(created.id);
      window.dispatchEvent(new CustomEvent("omc-project-changed", { detail: created.id }));
      router.replace(`/projects/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <h1>{projects.length === 0 ? "Create your first project" : "New project"}</h1>
      <p className="muted">
        Projects group workflows and hold the default coding workspace plus GitHub credentials.
      </p>
      {error && <div className="panel error">{error}</div>}

      <form className="panel" onSubmit={onSubmit}>
        <label className="field">
          <span>Project name *</span>
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="My SaaS"
          />
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
            placeholder="owner/repo or https://github.com/owner/repo"
          />
        </label>
        <label className="field">
          <span>GitHub username</span>
          <input
            value={githubUsername}
            onChange={(e) => setGithubUsername(e.target.value)}
            placeholder="octocat"
            autoComplete="username"
          />
        </label>
        <label className="field">
          <span>GitHub PAT</span>
          <input
            type="password"
            value={githubPat}
            onChange={(e) => setGithubPat(e.target.value)}
            placeholder="ghp_…"
            autoComplete="new-password"
          />
          <span className="muted" style={{ fontSize: "0.85rem" }}>
            Stored write-only in the project secrets file (never returned by the API).
          </span>
        </label>
        <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem" }}>
          <button type="submit" disabled={saving || !name.trim()}>
            {saving ? "Creating…" : "Create project"}
          </button>
          {projects.length > 0 && (
            <button type="button" className="btn-secondary" onClick={() => router.push("/projects")}>
              Cancel
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
