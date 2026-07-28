"use client";

import { useEffect, useState } from "react";
import type { ConnField } from "@/components/ChatConnectionDialog";

export type TrackingConnectionForm = {
  /** Existing connection when editing */
  id?: string;
  label: string;
  provider: string;
  values: Record<string, string>;
  storedSecrets?: Record<string, boolean>;
};

type Props = {
  open: boolean;
  title: string;
  providers: string[];
  fieldsByProvider: Record<string, ConnField[]>;
  initial: TrackingConnectionForm;
  saving?: boolean;
  suggestLabel?: (provider: string) => string;
  /** Edit mode: probe tracker credentials */
  onTestConnection?: (
    form: TrackingConnectionForm
  ) => Promise<{ ok: boolean; message: string }>;
  onClose: () => void;
  onSubmit: (form: TrackingConnectionForm) => void | Promise<void>;
};

export function providerDisplayName(provider: string): string {
  const p = (provider || "").trim();
  if (!p) return "Tracker";
  return p.charAt(0).toUpperCase() + p.slice(1).toLowerCase();
}

export function nextTrackingLabel(
  provider: string,
  existing: { provider: string; label: string }[] | string[] = []
): string {
  const base = providerDisplayName(provider);
  const items = existing || [];
  let sameCount = 0;
  let maxN = 0;
  const re = new RegExp(
    `^${base.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s+#(\\d+)$`,
    "i"
  );
  for (const item of items) {
    if (typeof item === "string") {
      const m = item.trim().match(re);
      if (m) maxN = Math.max(maxN, parseInt(m[1], 10));
      continue;
    }
    if (item.provider === provider) {
      sameCount += 1;
      const m = (item.label || "").trim().match(re);
      if (m) maxN = Math.max(maxN, parseInt(m[1], 10));
    }
  }
  const next = Math.max(maxN, sameCount) + 1;
  return `${base} #${next}`;
}

export function TrackingConnectionDialog({
  open,
  title,
  providers,
  fieldsByProvider,
  initial,
  saving,
  suggestLabel,
  onTestConnection,
  onClose,
  onSubmit,
}: Props) {
  const [label, setLabel] = useState(initial.label);
  const [provider, setProvider] = useState(initial.provider);
  const [values, setValues] = useState<Record<string, string>>(initial.values || {});
  const [testing, setTesting] = useState(false);
  const [testMsg, setTestMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (!open) return;
    setLabel(initial.label);
    setProvider(initial.provider);
    setValues({ ...(initial.values || {}) });
    setTesting(false);
    setTestMsg(null);
  }, [open, initial]);

  if (!open) return null;

  const fields = fieldsByProvider[provider] || [];
  const currentForm = (): TrackingConnectionForm => ({
    id: initial.id,
    label,
    provider,
    values,
    storedSecrets: initial.storedSecrets,
  });

  async function handleTest() {
    if (!onTestConnection || !initial.id) return;
    setTesting(true);
    setTestMsg(null);
    try {
      const res = await onTestConnection(currentForm());
      setTestMsg({ ok: res.ok, text: res.message });
    } catch (e) {
      setTestMsg({
        ok: false,
        text: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="tracking-conn-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h2 id="tracking-conn-title">{title}</h2>
          <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="modal-body">
          <label>
            Label
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. Jira #1"
            />
          </label>
          <label>
            Provider
            <select
              value={provider}
              onChange={(e) => {
                const next = e.target.value;
                setProvider(next);
                setValues({});
                setTestMsg(null);
                if (!initial.id && suggestLabel) {
                  setLabel(suggestLabel(next));
                }
              }}
              disabled={!!initial.id}
            >
              {providers.map((p) => (
                <option key={p} value={p}>
                  {providerDisplayName(p)}
                </option>
              ))}
            </select>
          </label>
          {!!initial.id && (
            <p className="muted" style={{ margin: 0, fontSize: "0.85rem" }}>
              Provider is fixed after create. Remove and add a new connection to switch.
            </p>
          )}
          {fields.map((f) => {
            const stored = !!initial.storedSecrets?.[f.key];
            return (
              <label key={f.key}>
                {f.label}
                {f.kind === "secret" && stored ? (
                  <span className="muted"> (stored)</span>
                ) : null}
                <input
                  type={f.input === "password" ? "password" : "text"}
                  autoComplete="off"
                  placeholder={
                    f.kind === "secret" && stored
                      ? "leave blank to keep"
                      : f.label.toLowerCase().includes("url")
                        ? "https://…"
                        : ""
                  }
                  value={values[f.key] || ""}
                  onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
                />
              </label>
            );
          })}
          {testMsg && (
            <p
              className={testMsg.ok ? "muted" : "error"}
              style={{ margin: 0, fontSize: "0.9rem" }}
            >
              {testMsg.ok ? "✓ " : "✕ "}
              {testMsg.text}
            </p>
          )}
        </div>

        <div className="modal-footer">
          <button
            type="button"
            className="btn-ghost"
            onClick={onClose}
            disabled={!!saving || testing}
          >
            Cancel
          </button>
          {!!initial.id && onTestConnection && (
            <button
              type="button"
              className="btn-ghost"
              onClick={handleTest}
              disabled={!!saving || testing}
            >
              {testing ? "Testing…" : "Test connection"}
            </button>
          )}
          <button
            type="button"
            onClick={() => onSubmit(currentForm())}
            disabled={!!saving || testing || !label.trim()}
          >
            {saving ? "Saving…" : initial.id ? "Save changes" : "Create connection"}
          </button>
        </div>
      </div>
    </div>
  );
}
