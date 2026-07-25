import { apiGet } from "@/lib/api";
import Link from "next/link";
import { BridgePanel } from "@/components/BridgePanel";

export const dynamic = "force-dynamic";

type Wf = {
  id: string;
  name: string;
  is_active: boolean;
  reasoning_engine: string;
  memory_provider: string;
};

export default async function HomePage() {
  let health: { ok?: boolean; active_workflows?: number } = {};
  let workflows: Wf[] = [];
  let runtime: { channel_index?: unknown[] } = {};
  let err = "";
  try {
    health = await apiGet("/api/health");
    const w = await apiGet<{ workflows: Wf[] }>("/api/workflows");
    workflows = w.workflows || [];
    runtime = await apiGet("/api/runtime/status");
  } catch (e) {
    err = e instanceof Error ? e.message : String(e);
  }

  const active = workflows.filter((w) => w.is_active);

  return (
    <div>
      <h1>Overview</h1>
      <p className="muted">
        Multi-workflow control plane — activate SDLC companies, pick engines, enable MCP tools.
      </p>
      {err ? (
        <div className="panel error">
          API unreachable ({err}). Start with <code>python -m apps.api.main</code> (port 8790).
        </div>
      ) : (
        <>
          <div className="grid grid-2">
            <div className="panel">
              <h2>API</h2>
              <p>Status: {health.ok ? "healthy" : "down"}</p>
              <p>Active workflows: {health.active_workflows ?? active.length}</p>
            </div>
            <div className="panel">
              <h2>Channel map</h2>
              <p>{(runtime.channel_index || []).length} owned channel(s)</p>
            </div>
          </div>

          <BridgePanel />

          <h2 className="section-title">Active workflows</h2>
          {active.length === 0 ? (
            <p className="muted">
              None active. <Link href="/workflows">Activate or clone SDLC Workflow</Link>
            </p>
          ) : (
            <ul className="link-list">
              {active.map((w) => (
                <li key={w.id}>
                  <Link href={`/workflows/${w.id}`}>{w.name}</Link>
                  <span className="muted">
                    {" "}
                    — engine <code>{w.reasoning_engine}</code>, memory{" "}
                    <code>{w.memory_provider}</code>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
