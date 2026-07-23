# OMC Cross-Agent Handoff Protocol

## Boss rule

- The human Boss talks **only** in `#pm`.
- Other agents never address the Boss directly; escalate via `@pm:`.

## @mention syntax

To talk to another agent, put the mention at the **start of a line**:

```
@sa: Please produce a spec for TASK-001 covering auth and rate limits.
```

Rules:

1. One `@channel:` handoff per line.
2. Only mention channels listed in your CROSS-CHANNEL RULES.
3. Always include the `TASK-NNN` id when the work has a ticket.
4. Keep the handoff message self-contained (goal, constraints, links, status keyword).

## TASK-NNN convention

- Format: `TASK-001`, `TASK-002`, …
- PM (or SA when creating analysis work) owns ticket creation.
- Every subsequent message about that work must reference the same `TASK-NNN`.

## Standard handoff chain

1. **Boss → PM** — goal, priority, constraints.
2. **PM → SA** — `@sa:` with problem statement; status `todo`.
3. **SA → Coder** — `@coder:` with spec + acceptance criteria; status `in progress`.
4. **SA → QA** — `@qa:` with acceptance criteria (can be parallel to coding).
5. **Coder → QA** — `@qa:` with build/PR notes; status `in review` / `qa review`.
6. **QA pass → DevOps** — `@devops:` with `qa verified` / `ready to deploy`.
7. **QA fail → Coder/SA** — `@coder:` or `@sa:` with `qa failed` + defect list.
8. **DevOps → PM** — `@pm:` with `deployed` + version/env.
9. **PM → Marketing** (optional) — `@marketing:` after `deployed` / when Boss wants GTM.
10. **PM → Boss** — status `done` with concise outcome.

## Escalation

- Blocked on requirements → `@pm:`
- Spec gap during coding → `@sa:`
- Environment/deploy blocker → `@devops:`
- Product priority conflict → `@pm:` only (never invent priority)

## Response style

- Be concise and actionable.
- Lead with TASK id and status keyword when changing stage.
- Prefer bullet lists for specs, defects, and deploy notes.
