"""Shared helpers for Control Coverage scripts: config loading, git diff parsing, naming."""
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # sandbox may not have it yet
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pyyaml"], check=True)
    import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = "controls/config"
TESTS_DIR = "controls/tests"


def git(repo, *args, check=True):
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


def load_standards():
    data = yaml.safe_load((SKILL_DIR / "controls.yaml").read_text())
    return {s["id"]: s for s in data["standards"]}


def all_controls(standards):
    return {c["id"]: {**c, "standard": s["id"], "severity": c.get("severity", s["severity"])}
            for s in standards.values() for c in s["controls"]}


def file_at(repo, rev, path):
    """File content at a git revision, or None if it does not exist there. rev=None means working tree."""
    if rev is None:
        p = Path(repo) / path
        return p.read_text() if p.exists() else None
    out = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else None


def load_app_config(repo, rev):
    """Per-app config from controls/config/ at a revision. Returns None if the app has no config there."""
    app = file_at(repo, rev, f"{CONFIG_DIR}/app.yaml")
    if app is None:
        return None
    def y(name, default):
        text = file_at(repo, rev, f"{CONFIG_DIR}/{name}")
        return (yaml.safe_load(text) if text else None) or default
    return {
        "app": yaml.safe_load(app) or {},
        "paths": y("paths.yaml", {}),
        "data": y("data-classification.yaml", {}),
    }


def changed_lines(repo, base, head):
    """{path: sorted list of changed line numbers in head}. base=None means every line of every tracked file."""
    if base is None:
        files = git(repo, "ls-tree", "-r", "--name-only", head).split()
        result = {}
        for f in files:
            text = file_at(repo, head, f) or ""
            result[f] = list(range(1, text.count("\n") + 2))
        return result
    diff = git(repo, "diff", "-U0", "--no-color", base, head)
    result, current = {}, None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = None if line.endswith("/dev/null") else line[6:]
            if current:
                result.setdefault(current, [])
        elif line.startswith("@@") and current:
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            start, count = int(m.group(1)), int(m.group(2) or 1)
            # pure deletions: mark the line where code was removed
            lines = range(start, start + count) if count else [max(start, 1)]
            result[current].extend(lines)
    return {f: sorted(set(v)) for f, v in result.items()}


def match_globs(path, globs):
    return any(fnmatch.fnmatch(path, g) or fnmatch.fnmatch(path, g.rstrip("*").rstrip("/") + "/*")
               for g in globs)


TEST_NAME = re.compile(r"test_std_([a-z]+)_(\d+)_([a-z])(?:_[\w]*)?\.py$")


def control_of_test(path):
    """controls/tests/test_std_crypto_02_a_refunds.py -> STD-CRYPTO-02.a"""
    m = TEST_NAME.search(path)
    return f"STD-{m.group(1).upper()}-{m.group(2)}.{m.group(3)}" if m else None


def test_prefix(control_id):
    """STD-CRYPTO-02.a -> test_std_crypto_02_a"""
    std, letter = control_id.split(".")
    return "test_" + std.lower().replace("-", "_") + "_" + letter


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True))


def read_json(path, default=None):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else default
