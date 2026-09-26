#!/usr/bin/env python3
"""Build the release evidence section (markdown) from machine-written files only.

usage: evidence.py --work /work --repo /work/repo --base REV --head REV --out evidence.md
"""
import argparse
import subprocess
from pathlib import Path

from cc_lib import TESTS_DIR, control_of_test, load_standards, read_json


def blob(repo, path):
    p = subprocess.run(["git", "-C", repo, "hash-object", path], capture_output=True, text=True)
    return p.stdout.strip()[:10]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    w = Path(a.work)
    v = read_json(w / "verdict.json", {})
    scope = read_json(w / "scope.json", {})
    changes = read_json(w / "control_changes.json", {})
    standards = load_standards()
    subagents = {r["control"]: r for r in (read_json(f) for f in (w / "results/subagents").glob("*.json"))} \
        if (w / "results/subagents").exists() else {}

    tests_by_control = {}
    for f in sorted(Path(a.repo, TESTS_DIR).glob("test_*.py")):
        rel = f"{TESTS_DIR}/{f.name}"
        tests_by_control.setdefault(control_of_test(rel), []).append(f"`{f.name}` ({blob(a.repo, rel)})")

    sha = (scope.get("head_sha") or a.head)[:10]
    lines = [f"## Release evidence: {a.head} (sha {sha})",
             f"Verdict: **{v.get('verdict')}**. Checked by Control Coverage (TrueForge). Previous release: {a.base}.", "",
             "Standards selected (layers): " + ", ".join(f"{s} ({'/'.join(l)})" for s, l in
                                                         v.get("selected_standards", {}).items()), "",
             "| Control | Framework rules | Tests (blob) | Result | Two-sided check |",
             "|---|---|---|---|---|"]
    for row in v.get("controls", []):
        cid = row["control"]
        rules = ", ".join(standards[row["standard"]]["framework_rules"])
        two = subagents.get(cid)
        two_txt = (f"{two['counter_patch_kind']} patch -> {two['counter_run']} ✔" if two and two.get("status", "").startswith("proven")
                   else ("new this run: " + two["status"]) if two else "existing test")
        lines.append(f"| {cid} | {rules} | {'<br>'.join(tests_by_control.get(cid, ['-']))} | {row['status']} | {two_txt} |")
    lines += ["", f"Outside evidence required (not checked here): {', '.join(v.get('outside_evidence', [])) or 'none'}"]
    changed = changes.get("tests_changed", [])
    lines.append("Control test changes since previous release: " +
                 ("; ".join(f"{t['path']} {t['change']} (previous version on this release: {t['previous_version_on_head']})"
                            for t in changed) or "none"))
    if v.get("accepted"):
        lines.append("Accepted exceptions:")
        lines += [f"- {e['id']}: {e['summary']}. Accepted by {e.get('accepted_by')}: \"{e.get('reason')}\" (fix by {e.get('fix_by')})"
                  for e in v["accepted"]]
    prs = scope.get("merged_prs", [])
    if prs:
        lines.append("Merged PRs: " + ", ".join(f"#{p['number']} (approved by {', '.join(p['approved_by']) or 'nobody'})" for p in prs))
    lines += ["", f"Re-run: `git checkout {sha} && pytest controls/tests`"]
    Path(a.out).write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
