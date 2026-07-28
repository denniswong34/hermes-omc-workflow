"use client";

import { useState } from "react";

export type HermesSetupAgent = {
  agent_id: string;
  role_id: string;
  display_name?: string;
  mention?: string;
  hermes_profile: string;
  profile_exists?: boolean;
  env_path_display?: string;
  platforms?: string[];
  gateways_applied?: string[];
  platforms_enabled?: string[];
  action?: string;
  gateway?: { status?: string; error?: string; reason?: string };
  error?: string | null;
  command_block?: string;
};

export type HermesSetupGuide = {
  ok: boolean;
  hermes_root?: string;
  profiles_root?: string;
  naming?: string;
  instructions?: string[];
  script?: string;
  note?: string;
  created?: number;
  updated?: number;
  exists?: number;
  errors?: number;
  gateways_started?: number;
  gateway_errors?: number;
  platforms_enabled?: string[];
  bridge_stopped?: { ok?: boolean; stopped?: boolean; message?: string };
  agents?: HermesSetupAgent[];
};

type Props = {
  open: boolean;
  guide: HermesSetupGuide | null;
  onClose: () => void;
};

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export function HermesSetupDialog({ open, guide, onClose }: Props) {
  const [copied, setCopied] = useState("");

  if (!open || !guide) return null;

  async function onCopy(label: string, text: string) {
    const ok = await copyText(text);
    setCopied(ok ? label : "failed");
    window.setTimeout(() => setCopied(""), 2000);
  }

  const summary = [
    guide.created ? `${guide.created} created` : "",
    guide.updated ? `${guide.updated} updated` : "",
    guide.exists ? `${guide.exists} unchanged` : "",
    guide.platforms_enabled?.length
      ? `channels enabled: ${guide.platforms_enabled.join(", ")}`
      : "",
    guide.gateways_started ? `${guide.gateways_started} gateways running` : "",
    guide.gateway_errors ? `${guide.gateway_errors} gateway errors` : "",
    guide.errors ? `${guide.errors} failed` : "",
  ].filter(Boolean);

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="Sync Hermes profiles"
        style={{ maxWidth: "46rem", width: "min(46rem, 94vw)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h2 style={{ margin: 0 }}>Sync Hermes profiles</h2>
          <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body" style={{ display: "grid", gap: "1rem" }}>
          <p className="muted" style={{ margin: 0 }}>
            Assigned short names (<code>omc-pm</code>, …), copied OMC portal personas into
            each profile <code>SOUL.md</code> + description, installed Windows command aliases,
            wrote OMC bot tokens + allow-all flags, enabled matching channels in{" "}
            <code>config.yaml</code>, stopped the OMC bridge if it was running, and started
            Hermes gateways with login auto-start.
          </p>
          {summary.length > 0 && (
            <p style={{ margin: 0 }}>
              Result: <strong>{summary.join(", ")}</strong>
            </p>
          )}
          {guide.note && (
            <p className="muted" style={{ margin: 0, fontSize: "0.85rem" }}>
              {guide.note}
            </p>
          )}
          {(guide.instructions || []).length > 0 && (
            <ol style={{ margin: 0, paddingLeft: "1.25rem" }}>
              {(guide.instructions || []).map((step) => (
                <li key={step} style={{ marginBottom: "0.35rem" }}>
                  {step}
                </li>
              ))}
            </ol>
          )}
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={() => onCopy("all", guide.script || "")}
              disabled={!guide.script}
            >
              {copied === "all" ? "Copied CLI fallback" : "Copy CLI fallback script"}
            </button>
            {copied === "failed" && (
              <span className="muted" style={{ alignSelf: "center" }}>
                Copy failed — select the text manually
              </span>
            )}
          </div>
          <div style={{ display: "grid", gap: "0.75rem" }}>
            {(guide.agents || []).map((ag) => {
              const gw = ag.gateway?.status || "—";
              const plats =
                (ag.platforms_enabled || ag.gateways_applied || ag.platforms || []).join(
                  ", "
                ) || "none";
              return (
                <details
                  key={ag.agent_id}
                  open={!!ag.error || ag.gateway?.status === "error"}
                >
                  <summary style={{ cursor: "pointer" }}>
                    @{ag.mention || ag.role_id} → <code>{ag.hermes_profile}</code>
                    {` · ${ag.action || "ok"} · gateway=${gw} · channels=${plats}`}
                    {ag.error ? " · ERROR" : ""}
                  </summary>
                  <div style={{ marginTop: "0.5rem", display: "grid", gap: "0.5rem" }}>
                    {ag.error && (
                      <p className="panel error" style={{ margin: 0 }}>
                        {ag.error}
                      </p>
                    )}
                    {ag.command_block && (
                      <>
                        <button
                          type="button"
                          onClick={() => onCopy(ag.hermes_profile, ag.command_block || "")}
                        >
                          {copied === ag.hermes_profile
                            ? `Copied ${ag.hermes_profile}`
                            : `Copy ${ag.hermes_profile} CLI`}
                        </button>
                        <pre
                          style={{
                            margin: 0,
                            padding: "0.65rem",
                            background: "var(--surface-2, #0f1419)",
                            border: "1px solid var(--border)",
                            borderRadius: "0.4rem",
                            fontSize: "0.78rem",
                            whiteSpace: "pre-wrap",
                          }}
                        >
                          {ag.command_block}
                        </pre>
                      </>
                    )}
                  </div>
                </details>
              );
            })}
          </div>
        </div>
        <div className="modal-footer">
          <button type="button" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
