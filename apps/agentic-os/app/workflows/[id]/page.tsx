"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import {
  ChatConnectionDialog,
  IconEdit,
  IconTrash,
  defaultTopicChannels,
  nextChatLabel,
  type ChatConnectionForm,
  type ConnField,
} from "@/components/ChatConnectionDialog";
import {
  TrackingConnectionDialog,
  nextTrackingLabel,
  type TrackingConnectionForm,
} from "@/components/TrackingConnectionDialog";
import {
  AgentDialog,
  type AgentDialogForm,
  type PersonaOption,
} from "@/components/AgentDialog";
import { HermesSetupDialog, type HermesSetupGuide } from "@/components/HermesSetupDialog";

type Agent = {
  id: string;
  role_id: string;
  display_name: string;
  mention: string;
  kind: string;
  reasoning_engine: string | null;
  coding_backend: string | null;
  hermes_profile?: string;
  llm_model?: string;
  persona_file: string;
  mcp_allowlist: string[];
  gateways?: Record<string, { enabled?: boolean; configured?: boolean }>;
};

type Chat = {
  id: string;
  platform: string;
  label: string;
  config?: Record<string, string>;
  connection_fields?: ConnField[];
  stored_secrets?: Record<string, boolean>;
  connection_values?: Record<string, string>;
};

type Channel = {
  id: string;
  name: string;
  external_id: string;
  platform: string;
  chat_id: string;
  agents: string[];
};

type CronJob = {
  id: string;
  name: string;
  cron_expr: string;
  agent_role: string;
  channel_name: string;
  enabled: boolean;
};

type TrackingInfo = {
  id?: string;
  provider: string;
  label: string;
  configured: boolean;
  is_active?: boolean;
  connection_fields?: ConnField[];
  stored_secrets?: Record<string, boolean>;
  connection_values?: Record<string, string>;
  config?: Record<string, string>;
};

type Workflow = {
  id: string;
  name: string;
  description: string;
  is_active: boolean;
  reasoning_engine: string;
  coding_default: string;
  memory_provider: string;
  memory_config: Record<string, unknown>;
  tracking_provider: string;
  tracking_config: Record<string, unknown>;
  tracking?: TrackingInfo;
  trackings?: TrackingInfo[];
  agents: Agent[];
  chats: Chat[];
  channels: Channel[];
  cron_jobs: CronJob[];
  mcp_servers: { catalog_id: string; name: string; enabled: boolean }[];
};

const ENGINES = ["hermes", "claude", "cursor", "opencode", "codex"];
const DEFAULT_PLATFORMS = ["discord", "slack", "zulip", "telegram"];
const DEFAULT_TRACKING_PROVIDERS = ["jira", "plane"];

const DEFAULT_TOPIC_AGENTS: Record<string, string[]> = {
  product: ["pm", "sa"],
  engineering: ["pm", "sa", "coder", "qa", "devops", "hermes", "claude", "cursor", "opencode", "codex"],
  marketing: ["pm", "marketing"],
  support: ["pm", "sa", "coder", "qa", "hermes", "claude", "cursor", "opencode", "codex"],
  standup: ["standup"],
};

const DEFAULT_TICKET_ROLES: Record<string, string[]> = {
  product: ["pm", "sa"],
  engineering: ["pm", "sa"],
  marketing: ["pm"],
  support: ["pm", "sa"],
  standup: [],
};

const MESSAGE_FORMAT_FIELD: ConnField = {
  key: "message_format",
  label: "Message format",
  kind: "config",
  input: "select",
  default: "card",
  options: [
    { value: "block", label: "Block (━━ bars)" },
    { value: "card", label: "Card (box header) — default" },
    { value: "quote", label: "Quote (speaker style)" },
    { value: "sections", label: "Sections (FROM/RESPONSE)" },
  ],
};

/** Fallback field schemas if /api/platforms is stale */
const FALLBACK_FIELDS: Record<string, ConnField[]> = {
  discord: [
    { key: "DISCORD_BOT_TOKEN", label: "Bot token", kind: "secret", input: "password" },
    MESSAGE_FORMAT_FIELD,
  ],
  slack: [
    { key: "SLACK_BOT_TOKEN", label: "Bot token", kind: "secret", input: "password" },
    { key: "SLACK_APP_TOKEN", label: "App token (Socket Mode)", kind: "secret", input: "password" },
    MESSAGE_FORMAT_FIELD,
  ],
  telegram: [
    { key: "TELEGRAM_BOT_TOKEN", label: "Bot token", kind: "secret", input: "password" },
    MESSAGE_FORMAT_FIELD,
  ],
  zulip: [
    { key: "ZULIP_SITE", label: "Site URL", kind: "config", input: "text" },
    { key: "ZULIP_EMAIL", label: "Bot email", kind: "config", input: "text" },
    { key: "ZULIP_API_KEY", label: "API key", kind: "secret", input: "password" },
    MESSAGE_FORMAT_FIELD,
  ],
};

const FALLBACK_TRACKING_FIELDS: Record<string, ConnField[]> = {
  jira: [
    { key: "base_url", label: "Base URL", kind: "config", input: "text" },
    { key: "email", label: "Email", kind: "config", input: "text" },
    { key: "project_key", label: "Project key", kind: "config", input: "text" },
    { key: "api_token", label: "API token", kind: "secret", input: "password" },
  ],
  plane: [
    { key: "base_url", label: "Base URL", kind: "config", input: "text" },
    { key: "workspace", label: "Workspace", kind: "config", input: "text" },
    { key: "project_id", label: "Project ID", kind: "config", input: "text" },
    { key: "api_key", label: "API key", kind: "secret", input: "password" },
  ],
};

function splitFormValues(
  fields: ConnField[],
  values: Record<string, string>
): { config: Record<string, string>; secrets: Record<string, string> } {
  const config: Record<string, string> = {};
  const secrets: Record<string, string> = {};
  for (const f of fields) {
    const v = values[f.key] ?? "";
    if (f.kind === "secret") {
      if (v && !v.startsWith("(stored")) secrets[f.key] = v;
    } else {
      config[f.key] = v;
    }
  }
  return { config, secrets };
}

export default function WorkflowDetailPage() {
  const params = useParams();
  const id = String(params.id);
  const [wf, setWf] = useState<Workflow | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [tplName, setTplName] = useState("");
  const [personas, setPersonas] = useState<PersonaOption[]>([]);
  const [agentDialogOpen, setAgentDialogOpen] = useState(false);
  const [agentDialogMode, setAgentDialogMode] = useState<"add" | "edit">("add");
  const [agentDialogForm, setAgentDialogForm] = useState<AgentDialogForm>({
    role_id: "",
    display_name: "",
    mention: "",
    kind: "persona",
    reasoning_engine: "",
    coding_backend: "hermes",
    hermes_profile: "",
    llm_model: "",
  });
  const [agentSaving, setAgentSaving] = useState(false);
  const [hermesSyncing, setHermesSyncing] = useState(false);
  const [hermesGuideOpen, setHermesGuideOpen] = useState(false);
  const [hermesGuide, setHermesGuide] = useState<HermesSetupGuide | null>(null);
  const [platforms, setPlatforms] = useState<string[]>(DEFAULT_PLATFORMS);
  const [fieldsByPlatform, setFieldsByPlatform] =
    useState<Record<string, ConnField[]>>(FALLBACK_FIELDS);
  const [chatDialogOpen, setChatDialogOpen] = useState(false);
  const [chatDialogMode, setChatDialogMode] = useState<"add" | "edit">("add");
  const [chatDialogForm, setChatDialogForm] = useState<ChatConnectionForm>({
    label: "",
    platform: "discord",
    values: {},
    channels: [],
  });
  const [chatSaving, setChatSaving] = useState(false);
  const [trackingProviders, setTrackingProviders] =
    useState<string[]>(DEFAULT_TRACKING_PROVIDERS);
  const [fieldsByTracking, setFieldsByTracking] =
    useState<Record<string, ConnField[]>>(FALLBACK_TRACKING_FIELDS);
  const [trackingDialogOpen, setTrackingDialogOpen] = useState(false);
  const [trackingDialogMode, setTrackingDialogMode] = useState<"add" | "edit">("add");
  const [trackingDialogForm, setTrackingDialogForm] = useState<TrackingConnectionForm>({
    label: nextTrackingLabel("jira", []),
    provider: "jira",
    values: {},
  });
  const [trackingSaving, setTrackingSaving] = useState(false);

  async function load() {
    const data = await apiGet<Workflow>(`/api/workflows/${id}`);
    setWf(data);
  }

  useEffect(() => {
    load().catch((e) => setError(String(e.message || e)));
    apiGet<{ platforms: string[]; connection_fields: Record<string, ConnField[]> }>("/api/platforms")
      .then((p) => {
        setPlatforms(p.platforms?.length ? p.platforms : DEFAULT_PLATFORMS);
        if (p.connection_fields && Object.keys(p.connection_fields).length) {
          setFieldsByPlatform(p.connection_fields);
        }
      })
      .catch(() => undefined);
    apiGet<{ providers: string[]; connection_fields: Record<string, ConnField[]> }>(
      "/api/tracking-providers"
    )
      .then((p) => {
        setTrackingProviders(p.providers?.length ? p.providers : DEFAULT_TRACKING_PROVIDERS);
        if (p.connection_fields && Object.keys(p.connection_fields).length) {
          setFieldsByTracking(p.connection_fields);
        }
      })
      .catch(() => undefined);
    apiGet<{ roles: PersonaOption[] }>("/api/agents")
      .then((a) => setPersonas(a.roles || []))
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  function suggestChatLabel(platform: string) {
    return nextChatLabel(platform, wf?.chats || []);
  }

  function openAddChatDialog() {
    const platform = "discord";
    const hasAnyChannels = (wf?.channels || []).length > 0;
    setChatDialogMode("add");
    setChatDialogForm({
      label: suggestChatLabel(platform),
      platform,
      values: {},
      // Default SDLC topics only when workflow has none yet (names are unique per workflow)
      channels: hasAnyChannels ? [] : defaultTopicChannels(),
    });
    setChatDialogOpen(true);
  }

  function openEditChatDialog(chat: Chat) {
    const bound = (wf?.channels || [])
      .filter((c) => c.chat_id === chat.id)
      .map((c) => ({
        id: c.id,
        name: c.name,
        external_id: c.external_id || "",
      }));
    setChatDialogMode("edit");
    setChatDialogForm({
      id: chat.id,
      label: chat.label,
      platform: chat.platform,
      values: { ...(chat.connection_values || {}) },
      storedSecrets: chat.stored_secrets,
      channels: bound.length ? bound : defaultTopicChannels(),
    });
    setChatDialogOpen(true);
  }

  async function syncChannelsForChat(chatId: string, drafts: ChatConnectionForm["channels"]) {
    for (const ch of drafts) {
      if (ch._delete && ch.id) {
        await apiDelete(`/api/workflows/${id}/channels/${ch.id}`);
        continue;
      }
      if (ch._delete) continue;
      const name = ch.name.trim().toLowerCase().replace(/\s+/g, "_");
      if (!name) continue;
      if (ch.id) {
        await apiPatch(`/api/workflows/${id}/channels/${ch.id}`, {
          external_id: ch.external_id || "",
          chat_id: chatId,
        });
        continue;
      }
      // Reuse existing workflow channel name if present (unique per workflow)
      const existing = (wf?.channels || []).find((c) => c.name === name);
      if (existing) {
        await apiPatch(`/api/workflows/${id}/channels/${existing.id}`, {
          external_id: ch.external_id || existing.external_id || "",
          chat_id: chatId,
        });
      } else {
        await apiPost(`/api/workflows/${id}/channels`, {
          name,
          chat_id: chatId,
          external_id: ch.external_id || "",
          agents: DEFAULT_TOPIC_AGENTS[name] || [],
          ticket_create_roles: DEFAULT_TICKET_ROLES[name] || [],
        });
      }
    }
  }

  async function submitChatDialog(form: ChatConnectionForm) {
    setError("");
    setChatSaving(true);
    try {
      const fields = fieldsByPlatform[form.platform] || [];
      const { config, secrets } = splitFormValues(fields, form.values);
      const label =
        form.label.trim() || nextChatLabel(form.platform, wf?.chats || []);
      let chatId = form.id;
      if (chatDialogMode === "add") {
        const created = await apiPost<{ id: string }>(`/api/workflows/${id}/chats`, {
          platform: form.platform,
          label,
          config,
          secrets,
        });
        chatId = created.id;
        setMsg(`Added ${label}`);
      } else if (form.id) {
        await apiPatch(`/api/workflows/${id}/chats/${form.id}`, {
          label,
          config,
          secrets,
        });
        setMsg(`Updated ${label}`);
      }
      if (chatId) {
        await syncChannelsForChat(chatId, form.channels || []);
      }
      setChatDialogOpen(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setChatSaving(false);
    }
  }

  async function saveCore() {
    if (!wf) return;
    setError("");
    try {
      const updated = await apiPatch<Workflow>(`/api/workflows/${id}`, {
        name: wf.name,
        description: wf.description,
        reasoning_engine: wf.reasoning_engine,
        coding_default: wf.coding_default,
      });
      setWf(updated);
      setMsg("Saved");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function saveMemory() {
    if (!wf) return;
    setError("");
    try {
      const updated = await apiPatch<Workflow>(`/api/workflows/${id}`, {
        memory_provider: wf.memory_provider,
        memory_config: wf.memory_config,
      });
      setWf(updated);
      setMsg("Memory saved");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function trackingList(): TrackingInfo[] {
    if (wf?.trackings?.length) return wf.trackings;
    if (wf?.tracking?.configured) return [wf.tracking];
    return [];
  }

  function suggestTrackingLabel(provider: string): string {
    return nextTrackingLabel(provider, trackingList());
  }

  function openAddTrackingDialog() {
    const provider = trackingProviders[0] || "jira";
    setTrackingDialogMode("add");
    setTrackingDialogForm({
      label: suggestTrackingLabel(provider),
      provider,
      values: {},
    });
    setTrackingDialogOpen(true);
  }

  function openEditTrackingDialog(t: TrackingInfo) {
    if (!t?.configured || !t.id) return;
    setTrackingDialogMode("edit");
    setTrackingDialogForm({
      id: t.id,
      label: t.label || suggestTrackingLabel(t.provider),
      provider: t.provider,
      values: { ...(t.connection_values || {}) },
      storedSecrets: t.stored_secrets,
    });
    setTrackingDialogOpen(true);
  }

  async function submitTrackingDialog(form: TrackingConnectionForm) {
    setTrackingSaving(true);
    setError("");
    try {
      const fields = fieldsByTracking[form.provider] || [];
      const { config, secrets } = splitFormValues(fields, form.values);
      const label = form.label.trim() || suggestTrackingLabel(form.provider);
      let updated: Workflow;
      if (trackingDialogMode === "add") {
        updated = await apiPost<Workflow>(`/api/workflows/${id}/trackings`, {
          provider: form.provider,
          label,
          config,
          secrets,
          activate: trackingList().length === 0,
        });
        setMsg(`Added ${label}`);
      } else if (form.id) {
        updated = await apiPatch<Workflow>(
          `/api/workflows/${id}/trackings/${form.id}`,
          { label, config, secrets }
        );
        setMsg(`Updated ${label}`);
      } else {
        throw new Error("Missing tracking connection id");
      }
      setWf(updated);
      setTrackingDialogOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setTrackingSaving(false);
    }
  }

  async function testTrackingConnection(form: TrackingConnectionForm) {
    if (!form.id) {
      return { ok: false, message: "Save the connection before testing" };
    }
    const fields = fieldsByTracking[form.provider] || [];
    const { config, secrets } = splitFormValues(fields, form.values);
    const res = await apiPost<{ ok: boolean; message: string }>(
      `/api/workflows/${id}/trackings/${form.id}/test`,
      {
        provider: form.provider,
        config,
        secrets,
      }
    );
    return { ok: !!res.ok, message: res.message || (res.ok ? "OK" : "Failed") };
  }

  async function activateTracking(t: TrackingInfo) {
    if (!t.id) return;
    setError("");
    try {
      const updated = await apiPost<Workflow>(
        `/api/workflows/${id}/trackings/${t.id}/activate`
      );
      setWf(updated);
      setMsg(`Active tracker: ${t.label || t.provider}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function removeTracking(t: TrackingInfo) {
    if (!t.id) return;
    const label = t.label || t.provider || "tracking";
    if (!window.confirm(`Remove ${label} tracking connection?`)) return;
    setError("");
    try {
      const updated = await apiDelete<Workflow>(
        `/api/workflows/${id}/trackings/${t.id}`
      );
      setWf(updated);
      setMsg("Tracking removed");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function trackingStatus(t?: TrackingInfo): string {
    if (!t?.configured) return "—";
    const fields = t.connection_fields || fieldsByTracking[t.provider] || [];
    const secretFields = fields.filter((f) => f.kind === "secret");
    const configFields = fields.filter((f) => f.kind === "config");
    const configOk = configFields.every((f) => !!(t.connection_values?.[f.key] || t.config?.[f.key]));
    const secretsOk =
      !secretFields.length || secretFields.every((f) => t.stored_secrets?.[f.key]);
    if (configOk && secretsOk) return "Connected";
    return "Needs credentials";
  }

  function availablePersonas(): PersonaOption[] {
    const used = new Set((wf?.agents || []).map((a) => a.role_id));
    return personas.filter((p) => !used.has(p.role));
  }

  function openAddAgentDialog() {
    const available = availablePersonas();
    const first = available[0]?.role || "";
    const pretty = first
      ? first
          .split(/[_\s-]+/)
          .filter(Boolean)
          .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
          .join(" ")
      : "";
    setAgentDialogMode("add");
    setAgentDialogForm({
      role_id: first,
      display_name: pretty,
      mention: pretty,
      kind: "persona",
      reasoning_engine: "",
      coding_backend: wf?.coding_default || "hermes",
      hermes_profile: first ? `omc-${first}` : "",
      llm_model: "",
    });
    setAgentDialogOpen(true);
  }

  function openEditAgentDialog(ag: Agent) {
    setAgentDialogMode("edit");
    setAgentDialogForm({
      id: ag.id,
      role_id: ag.role_id,
      display_name: ag.display_name,
      mention: ag.mention,
      kind: ag.kind === "coding" ? "coding" : "persona",
      reasoning_engine: ag.reasoning_engine || "",
      coding_backend: ag.coding_backend || wf?.coding_default || "hermes",
      hermes_profile: ag.hermes_profile || `omc-${ag.role_id}`,
      llm_model: ag.llm_model || "",
    });
    setAgentDialogOpen(true);
  }

  async function submitAgentDialog(form: AgentDialogForm) {
    setAgentSaving(true);
    setError("");
    try {
      if (agentDialogMode === "edit" && form.id) {
        await apiPatch(`/api/workflows/${id}/agents/${form.id}`, {
          display_name: form.display_name,
          mention: form.mention,
          kind: form.kind,
          reasoning_engine: form.kind === "persona" ? form.reasoning_engine || null : null,
          coding_backend: form.kind === "coding" ? form.coding_backend : null,
          hermes_profile: form.hermes_profile || `omc-${form.role_id}`,
          llm_model: form.llm_model || "",
        });
        setMsg(`Updated @${form.mention}`);
      } else {
        await apiPost(`/api/workflows/${id}/agents`, {
          role_id: form.role_id,
          mention: form.mention || form.role_id,
          display_name: form.display_name || form.role_id,
          kind: form.kind,
          persona_file: `${form.role_id}.md`,
          reasoning_engine: form.kind === "persona" ? form.reasoning_engine || null : null,
          coding_backend: form.kind === "coding" ? form.coding_backend : null,
          hermes_profile: form.hermes_profile || `omc-${form.role_id}`,
          llm_model: form.llm_model || "",
          create_persona_file: false,
        });
        setMsg(`Added @${form.mention || form.role_id}`);
      }
      setAgentDialogOpen(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setAgentSaving(false);
    }
  }

  async function removeAgent(ag: Agent) {
    if (!window.confirm(`Remove @${ag.mention} from this workflow?`)) return;
    await apiDelete(`/api/workflows/${id}/agents/${ag.id}`);
    setMsg("Agent removed");
    await load();
  }

  async function openHermesSetupGuide() {
    if (!wf?.agents?.length) {
      setMsg("Add agents before syncing Hermes profiles.");
      return;
    }
    setHermesSyncing(true);
    setError("");
    setMsg("");
    try {
      const res = await apiPost<HermesSetupGuide>(
        `/api/workflows/${id}/hermes-profiles/sync`
      );
      setHermesGuide(res);
      setHermesGuideOpen(true);
      const parts = [
        res.created ? `${res.created} created` : "",
        res.updated ? `${res.updated} updated` : "",
        res.platforms_enabled?.length
          ? `channels enabled: ${res.platforms_enabled.join(", ")}`
          : "",
        res.gateways_started ? `${res.gateways_started} gateways running` : "",
        res.gateway_errors ? `${res.gateway_errors} gateway errors` : "",
      ].filter(Boolean);
      setMsg(
        `Hermes profiles synced${parts.length ? ` (${parts.join(", ")})` : ""}. ` +
          "Tokens written, channels enabled in config.yaml, gateways started."
      );
      if (!res.ok) {
        const detail =
          (res.agents || [])
            .filter((a) => a.error || a.gateway?.status === "error")
            .map((a) => `${a.role_id}: ${a.error || a.gateway?.error || "error"}`)
            .join("; ") || "Some agents failed — see dialog";
        setError(detail);
      }
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setHermesSyncing(false);
    }
  }

  function agentEngineLabel(ag: Agent): string {
    if (ag.kind === "coding") {
      return ag.coding_backend || wf?.coding_default || "—";
    }
    return ag.reasoning_engine || "(workflow default)";
  }

  async function removeChat(chat: Chat) {
    if (!window.confirm(`Remove ${chat.label} (${chat.platform}) and its channels?`)) return;
    await apiDelete(`/api/workflows/${id}/chats/${chat.id}`);
    setMsg("Chat removed");
    await load();
  }

  async function testChatConnection(form: ChatConnectionForm) {
    if (!form.id) {
      return { ok: false, message: "Save the connection before testing" };
    }
    const fields = fieldsByPlatform[form.platform] || [];
    const { config, secrets } = splitFormValues(fields, form.values);
    const res = await apiPost<{ ok: boolean; message: string }>(
      `/api/workflows/${id}/chats/${form.id}/test`,
      {
        platform: form.platform,
        config,
        secrets,
      }
    );
    return { ok: !!res.ok, message: res.message || (res.ok ? "OK" : "Failed") };
  }

  async function saveAsTemplate() {
    await apiPost(`/api/workflows/${id}/save-template`, {
      name: tplName || `${wf?.name} template`,
      description: wf?.description || "",
    });
    setMsg("Saved as template");
  }

  function connectionStatus(chat: Chat): string {
    const fields = chat.connection_fields || fieldsByPlatform[chat.platform] || [];
    const secretFields = fields.filter((f) => f.kind === "secret");
    if (!secretFields.length) return "Configured";
    const allStored = secretFields.every((f) => chat.stored_secrets?.[f.key]);
    return allStored ? "Connected" : "Needs credentials";
  }

  if (!wf) {
    return <div>{error || "Loading…"}</div>;
  }

  return (
    <div>
      <p>
        <Link href="/workflows">← Workflows</Link>
      </p>
      <h1>{wf.name}</h1>
      {error && <div className="panel error">{error}</div>}
      {msg && <div className="panel">{msg}</div>}

      <div className="panel">
        <h2>Core</h2>
        <label>
          Name{" "}
          <input value={wf.name} onChange={(e) => setWf({ ...wf, name: e.target.value })} />
        </label>
        <br />
        <label>
          Reasoning engine{" "}
          <select
            value={wf.reasoning_engine}
            onChange={(e) => setWf({ ...wf, reasoning_engine: e.target.value })}
          >
            {ENGINES.map((x) => (
              <option key={x} value={x}>
                {x}
              </option>
            ))}
          </select>
        </label>
        <br />
        <label>
          Coding default{" "}
          <select
            value={wf.coding_default}
            onChange={(e) => setWf({ ...wf, coding_default: e.target.value })}
          >
            {ENGINES.map((x) => (
              <option key={x} value={x}>
                {x}
              </option>
            ))}
          </select>
        </label>
        <br />
        <button type="button" onClick={saveCore} style={{ marginTop: "0.75rem" }}>
          Save
        </button>
        <span className="muted" style={{ marginLeft: "1rem" }}>
          Active: {wf.is_active ? "yes" : "no"}
        </span>
      </div>

      <div className="panel" style={{ marginTop: "1rem" }}>
        <h2>Memory</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          Shared task memory for coding agents in this workflow.
        </p>
        <label>
          Provider{" "}
          <select
            value={wf.memory_provider}
            onChange={(e) => setWf({ ...wf, memory_provider: e.target.value })}
          >
            <option value="hermes">hermes</option>
            <option value="obsidian">obsidian</option>
            <option value="none">none</option>
          </select>
        </label>
        {wf.memory_provider === "obsidian" && (
          <>
            <br />
            <label>
              Vault path{" "}
              <input
                style={{ width: "100%" }}
                value={String(wf.memory_config?.vault_path || "")}
                onChange={(e) =>
                  setWf({
                    ...wf,
                    memory_config: { ...wf.memory_config, vault_path: e.target.value },
                  })
                }
              />
            </label>
          </>
        )}
        <br />
        <button type="button" onClick={saveMemory} style={{ marginTop: "0.75rem" }}>
          Save memory
        </button>
      </div>

      <div className="panel" style={{ marginTop: "1rem" }}>
        <div className="panel-toolbar">
          <div>
            <h2 style={{ margin: 0 }}>Tracking</h2>
            <p className="muted" style={{ margin: "0.35rem 0 0" }}>
              Ticket trackers (Jira or Plane). Only one connection is active for sync at a time.
            </p>
          </div>
          <button type="button" onClick={openAddTrackingDialog}>
            Add tracking connection
          </button>
        </div>
        {trackingList().length === 0 ? (
          <p className="muted">No tracking connection yet. Add Jira or Plane to sync tickets.</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Label</th>
                <th>Provider</th>
                <th>Active</th>
                <th>Status</th>
                <th style={{ textAlign: "right" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {trackingList().map((t) => (
                <tr key={t.id || t.label}>
                  <td>{t.label || "—"}</td>
                  <td>
                    <span className="badge">{t.provider}</span>
                  </td>
                  <td className="muted">{t.is_active ? "Yes" : "—"}</td>
                  <td className="muted">{trackingStatus(t)}</td>
                  <td>
                    <div className="actions">
                      {!t.is_active && (
                        <button
                          type="button"
                          onClick={() => activateTracking(t)}
                          title="Use this tracker for ticket sync"
                        >
                          Set active
                        </button>
                      )}
                      <button
                        type="button"
                        className="icon-btn"
                        aria-label={`Edit ${t.label}`}
                        title="Edit"
                        onClick={() => openEditTrackingDialog(t)}
                      >
                        <IconEdit />
                      </button>
                      <button
                        type="button"
                        className="icon-btn danger"
                        aria-label={`Remove ${t.label}`}
                        title="Remove"
                        onClick={() => removeTracking(t)}
                      >
                        <IconTrash />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel" style={{ marginTop: "1rem" }}>
        <div className="panel-toolbar">
          <div>
            <h2 style={{ margin: 0 }}>Chat apps</h2>
            <p className="muted" style={{ margin: "0.35rem 0 0" }}>
              Connections and topic channels are configured in the dialog (Connection / Channels tabs).
            </p>
          </div>
          <button type="button" onClick={openAddChatDialog}>
            Add chat connection
          </button>
        </div>
        {wf.chats.length === 0 ? (
          <p className="muted">No chat apps yet. Add a connection to get started.</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Label</th>
                <th>Platform</th>
                <th>Channels</th>
                <th>Status</th>
                <th style={{ textAlign: "right" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {wf.chats.map((chat) => {
                const channelCount = wf.channels.filter((c) => c.chat_id === chat.id).length;
                return (
                  <tr key={chat.id}>
                    <td>{chat.label || "—"}</td>
                    <td>
                      <span className="badge">{chat.platform}</span>
                    </td>
                    <td className="muted">{channelCount}</td>
                    <td className="muted">{connectionStatus(chat)}</td>
                    <td>
                      <div className="actions">
                        <button
                          type="button"
                          className="icon-btn"
                          aria-label={`Edit ${chat.label}`}
                          title="Edit"
                          onClick={() => openEditChatDialog(chat)}
                        >
                          <IconEdit />
                        </button>
                        <button
                          type="button"
                          className="icon-btn danger"
                          aria-label={`Remove ${chat.label}`}
                          title="Remove"
                          onClick={() => removeChat(chat)}
                        >
                          <IconTrash />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <ChatConnectionDialog
        open={chatDialogOpen}
        title={chatDialogMode === "add" ? "Add chat connection" : "Edit chat connection"}
        platforms={platforms}
        fieldsByPlatform={fieldsByPlatform}
        initial={chatDialogForm}
        saving={chatSaving}
        suggestLabel={suggestChatLabel}
        onTestConnection={testChatConnection}
        onClose={() => setChatDialogOpen(false)}
        onSubmit={submitChatDialog}
      />

      <TrackingConnectionDialog
        open={trackingDialogOpen}
        title={
          trackingDialogMode === "add" ? "Add tracking connection" : "Edit tracking connection"
        }
        providers={trackingProviders}
        fieldsByProvider={fieldsByTracking}
        initial={trackingDialogForm}
        saving={trackingSaving}
        suggestLabel={suggestTrackingLabel}
        onTestConnection={testTrackingConnection}
        onClose={() => setTrackingDialogOpen(false)}
        onSubmit={submitTrackingDialog}
      />

      <div className="panel" style={{ marginTop: "1rem" }}>
        <div className="panel-toolbar">
          <div>
            <h2 style={{ margin: 0 }}>Agents / engines</h2>
            <p className="muted" style={{ margin: "0.35rem 0 0" }}>
              Assign personas from the{" "}
              <Link href="/agents">Personas</Link> page. Hermes profiles use short names like{" "}
              <code>omc-pm</code>. <strong>Sync Hermes profiles</strong> copies portal personas into
              <code>SOUL.md</code>, updates descriptions, writes OMC bot tokens + allow-all, enables
              Telegram/Discord in each profile&apos;s <code>config.yaml</code>, stops the OMC bridge
              if it is running, and starts Hermes gateways (with Windows login auto-start).
            </p>
          </div>
          <div className="panel-toolbar-actions">
            <button
              type="button"
              onClick={openHermesSetupGuide}
              disabled={hermesSyncing || !wf.agents.length}
              title="Sync SOUL.md + description, write tokens, enable channels, stop OMC bridge, start gateways"
            >
              {hermesSyncing ? "Syncing…" : "Sync Hermes profiles"}
            </button>
            <button type="button" onClick={openAddAgentDialog}>
              Add agent
            </button>
          </div>
        </div>
        {wf.agents.length === 0 ? (
          <p className="muted">No agents yet. Add a persona to this workflow.</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Role</th>
                <th>Mention</th>
                <th>Kind</th>
                <th>Engine</th>
                <th>Hermes profile</th>
                <th>Gateways</th>
                <th style={{ textAlign: "right" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {wf.agents.map((ag) => (
                <tr key={ag.id}>
                  <td>
                    {ag.display_name}
                    <div className="muted" style={{ fontSize: "0.8rem" }}>
                      {ag.role_id}
                    </div>
                  </td>
                  <td>@{ag.mention}</td>
                  <td>
                    <span className="badge">{ag.kind}</span>
                  </td>
                  <td className="muted">{agentEngineLabel(ag)}</td>
                  <td className="muted" style={{ fontSize: "0.8rem", maxWidth: "14rem", wordBreak: "break-all" }}>
                    {ag.hermes_profile || `omc-${ag.role_id}`}
                  </td>
                  <td className="muted" style={{ fontSize: "0.8rem" }}>
                    {Object.entries(ag.gateways || {})
                      .filter(([, g]) => g.enabled || g.configured)
                      .map(([p]) => p)
                      .join(", ") || "—"}
                  </td>
                  <td>
                    <div className="actions">
                      <button
                        type="button"
                        className="icon-btn"
                        aria-label={`Edit @${ag.mention}`}
                        title="Edit"
                        onClick={() => openEditAgentDialog(ag)}
                      >
                        <IconEdit />
                      </button>
                      <button
                        type="button"
                        className="icon-btn danger"
                        aria-label={`Remove @${ag.mention}`}
                        title="Remove"
                        onClick={() => removeAgent(ag)}
                      >
                        <IconTrash />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <AgentDialog
        open={agentDialogOpen}
        title={agentDialogMode === "add" ? "Add agent" : "Edit agent"}
        mode={agentDialogMode}
        workflowId={id}
        engines={ENGINES}
        platforms={platforms}
        personas={availablePersonas()}
        initial={agentDialogForm}
        saving={agentSaving}
        onClose={() => setAgentDialogOpen(false)}
        onSubmit={submitAgentDialog}
      />

      <HermesSetupDialog
        open={hermesGuideOpen}
        guide={hermesGuide}
        onClose={() => setHermesGuideOpen(false)}
      />

      <div className="panel" style={{ marginTop: "1rem" }}>
        <h2>MCP enabled</h2>
        {wf.mcp_servers.length === 0 ? (
          <p className="muted">
            None. Enable from <Link href="/mcp">MCP Marketplace</Link>.
          </p>
        ) : (
          <ul>
            {wf.mcp_servers.map((m) => (
              <li key={m.catalog_id}>
                {m.name} {m.enabled ? "" : "(disabled)"}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="panel" style={{ marginTop: "1rem" }}>
        <h2>Cron</h2>
        {wf.cron_jobs.length === 0 ? (
          <p className="muted">No jobs</p>
        ) : (
          <ul>
            {wf.cron_jobs.map((j) => (
              <li key={j.id}>
                <code>{j.cron_expr}</code> — {j.name} → @{j.agent_role} in #{j.channel_name}{" "}
                {j.enabled ? "" : "(off)"}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="panel" style={{ marginTop: "1rem" }}>
        <h2>Save as template</h2>
        <input
          value={tplName}
          onChange={(e) => setTplName(e.target.value)}
          placeholder="Template name"
        />
        <button type="button" onClick={saveAsTemplate}>
          Save template
        </button>
      </div>
    </div>
  );
}
