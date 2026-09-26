# Control Coverage

**Code coverage for bank security controls.** A [TrueForge](https://github.com/truefoundry/trueforge) agent that turns
written security controls into pytest tests, runs them against each release, proves every test is meaningful,
measures whether the release's changed lines are actually executed by those tests, and holds the release until a
person approves it.

- How it works, step by step: [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md)
- Sample app to run it on: **[oplatechie/payments-demo](https://github.com/oplatechie/payments-demo)** (FastAPI payments service with planted gaps)
- Built for the TrueFoundry × Polaris "Agents That Act" hackathon, 26 Sep 2026

---

## What you get after setup

- A local TrueForge (chat UI + API) on `http://localhost:8791`, with state stored in this folder
- A local MCP server, **controls-mcp**, on `http://127.0.0.1:8801/mcp`: the agent's only way to reach GitHub
- Registered in TrueForge: an OpenAI model provider, a Daytona sandbox provider, the **control-coverage** skill
  (loaded from GitHub), the **controls-mcp** connector, and the **control-coverage** agent
- A chat where you type *"Check release v1.2.0 of <you>/payments-demo …"*. The agent then:
  1. finds the controls the change touches;
  2. writes and proves tests with parallel subagents;
  3. files issues and fix PRs;
  4. asks you to accept or reject what it found;
  5. publishes the release only after you approve.

---

## Instructions for AI coding assistants

If you are an AI assistant setting this up for a user, follow the steps below **in order** and run each
**Check** command before moving on. Rules:
- Never print, log or commit the values in `.env`.
- Never add spaces around `=` in `.env`.
- Ask the user for secrets (API keys, tokens). Never invent them.
- Steps that need a browser (creating keys, forking, enabling Issues) must be done by the user. Tell them exactly what to click.
- Keep TrueForge and controls-mcp running in two separate terminals for the whole session.

---

## 1. Prerequisites

| Need | Version / note | Check |
|---|---|---|
| macOS or Linux | Windows via WSL2 should work, untested | |
| Node.js | **22.14 or newer** (TrueForge requirement) | `node -v` |
| npx | comes with Node | `npx -v` |
| Python | **3.11 or newer** | `python3 --version` |
| git | any recent version | `git --version` |
| GitHub CLI (optional) | makes forking and checking easier | `gh --version` |
| OpenAI API key | model calls (`gpt-5.5`; `gpt-5.4-mini` also registered) | |
| Daytona API key | sandbox for running code. **Needs "Snapshots: write" permission**, not just sandbox access. Create at app.daytona.io | |
| GitHub account | to fork the demo repo and create a token | |

---

## 2. Fork the sample app (payments-demo)

The agent creates tags, releases, issues and PRs on the app repo, so you need your own copy.

1. The user forks **https://github.com/oplatechie/payments-demo** (or `gh repo fork oplatechie/payments-demo --clone=false`).
   Forks keep the tags `v1.0.0`, `v1.0.1`, `v1.1.0`, `v1.1.1`, which the demo uses.
2. **Enable Issues on the fork**: GitHub disables them on forks by default. Repo → Settings → General → Features → tick **Issues**.
   Without this, `create_issue` fails.
3. If a release `v1.2.0` already exists on the fork (copied from an earlier run), delete it and its tag
   (Releases → v1.2.0 → Delete; then `git push origin :refs/tags/v1.2.0`). The agent creates `v1.2.0` itself.

**Check:** `gh repo view <you>/payments-demo --json hasIssuesEnabled` returns `true`.

### What the sample app contains

| Tag / PR | Change | Control state |
|---|---|---|
| `v1.0.0` / `v1.0.1` | Payments API, admin login, audit log (v1.0.1 upgrades dependencies to clear CVEs) | Before Control Coverage |
| PR #3 → `v1.1.0` | Setup run by the agent: `controls/config/` + 9 control tests | 2 known gaps (xfail + issues) |
| PR #4 → `v1.1.1` | Admin MFA switched from emailed codes to TOTP | STD-AC-02.a fixed |
| PR #5 (on `main`) | Refunds feature | **Planted gap:** reading a refund writes no audit record (STD-LOG-01.a, high) |
| PR #6 (on `main`) | "Allow negative refund amounts" | **Planted gap:** negative/zero refunds accepted (STD-SDLC-01.a, medium) |
| still open | Admin merchant list returns emails | Known gap STD-DP-01.a (medium, issue #2) |
| PRs #5, #6 | Merged without an independent review | Maker-checker finding (high) |

None of these gaps is critical, so a release can reach the approval card if a person accepts them.

---

## 3. Create a GitHub token

The user creates a **fine-grained personal access token**: GitHub → Settings → Developer settings → Fine-grained tokens.
- **Repository access:** only `<you>/payments-demo`. Don't give it access to this repo; the agent must not be able to edit its own rules.
- **Permissions:** Contents **read and write**, Issues **read and write**, Pull requests **read and write**, Metadata **read**.

**Check** (the token must be able to push to the fork):
```bash
curl -s -H "Authorization: Bearer <token>" https://api.github.com/repos/<you>/payments-demo | python3 -c "import json,sys; print(json.load(sys.stdin)['permissions'])"
# expect 'push': True
```

---

## 4. Get this repo and configure `.env`

```bash
git clone https://github.com/oplatechie/control-coverage.git
cd control-coverage
cp .env.example .env
```

Edit `.env`. **Format rules: `KEY=value`, no spaces around `=`, no quotes.**

| Variable | Value |
|---|---|
| `TRUEFORGE_PORT` | `8791` (leave as is unless the port is taken) |
| `OPENAI_API_KEY` | your OpenAI key |
| `GITHUB_TOKEN` | the fine-grained token from step 3 |
| `DAYTONA_API_KEY` | your Daytona key (with Snapshots write) |
| `DEMO_REPO` | `<you>/payments-demo`: the only repo controls-mcp will act on |
| `CONTROLS_SOURCE` (optional) | where controls come from: an `https://` URL (e.g. a GRC system export) or a file path. Default: `skills/control-coverage/controls.yaml` |
| `CONTROLS_MCP_PORT` (optional) | default `8801`. If you change it, also change `trueforge/mcp-servers.json` |

**Check** (prints variable names with value lengths only, never the values):
```bash
awk -F= '/^[A-Z_]+=/{v=substr($0,length($1)+2); printf "%s: %d chars%s\n",$1,length(v),(v~/^ /?"  <-- REMOVE LEADING SPACE":"")}' .env
```

**If you forked this repo too** (to change the skill): the skill is loaded **from GitHub**, not from your disk. Edit
`trueforge/skills.json` → `"url": "https://github.com/<you>/control-coverage"`, and push every skill change
before starting a new chat.

---

## 5. Install Python dependencies

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt     # mcp (pinned <2), pyyaml
```
**Check:** `.venv/bin/python -c "import mcp, yaml; from mcp.server.fastmcp import FastMCP; print('ok')"`

---

## 6. Start the two servers (two terminals, keep both running)

**Terminal 1: TrueForge** (downloads `@truefoundry/trueforge@0.2.1` on first run)
```bash
./scripts/start-trueforge.sh
```
This runs TrueForge in local mode with:
- the SQLite database at `.trueforge/db.sqlite`
- `PORT=8791`
- `OUTBOUND_URL_ALLOWED_HOSTS=["127.0.0.1","localhost"]`. TrueForge blocks connections to local addresses by default; this allows only the local controls-mcp.

**Terminal 2: controls-mcp**
```bash
./scripts/start-controls-mcp.sh
```

**Check:**
```bash
curl -s -o /dev/null -w "trueforge %{http_code}\n" http://localhost:8791/api/v1/docs     # 200
lsof -nP -iTCP:8801 -sTCP:LISTEN | tail -1                                           # a python process
```

---

## 7. Register everything in TrueForge

```bash
.venv/bin/python scripts/setup.py
```
This calls the TrueForge HTTP API (`PUT` = create or replace) using `.env` and `trueforge/*.json`:

| Registers | From |
|---|---|
| Model provider `openai` with `gpt-5.4-mini` and `gpt-5.5` | `OPENAI_API_KEY` |
| Sandbox provider Daytona (skipped if one is already configured, because re-saving rebuilds the snapshot and can time out) | `DAYTONA_API_KEY` |
| Skill `control-coverage` | `trueforge/skills.json` |
| MCP server `controls-mcp` | `trueforge/mcp-servers.json` |
| Agent `control-coverage` (model `openai/gpt-5-5`, approval on `@destructive` tools, sandbox, subagents, questions, compaction) | `trueforge/agent.json` |

Expected output:
```
model provider: openai
sandbox provider: daytona            (or "already configured, kept")
skill: control-coverage
mcp-server: controls-mcp
agent created: control-coverage (<id>)
```

**Check:**
```bash
curl -s http://localhost:8791/api/v1/mcp-servers/controls-mcp/tools | python3 -c "import json,sys; print([t['name'] for t in json.load(sys.stdin)['data']])"
# ['get_controls', 'get_release_scope', 'create_issue', 'add_controls', 'propose_fix', 'change_controls', 'create_release']
curl -s http://localhost:8791/api/v1/agents | python3 -c "import json,sys; print([a['name'] for a in json.load(sys.stdin)['data']])"
# includes 'control-coverage'
```

---

## 8. Run it

Open **http://localhost:8791**, start a new chat, and pick the **control-coverage** agent.

### Release check (the main flow; payments-demo is already set up)
```
Check release v1.2.0 of <you>/payments-demo. Previous release: v1.1.1. Release head: main.
```
What you'll see (about 5–8 minutes):
1. `Step N/9` headers with a one-line *Why*. Controls always shown as ID + name, e.g. "STD-LOG-01.a Audit record on every sensitive read".
2. Selection and control coverage: the existing tests pass, but they don't run the new refund code.
3. **Parallel subagents** named `test-writer · <control>`, one per uncovered control. Each writes a test and runs `two_sided.py`.
4. The two planted gaps come back **proven-fail**. The agent opens an issue for each, with the failing output and a fix patch it has tested.
5. A **question** listing the open items: accept for this release, or reject. You also give your name, a reason and a fix-by version.
   - **Accept:** the agent opens a PR with the new tests, builds the evidence, and calls `create_release`. TrueForge shows an **approval card**; approve it, and the release `v1.2.0` is published with an evidence section.
   - **Reject:** the release is blocked, and the agent opens a **fix PR** (`propose_fix`) for each proven-fail. You review and merge those.

### Setup run (first time on a new app)
For an app with no `controls/config/`:
```
Run setup for <you>/<repo> at <tag or branch>.
```
The agent asks the app tier, drafts `controls/config/`, writes a test per control, files issues for gaps, and opens
one setup PR. Nothing is released until a person merges that PR.

### Re-running the demo
The agent refuses to create a tag that already exists. To run the release check again: delete release `v1.2.0` and
its tag on your fork (the agent has no tool to delete them). Close the issues and PRs from the earlier run if you like.

---

## 9. Using it on your own repo

It works on Python/FastAPI repos that use pytest. The agent's tests rely on fixtures in the app's `conftest.py`:
`client` (FastAPI `TestClient`), `db` (with `all_values()` and `rows(sql, params)`), merchant/user auth fixtures, and
`caplog`. Copy `conftest.py` and `testkit.py` from payments-demo as a starting point, set `DEMO_REPO` to your repo,
restart controls-mcp, and start with a **setup run**.

---

## 10. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `start-trueforge.sh` exits with 127 or "command not found" | `npx` not on PATH (nvm not loaded in this shell) | `source ~/.nvm/nvm.sh` or open a new login shell; check `which npx` |
| Chat error: "Cannot connect to API … api.openai.com timeout" | Network blip | Re-send the message; check `curl -s -o /dev/null -w "%{http_code}" https://api.openai.com/v1/models` (401 is fine) |
| 429 rate-limit errors | Low-tier model provider limits | Use an OpenAI key with enough tokens per minute; avoid free-tier providers |
| Registering an MCP server says "Outbound URL blocked for host 127.0.0.1" | TrueForge started without the allowlist | Start it with `./scripts/start-trueforge.sh`, not plain `npx` |
| `setup.py`: "Unknown model … not configured on provider" | Wrong model name format | Agent model names use the display name: `openai/gpt-5-5`, not `gpt-5.5` |
| `setup.py`: sandbox provider 500 / "sandbox buildImage" timeout | Re-saving Daytona rebuilds the snapshot | Already handled: setup keeps an existing provider. On first setup, check the Daytona key has **Snapshots: write** |
| Agent can't call controls-mcp tools | controls-mcp not running, or `.env` missing `GITHUB_TOKEN`/`DEMO_REPO` | Start it in terminal 2; its log shows `controls-mcp for <repo> on http://127.0.0.1:8801/mcp` |
| `create_issue` fails with 410/404 | Issues disabled on the fork | Enable Issues (step 2) |
| `create_release` refused: "tag already exists" | Earlier run published v1.2.0 | Delete the release and tag (step 8) |
| Skill changes not picked up | The skill is loaded from GitHub at session start | Push the change, start a **new** chat |
| Stale behaviour after editing `trueforge/agent.json` | Agent not re-registered | Re-run `scripts/setup.py` |

Local-only files (git-ignored): `.env`, `.trueforge/`, `.venv/`, `*.log`. Stop the servers with Ctrl+C in each terminal.

---

## What the agent can and can't do

| Level | Actions |
|---|---|
| Without asking | Read GitHub, run code in the sandbox, open issues, open PRs that **add** new files under `controls/`, open **fix PRs** that change app code only |
| Asks a person | Accept or reject findings (question card) |
| Needs approval | `create_release` (publish) and `change_controls` (modify or delete existing control files): approval card |
| Can't at all | Merge PRs, push to `main`, delete tags or branches, change CI, edit its own rules (the token only reaches the app repo) |

These limits are enforced in code (controls-mcp), by TrueForge's approval policy, and by the token's scope, not
only by the prompt. Details: [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md#7-where-the-agent-stops).

---

## Repo layout

```
trueforge/            agent.json, skills.json, mcp-servers.json   (what setup.py registers)
scripts/              start-trueforge.sh, start-controls-mcp.sh, setup.py
controls_mcp/         server.py: GitHub tools with checks in code
skills/control-coverage/
  SKILL.md            the procedure the agent follows
  controls.yaml       10 standards, 15 controls
  templates/          test-writer subagent instructions, per-app config formats
  scripts/            selection, checks, control coverage, two-sided check, verdict, evidence
docs/HOW-IT-WORKS.md  full explanation
```

## AI assistance

Built with help from Claude Code (Anthropic). Design and code were reviewed by the team, who can explain every part.
