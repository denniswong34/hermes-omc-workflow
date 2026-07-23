# OMC SDLC — Shared Stage Definitions

This One Man Company follows a standard software development lifecycle.
Every agent must use these **exact status keywords** when announcing a stage change
(so ticket boards stay in sync).

## Canonical stages

| Keyword | Meaning | Typical owner |
|---------|---------|---------------|
| `backlog` | Idea captured, not yet prioritized | PM |
| `todo` | Accepted and ready to start | PM / SA |
| `in progress` | Active design or implementation | SA / Coder |
| `in review` | Implementation submitted for review | Coder |
| `qa review` | Formal QA testing underway | QA |
| `qa failed` | Defects found; rework required | QA |
| `qa verified` | Acceptance criteria met | QA |
| `ready to deploy` | Approved for release packaging | QA / DevOps |
| `deployed` | Live in target environment | DevOps |
| `done` | Boss notified; work closed | PM |
| `cancelled` | Abandoned / won't do | PM |

## Happy path

`backlog` → `todo` → `in progress` → `in review` → `qa review` → `qa verified` → `ready to deploy` → `deployed` → `done`

## Rework path

`qa failed` → `@coder:` or `@sa:` → `in progress` → `in review` → `qa review` …

## Expected artifacts by stage

| Stage | Artifact |
|-------|----------|
| `todo` | Clear problem statement / user story (PM) |
| `in progress` (SA) | Spec: scope, constraints, data model, APIs, risks |
| `in progress` (Coder) | Working code + brief notes on how to run |
| `in review` | Testable build / PR / change summary |
| `qa review` | Test plan executed against acceptance criteria |
| `qa verified` | Pass report + residual risks |
| `ready to deploy` | Deploy checklist / version tag |
| `deployed` | Environment, version, rollback note |
| `done` | Boss summary + optional Marketing handoff |

## Status keyword authority (who may move the board)

| Role | Allowed status keywords for ticket updates |
|------|--------------------------------------------|
| PM | `backlog`, `todo`, `done`, `cancelled` |
| SA | `todo`, `in progress` |
| Coder | `in progress`, `in review` |
| QA | `qa review`, `qa failed`, `qa verified`, `ready to deploy` |
| DevOps | `ready to deploy`, `deployed` |
| Marketing | _(none — does not update engineering tickets)_ |

Do **not** jump stages (e.g. Coder must never emit `done` or `deployed`).
