# Control Coverage

Code coverage for bank security controls. A TrueForge agent that turns written security controls into tests, measures whether each release's changes are covered by those tests, and holds the release until a person signs off.

Built for the TrueFoundry × Polaris "Agents That Act" hackathon (26 Sep 2026). Work in progress.

## Setup

Requires Node.js 22.14+ and Python 3.11+.

```bash
cp .env.example .env                      # fill in keys
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./scripts/start-trueforge.sh              # terminal 1: TrueForge on http://localhost:8791
.venv/bin/python scripts/setup.py         # registers model provider, sandbox, skill, MCP servers, agent
```

TrueForge state (sessions, stored keys) is kept in `.trueforge/` inside this folder and is git-ignored.
The start script allows outbound calls only to `127.0.0.1` / `localhost` in addition to TrueForge's defaults, so the local `controls-mcp` server can be reached.

## AI assistance

Built with help from Claude Code (Anthropic). Design notes and code were reviewed by the team.
