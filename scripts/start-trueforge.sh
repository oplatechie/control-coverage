#!/usr/bin/env bash
# Start a TrueForge instance whose state lives inside this repo (.trueforge/, git-ignored).
set -euo pipefail
cd "$(dirname "$0")/.."
# read only what this script needs; never execute .env as shell code
PORT_FROM_ENV=$( [ -f .env ] && grep -E '^TRUEFORGE_PORT=' .env | head -1 | cut -d= -f2- | tr -d '[:space:]"' || true)
TRUEFORGE_PORT="${PORT_FROM_ENV:-8791}"
mkdir -p .trueforge
export SQLITE_PATH="$PWD/.trueforge/db.sqlite"
export PORT="${TRUEFORGE_PORT:-8791}"
# controls-mcp runs on this machine; allow only local hosts, keep the outbound guard on for everything else
export OUTBOUND_URL_ALLOWED_HOSTS='["127.0.0.1","localhost"]'
echo "TrueForge on http://localhost:$PORT  (db: $SQLITE_PATH)"
exec npx -y @truefoundry/trueforge@0.2.1
