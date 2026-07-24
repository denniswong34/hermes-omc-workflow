# OMC Cross-Agent Handoff Protocol (Topic Channels)

## Topic rooms (SaaS)

Work happens in shared topic channels — not one channel per role:

| Topic | Use for |
|-------|---------|
| `#product` | Roadmap, ideas, prioritization |
| `#engineering` | Spec → code → QA → deploy |
| `#marketing` | Launch / GTM |
| `#support` | Customer issues and bugs |
| `#standup` | Digests / status recap |

The Boss (human) may speak in any topic. Always `@mention` the agent you want.

## @mention syntax (same channel)

To talk to an agent, mention them in the message (anywhere, but handoffs should start a line):

```
@PM Please help me start to implement login for saas
```

Agent-to-agent handoff — put the mention at the **start of a line**:

```
@SA: Please produce a spec for TASK-001 covering auth and rate limits.
```

Rules:

1. Stay in the current topic channel. Never ask people to “go to #pm”.
2. One primary handoff `@role:` per line.
3. Only mention agents listed in your IN-CHANNEL RULES for this topic.
4. Always include `TASK-NNN` when the work has a ticket.
5. Keep handoffs self-contained (goal, constraints, status keyword).

## Coding agents

In `#engineering` / `#support` you may also ping implementation backends:

- `@Coder` — default coding backend (see config `coding.default`)
- `@Hermes` / `@Claude` / `@Cursor` / `@OpenCode` — force a specific CLI

Prefer `@Coder` in the company flow; use vendor aliases when you need that tool.

## TASK-NNN convention

- Format: `TASK-001`, `TASK-002`, …
- PM (or SA when allowed) owns ticket creation; status lives in Jira/Plane.
- Every follow-up about that work must reference the same `TASK-NNN`.

## Standard handoff chain (engineering)

1. Boss `@PM` — goal, priority, constraints.
2. PM `@SA:` — problem statement; status `todo`.
3. SA `@Coder:` — spec + acceptance criteria; status `in progress`.
4. SA `@QA:` — acceptance criteria (can be parallel).
5. Coder `@QA:` — build/PR notes; status `in review` / `qa review`.
6. QA `@DevOps:` — `qa verified` / `ready to deploy` (or `@Coder:` / `@SA:` on `qa failed`).
7. DevOps `@PM:` — `deployed` + version/env.
8. PM may `@Marketing:` in `#marketing` after ship (or Boss asks there).
9. PM closes with Boss — status `done`.

## Support chain

1. Boss `@PM` in `#support` with customer symptom.
2. PM `@SA:` triage → `@Coder:` fix → `@QA:` verify.
3. Keep product roadmap talk in `#product`, not `#support`.

## Escalation

- Blocked on requirements → `@PM`
- Spec gap during coding → `@SA`
- Deploy/env blocker → `@DevOps`
- Priority conflict → `@PM` only

## Response style

- Be concise and actionable.
- Lead with TASK id and status keyword when changing stage.
- Prefer bullet lists for specs, defects, and deploy notes.
