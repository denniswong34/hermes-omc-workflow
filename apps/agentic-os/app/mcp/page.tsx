"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";

type CatalogItem = {
  id: string;
  name: string;
  description: string;
  transport: string;
  command: string[];
  docs_url: string;
  is_builtin: boolean;
};

type Wf = { id: string; name: string; is_active: boolean };

export default function McpPage() {
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [workflows, setWorkflows] = useState<Wf[]>([]);
  const [wfId, setWfId] = useState("");
  const [customName, setCustomName] = useState("");
  const [customCmd, setCustomCmd] = useState("npx -y @modelcontextprotocol/server-filesystem .");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  async function refresh() {
    const c = await apiGet<{ catalog: CatalogItem[] }>("/api/mcp/catalog");
    const w = await apiGet<{ workflows: Wf[] }>("/api/workflows");
    setCatalog(c.catalog);
    setWorkflows(w.workflows);
    if (!wfId && w.workflows[0]) setWfId(w.workflows[0].id);
  }

  useEffect(() => {
    refresh().catch((e) => setError(String(e.message || e)));
  }, []);

  async function enable(catalogId: string, enabled: boolean) {
    if (!wfId) return;
    setError("");
    try {
      await apiPost(`/api/workflows/${wfId}/mcp`, {
        catalog_id: catalogId,
        enabled,
      });
      setMsg(`${enabled ? "Enabled" : "Disabled"} on workflow`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function addCustom() {
    setError("");
    try {
      await apiPost("/api/mcp/catalog", {
        name: customName || "Custom MCP",
        description: "User-added MCP server",
        transport: "stdio",
        command: customCmd.split(/\s+/).filter(Boolean),
      });
      setMsg("Added to catalog");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div>
      <h1>MCP Marketplace</h1>
      <p className="muted">
        Local curated catalog + custom servers. Enable per workflow; engines use native MCP or the OMC tool proxy.
      </p>
      {error && <div className="panel error">{error}</div>}
      {msg && <div className="panel">{msg}</div>}

      <div className="panel">
        <label>
          Target workflow{" "}
          <select value={wfId} onChange={(e) => setWfId(e.target.value)}>
            {workflows.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
                {w.is_active ? " ●" : ""}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="grid grid-2" style={{ marginTop: "1rem" }}>
        {catalog.map((item) => (
          <div className="panel" key={item.id}>
            <h2>
              {item.name} {item.is_builtin ? "" : "(custom)"}
            </h2>
            <p className="muted">{item.description}</p>
            <p>
              <code>{(item.command || []).join(" ")}</code>
            </p>
            {item.docs_url && (
              <p>
                <a href={item.docs_url} target="_blank" rel="noreferrer">
                  Docs
                </a>
              </p>
            )}
            <button type="button" onClick={() => enable(item.id, true)}>
              Enable on workflow
            </button>{" "}
            <button type="button" onClick={() => enable(item.id, false)}>
              Disable
            </button>
          </div>
        ))}
      </div>

      <div className="panel" style={{ marginTop: "1rem" }}>
        <h2>Add custom server</h2>
        <input
          placeholder="Name"
          value={customName}
          onChange={(e) => setCustomName(e.target.value)}
          style={{ width: "100%", marginBottom: "0.5rem" }}
        />
        <input
          placeholder="Command"
          value={customCmd}
          onChange={(e) => setCustomCmd(e.target.value)}
          style={{ width: "100%", marginBottom: "0.5rem" }}
        />
        <button type="button" onClick={addCustom}>
          Add to catalog
        </button>
      </div>
    </div>
  );
}
