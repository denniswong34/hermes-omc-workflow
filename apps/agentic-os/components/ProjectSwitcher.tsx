"use client";

import { useRouter } from "next/navigation";
import { useProject } from "@/lib/project-context";

export function ProjectSwitcher() {
  const { projects, activeProject, loading, switchProject } = useProject();
  const router = useRouter();

  if (loading) {
    return <span className="project-switcher muted">Loading…</span>;
  }

  if (projects.length === 0) {
    return (
      <button
        type="button"
        className="project-switcher-btn"
        onClick={() => router.push("/projects/new")}
      >
        Create project
      </button>
    );
  }

  return (
    <label className="project-switcher">
      <span className="muted">Project</span>
      <select
        value={activeProject?.id || ""}
        aria-label="Active project"
        onChange={async (e) => {
          const value = e.target.value;
          if (value === "__new__") {
            router.push("/projects/new");
            return;
          }
          if (!value || value === activeProject?.id) return;
          try {
            await switchProject(value);
            router.refresh();
            // Force client pages that fetched workflows to remount via soft nav
            if (typeof window !== "undefined") {
              window.dispatchEvent(new CustomEvent("omc-project-changed", { detail: value }));
            }
          } catch {
            /* keep previous selection */
          }
        }}
      >
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
        <option value="__new__">+ New project…</option>
      </select>
    </label>
  );
}
