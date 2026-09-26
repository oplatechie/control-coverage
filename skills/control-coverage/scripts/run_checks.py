#!/usr/bin/env python3
"""Run every check on a repo checkout and write raw results to --results.

- unit tests (tests/)                    -> unit-junit.xml
- ALL control tests (controls/tests/)    -> controls-junit.xml + coverage.json (per-test contexts)
- gitleaks                               -> gitleaks.json
- pip-audit                              -> pip-audit.json
- code rules (tls-outbound)              -> code-rules.json
Summary                                  -> checks.json

usage: run_checks.py --repo PATH --results DIR [--install]
"""
import argparse
import ast
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from cc_lib import TESTS_DIR, control_of_test, write_json

GITLEAKS_VERSION = "8.21.2"


def run(cmd, cwd, env=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env={**os.environ, **(env or {})})
    return p.returncode, p.stdout, p.stderr[-4000:]


def junit_results(path):
    """{test_id: 'passed'|'failed'|'error'|'xfail'|'skipped'} from a junit xml file."""
    out = {}
    if not Path(path).exists():
        return out
    for case in ET.parse(path).getroot().iter("testcase"):
        tid = f"{case.get('file') or case.get('classname', '').replace('.', '/') + '.py'}::{case.get('name')}"
        status = "passed"
        for child in case:
            if child.tag == "failure":
                status = "failed"
            elif child.tag == "error":
                status = "error"
            elif child.tag == "skipped":
                status = "xfail" if (child.get("type") or "").endswith("xfail") else "skipped"
        out[tid] = status
    return out


def pytest(repo, paths, junit, cov_json=None):
    existing = [p for p in paths if (Path(repo) / p).exists()]
    if not existing:
        return {"ran": False}
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *existing, f"--junitxml={junit}",
           "-o", "junit_family=xunit1"]
    if cov_json:
        cmd += ["--cov=app", f"--cov-report=json:{cov_json}"]
    code, out, err = run(cmd, repo)
    return {"ran": True, "exit_code": code, "tail": out[-1500:], "results": junit_results(junit)}


def per_control_coverage(repo, results, per_control):
    """One coverage run per control, so executed lines are attributed to that control's tests only.
    (Per-test coverage contexts are unreliable here: FastAPI runs sync endpoints in worker threads.)"""
    out_dir = Path(results) / "coverage"
    out_dir.mkdir(exist_ok=True)
    for cid, tests in per_control.items():
        files = sorted({t.split("::")[0] for t in tests})
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--runxfail", *files,
               "--cov=app", f"--cov-report=json:{out_dir / (cid + '.json')}"]
        run(cmd, repo)


def gitleaks_bin():
    found = shutil.which("gitleaks")
    if found:
        return found
    arch = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}[platform.machine().lower()]
    osname = {"Linux": "linux", "Darwin": "darwin"}[platform.system()]
    dest = Path("/tmp/cc-bin")
    dest.mkdir(exist_ok=True)
    url = (f"https://github.com/gitleaks/gitleaks/releases/download/v{GITLEAKS_VERSION}/"
           f"gitleaks_{GITLEAKS_VERSION}_{osname}_{arch}.tar.gz")
    tgz = dest / "gitleaks.tgz"
    urllib.request.urlretrieve(url, tgz)
    with tarfile.open(tgz) as t:
        t.extract("gitleaks", dest)
    return str(dest / "gitleaks")


def gitleaks(repo, results):
    report = Path(results) / "gitleaks.json"
    try:
        binary = gitleaks_bin()
    except Exception as e:  # noqa: BLE001
        return {"status": "unavailable", "error": str(e)}
    code, out, err = run([binary, "detect", "--no-git", "--redact", "-s", ".", "-r", str(report),
                          "--no-banner", "--exit-code", "0"], repo)
    findings = json.loads(report.read_text() or "[]") if report.exists() else []
    findings = [f for f in findings if not f.get("File", "").startswith((".venv", "results"))]
    return {"status": "ok", "findings": [{"file": f.get("File"), "line": f.get("StartLine"),
                                          "rule": f.get("RuleID")} for f in findings]}


def pip_audit(repo, results):
    req = Path(repo) / "requirements.txt"
    if not req.exists():
        return {"status": "no-requirements"}
    exe = shutil.which("pip-audit") or str(Path(sys.executable).parent / "pip-audit")
    if not Path(exe).exists() and not shutil.which("pip-audit"):
        run([sys.executable, "-m", "pip", "install", "-q", "pip-audit"], repo)
    code, out, err = run([sys.executable, "-m", "pip_audit", "-r", str(req), "-f", "json", "--progress-spinner", "off"], repo)
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {"status": "error", "error": err[-500:]}
    (Path(results) / "pip-audit.json").write_text(out)
    vulns = [{"package": d["name"], "version": d["version"], "id": v["id"], "fix": v.get("fix_versions")}
             for d in data.get("dependencies", []) for v in d.get("vulns", [])]
    unique = {(v["package"], v["id"]): v for v in vulns}
    return {"status": "ok", "findings": list(unique.values())}


def tls_rule(repo):
    """STD-CRYPTO-01.a: no http:// URLs in calls, no verify=False."""
    findings = []
    for path in Path(repo, "app").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "verify" and isinstance(kw.value, ast.Constant) and kw.value.value is False:
                        findings.append({"file": str(path.relative_to(repo)), "line": node.lineno, "rule": "verify=False"})
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("http://"):
                        findings.append({"file": str(path.relative_to(repo)), "line": node.lineno, "rule": "http-url"})
    return {"status": "ok", "findings": findings}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--results", required=True)
    ap.add_argument("--install", action="store_true", help="pip install the repo requirements first")
    a = ap.parse_args()
    repo, results = os.path.abspath(a.repo), os.path.abspath(a.results)
    Path(results).mkdir(parents=True, exist_ok=True)
    if a.install:
        run([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"], repo)

    unit = pytest(repo, ["tests"], f"{results}/unit-junit.xml")
    ctl = pytest(repo, [TESTS_DIR], f"{results}/controls-junit.xml", f"{results}/coverage.json")
    per_control = {}
    for tid, status in (ctl.get("results") or {}).items():
        cid = control_of_test(tid.split("::")[0])
        if cid:
            per_control.setdefault(cid, {})[tid] = status
    per_control_coverage(repo, results, per_control)
    summary = {
        "unit_tests": {k: unit.get(k) for k in ("ran", "exit_code", "results")},
        "control_tests": {"ran": ctl.get("ran", False), "by_control": per_control},
        "scanners": {"gitleaks": gitleaks(repo, results), "pip-audit": pip_audit(repo, results)},
        "code_rules": {"tls-outbound": tls_rule(repo)},
    }
    write_json(f"{results}/checks.json", summary)
    unit_res = list((unit.get("results") or {}).values())
    print(f"unit tests: {unit_res.count('passed')} passed, {len(unit_res) - unit_res.count('passed')} not passed")
    for cid, tests in sorted(per_control.items()):
        print(f"control {cid}: " + ", ".join(f"{t.split('::')[1]}={s}" for t, s in tests.items()))
    for name, r in summary["scanners"].items():
        print(f"{name}: {r['status']} findings={len(r.get('findings', []))}")
    print(f"tls-outbound: findings={len(summary['code_rules']['tls-outbound']['findings'])}")


if __name__ == "__main__":
    main()
