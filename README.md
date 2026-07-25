# Hermes OMC Workflow Bridge

**One Man Company (OMC)** — Boss talks in SaaS **topic channels** and `@mentions` agents.
Agents hand off **in the same channel**. Tickets live in Plane / Jira. Shared memory lives in an **Obsidian vault**. Configure everything in **Agentic OS**.

## Topic rooms (defaults)

| Channel | Purpose | Who you can @ |
|---------|---------|----------------|
| `#product` | Roadmap / ideas | `@PM` `@SA` |
| `#engineering` | Spec → code → QA → deploy | `@PM` `@SA` `@Coder` `@QA` `@DevOps` (+ coding aliases) |
| `#marketing` | Launch / GTM | `@PM` `@Marketing` |
| `#support` | Customer bugs | `@PM` `@SA` `@Coder` `@QA` |
| `#standup` | Digests | `@Standup` |

Set channel IDs in [`config/omc.yaml`](config/omc.yaml).

## Coding backends

| Mention | Backend |
|---------|---------|
| `@Coder` | `coding.default` (usually Hermes) |
| `@Hermes` | Hermes CLI |
| `@Claude` | Claude Code CLI |
| `@Cursor` | Cursor `agent` CLI |
| `@OpenCode` | OpenCode CLI |
| `@Codex` | OpenAI Codex CLI (`codex exec`) |

```bash
export OMC_WORKSPACE=/path/to/your/saas/repo
```

## Obsidian shared memory

All agents/backends read and write the same TASK notes so switching `@Claude` → `@Codex` keeps context.

```yaml
memory:
  provider: obsidian
  obsidian:
    vault_path: "${OMC_OBSIDIAN_VAULT}"
    root_folder: OMC
```

```bash
export OMC_OBSIDIAN_VAULT=/path/to/your/obsidian/vault
```

Vault layout (auto-created):

```text
{vault}/OMC/tasks/TASK-014.md
{vault}/OMC/handoffs/
{vault}/OMC/daily/
```

## Agentic OS (control plane)

Web UI + API to edit config, agents, secrets, memory, and a read-only Kanban board.

```bash
pip install -r requirements.txt

# API (http://127.0.0.1:8787)
python -m apps.api.main

# UI (http://127.0.0.1:3000)
cd apps/agentic-os && npm install && npm run dev
```

Pages: Overview, Connections, Agents, Memory, Kanban.

Optional: `NEXT_PUBLIC_API_BASE=http://127.0.0.1:8787`

## Quick start (bridge)

```bash
pip install -r requirements.txt

# 1. Paste Discord topic channel IDs into config/omc.yaml
# 2. DISCORD_BOT_TOKEN in ~/.hermes/.env
# 3. OMC_WORKSPACE + OMC_OBSIDIAN_VAULT
python bridge.py
```

## Tickets

```yaml
tickets:
  provider: none   # or plane | jira
```

## Architecture

```
Discord / Zulip / Slack
        │
        ▼
  AgentRouter ──► CodingBackends (hermes/claude/cursor/opencode/codex)
        │
        ├──► ObsidianMemoryStore  (shared TASK notes)
        └──► TicketTracker        (Plane / Jira / none)

Agentic OS (Next.js) ──► FastAPI ──► omc.yaml / agents/*.md / vault / task_map
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

## Roadmap

- [x] Topic channels + in-channel @mentions
- [x] Pluggable tickets (Plane / Jira / none)
- [x] Pluggable coding backends (+ Codex)
- [x] Obsidian shared memory
- [x] Agentic OS MVP (config / agents / memory / kanban)
- [ ] Kanban drag-drop → ticket transitions
- [ ] Bridge process manager in Agentic OS
- [ ] Zulip / Slack adapter completion
