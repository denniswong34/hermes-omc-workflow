"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

type Task = {
  task_id: string;
  status: string;
  topic: string;
  assignee: string;
  backend: string;
  title: string;
  updated: string;
};

type Wf = { id: string; name: string; is_active: boolean; memory_provider: string };

export default function MemoryPage() {
  const [workflows, setWorkflows] = useState<Wf[]>([]);
  const [wfId, setWfId] = useState("");
  const [health, setHealth] = useState<Record<string, unknown>>({});
  const [tasks, setTasks] = useState<Task[]>([]);
  const [err, setErr] = useState("");

  async function load(id: string) {
    if (!id) return;
    const h = await apiGet<Record<string, unknown>>(`/api/workflows/${id}/memory/health`);
    const t = await apiGet<{ tasks: Task[] }>(`/api/workflows/${id}/memory/tasks`);
    setHealth(h);
    setTasks(t.tasks || []);
  }

  useEffect(() => {
    const boot = async () => {
      try {
        setErr("");
        const w = await apiGet<{ workflows: Wf[] }>("/api/workflows");
        setWorkflows(w.workflows);
        const first = w.workflows.find((x) => x.is_active) || w.workflows[0];
        if (first) {
          setWfId(first.id);
          await load(first.id);
        } else {
          setWfId("");
          setTasks([]);
          setHealth({});
        }
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
        setWorkflows([]);
        setWfId("");
      }
    };
    boot();
    window.addEventListener("omc-project-changed", boot);
    return () => window.removeEventListener("omc-project-changed", boot);
  }, []);

  return (
    <div>
      <h1>Memory</h1>
      <p className="muted">
        Per-workflow memory (hermes markdown store or Obsidian vault), namespaced by workflow id.
      </p>
      {err && <div className="panel error">{err}</div>}
      <div className="panel">
        <label>
          Workflow{" "}
          <select
            value={wfId}
            onChange={async (e) => {
              setWfId(e.target.value);
              try {
                await load(e.target.value);
              } catch (ex) {
                setErr(ex instanceof Error ? ex.message : String(ex));
              }
            }}
          >
            {workflows.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name} ({w.memory_provider})
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="panel">
        <h2>Health</h2>
        <pre>{JSON.stringify(health, null, 2)}</pre>
      </div>
      <div className="panel">
        <h2>Tasks ({tasks.length})</h2>
        {tasks.length === 0 ? (
          <p className="muted">No TASK notes in this workflow namespace yet.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "1px solid #2a3344" }}>
                <th>ID</th>
                <th>Title</th>
                <th>Status</th>
                <th>Assignee</th>
                <th>Backend</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t) => (
                <tr key={t.task_id} style={{ borderBottom: "1px solid #1c2430" }}>
                  <td>{t.task_id}</td>
                  <td>{t.title}</td>
                  <td>{t.status}</td>
                  <td>{t.assignee}</td>
                  <td>{t.backend}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
