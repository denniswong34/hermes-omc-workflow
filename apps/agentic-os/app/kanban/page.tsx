"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

type Card = {
  id: string;
  title?: string;
  task_id?: string;
  status: string;
  topic?: string;
  assignee?: string;
  backend?: string;
  ticket_url?: string;
  workflow_id?: string;
  workflow_name?: string;
};

type Wf = { id: string; name: string; is_active: boolean };

export default function KanbanPage() {
  const [columns, setColumns] = useState<string[]>([]);
  const [board, setBoard] = useState<Record<string, Card[]>>({});
  const [workflows, setWorkflows] = useState<Wf[]>([]);
  const [filter, setFilter] = useState("");
  const [err, setErr] = useState("");

  async function load(wfId: string) {
    const q = wfId ? `?workflow_id=${encodeURIComponent(wfId)}` : "";
    const data = await apiGet<{ columns: string[]; board: Record<string, Card[]> }>(
      `/api/kanban/v2${q}`
    );
    setColumns(data.columns || []);
    setBoard(data.board || {});
  }

  useEffect(() => {
    (async () => {
      try {
        const w = await apiGet<{ workflows: Wf[] }>("/api/workflows");
        setWorkflows(w.workflows.filter((x) => x.is_active));
        await load("");
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      }
    })();
  }, []);

  return (
    <div>
      <h1>Kanban</h1>
      <p className="muted">Tasks from active workflow memory namespaces.</p>
      {err && <div className="panel error">{err}</div>}
      <div className="panel" style={{ marginBottom: "1rem" }}>
        <label>
          Workflow filter{" "}
          <select
            value={filter}
            onChange={async (e) => {
              setFilter(e.target.value);
              try {
                await load(e.target.value);
              } catch (ex) {
                setErr(ex instanceof Error ? ex.message : String(ex));
              }
            }}
          >
            <option value="">All active</option>
            {workflows.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="kanban">
        {columns.map((col) => (
          <div className="column" key={col}>
            <strong style={{ fontSize: "0.85rem" }}>{col}</strong>
            <div style={{ marginTop: "0.5rem" }}>
              {(board[col] || []).map((c) => (
                <div className="card" key={`${c.workflow_id}-${c.id || c.task_id}`}>
                  <div>
                    <strong>{c.id || c.task_id}</strong>
                  </div>
                  <div>{c.title}</div>
                  <div className="muted" style={{ fontSize: "0.75rem", marginTop: "0.35rem" }}>
                    {c.workflow_name} · @{c.assignee || "—"} · {c.backend || "—"}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
