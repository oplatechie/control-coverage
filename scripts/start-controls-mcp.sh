#!/usr/bin/env bash
# Start controls-mcp (GitHub access for the agent) on 127.0.0.1:8801
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python controls_mcp/server.py
