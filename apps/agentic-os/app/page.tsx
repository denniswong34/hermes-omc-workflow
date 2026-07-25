import { apiGet } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  let health: { ok?: boolean } = {};
  let memory: { ok?: boolean; provider?: string; tasks?: number } = {};
  let bridge: { running?: boolean; message?: string } = {};
  let err = "";
  try {
    health = await apiGet("/api/health");
    memory = await apiGet("/api/memory/health");
    bridge = await apiGet("/api/bridge/status");
  } catch (e) {
    err = e instanceof Error ? e.message : String(e);
  }

  return (
    <div>
      <h1>Overview</h1>
      <p className="muted">
        Control plane for OMC topics, agents, coding backends, Obsidian memory, and Kanban.
      </p>
      {err ? (
        <div className="panel error">
          API unreachable ({err}). Start with{" "}
          <code>python -m apps.api.main</code> on port 8787.
        </div>
      ) : (
        <div className="grid grid-2">
          <div className="panel">
            <h2>API</h2>
            <p>Status: {health.ok ? "healthy" : "down"}</p>
          </div>
          <div className="panel">
            <h2>Memory</h2>
            <p>Provider: {memory.provider || "none"}</p>
            <p>Vault OK: {String(memory.ok)}</p>
            <p>Tasks: {memory.tasks ?? 0}</p>
          </div>
          <div className="panel">
            <h2>Bridge</h2>
            <p>{bridge.message || (bridge.running ? "running" : "stopped")}</p>
          </div>
        </div>
      )}
    </div>
  );
}
