#!/usr/bin/env bash
# SDLC E2E runner — packages and executes the Discord E2E test suite.
# Usage: export DISCORD_BOT_TOKEN="..." && ./scripts/run-e2e.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

export OMC_CONFIG="$SCRIPT_DIR/tests/fixtures/omc.e2e.yaml"
export OMC_OBSIDIAN_VAULT="$SCRIPT_DIR/tests/fixtures/e2e-vault"
export OMC_E2E_TASK_MAP="$SCRIPT_DIR/tests/fixtures/e2e-task_map.json"
export OMC_E2E="1"
export OMC_WORKSPACE="$SCRIPT_DIR"

cd "$SCRIPT_DIR"
python -m pip install -q -r requirements.txt fastapi uvicorn pyyaml pydantic aiohttp apscheduler discord.py 2>/dev/null
exec python tests/sdlc_discord_e2e.py
