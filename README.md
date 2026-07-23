# Hermes OMC Workflow Bridge

**One Man Company (OMC) SDLC automation** — Boss talks to the PM agent; PM orchestrates SA, Coder, QA, DevOps, and Marketing via cross-channel `@mentions`.

## Company flow

```
Boss (human)
  └─ #pm  (Product Manager)
        ├─ @sa:        → #sa     (Systems Analyst / Architect)
        │                 ├─ @coder: → #coder
        │                 └─ @qa:    → #qa
        ├─ @devops:    → #devops (Release / Deploy)
        └─ @marketing: → #marketing (GTM after deploy)
```

Happy path statuses:

`backlog` → `todo` → `in progress` → `in review` → `qa review` → `qa verified` → `ready to deploy` → `deployed` → `done`

## Agent roster

| Channel | Role | Boss-facing |
|---------|------|-------------|
| `#pm` | Product Manager | Yes — only entry point |
| `#sa` | Systems Analyst / Solution Architect | No |
| `#coder` | Software Engineer | No |
| `#qa` | QA Engineer | No |
| `#devops` | DevOps / Release | No |
| `#marketing` | Go-to-market | No |

Personas live in version-controlled markdown under [`agents/`](agents/) (plus shared SDLC + handoff rules in `agents/_shared/`).

## Quick start

```bash
pip install -r requirements.txt

# 1. Create a Discord #devops channel and set its ID in config/omc.yaml
# 2. Ensure DISCORD_BOT_TOKEN is in ~/.hermes/.env
# 3. Run
python bridge.py

# Optional overrides
OMC_CONFIG=config/omc.yaml OMC_ADAPTER=discord python bridge.py
```

## Configuration

Default config: [`config/omc.yaml`](config/omc.yaml) (override with `OMC_CONFIG`).

- **`channels`** — role → Discord channel id (fill in `devops`)
- **`routes`** — who may `@mention` whom
- **`status_authority`** — which roles may move the ticket board
- **`tickets.provider`** — `none` | `plane` | `jira`

Agent prompts are built at runtime from `agents/_shared/*.md` + `agents/{role}.md`.

## Cross-agent handoffs

Agents start a line with `@channel: message`. The bridge forwards it automatically.

```
@sa: TASK-001 — produce a spec for password reset. Status: todo
```

Example chain:

1. Boss → `#pm`: “Add password reset”
2. PM → `@sa:` with `todo`
3. SA → `@coder:` + `@qa:` with spec / acceptance criteria
4. Coder → `@qa:` with `in review`
5. QA → `@devops:` with `qa verified` / `ready to deploy`
6. DevOps → `@pm:` with `deployed`
7. PM → Boss (`done`) and optionally `@marketing:`

## Ticket tracking (pluggable)

Set in `config/omc.yaml`:

```yaml
tickets:
  provider: none   # or plane | jira
```

### none

Local `TASK-NNN` ids only (stored under `~/.hermes/omc/task_map.json`). No external API.

### Plane.so

```yaml
tickets:
  provider: plane
  plane:
    base_url: "${PLANE_BASE_URL}"
    workspace: "${PLANE_WORKSPACE}"
    project_id: "${PLANE_PROJECT_ID}"
    api_key: "${PLANE_API_KEY}"
    status_map:
      todo: "<plane-state-uuid>"
      in_progress: "<uuid>"
      # ... see config/omc.yaml for full keys
```

Env vars: `PLANE_BASE_URL`, `PLANE_WORKSPACE`, `PLANE_PROJECT_ID`, `PLANE_API_KEY`.

### Jira Cloud

```yaml
tickets:
  provider: jira
  jira:
    base_url: "${JIRA_BASE_URL}"
    email: "${JIRA_EMAIL}"
    api_token: "${JIRA_API_TOKEN}"
    project_key: "${JIRA_PROJECT_KEY}"
    status_map:
      todo: "To Do"
      in_progress: "In Progress"
      # ...
```

Env vars: `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY`.

Status updates from agent text are applied only if the emitting role is allowed (see `status_authority`).

## Architecture

```
User / Agent message
       │
       ▼
ChannelAdapter (Discord / Zulip / Slack)
       │
       ▼
AgentRouter
  • Load persona from agents/
  • Create / reference TASK-NNN
  • Call hermes CLI
  • Parse @mentions → forward
  • Detect status → TicketTracker
       │
       ├─ PlaneTracker
       ├─ JiraTracker
       └─ NullTracker
```

## Discord channel checklist

1. `#pm`, `#sa`, `#coder`, `#qa`, `#marketing` (existing IDs in config)
2. Create `#devops` and paste its channel ID into `config/omc.yaml` → `channels.devops`
3. Invite the bot to all agent channels with message content intent enabled

## Adapter pattern

Implement `ChannelAdapter` in `adapters/`, register in `bridge.py`, set `OMC_ADAPTER`.

## Roadmap

- [x] Discord adapter
- [x] In-repo agent personas + SDLC handoffs
- [x] Pluggable tickets (Plane / Jira / none)
- [ ] Zulip adapter (implemented; verify end-to-end)
- [ ] Slack adapter
- [ ] Telegram adapter
