import { apiGet } from "@/lib/api";

export const dynamic = "force-dynamic";

type Card = {
  id: string;
  title: string;
  status: string;
  topic: string;
  assignee: string;
  backend: string;
  ticket_url: string;
  source: string;
};

export default async function KanbanPage() {
  let columns: string[] = [];
  let board: Record<string, Card[]> = {};
  let err = "";
  try {
    const data = await apiGet<{ columns: string[]; board: Record<string, Card[]> }>(
      "/api/kanban"
    );
    columns = data.columns || [];
    board = data.board || {};
  } catch (e) {
    err = e instanceof Error ? e.message : String(e);
  }

  return (
    <div>
      <h1>Kanban</h1>
      <p className="muted">Read-only board from Obsidian TASK notes + local task_map.</p>
      {err && <div className="panel error">{err}</div>}
      <div className="kanban">
        {columns.map((col) => (
          <div className="column" key={col}>
            <strong style={{ fontSize: "0.85rem" }}>{col}</strong>
            <div style={{ marginTop: "0.5rem" }}>
              {(board[col] || []).map((c) => (
                <div className="card" key={c.id}>
                  <div>
                    <strong>{c.id}</strong>
                  </div>
                  <div>{c.title}</div>
                  <div className="muted" style={{ fontSize: "0.75rem", marginTop: "0.35rem" }}>
                    @{c.assignee || "—"} · {c.backend || "—"} · {c.source}
                  </div>
                  {c.ticket_url ? (
                    <div style={{ marginTop: "0.25rem" }}>
                      <a href={c.ticket_url} target="_blank" rel="noreferrer">
                        ticket
                      </a>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
