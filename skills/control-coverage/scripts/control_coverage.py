#!/usr/bin/env python3
"""Control coverage: are each selected control's trigger lines executed by that control's own tests?

Inputs:  selection.json (select_controls.py), results/checks.json + results/coverage.json (run_checks.py)
Output:  control_coverage.json with one row per behaviour_test control:
         status = no_tests | failing | known_gap | covered | uncovered
         uncovered_lines = executable trigger lines not run by any passing test of the control

usage: control_coverage.py --selection selection.json --results DIR --out control_coverage.json
"""
import argparse
from collections import defaultdict
from pathlib import Path

from cc_lib import control_of_test, read_json, write_json


def executed_by_control(results_dir):
    """{control_id: {file: set(lines)}} from one coverage run per control (results/coverage/<control>.json)."""
    out = defaultdict(lambda: defaultdict(set))
    cov_dir = Path(results_dir) / "coverage"
    for f in cov_dir.glob("*.json") if cov_dir.exists() else []:
        for path, data in (read_json(f) or {}).get("files", {}).items():
            out[f.stem][path] |= set(data.get("executed_lines", []))
    return out


def executable_lines(coverage, path):
    data = (coverage or {}).get("files", {}).get(path)
    if not data:
        return None  # file never imported by any test
    return set(data.get("executed_lines", [])) | set(data.get("missing_lines", []))


def evaluate(selection, checks, coverage, results_dir):
    by_control = (checks.get("control_tests") or {}).get("by_control", {})
    executed = executed_by_control(results_dir)
    rows = []
    for c in selection["controls"]:
        if c["method"] != "behaviour_test":
            continue
        cid = c["control"]
        tests = by_control.get(cid, {})
        statuses = list(tests.values())
        uncovered = {}
        for path, lines in c["trigger_lines"].items():
            if not path.endswith(".py"):
                continue
            exe = executable_lines(coverage, path)
            relevant = set(lines) if exe is None else set(lines) & exe
            missing = sorted(relevant - executed.get(cid, {}).get(path, set()))
            if missing:
                uncovered[path] = missing
        if not tests:
            status = "no_tests"
        elif any(s in ("failed", "error") for s in statuses):
            status = "failing"
        elif any(s == "xfail" for s in statuses):
            status = "known_gap"
        elif uncovered:
            status = "uncovered"
        else:
            status = "covered"
        rows.append({"control": cid, "standard": c["standard"], "severity": c["severity"],
                     "status": status, "tests": tests, "uncovered_lines": uncovered})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selection", required=True)
    ap.add_argument("--results", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rows = evaluate(read_json(a.selection), read_json(f"{a.results}/checks.json", {}),
                    read_json(f"{a.results}/coverage.json", {}), a.results)
    write_json(a.out, rows)
    for r in rows:
        extra = f" uncovered={r['uncovered_lines']}" if r["uncovered_lines"] else ""
        print(f"{r['control']}: {r['status']} ({len(r['tests'])} tests){extra}")


if __name__ == "__main__":
    main()
