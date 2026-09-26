#!/usr/bin/env python3
"""Configure this project's TrueForge instance from .env and the manifests in trueforge/.

Registers (idempotent, PUT = create or replace):
  - model provider   (OpenAI, if OPENAI_API_KEY is set)
  - sandbox provider (Daytona, if DAYTONA_API_KEY is set)
  - skills           (trueforge/skills.json)
  - MCP servers      (trueforge/mcp-servers.json)
  - agent            (trueforge/agent.json, or --agent PATH)

Manifests may contain ${VAR} placeholders; they are filled from the environment / .env.
Standard library only.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TF_DIR = ROOT / "trueforge"

OPENAI_MODELS = [
    {"model_id": "gpt-5.4-mini", "name": "gpt-5-4-mini",
     "properties": {"context_length": 400000, "max_output_tokens": 128000,
                    "reasoning_efforts": ["none", "low", "medium", "high", "xhigh"]}},
    {"model_id": "gpt-5.5", "name": "gpt-5-5",
     "properties": {"context_length": 1050000, "max_output_tokens": 128000,
                    "reasoning_efforts": ["none", "low", "medium", "high", "xhigh"]}},
]


def load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def fill(text):
    def sub(match):
        value = os.environ.get(match.group(1))
        if value is None:
            sys.exit(f"missing env var {match.group(1)} (set it in .env)")
        return value
    return re.sub(r"\$\{([A-Z0-9_]+)\}", sub, text)


def load_manifest(path):
    return json.loads(fill(Path(path).read_text()))


def call(method, path, body=None):
    base = f"http://localhost:{os.environ.get('TRUEFORGE_PORT', '8791')}/api/v1"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as err:
        detail = err.read().decode()[:300]
        sys.exit(f"{method} {path} failed ({err.code}): {detail}")
    except urllib.error.URLError as err:
        sys.exit(f"cannot reach TrueForge at {base} ({err.reason}); run ./scripts/start-trueforge.sh first")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", default=str(TF_DIR / "agent.json"))
    args = parser.parse_args()
    load_env()

    if os.environ.get("OPENAI_API_KEY"):
        call("PUT", "/settings/model-providers", {"manifest": {
            "type": "openai", "auth": {"api_key": os.environ["OPENAI_API_KEY"]}, "models": OPENAI_MODELS}})
        print("model provider: openai")
    else:
        print("model provider: skipped (OPENAI_API_KEY not set)")

    if os.environ.get("DAYTONA_API_KEY"):
        call("PUT", "/settings/sandbox-providers", {"manifest": {
            "type": "daytona", "auth": {"api_key": os.environ["DAYTONA_API_KEY"]},
            "exec_timeout_ms": 600000, "auto_stop_interval_in_minutes": 30,
            "auto_archive_interval_in_minutes": 60, "auto_delete_interval_in_minutes": 1440}})
        print("sandbox provider: daytona")
    else:
        print("sandbox provider: skipped (DAYTONA_API_KEY not set; local fallback if available)")

    for name in ("skills", "mcp-servers"):
        path = TF_DIR / f"{name}.json"
        if path.exists():
            for manifest in load_manifest(path):
                call("PUT", f"/settings/{name}", {"manifest": manifest})
                print(f"{name[:-1]}: {manifest['name']}")

    agent = load_manifest(args.agent)
    existing = [a for a in call("GET", "/agents").get("data", []) if a.get("name") == agent["name"]]
    if existing:
        call("PUT", f"/agents/{existing[0]['id']}", agent)
        print(f"agent updated: {agent['name']} ({existing[0]['id']})")
    else:
        created = call("POST", "/agents", agent).get("data", {})
        print(f"agent created: {agent['name']} ({created.get('id')})")


if __name__ == "__main__":
    main()
