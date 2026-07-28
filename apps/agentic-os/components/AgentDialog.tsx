"use client";

import { useEffect, useMemo, useState } from "react";
import { apiGet, apiPatch, apiPost } from "@/lib/api";

export type PersonaOption = {
  role: string;
  path: string;
};

export type ConnField = {
  key: string;
  label: string;
  kind: string;
  input?: string;
  default?: string;
  options?: { value: string; label: string }[];
};

export type GatewayPlatformState = {
  enabled: boolean;
  bot_user_id?: string;
  bot_username?: string;
  bot_email?: string;
  connection_fields: ConnField[];
  stored_secrets: Record<string, boolean>;
  connection_values: Record<string, string>;
  configured?: boolean;
};

export type AgentDialogForm = {
  /** Existing agent id when editing */
  id?: string;
  role_id: string;
  display_name: string;
  mention: string;
  kind: "persona" | "coding";
  reasoning_engine: string;
  coding_backend: string;
  hermes_profile: string;
  llm_model: string;
};

type GatewayGuide = {
  title: string;
  summary: string;
  steps: string[];
  links?: { label: string; url: string }[];
  tips?: string[];
};

type Props = {
  open: boolean;
  title: string;
  mode: "add" | "edit";
  workflowId: string;
  engines: string[];
  platforms?: string[];
  /** Personas from /api/agents (add mode). Already-assigned roles should be omitted by caller. */
  personas: PersonaOption[];
  initial: AgentDialogForm;
  saving?: boolean;
  onClose: () => void;
  onSubmit: (form: AgentDialogForm) => void | Promise<void>;
};

const DEFAULT_PLATFORMS = ["discord", "telegram", "slack", "zulip"];

function titleCaseRole(role: string): string {
  return role
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(" ");
}

type TabId = "role" | "hermes" | "gateways";

export function AgentDialog({
  open,
  title,
  mode,
  workflowId,
  engines,
  platforms = DEFAULT_PLATFORMS,
  personas,
  initial,
  saving,
  onClose,
  onSubmit,
}: Props) {
  const [tab, setTab] = useState<TabId>("role");
  const [roleId, setRoleId] = useState(initial.role_id);
  const [displayName, setDisplayName] = useState(initial.display_name);
  const [mention, setMention] = useState(initial.mention);
  const [kind, setKind] = useState<"persona" | "coding">(initial.kind);
  const [reasoningEngine, setReasoningEngine] = useState(initial.reasoning_engine);
  const [codingBackend, setCodingBackend] = useState(initial.coding_backend);
  const [hermesProfile, setHermesProfile] = useState(initial.hermes_profile);
  const [llmModel, setLlmModel] = useState(initial.llm_model);

  const [gateways, setGateways] = useState<Record<string, GatewayPlatformState>>({});
  const [gatewayDrafts, setGatewayDrafts] = useState<
    Record<string, { enabled: boolean; values: Record<string, string> }>
  >({});
  const [guides, setGuides] = useState<Record<string, GatewayGuide>>({});
  const [helpPlatform, setHelpPlatform] = useState<string | null>(null);
  const [gatewaySaving, setGatewaySaving] = useState(false);
  const [gatewayMsg, setGatewayMsg] = useState("");
  const [testBusy, setTestBusy] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setTab("role");
    setRoleId(initial.role_id);
    setDisplayName(initial.display_name);
    setMention(initial.mention);
    setKind(initial.kind);
    setReasoningEngine(initial.reasoning_engine);
    setCodingBackend(initial.coding_backend || engines[0] || "hermes");
    setHermesProfile(initial.hermes_profile || "");
    setLlmModel(initial.llm_model || "");
    setGatewayMsg("");
    setHelpPlatform(null);
  }, [open, initial, engines]);

  useEffect(() => {
    if (!open) return;
    apiGet<{ guides: Record<string, GatewayGuide> }>("/api/platforms/gateway-guides")
      .then((p) => setGuides(p.guides || {}))
      .catch(() => setGuides({}));
  }, [open]);

  useEffect(() => {
    if (!open || mode !== "edit" || !initial.id) {
      setGateways({});
      setGatewayDrafts({});
      return;
    }
    apiGet<{ gateways: Record<string, GatewayPlatformState> }>(
      `/api/workflows/${workflowId}/agents/${initial.id}/gateways`
    )
      .then((p) => {
        const g = p.gateways || {};
        setGateways(g);
        const drafts: Record<string, { enabled: boolean; values: Record<string, string> }> = {};
        for (const plat of Object.keys(g)) {
          drafts[plat] = {
            enabled: !!g[plat].enabled,
            values: { ...(g[plat].connection_values || {}) },
          };
        }
        setGatewayDrafts(drafts);
      })
      .catch(() => {
        setGateways({});
        setGatewayDrafts({});
      });
  }, [open, mode, workflowId, initial.id]);

  const canSubmit = useMemo(
    () =>
      mode === "edit"
        ? !!roleId.trim() && !!mention.trim()
        : !!roleId.trim() && personas.some((p) => p.role === roleId),
    [mode, roleId, mention, personas]
  );

  if (!open) return null;

  function applyPersona(role: string) {
    setRoleId(role);
    const pretty = titleCaseRole(role);
    setDisplayName(pretty);
    setMention(pretty);
    if (!hermesProfile) {
      setHermesProfile(`omc-${workflowId}-${role}`);
    }
  }

  function currentForm(): AgentDialogForm {
    return {
      id: initial.id,
      role_id: roleId,
      display_name: displayName.trim() || titleCaseRole(roleId),
      mention: mention.trim() || titleCaseRole(roleId),
      kind,
      reasoning_engine: reasoningEngine,
      coding_backend: codingBackend,
      hermes_profile: hermesProfile.trim(),
      llm_model: llmModel.trim(),
    };
  }

  async function saveGateway(platform: string) {
    if (!initial.id) return;
    const draft = gatewayDrafts[platform];
    if (!draft) return;
    setGatewaySaving(true);
    setGatewayMsg("");
    try {
      const fields = gateways[platform]?.connection_fields || [];
      const config: Record<string, string> = {};
      const secrets: Record<string, string> = {};
      for (const f of fields) {
        const v = draft.values[f.key] ?? "";
        if (f.kind === "secret") {
          if (v && !v.startsWith("(stored")) secrets[f.key] = v;
        } else {
          config[f.key] = v;
        }
      }
      const updated = await apiPatch<{ gateways: Record<string, GatewayPlatformState> }>(
        `/api/workflows/${workflowId}/agents/${initial.id}/gateways`,
        {
          platform,
          enabled: draft.enabled,
          config,
          secrets,
        }
      );
      const g = updated.gateways || {};
      setGateways(g);
      const nextDrafts = { ...gatewayDrafts };
      for (const plat of Object.keys(g)) {
        nextDrafts[plat] = {
          enabled: !!g[plat].enabled,
          values: { ...(g[plat].connection_values || {}) },
        };
      }
      setGatewayDrafts(nextDrafts);
      setGatewayMsg(`${platform} gateway saved`);
    } catch (e) {
      setGatewayMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setGatewaySaving(false);
    }
  }

  async function testGateway(platform: string) {
    if (!initial.id) return;
    const draft = gatewayDrafts[platform];
    setTestBusy(platform);
    setGatewayMsg("");
    try {
      const fields = gateways[platform]?.connection_fields || [];
      const config: Record<string, string> = {};
      const secrets: Record<string, string> = {};
      for (const f of fields) {
        const v = draft?.values[f.key] ?? "";
        if (f.kind === "secret") {
          if (v && !v.startsWith("(stored")) secrets[f.key] = v;
        } else if (v) {
          config[f.key] = v;
        }
      }
      const res = await apiPost<{ ok: boolean; message: string }>(
        `/api/workflows/${workflowId}/agents/${initial.id}/gateways/${platform}/test`,
        { platform, config, secrets }
      );
      setGatewayMsg(res.ok ? `✓ ${res.message}` : `✗ ${res.message}`);
    } catch (e) {
      setGatewayMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setTestBusy(null);
    }
  }

  const help = helpPlatform ? guides[helpPlatform] : null;

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="agent-dialog-title"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 560 }}
      >
        <div className="modal-header">
          <h2 id="agent-dialog-title">{title}</h2>
          <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="modal-tabs" style={{ display: "flex", gap: 8, padding: "0 1rem" }}>
          {(
            [
              ["role", "Role"],
              ["hermes", "Hermes"],
              ["gateways", "Gateways"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={tab === id ? "btn-ghost active" : "btn-ghost"}
              onClick={() => setTab(id)}
              style={{
                borderBottom: tab === id ? "2px solid var(--accent, #3b82f6)" : "2px solid transparent",
                borderRadius: 0,
              }}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="modal-body">
          {tab === "role" && (
            <>
              {mode === "add" ? (
                <>
                  <label>
                    Persona
                    <select value={roleId} onChange={(e) => applyPersona(e.target.value)}>
                      <option value="">Select a persona…</option>
                      {personas.map((p) => (
                        <option key={p.role} value={p.role}>
                          @{p.role}
                        </option>
                      ))}
                    </select>
                  </label>
                  {personas.length === 0 && (
                    <p className="muted" style={{ margin: 0, fontSize: "0.85rem" }}>
                      No available personas. Create one on the Personas page, or all are already on
                      this workflow.
                    </p>
                  )}
                </>
              ) : (
                <label>
                  Role
                  <input value={roleId} disabled readOnly />
                </label>
              )}

              <label>
                Display name
                <input
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="Product Manager"
                />
              </label>
              <label>
                Mention
                <input
                  value={mention}
                  onChange={(e) => setMention(e.target.value)}
                  placeholder="PM"
                />
              </label>
              <label>
                Kind
                <select
                  value={kind}
                  onChange={(e) => setKind(e.target.value as "persona" | "coding")}
                >
                  <option value="persona">persona</option>
                  <option value="coding">coding</option>
                </select>
              </label>
              {kind === "persona" ? (
                <label>
                  Reasoning engine
                  <select
                    value={reasoningEngine}
                    onChange={(e) => setReasoningEngine(e.target.value)}
                  >
                    <option value="">(workflow default)</option>
                    {engines.map((x) => (
                      <option key={x} value={x}>
                        {x}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <label>
                  Coding backend
                  <select
                    value={codingBackend}
                    onChange={(e) => setCodingBackend(e.target.value)}
                  >
                    {engines.map((x) => (
                      <option key={x} value={x}>
                        {x}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </>
          )}

          {tab === "hermes" && (
            <>
              <label>
                Hermes profile
                <input
                  value={hermesProfile}
                  onChange={(e) => setHermesProfile(e.target.value)}
                  placeholder={`omc-${roleId || "pm"}`}
                />
              </label>
              <p className="muted" style={{ margin: 0, fontSize: "0.85rem" }}>
                Short Hermes profile name for CLI (<code>hermes -p …</code>). Defaults to{" "}
                <code>omc-{"{role}"}</code> (e.g. <code>omc-pm</code>).
              </p>
              <label>
                LLM model
                <input
                  value={llmModel}
                  onChange={(e) => setLlmModel(e.target.value)}
                  placeholder="(Hermes default)"
                />
              </label>
              <p className="muted" style={{ margin: 0, fontSize: "0.85rem" }}>
                Optional model id passed to Hermes via <code>HERMES_MODEL</code>.
              </p>
            </>
          )}

          {tab === "gateways" && (
            <>
              {mode !== "edit" || !initial.id ? (
                <p className="muted" style={{ margin: 0 }}>
                  Save the agent first, then configure per-platform bot tokens here.
                </p>
              ) : (
                <>
                  <p className="muted" style={{ margin: "0 0 0.75rem", fontSize: "0.85rem" }}>
                    Each agent can be its own Discord / Telegram / Slack / Zulip bot. Leave disabled
                    to use the workflow Chat app bot with <code>[@Role]</code> prefixes.
                  </p>
                  {platforms.map((platform) => {
                    const state = gateways[platform];
                    const draft = gatewayDrafts[platform] || {
                      enabled: false,
                      values: {},
                    };
                    const fields = state?.connection_fields || [];
                    return (
                      <div
                        key={platform}
                        style={{
                          borderTop: "1px solid var(--border, #333)",
                          paddingTop: "0.75rem",
                          marginTop: "0.75rem",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            gap: 8,
                          }}
                        >
                          <label style={{ display: "flex", alignItems: "center", gap: 8, margin: 0 }}>
                            <input
                              type="checkbox"
                              checked={draft.enabled}
                              onChange={(e) =>
                                setGatewayDrafts((prev) => ({
                                  ...prev,
                                  [platform]: { ...draft, enabled: e.target.checked },
                                }))
                              }
                            />
                            <strong style={{ textTransform: "capitalize" }}>{platform}</strong>
                            {state?.configured ? (
                              <span className="muted" style={{ fontSize: "0.8rem" }}>
                                configured
                              </span>
                            ) : null}
                          </label>
                          <button
                            type="button"
                            className="btn-ghost"
                            style={{ fontSize: "0.8rem" }}
                            onClick={() =>
                              setHelpPlatform((p) => (p === platform ? null : platform))
                            }
                          >
                            How to get token
                          </button>
                        </div>

                        {helpPlatform === platform && help && (
                          <div
                            className="muted"
                            style={{
                              fontSize: "0.8rem",
                              margin: "0.5rem 0",
                              padding: "0.5rem 0.75rem",
                              background: "var(--surface-2, #1a1a1a)",
                              borderRadius: 6,
                            }}
                          >
                            <strong>{help.title}</strong>
                            <p style={{ margin: "0.35rem 0" }}>{help.summary}</p>
                            <ol style={{ margin: 0, paddingLeft: "1.2rem" }}>
                              {help.steps.map((s) => (
                                <li key={s}>{s}</li>
                              ))}
                            </ol>
                            {help.links?.length ? (
                              <p style={{ margin: "0.5rem 0 0" }}>
                                {help.links.map((l) => (
                                  <a
                                    key={l.url}
                                    href={l.url}
                                    target="_blank"
                                    rel="noreferrer"
                                    style={{ marginRight: 12 }}
                                  >
                                    {l.label}
                                  </a>
                                ))}
                              </p>
                            ) : null}
                          </div>
                        )}

                        {draft.enabled &&
                          fields.map((f) => (
                            <label key={f.key}>
                              {f.label}
                              {f.kind === "secret" && state?.stored_secrets?.[f.key] ? (
                                <span className="muted" style={{ fontSize: "0.75rem" }}>
                                  {" "}
                                  (stored — leave blank to keep)
                                </span>
                              ) : null}
                              <input
                                type={f.input === "password" ? "password" : "text"}
                                value={draft.values[f.key] || ""}
                                placeholder={
                                  f.kind === "secret" && state?.stored_secrets?.[f.key]
                                    ? "(stored)"
                                    : ""
                                }
                                onChange={(e) =>
                                  setGatewayDrafts((prev) => ({
                                    ...prev,
                                    [platform]: {
                                      ...draft,
                                      values: { ...draft.values, [f.key]: e.target.value },
                                    },
                                  }))
                                }
                                autoComplete="off"
                              />
                            </label>
                          ))}

                        {draft.enabled && (
                          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                            <button
                              type="button"
                              onClick={() => saveGateway(platform)}
                              disabled={gatewaySaving}
                            >
                              {gatewaySaving ? "Saving…" : "Save gateway"}
                            </button>
                            <button
                              type="button"
                              className="btn-ghost"
                              onClick={() => testGateway(platform)}
                              disabled={!!testBusy}
                            >
                              {testBusy === platform ? "Testing…" : "Test connection"}
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                  {gatewayMsg ? (
                    <p className="muted" style={{ margin: "0.75rem 0 0", fontSize: "0.85rem" }}>
                      {gatewayMsg}
                    </p>
                  ) : null}
                </>
              )}
            </>
          )}
        </div>

        <div className="modal-footer">
          <button type="button" className="btn-ghost" onClick={onClose} disabled={!!saving}>
            Cancel
          </button>
          <button
            type="button"
            onClick={() => onSubmit(currentForm())}
            disabled={!!saving || !canSubmit}
          >
            {saving ? "Saving…" : mode === "add" ? "Add agent" : "Save changes"}
          </button>
        </div>
      </div>
    </div>
  );
}
