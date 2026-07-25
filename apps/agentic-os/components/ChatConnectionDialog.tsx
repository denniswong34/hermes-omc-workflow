"use client";

import { useEffect, useState } from "react";

export type ConnField = {
  key: string;
  label: string;
  kind: "secret" | "config";
  input: string;
};

export type ChannelDraft = {
  /** Existing DB id when editing; empty for new rows */
  id?: string;
  name: string;
  external_id: string;
  /** Mark for deletion on save */
  _delete?: boolean;
};

export type ChatConnectionForm = {
  id?: string;
  label: string;
  platform: string;
  values: Record<string, string>;
  storedSecrets?: Record<string, boolean>;
  channels: ChannelDraft[];
};

type TabId = "connection" | "channels";

type Props = {
  open: boolean;
  title: string;
  platforms: string[];
  fieldsByPlatform: Record<string, ConnField[]>;
  initial: ChatConnectionForm;
  saving?: boolean;
  /** Suggest next label when platform changes (add mode) */
  suggestLabel?: (platform: string) => string;
  /** Edit mode: probe platform credentials */
  onTestConnection?: (form: ChatConnectionForm) => Promise<{ ok: boolean; message: string }>;
  onClose: () => void;
  onSubmit: (form: ChatConnectionForm) => void | Promise<void>;
};

const DEFAULT_TOPIC_NAMES = ["product", "engineering", "marketing", "support", "standup"];

export function defaultTopicChannels(): ChannelDraft[] {
  return DEFAULT_TOPIC_NAMES.map((name) => ({ name, external_id: "" }));
}

export function platformDisplayName(platform: string): string {
  const p = (platform || "").trim();
  if (!p) return "Chat";
  return p.charAt(0).toUpperCase() + p.slice(1).toLowerCase();
}

export function nextChatLabel(
  platform: string,
  existing: { platform: string; label: string }[] | string[]
): string {
  const base = platformDisplayName(platform);
  const items = existing || [];
  // Support legacy string[] of labels or chat objects
  let sameCount = 0;
  let maxN = 0;
  const re = new RegExp(`^${base.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s+#(\\d+)$`, "i");
  for (const item of items) {
    if (typeof item === "string") {
      const m = item.trim().match(re);
      if (m) maxN = Math.max(maxN, parseInt(m[1], 10));
      continue;
    }
    if (item.platform === platform) {
      sameCount += 1;
      const m = (item.label || "").trim().match(re);
      if (m) maxN = Math.max(maxN, parseInt(m[1], 10));
    }
  }
  const next = Math.max(maxN, sameCount) + 1;
  return `${base} #${next}`;
}

export function ChatConnectionDialog({
  open,
  title,
  platforms,
  fieldsByPlatform,
  initial,
  saving,
  suggestLabel,
  onTestConnection,
  onClose,
  onSubmit,
}: Props) {
  const [tab, setTab] = useState<TabId>("connection");
  const [label, setLabel] = useState(initial.label);
  const [platform, setPlatform] = useState(initial.platform);
  const [values, setValues] = useState<Record<string, string>>(initial.values || {});
  const [channels, setChannels] = useState<ChannelDraft[]>(initial.channels || []);
  const [newChannelName, setNewChannelName] = useState("");
  const [testing, setTesting] = useState(false);
  const [testMsg, setTestMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (!open) return;
    setTab("connection");
    setLabel(initial.label);
    setPlatform(initial.platform);
    setValues({ ...(initial.values || {}) });
    setChannels(
      (initial.channels || []).length
        ? initial.channels.map((c) => ({ ...c }))
        : defaultTopicChannels()
    );
    setNewChannelName("");
    setTesting(false);
    setTestMsg(null);
  }, [open, initial]);

  if (!open) return null;

  const fields = fieldsByPlatform[platform] || [];
  const visibleChannels = channels.filter((c) => !c._delete);
  const currentForm = (): ChatConnectionForm => ({
    id: initial.id,
    label,
    platform,
    values,
    storedSecrets: initial.storedSecrets,
    channels,
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

  function updateChannel(idx: number, patch: Partial<ChannelDraft>) {
    setChannels((prev) => {
      const visible = prev.filter((c) => !c._delete);
      const target = visible[idx];
      if (!target) return prev;
      return prev.map((c) => (c === target ? { ...c, ...patch } : c));
    });
  }

  function removeChannelRow(idx: number) {
    setChannels((prev) => {
      const visible = prev.filter((c) => !c._delete);
      const target = visible[idx];
      if (!target) return prev;
      if (target.id) {
        return prev.map((c) => (c === target ? { ...c, _delete: true } : c));
      }
      return prev.filter((c) => c !== target);
    });
  }

  function addChannelRow() {
    const name = newChannelName.trim().toLowerCase().replace(/\s+/g, "_");
    if (!name) return;
    if (visibleChannels.some((c) => c.name === name)) return;
    setChannels((prev) => [...prev, { name, external_id: "" }]);
    setNewChannelName("");
  }

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="modal modal-wide"
        role="dialog"
        aria-modal="true"
        aria-labelledby="chat-conn-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h2 id="chat-conn-title">{title}</h2>
          <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "connection"}
            className={tab === "connection" ? "tab active" : "tab"}
            onClick={() => setTab("connection")}
          >
            Connection
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "channels"}
            className={tab === "channels" ? "tab active" : "tab"}
            onClick={() => setTab("channels")}
          >
            Channels ({visibleChannels.length})
          </button>
        </div>

        <div className="modal-body">
          {tab === "connection" && (
            <>
              <label>
                Label
                <input
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder="e.g. Discord #1"
                />
              </label>
              <label>
                Platform
                <select
                  value={platform}
                  onChange={(e) => {
                    const next = e.target.value;
                    setPlatform(next);
                    setValues({});
                    if (!initial.id && suggestLabel) {
                      setLabel(suggestLabel(next));
                    }
                  }}
                  disabled={!!initial.id}
                >
                  {platforms.map((p) => (
                    <option key={p} value={p}>
                      {platformDisplayName(p)}
                    </option>
                  ))}
                </select>
              </label>
              {!!initial.id && (
                <p className="muted" style={{ margin: 0, fontSize: "0.85rem" }}>
                  Platform is fixed after create. Remove and add a new connection to switch apps.
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
            </>
          )}

          {tab === "channels" && (
            <>
              <p className="muted" style={{ margin: 0, fontSize: "0.85rem" }}>
                Topic channels for this chat app. Paste each platform channel / stream / chat ID.
              </p>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>External ID</th>
                    <th style={{ textAlign: "right" }} />
                  </tr>
                </thead>
                <tbody>
                  {visibleChannels.map((ch, idx) => (
                    <tr key={`${ch.id || "new"}-${ch.name}-${idx}`}>
                      <td>
                        <code>#{ch.name}</code>
                      </td>
                      <td>
                        <input
                          value={ch.external_id}
                          placeholder="channel id"
                          onChange={(e) => updateChannel(idx, { external_id: e.target.value })}
                        />
                      </td>
                      <td>
                        <div className="actions">
                          <button
                            type="button"
                            className="icon-btn danger"
                            aria-label={`Remove #${ch.name}`}
                            title="Remove"
                            onClick={() => removeChannelRow(idx)}
                          >
                            <IconTrash />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                <input
                  placeholder="new channel name"
                  value={newChannelName}
                  onChange={(e) => setNewChannelName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      addChannelRow();
                    }
                  }}
                />
                <button type="button" className="btn-ghost" onClick={addChannelRow}>
                  Add channel
                </button>
              </div>
            </>
          )}
        </div>

        <div className="modal-footer">
          <button type="button" className="btn-ghost" onClick={onClose} disabled={!!saving || testing}>
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

export function IconEdit({ title = "Edit" }: { title?: string }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <title>{title}</title>
      <path
        d="M4 20h4.5L19 9.5 14.5 5 4 15.5V20z"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinejoin="round"
      />
      <path d="M12.5 7.5l4 4" stroke="currentColor" strokeWidth="1.75" />
    </svg>
  );
}

export function IconTrash({ title = "Remove" }: { title?: string }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <title>{title}</title>
      <path d="M5 7h14" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
      <path d="M9 7V5h6v2" stroke="currentColor" strokeWidth="1.75" strokeLinejoin="round" />
      <path
        d="M8 7l1 12h6l1-12"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinejoin="round"
      />
    </svg>
  );
}
