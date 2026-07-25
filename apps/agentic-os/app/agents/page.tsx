"use client";

import { useEffect, useState } from "react";
import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";

type AgentList = {
  roles: { role: string; path: string }[];
  shared: { name: string; path: string }[];
};

export default function AgentsPage() {
  const [list, setList] = useState<AgentList | null>(null);
  const [selected, setSelected] = useState("pm");
  const [content, setContent] = useState("");
  const [newRole, setNewRole] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  async function loadList() {
    const l = await apiGet<AgentList>("/api/agents");
    setList(l);
  }

  async function loadRole(role: string) {
    setSelected(role);
    setMsg("");
    setErr("");
    const a = await apiGet<{ content: string }>(`/api/agents/${encodeURIComponent(role)}`);
    setContent(a.content);
  }

  useEffect(() => {
    (async () => {
      try {
        await loadList();
        await loadRole("pm");
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      }
    })();
  }, []);

  async function save() {
    try {
      await apiPut(`/api/agents/${encodeURIComponent(selected)}`, { content });
      setMsg(`Saved ${selected}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  async function addRole() {
    setErr("");
    const role = newRole.trim().toLowerCase().replace(/\s+/g, "_");
    if (!role) return;
    try {
      const res = await apiPost<{ role: string }>("/api/agents", {
        role,
        content: `# ${role}\n\nYou are @${role}.\n`,
      });
      setNewRole("");
      await loadList();
      await loadRole(res.role);
      setMsg(`Created ${res.role}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  async function removeRole() {
    if (selected.startsWith("shared:")) {
      setErr("Shared docs can be deleted too — confirm in UI; proceeding.");
    }
    if (!window.confirm(`Delete persona "${selected}"? This cannot be undone.`)) return;
    try {
      await apiDelete(`/api/agents/${encodeURIComponent(selected)}`);
      setMsg(`Deleted ${selected}`);
      await loadList();
      const next = (await apiGet<AgentList>("/api/agents")).roles[0]?.role;
      if (next) await loadRole(next);
      else {
        setSelected("");
        setContent("");
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div>
      <h1>Personas</h1>
      <p className="muted">
        Markdown personas used by workflow agents. Add/remove roles here; assign them on a workflow.
      </p>
      {err && <div className="panel error">{err}</div>}
      {msg && <div className="panel">{msg}</div>}

      <div className="grid grid-sidebar">
        <div className="panel">
          <h2>Roles</h2>
          <div style={{ display: "flex", gap: "0.35rem", marginBottom: "0.75rem" }}>
            <input
              placeholder="new_role"
              value={newRole}
              onChange={(e) => setNewRole(e.target.value)}
              style={{ flex: 1 }}
            />
            <button type="button" onClick={addRole}>
              Add
            </button>
          </div>
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {(list?.roles || []).map((r) => (
              <li key={r.role} style={{ marginBottom: "0.35rem" }}>
                <button type="button" className="btn" onClick={() => loadRole(r.role)}>
                  @{r.role}
                </button>
              </li>
            ))}
          </ul>
          <h2>Shared</h2>
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {(list?.shared || []).map((s) => (
              <li key={s.name} style={{ marginBottom: "0.35rem" }}>
                <button
                  type="button"
                  className="btn"
                  onClick={() => loadRole(`shared:${s.name}`)}
                >
                  {s.name}
                </button>
              </li>
            ))}
          </ul>
        </div>
        <div className="panel">
          <h2>{selected || "(none)"}</h2>
          {selected ? (
            <>
              <textarea rows={28} value={content} onChange={(e) => setContent(e.target.value)} />
              <p style={{ marginTop: "0.75rem", display: "flex", gap: "0.5rem" }}>
                <button type="button" onClick={save}>
                  Save
                </button>
                <button type="button" onClick={removeRole}>
                  Delete
                </button>
              </p>
            </>
          ) : (
            <p className="muted">Create a persona to get started.</p>
          )}
        </div>
      </div>
    </div>
  );
}
