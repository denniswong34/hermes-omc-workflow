#!/usr/bin/env bash
# Stop the OMC Agentic OS portal (API + Next.js UI).
# Usage: ./scripts/stop-portal.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$REPO_ROOT/.run"
API_PID_FILE="$RUN_DIR/api.pid"
UI_PID_FILE="$RUN_DIR/ui.pid"

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

stop_pid_file() {
  local name="$1" pid_file="$2"
  if [[ ! -f "$pid_file" ]]; then
    echo "$name: no pid file"
    return 0
  fi
  local pid
  pid="$(tr -d '[:space:]' < "$pid_file")"
  if [[ -z "$pid" ]]; then
    rm -f "$pid_file"
    echo "$name: empty pid file removed"
    return 0
  fi
  if kill -0 "$pid" 2>/dev/null; then
    echo "$name: stopping pid $pid..."
    # Kill process group children when possible (npm → node)
    pkill -P "$pid" 2>/dev/null || true
    kill "$pid" 2>/dev/null || true
    sleep 0.4
    kill -9 "$pid" 2>/dev/null || true
    echo "$name: stopped"
  else
    echo "$name: pid $pid not running"
  fi
  rm -f "$pid_file"
}

free_port() {
  local name="$1" port="$2"
  local pids=""
  if command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  elif command -v ss >/dev/null 2>&1; then
    pids="$(ss -ltnp "sport = :$port" 2>/dev/null | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | sort -u || true)"
  fi
  if [[ -z "$pids" ]]; then
    echo "$name: port $port free"
    return 0
  fi
  for pid in $pids; do
    echo "$name: freeing port $port (pid $pid)..."
    kill "$pid" 2>/dev/null || true
    sleep 0.2
    kill -9 "$pid" 2>/dev/null || true
  done
}

load_dotenv "$REPO_ROOT/.env"
OMC_API_PORT="${OMC_API_PORT:-8787}"
OMC_UI_PORT="${OMC_UI_PORT:-3000}"

echo "Stopping OMC Agent Portal..."
stop_pid_file "UI" "$UI_PID_FILE"
stop_pid_file "API" "$API_PID_FILE"
free_port "UI" "$OMC_UI_PORT"
free_port "API" "$OMC_API_PORT"
echo "Done."
