"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPut } from "@/lib/api";

type ConfigResp = { path: string; data: Record<string, unknown> };

export default function ConnectionsPage() {
  const [cfg, setCfg] = useState<ConfigResp | null>(null);
  const [jsonText, setJsonText] = useState("");
  const [secrets, setSecrets] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const c = await apiGet<ConfigResp>("/api/config");
        setCfg(c);
        setJsonText(JSON.stringify(c.data, null, 2));
        const s = await apiGet<{ keys: string[]; path: string }>("/api/secrets");
        setSecrets(s.keys.map((k) => `${k}=`).join("\n"));
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      }
    })();
  }, []);

  async function saveConfig() {
    setMsg("");
    try {
      const data = JSON.parse(jsonText);
      await apiPut("/api/config", { data });
      setMsg("Config saved.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  async function saveSecrets() {
    setMsg("");
    const entries: Record<string, string> = {};
    for (const line of secrets.split("\n")) {
      const t = line.trim();
      if (!t || t.startsWith("#") || !t.includes("=")) continue;
      const [k, ...rest] = t.split("=");
      if (k.trim()) entries[k.trim()] = rest.join("=");
    }
    try {
      await apiPut("/api/secrets", { entries });
      setMsg("Secrets saved (values write-only).");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  const data = cfg?.data || {};
  const omc = (data.omc || {}) as Record<string, unknown>;
  const topics = (data.topics || {}) as Record<string, unknown>;
  const coding = (data.coding || {}) as Record<string, unknown>;
  const memory = (data.memory || {}) as Record<string, unknown>;
  const tickets = (data.tickets || {}) as Record<string, unknown>;

  return (
    <div>
      <h1>Connections</h1>
      <p className="muted">
        Adapter, topics, tickets, coding backends, memory. Edits write to{" "}
        <code>{cfg?.path || "config/omc.yaml"}</code>.
      </p>
      {err && <div className="panel error">{err}</div>}
      {msg && <div className="panel">{msg}</div>}

      <div className="grid grid-2">
        <div className="panel">
          <h2>Summary</h2>
          <p>Adapter: {String(omc.adapter || "—")}</p>
          <p>Topics: {Object.keys(topics).join(", ") || "—"}</p>
          <p>Tickets: {String(tickets.provider || "—")}</p>
          <p>Coding default: {String(coding.default || "—")}</p>
          <p>Memory: {String(memory.provider || "—")}</p>
        </div>
        <div className="panel">
          <h2>Secrets (.env style)</h2>
          <p className="muted">DISCORD_BOT_TOKEN, PLANE_*, JIRA_*, OMC_WORKSPACE, OMC_OBSIDIAN_VAULT…</p>
          <textarea rows={8} value={secrets} onChange={(e) => setSecrets(e.target.value)} />
          <p style={{ marginTop: "0.75rem" }}>
            <button type="button" onClick={saveSecrets}>
              Save secrets
            </button>
          </p>
        </div>
      </div>

      <div className="panel">
        <h2>Full config (JSON)</h2>
        <textarea rows={22} value={jsonText} onChange={(e) => setJsonText(e.target.value)} />
        <p style={{ marginTop: "0.75rem" }}>
          <button type="button" onClick={saveConfig}>
            Save config
          </button>
        </p>
      </div>
    </div>
  );
}
