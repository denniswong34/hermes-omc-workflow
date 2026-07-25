# Hermes OMC Workflow — Agentic OS

**One Man Company (OMC)** — Boss talks in SaaS topic channels and `@mentions` agents.
**Agentic OS** is the multi-workflow control plane: templates, reasoning engines, MCP marketplace, memory, tracking, and cron.

## Agentic OS (multi-workflow)

SQLite stores workflows (many may be `is_active`). Secrets stay in `~/.hermes/omc/secrets.env`.

| Layer | Role |
|-------|------|
| Reasoning engine | hermes / claude / cursor / opencode / codex (workflow default + per-agent override) |
| MCP tools | Local marketplace catalog → enable per workflow → agent allowlists |
| Chat hub | Discord / Slack / Zulip / Telegram; `(platform, channel_id)` → one active workflow |
| Memory | hermes (local markdown) or obsidian, namespaced per workflow |
| Tracking | jira / plane / none |
| Cron | APScheduler jobs per active workflow |

### Run control plane

```bash
pip install -r requirements.txt

# API http://127.0.0.1:8787
python -m apps.api.main

# UI http://127.0.0.1:3000
cd apps/agentic-os && npm install && npm run dev
```

UI pages: Overview, **Workflows**, **MCP Marketplace**, Personas, Memory, Kanban, Secrets.

### SDLC template

On first API start the DB seeds system template **SDLC Workflow** and a default company instance.
Clone from the Workflows page; activate multiple companies (soft max 5). Activation fails if a channel ID is already owned by another active workflow.

### Multi-workflow bridge

```bash
python bridge_multi.py
```

Legacy single-YAML bridge:

```bash
python bridge.py
```

### Smoke tests

```bash
python -m tests.test_redesign_smoke -v
```

Covers: SDLC seed, dual-active + channel conflict, engines, Hermes memory, MCP enable, runtime pool.

---

## Topic rooms (SDLC defaults)

| Channel | Purpose | Who you can @ |
|---------|---------|----------------|
| `#product` | Roadmap / ideas | `@PM` `@SA` |
| `#engineering` | Spec → code → QA → deploy | `@PM` `@SA` `@Coder` `@QA` `@DevOps` (+ coding aliases) |
| `#marketing` | Launch / GTM | `@PM` `@Marketing` |
| `#support` | Customer bugs | `@PM` `@SA` `@Coder` `@QA` |
| `#standup` | Digests | `@Standup` |

Configure channel IDs in Agentic OS → Workflow → Channels (or legacy `config/omc.yaml` for `bridge.py`).

## Coding / reasoning engines

| Mention | Backend |
|---------|---------|
| `@Coder` | workflow `coding_default` |
| `@Hermes` / `@Claude` / `@Cursor` / `@OpenCode` / `@Codex` | Named CLI |
| Persona roles | workflow `reasoning_engine` (override per agent) |

```bash
export OMC_WORKSPACE=/path/to/your/saas/repo
```

## Memory

- **hermes** — markdown under `~/.hermes/omc/memory/{workflow_id}/…`
- **obsidian** — vault path + root folder namespaced by workflow id

```bash
export OMC_OBSIDIAN_VAULT=/path/to/your/obsidian/vault
```

## Architecture

```
Discord / Slack / Zulip / Telegram
        │
        ▼
 ChatAdapterHub ──► WorkflowRuntimePool (N active)
        │                 │
        │                 ├── ReasoningEngines + MCP allowlist
        │                 ├── Memory (hermes|obsidian)
        │                 ├── Tickets (jira|plane|none)
        │                 └── Cron jobs
        ▼
Agentic OS (Next.js) ──► FastAPI ──► SQLite + secrets.env
```

## Agent roster

| Mention | Role |
|---------|------|
| `@PM` | Product Manager |
| `@SA` | Systems Analyst / Architect |
| `@Coder` | Default coding backend |
| `@QA` | QA |
| `@DevOps` | Release / deploy |
| `@Marketing` | GTM |
| `@Standup` | Digest bot |
| `@Hermes` `@Claude` `@Cursor` `@OpenCode` `@Codex` | Coding CLIs |

## Env

| Variable | Purpose |
|----------|---------|
| `OMC_DB_PATH` | SQLite path (default `~/.hermes/omc/omc.db`) |
| `OMC_SECRETS_ENV` | Secrets file |
| `NEXT_PUBLIC_API_BASE` | UI → API (default `http://127.0.0.1:8787`) |
| `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` | Slack |
| `TELEGRAM_BOT_TOKEN` | Telegram |
| `OMC_CONFIG` | Legacy YAML for `bridge.py` |
