"use client";

import { useEffect, useState } from "react";

export type PersonaOption = {
  role: string;
  path: string;
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
};

type Props = {
  open: boolean;
  title: string;
  mode: "add" | "edit";
  engines: string[];
  /** Personas from /api/agents (add mode). Already-assigned roles should be omitted by caller. */
  personas: PersonaOption[];
  initial: AgentDialogForm;
  saving?: boolean;
  onClose: () => void;
  onSubmit: (form: AgentDialogForm) => void | Promise<void>;
};

function titleCaseRole(role: string): string {
  return role
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(" ");
}

export function AgentDialog({
  open,
  title,
  mode,
  engines,
  personas,
  initial,
  saving,
  onClose,
  onSubmit,
}: Props) {
  const [roleId, setRoleId] = useState(initial.role_id);
  const [displayName, setDisplayName] = useState(initial.display_name);
  const [mention, setMention] = useState(initial.mention);
  const [kind, setKind] = useState<"persona" | "coding">(initial.kind);
  const [reasoningEngine, setReasoningEngine] = useState(initial.reasoning_engine);
  const [codingBackend, setCodingBackend] = useState(initial.coding_backend);

  useEffect(() => {
    if (!open) return;
    setRoleId(initial.role_id);
    setDisplayName(initial.display_name);
    setMention(initial.mention);
    setKind(initial.kind);
    setReasoningEngine(initial.reasoning_engine);
    setCodingBackend(initial.coding_backend || engines[0] || "hermes");
  }, [open, initial, engines]);

  if (!open) return null;

  function applyPersona(role: string) {
    setRoleId(role);
    const pretty = titleCaseRole(role);
    setDisplayName(pretty);
    setMention(pretty);
  }

  const canSubmit =
    mode === "edit"
      ? !!roleId.trim() && !!mention.trim()
      : !!roleId.trim() && personas.some((p) => p.role === roleId);

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="agent-dialog-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h2 id="agent-dialog-title">{title}</h2>
          <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="modal-body">
          {mode === "add" ? (
            <>
              <label>
                Persona
                <select
                  value={roleId}
                  onChange={(e) => applyPersona(e.target.value)}
                >
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
                  No available personas. Create one on the Personas page, or all are already on this
                  workflow.
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
        </div>

        <div className="modal-footer">
          <button type="button" className="btn-ghost" onClick={onClose} disabled={!!saving}>
            Cancel
          </button>
          <button
            type="button"
            onClick={() =>
              onSubmit({
                id: initial.id,
                role_id: roleId,
                display_name: displayName.trim() || titleCaseRole(roleId),
                mention: mention.trim() || titleCaseRole(roleId),
                kind,
                reasoning_engine: reasoningEngine,
                coding_backend: codingBackend,
              })
            }
            disabled={!!saving || !canSubmit}
          >
            {saving ? "Saving…" : mode === "add" ? "Add agent" : "Save changes"}
          </button>
        </div>
      </div>
    </div>
  );
}
