#!/usr/bin/env bash
# Start the OMC Agentic OS portal (API + Next.js UI).
# Usage: ./scripts/start-portal.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$REPO_ROOT/.run"
UI_DIR="$REPO_ROOT/apps/agentic-os"
API_PID_FILE="$RUN_DIR/api.pid"
UI_PID_FILE="$RUN_DIR/ui.pid"
API_LOG="$RUN_DIR/api.log"
UI_LOG="$RUN_DIR/ui.log"

mkdir -p "$RUN_DIR"

load_dotenv() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="$(echo "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    [[ -z "$line" || "$line" != *=* ]] && continue
    local key="${line%%=*}"
    local value="${line#*=}"
    key="$(echo "$key" | sed -e 's/[[:space:]]*$//')"
    value="$(echo "$value" | sed -e 's/^[[:space:]]*//' -e 's/^["'\'']//' -e 's/["'\'']$//')"
    if [[ -n "$key" && -n "$value" && -z "${!key:-}" ]]; then
      export "$key=$value"
    fi
  done < "$file"
}

pid_alive() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

port_pid() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -n1 || true
  elif command -v ss >/dev/null 2>&1; then
    ss -ltnp "sport = :$port" 2>/dev/null | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | head -n1 || true
  else
    true
  fi
}

assert_free() {
  local name="$1" pid_file="$2" port="$3"
  if [[ -f "$pid_file" ]]; then
    local existing
    existing="$(tr -d '[:space:]' < "$pid_file")"
    if pid_alive "$existing"; then
      echo "$name already running (pid $existing). Use ./scripts/stop-portal.sh first."
      exit 1
    fi
    rm -f "$pid_file"
  fi
  local occupied
  occupied="$(port_pid "$port")"
  if [[ -n "$occupied" ]]; then
    echo "$name port $port already in use by pid $occupied."
    exit 1
  fi
}

load_dotenv "$REPO_ROOT/.env"

OMC_API_HOST="${OMC_API_HOST:-127.0.0.1}"
OMC_API_PORT="${OMC_API_PORT:-8787}"
OMC_UI_PORT="${OMC_UI_PORT:-3000}"
export OMC_API_HOST OMC_API_PORT
export NEXT_PUBLIC_API_BASE="http://${OMC_API_HOST}:${OMC_API_PORT}"

# Keep Next.js .env.local aligned with the API we actually start.
UI_ENV_LOCAL="$UI_DIR/.env.local"
DESIRED_ENV="NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}"
if [[ ! -f "$UI_ENV_LOCAL" ]] || [[ "$(tr -d '\r\n' < "$UI_ENV_LOCAL")" != "$DESIRED_ENV" ]]; then
  printf '%s\n' "$DESIRED_ENV" >"$UI_ENV_LOCAL"
  echo "Updated apps/agentic-os/.env.local → $NEXT_PUBLIC_API_BASE"
fi

PYTHON="${OMC_PYTHON:-python3}"
command -v "$PYTHON" >/dev/null 2>&1 || PYTHON="python"
command -v "$PYTHON" >/dev/null 2>&1 || { echo "Python not found. Set OMC_PYTHON."; exit 1; }

assert_free "API" "$API_PID_FILE" "$OMC_API_PORT"
assert_free "UI" "$UI_PID_FILE" "$OMC_UI_PORT"

if [[ ! -d "$UI_DIR/node_modules" ]]; then
  echo "Installing UI dependencies..."
  (cd "$UI_DIR" && npm install)
fi

echo "Starting API on $NEXT_PUBLIC_API_BASE ..."
(
  cd "$REPO_ROOT"
  nohup "$PYTHON" -m apps.api.main >>"$API_LOG" 2>&1 &
  echo $! >"$API_PID_FILE"
)

echo "Starting UI on http://127.0.0.1:${OMC_UI_PORT} ..."
(
  cd "$UI_DIR"
  nohup npm run dev -- -p "$OMC_UI_PORT" >>"$UI_LOG" 2>&1 &
  echo $! >"$UI_PID_FILE"
)

API_PID="$(tr -d '[:space:]' < "$API_PID_FILE")"
UI_PID="$(tr -d '[:space:]' < "$UI_PID_FILE")"

echo
echo "OMC Agent Portal started"
echo "  API  $NEXT_PUBLIC_API_BASE   (pid $API_PID, log $API_LOG)"
echo "  UI   http://127.0.0.1:${OMC_UI_PORT}  (pid $UI_PID, log $UI_LOG)"
echo
echo "Stop with: ./scripts/stop-portal.sh"
