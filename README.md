# Control Coverage

Code coverage for bank security controls. A TrueForge agent that turns written security controls into tests, measures whether each release's changes are covered by those tests, and holds the release until a person signs off.

Built for the TrueFoundry × Polaris "Agents That Act" hackathon (26 Sep 2026). Work in progress.

## Run TrueForge for this project

Requires Node.js 22.14+.

```bash
cp .env.example .env        # fill in keys
./scripts/start-trueforge.sh
```

Opens on http://localhost:8791. State is kept in `.trueforge/` inside this folder (git-ignored).

## AI assistance

Built with help from Claude Code (Anthropic). Design notes and code were reviewed by the team.
