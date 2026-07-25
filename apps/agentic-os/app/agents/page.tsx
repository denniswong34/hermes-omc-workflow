"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPut } from "@/lib/api";

type AgentList = {
  roles: { role: string; path: string }[];
  shared: { name: string; path: string }[];
};

export default function AgentsPage() {
  const [list, setList] = useState<AgentList | null>(null);
  const [selected, setSelected] = useState("pm");
  const [content, setContent] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  async function loadList() {
    const l = await apiGet<AgentList>("/api/agents");
    setList(l);
  }

  async function loadRole(role: string) {
    setSelected(role);
    setMsg("");
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

  return (
    <div>
      <h1>Agents</h1>
      <p className="muted">Edit role personas and shared SDLC / handoff rules.</p>
      {err && <div className="panel error">{err}</div>}
      {msg && <div className="panel">{msg}</div>}

      <div className="grid" style={{ gridTemplateColumns: "220px 1fr", gap: "1rem" }}>
        <div className="panel">
          <h2>Roles</h2>
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
          <h2>{selected}</h2>
          <textarea rows={28} value={content} onChange={(e) => setContent(e.target.value)} />
          <p style={{ marginTop: "0.75rem" }}>
            <button type="button" onClick={save}>
              Save
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}
