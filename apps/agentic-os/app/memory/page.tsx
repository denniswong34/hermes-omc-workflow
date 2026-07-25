import { apiGet } from "@/lib/api";

export const dynamic = "force-dynamic";

type Task = {
  task_id: string;
  status: string;
  topic: string;
  assignee: string;
  backend: string;
  title: string;
  updated: string;
};

export default async function MemoryPage() {
  let health: Record<string, unknown> = {};
  let tasks: Task[] = [];
  let err = "";
  try {
    health = await apiGet("/api/memory/health");
    const t = await apiGet<{ tasks: Task[] }>("/api/memory/tasks");
    tasks = t.tasks || [];
  } catch (e) {
    err = e instanceof Error ? e.message : String(e);
  }

  return (
    <div>
      <h1>Memory (Obsidian)</h1>
      <p className="muted">
        Shared TASK notes so Hermes / Claude / Cursor / OpenCode / Codex keep the same context.
      </p>
      {err && <div className="panel error">{err}</div>}
      <div className="panel">
        <h2>Vault health</h2>
        <pre>{JSON.stringify(health, null, 2)}</pre>
      </div>
      <div className="panel">
        <h2>Tasks ({tasks.length})</h2>
        {tasks.length === 0 ? (
          <p className="muted">No TASK notes yet. Set OMC_OBSIDIAN_VAULT and run the bridge.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "1px solid #2a3344" }}>
                <th>ID</th>
                <th>Title</th>
                <th>Status</th>
                <th>Assignee</th>
                <th>Backend</th>
                <th>Updated</th>
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
                  <td className="muted">{t.updated}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
