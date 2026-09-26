#!/usr/bin/env bash
# Start a TrueForge instance whose state lives inside this repo (.trueforge/, git-ignored).
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a
mkdir -p .trueforge
export SQLITE_PATH="$PWD/.trueforge/db.sqlite"
export PORT="${TRUEFORGE_PORT:-8791}"
echo "TrueForge on http://localhost:$PORT  (db: $SQLITE_PATH)"
exec npx -y @truefoundry/trueforge@0.2.1
