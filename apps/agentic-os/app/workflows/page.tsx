"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiGet, apiPost } from "@/lib/api";

type Wf = {
  id: string;
  name: string;
  description: string;
  is_active: boolean;
  reasoning_engine: string;
  memory_provider: string;
  tracking_provider: string;
};

type Tpl = { id: string; name: string; description: string; is_system: boolean };

export default function WorkflowsPage() {
  const [workflows, setWorkflows] = useState<Wf[]>([]);
  const [templates, setTemplates] = useState<Tpl[]>([]);
  const [cloneName, setCloneName] = useState("My Company");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  async function refresh() {
    const w = await apiGet<{ workflows: Wf[] }>("/api/workflows");
    const t = await apiGet<{ templates: Tpl[] }>("/api/templates");
    setWorkflows(w.workflows);
    setTemplates(t.templates);
  }

  useEffect(() => {
    refresh().catch((e) => setError(String(e.message || e)));
  }, []);

  async function toggle(id: string, active: boolean) {
    setError("");
    setMsg("");
    try {
      await apiPost(`/api/workflows/${id}/activate`, { active });
      setMsg(active ? "Activated" : "Deactivated");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function clone() {
    setError("");
    try {
      const wf = await apiPost<Wf>("/api/workflows/clone", {
        name: cloneName || "New Workflow",
        template_id: "tpl-sdlc",
      });
      setMsg(`Cloned → ${wf.name}`);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div>
      <h1>Workflows</h1>
      <p className="muted">
        Multiple workflows may be active. A channel can belong to at most one active workflow.
      </p>
      {error && <div className="panel error">{error}</div>}
      {msg && <div className="panel">{msg}</div>}

      <div className="panel" style={{ marginBottom: "1rem" }}>
        <h2>Create from SDLC template</h2>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
          <input value={cloneName} onChange={(e) => setCloneName(e.target.value)} placeholder="Name" />
          <button type="button" onClick={clone}>
            Clone SDLC Workflow
          </button>
        </div>
        <p className="muted" style={{ marginTop: "0.5rem" }}>
          Templates: {templates.map((t) => t.name).join(", ") || "—"}
        </p>
      </div>

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "1px solid #2a3344" }}>
            <th>Name</th>
            <th>Engine</th>
            <th>Memory</th>
            <th>Tracking</th>
            <th>Active</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {workflows.map((w) => (
            <tr key={w.id} style={{ borderBottom: "1px solid #1a2230" }}>
              <td>
                <Link href={`/workflows/${w.id}`}>{w.name}</Link>
              </td>
              <td>
                <code>{w.reasoning_engine}</code>
              </td>
              <td>
                <code>{w.memory_provider}</code>
              </td>
              <td>
                <code>{w.tracking_provider}</code>
              </td>
              <td>
                <input
                  type="checkbox"
                  checked={w.is_active}
                  onChange={(e) => toggle(w.id, e.target.checked)}
                />
              </td>
              <td>
                <Link href={`/workflows/${w.id}`}>Edit</Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
