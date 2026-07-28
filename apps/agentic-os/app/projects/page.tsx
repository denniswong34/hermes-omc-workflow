"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useProject } from "@/lib/project-context";

export default function ProjectsPage() {
  const { projects, activeProject, loading, error, refresh, switchProject } = useProject();
  const router = useRouter();

  useEffect(() => {
    refresh().catch(() => undefined);
  }, [refresh]);

  if (loading) {
    return (
      <div>
        <h1>Projects</h1>
        <p className="muted">Loading…</p>
      </div>
    );
  }

  return (
    <div>
      <h1>Projects</h1>
      <p className="muted">
        Each project scopes workflows, GitHub credentials, and a default working directory.
      </p>
      {error && <div className="panel error">{error}</div>}

      <div className="panel" style={{ marginBottom: "1rem" }}>
        <button type="button" onClick={() => router.push("/projects/new")}>
          New project
        </button>
      </div>

      {projects.length === 0 ? (
        <div className="panel">
          <p>No projects yet. Create one to continue.</p>
          <button type="button" onClick={() => router.push("/projects/new")}>
            Create project
          </button>
        </div>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid #2a3344" }}>
              <th>Name</th>
              <th>Working directory</th>
              <th>GitHub</th>
              <th>PAT</th>
              <th>Active</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {projects.map((p) => (
              <tr key={p.id} style={{ borderBottom: "1px solid #1a2230" }}>
                <td>
                  <Link href={`/projects/${p.id}`}>{p.name}</Link>
                </td>
                <td className="muted" style={{ fontSize: "0.85rem" }}>
                  {p.working_directory || "—"}
                </td>
                <td className="muted" style={{ fontSize: "0.85rem" }}>
                  {p.github_repo || "—"}
                  {p.github_username ? ` (@${p.github_username})` : ""}
                </td>
                <td>{p.has_pat ? "Configured" : "Not set"}</td>
                <td>{activeProject?.id === p.id ? "●" : ""}</td>
                <td>
                  {activeProject?.id !== p.id && (
                    <button
                      type="button"
                      onClick={() =>
                        switchProject(p.id).then(() =>
                          window.dispatchEvent(
                            new CustomEvent("omc-project-changed", { detail: p.id })
                          )
                        )
                      }
                    >
                      Switch
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
