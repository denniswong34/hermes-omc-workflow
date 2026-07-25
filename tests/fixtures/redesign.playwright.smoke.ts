/**
 * Playwright-oriented smoke checklist (run against live API + UI).
 *
 * Automated unit coverage: python -m tests.test_redesign_smoke -v
 *
 * Manual / Playwright MCP:
 * 1. Clone SDLC Workflow → second company
 * 2. Activate both with distinct channel IDs
 * 3. Switch PM engine override to claude
 * 4. Enable Filesystem MCP on a workflow
 * 5. Confirm cron jobs listed on workflow detail
 */

export const REDESIGN_SMOKE = [
  "GET /api/templates includes tpl-sdlc",
  "POST /api/workflows/clone creates editable instance",
  "POST /api/workflows/{id}/activate rejects shared channel",
  "PATCH agent reasoning_engine=claude",
  "POST /api/workflows/{id}/mcp enable mcp-filesystem",
  "GET /api/workflows/{id}/cron lists seeded job",
];
