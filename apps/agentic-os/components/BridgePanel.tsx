"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";

type BridgeStatus = {
  running: boolean;
  pid?: number | null;
  message?: string;
  mode?: string;
};

export function BridgePanel() {
  const [status, setStatus] = useState<BridgeStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const refresh = useCallback(async () => {
    try {
      const s = await apiGet<BridgeStatus>("/api/bridge/status");
      setStatus(s);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 8000);
    return () => clearInterval(t);
  }, [refresh]);

  async function restart() {
    setBusy(true);
    setMsg("");
    setErr("");
    try {
      const res = await apiPost<{ message?: string; status?: BridgeStatus }>(
        "/api/bridge/restart"
      );
      setMsg(res.message || "Bridge restarted");
      setStatus(res.status || (await apiGet<BridgeStatus>("/api/bridge/status")));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  const running = !!status?.running;

  return (
    <div className="panel">
      <div className="panel-toolbar">
        <div>
          <h2 style={{ margin: 0 }}>Bridge</h2>
          <p className="muted" style={{ margin: "0.35rem 0 0" }}>
            Multi-workflow Discord/Slack adapter ({status?.mode || "bridge_multi"})
          </p>
        </div>
        <button type="button" onClick={restart} disabled={busy}>
          {busy ? "Restarting…" : "Restart bridge"}
        </button>
      </div>
      <p style={{ margin: "0.5rem 0 0" }}>
        Status:{" "}
        <span className={running ? "badge badge-ok" : "badge"}>
          {running ? "running" : "stopped"}
        </span>
        {status?.pid ? (
          <span className="muted"> · pid {status.pid}</span>
        ) : null}
      </p>
      {msg ? <p className="muted" style={{ marginBottom: 0 }}>{msg}</p> : null}
      {err ? <p className="error" style={{ marginBottom: 0 }}>{err}</p> : null}
    </div>
  );
}
