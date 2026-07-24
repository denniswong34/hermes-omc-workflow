# Hermes OMC Workflow Bridge

**One Man Company (OMC)** — Boss talks in SaaS **topic channels** and `@mentions` agents.
Agents hand off to each other **in the same channel**. Tickets live in Plane / Jira.

## Topic rooms (defaults)

| Channel | Purpose | Who you can @ |
|---------|---------|----------------|
| `#product` | Roadmap / ideas | `@PM` `@SA` |
| `#engineering` | Spec → code → QA → deploy | `@PM` `@SA` `@Coder` `@QA` `@DevOps` (+ coding aliases) |
| `#marketing` | Launch / GTM | `@PM` `@Marketing` |
| `#support` | Customer bugs | `@PM` `@SA` `@Coder` `@QA` |
| `#standup` | Digests | `@Standup` |

Set Discord (or Slack/Zulip) channel IDs in [`config/omc.yaml`](config/omc.yaml).

## How conversation works

```
#engineering
You:  @PM Please help me start to implement login for saas
PM:   **[@PM]** Creating TASK-014 … Status: todo
      @SA Please complete analysis/spec for login …
SA:   **[@SA]** Spec ready. Status: in progress
      @Coder Follow the spec and implement …
Coder:**[@Coder]** … Status: in review
      @QA Ready for qa review …
```

- **Trigger:** explicit `@Agent` only (no silent auto-replies).
- **Handoffs:** same channel via `@SA:` / `@Coder:` lines — not separate role channels.
- **Tracking:** status keywords update Plane/Jira/`none` TASK map.

## Coding backends

In `#engineering` / `#support`:

| Mention | Backend |
|---------|---------|
| `@Coder` | `coding.default` (usually Hermes) |
| `@Hermes` | Hermes CLI |
| `@Claude` | Claude Code CLI |
| `@Cursor` | Cursor `agent` CLI |
| `@OpenCode` | OpenCode CLI |

```yaml
coding:
  default: hermes
  workspace: "${OMC_WORKSPACE}"
```

```bash
export OMC_WORKSPACE=/path/to/your/saas/repo
```

Install the CLI you want on `PATH`. Missing tools return a clear error in-channel.

## Quick start

```bash
pip install -r requirements.txt

# 1. Create topic channels; paste IDs into config/omc.yaml
# 2. DISCORD_BOT_TOKEN in ~/.hermes/.env
# 3. Optional: OMC_WORKSPACE, Plane/Jira env vars
python bridge.py
```

```bash
OMC_CONFIG=config/omc.yaml OMC_ADAPTER=discord OMC_WORKSPACE=$PWD python bridge.py
```

## Tickets

```yaml
tickets:
  provider: none   # or plane | jira
```

See `config/omc.yaml` for Plane/Jira `status_map` and env placeholders (`PLANE_*`, `JIRA_*`).

## Architecture

```
Boss message in #engineering
       │
       ▼
ChannelAdapter (Discord / Zulip / Slack)
       │
       ▼
AgentRouter
  • Resolve topic from channel id
  • Parse @PM / @SA / @Coder …
  • Persona from agents/*.md
  • CodingBackend for coder aliases
  • Same-channel handoff chain
  • TicketTracker (Plane / Jira / none)
```

Personas: [`agents/`](agents/) (+ [`agents/_shared/`](agents/_shared/)).

## Agent roster

| Mention | Role |
|---------|------|
| `@PM` | Product Manager |
| `@SA` | Systems Analyst / Architect |
| `@Coder` | Software Engineer (default coding backend) |
| `@QA` | QA |
| `@DevOps` | Release / deploy |
| `@Marketing` | GTM |
| `@Standup` | Digest bot |
| `@Hermes` `@Claude` `@Cursor` `@OpenCode` | Direct coding CLIs |

## Roadmap

- [x] Topic channels + in-channel @mentions
- [x] Pluggable tickets (Plane / Jira / none)
- [x] Pluggable coding backends (Hermes / Claude / Cursor / OpenCode)
- [ ] Zulip end-to-end verification
- [ ] Slack adapter completion
