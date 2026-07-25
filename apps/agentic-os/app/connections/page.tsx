"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiGet, apiPut } from "@/lib/api";

type Wf = { id: string; name: string; is_active: boolean };
type Field = { key: string; label: string };
type SecretsResp = {
  path: string;
  keys: string[];
  fields: Field[];
  platforms: string[];
};

export default function ConnectionsPage() {
  const [workflows, setWorkflows] = useState<Wf[]>([]);
  const [wfId, setWfId] = useState("");
  const [fields, setFields] = useState<Field[]>([]);
  const [keys, setKeys] = useState<string[]>([]);
  const [path, setPath] = useState("");
  const [platforms, setPlatforms] = useState<string[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  async function loadSecrets(id: string) {
    const s = await apiGet<SecretsResp>(`/api/workflows/${id}/secrets`);
    setPath(s.path);
    setKeys(s.keys);
    setFields(s.fields);
    setPlatforms(s.platforms);
    const init: Record<string, string> = {};
    for (const f of s.fields) {
      init[f.key] = s.keys.includes(f.key) ? "(stored — leave blank to keep)" : "";
    }
    setValues(init);
  }

  useEffect(() => {
    (async () => {
      try {
        const w = await apiGet<{ workflows: Wf[] }>("/api/workflows");
        setWorkflows(w.workflows);
        const first = w.workflows.find((x) => x.is_active) || w.workflows[0];
        if (first) {
          setWfId(first.id);
          await loadSecrets(first.id);
        }
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      }
    })();
  }, []);

  async function save() {
    if (!wfId) return;
    setErr("");
    setMsg("");
    const entries: Record<string, string> = {};
    for (const [k, v] of Object.entries(values)) {
      if (!v || v.startsWith("(stored")) continue;
      entries[k] = v;
    }
    if (!Object.keys(entries).length) {
      setMsg("Nothing to update (blank fields keep existing values).");
      return;
    }
    try {
      const res = await apiPut<SecretsResp>(`/api/workflows/${wfId}/secrets`, { entries });
      setKeys(res.keys);
      setMsg("Secrets saved for this workflow.");
      await loadSecrets(wfId);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div>
      <h1>Secrets</h1>
      <p className="muted">
        Each workflow has its own secrets file. Fields follow the chat platforms configured on that
        workflow. Manage platforms under{" "}
        <Link href="/workflows">Workflows</Link>.
      </p>
      {err && <div className="panel error">{err}</div>}
      {msg && <div className="panel">{msg}</div>}

      <div className="panel">
        <label>
          Workflow{" "}
          <select
            value={wfId}
            onChange={async (e) => {
              setWfId(e.target.value);
              try {
                await loadSecrets(e.target.value);
              } catch (ex) {
                setErr(ex instanceof Error ? ex.message : String(ex));
              }
            }}
          >
            {workflows.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
                {w.is_active ? " ●" : ""}
              </option>
            ))}
          </select>
        </label>
        <p className="muted" style={{ marginTop: "0.5rem" }}>
          File: <code>{path || "—"}</code>
          <br />
          Platforms: {platforms.join(", ") || "—"}
        </p>
      </div>

      <div className="panel" style={{ marginTop: "1rem" }}>
        {fields.length === 0 ? (
          <p className="muted">Select a workflow.</p>
        ) : (
          fields.map((f) => (
            <label key={f.key} style={{ display: "block", marginBottom: "0.75rem" }}>
              {f.label}
              <br />
              <input
                type="password"
                autoComplete="off"
                style={{ width: "100%" }}
                value={values[f.key] || ""}
                onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
                placeholder={keys.includes(f.key) ? "stored" : "not set"}
              />
            </label>
          ))
        )}
        <button type="button" onClick={save} disabled={!wfId}>
          Save secrets
        </button>
      </div>
    </div>
  );
}
