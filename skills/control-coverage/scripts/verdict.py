#!/usr/bin/env python3
"""Compute the release verdict. The model runs this script but does not decide its result.

- Re-derives the control selection itself (select_controls.select), plus add-only model additions.
- Reads raw outputs: results/checks.json + coverage.json (run_checks.py), control_changes.json,
  results/subagents/*.json (two_sided.py), maker_checker.json, answers.json.
- Verdict: blocked | conditional | cleared_with_exceptions | cleared

usage: verdict.py --repo PATH --head REV [--base REV] --work DIR [--out verdict.json]
       DIR holds: results/, control_changes.json, added_controls.json, maker_checker.json, answers.json
"""
import argparse
from pathlib import Path

from cc_lib import read_json, write_json
from control_coverage import evaluate
from select_controls import select


def finding(fid, kind, severity, summary, control=None, detail=None):
    return {"id": fid, "kind": kind, "severity": severity, "summary": summary,
            "control": control, "detail": detail}


def build(repo, base, head, work):
    work = Path(work)
    selection = select(repo, base, head, read_json(work / "added_controls.json", []))
    if selection["mode"] == "setup":
        return {"verdict": "blocked", "reasons": ["setup not approved: this app has no controls/config on the release"],
                "findings": [], "selection": selection}

    findings, incomplete = [], []
    checks = read_json(work / "results/checks.json")
    if checks is None:
        incomplete.append("run_checks.py results missing")
        checks = {}
    coverage = read_json(work / "results/coverage.json", {})
    rows = evaluate(selection, checks, coverage, work / "results")
    subagents = {}
    for f in (work / "results/subagents").glob("*.json") if (work / "results/subagents").exists() else []:
        r = read_json(f)
        subagents.setdefault(r.get("control"), []).append(r)

    # behaviour-test controls
    for r in rows:
        cid, sev = r["control"], r["severity"]
        unverified = [s for s in subagents.get(cid, []) if s.get("status") == "unverified"]
        if r["status"] == "failing":
            findings.append(finding(f"{cid}:failing", "control_failing", sev, f"{cid} control test fails", cid, r["tests"]))
        elif r["status"] == "known_gap":
            findings.append(finding(f"{cid}:known_gap", "known_gap", sev, f"{cid} known gap still open (xfail)", cid, r["tests"]))
        elif r["status"] == "uncovered":
            findings.append(finding(f"{cid}:uncovered", "uncovered", "high" if sev == "critical" else sev,
                                    f"{cid} tests do not execute changed lines", cid, r["uncovered_lines"]))
        elif r["status"] == "no_tests":
            if unverified:
                findings.append(finding(f"{cid}:unverified", "unverified", "high" if sev == "critical" else sev,
                                        f"{cid} could not be verified by a test", cid, unverified[0].get("notes")))
            else:
                incomplete.append(f"{cid} has no test and no result")

    # tests written in this run must have passed the two-sided check
    for cid, results in subagents.items():
        for s in results:
            if s.get("status") == "unverified" or not s.get("test"):
                continue
            if s["status"] not in ("proven-pass", "proven-fail"):
                findings.append(finding(f"{cid}:two_sided", "unverified", "medium",
                                        f"{s['test']} did not pass the two-sided check", cid))

    # scanners and code rules, only for selected controls
    selected = {c["control"] for c in selection["controls"]}
    scanners = checks.get("scanners", {})
    rules = checks.get("code_rules", {})
    sev_of = {c["control"]: c["severity"] for c in selection["controls"]}
    for cid, result, label in (("STD-SEC-01.a", scanners.get("gitleaks"), "gitleaks"),
                               ("STD-SDLC-02.a", scanners.get("pip-audit"), "pip-audit"),
                               ("STD-CRYPTO-01.a", rules.get("tls-outbound"), "tls-outbound rule")):
        if cid not in selected:
            continue
        if not result or result.get("status") != "ok":
            incomplete.append(f"{label} did not run ({(result or {}).get('status', 'missing')})")
        elif result.get("findings"):
            findings.append(finding(f"{cid}:{label}", "scanner", sev_of[cid],
                                    f"{label}: {len(result['findings'])} finding(s)", cid, result["findings"]))

    # weakened tests and narrowed config
    changes = read_json(work / "control_changes.json")
    if changes is None and base:
        incomplete.append("check_control_changes.py results missing")
    for t in (changes or {}).get("tests_changed", []):
        if t["weakened"]:
            findings.append(finding(f"weakened:{t['path']}", "weakened_test", "critical",
                                    f"{t['path']} was weakened: its previous version fails on this release",
                                    t.get("control"), t.get("output_tail")))
    for n in (changes or {}).get("config_narrowed", []):
        findings.append(finding(f"narrowed:{n}", "narrowed_config", "critical", f"config narrowed: {n}"))

    # maker-checker
    mc = read_json(work / "maker_checker.json")
    if mc is None:
        incomplete.append("maker_checker.json missing")
    for pr in (mc or {}).get("gaps", []):
        findings.append(finding(f"maker-checker:PR{pr['number']}", "maker_checker", "high",
                                f"PR #{pr['number']} merged without independent approval", detail=pr))

    # changed files that no control covers
    for f in selection["unmatched_files"]:
        findings.append(finding(f"unmatched:{f}", "unmatched_file", "medium", f"{f} changed with no control applied"))

    # approver answers: only non-critical findings can be accepted
    answers = {a["id"]: a for a in read_json(work / "answers.json", [])}
    accepted, open_items = [], []
    for f in findings:
        a = answers.get(f["id"])
        if a and a.get("decision") == "accept" and f["severity"] != "critical":
            accepted.append({**f, "accepted_by": a.get("approver"), "reason": a.get("reason"), "fix_by": a.get("fix_by")})
        else:
            if a and a.get("decision") == "reject":
                f = {**f, "severity": "critical", "rejected_by": a.get("approver")}
            open_items.append(f)

    blocking = [f for f in open_items if f["severity"] == "critical"]
    if incomplete or blocking:
        verdict = "blocked"
    elif open_items:
        verdict = "conditional"
    elif accepted:
        verdict = "cleared_with_exceptions"
    else:
        verdict = "cleared"
    return {
        "verdict": verdict, "base": base, "head": head,
        "incomplete": incomplete, "blocking": blocking, "open": open_items, "accepted": accepted,
        "controls": rows, "outside_evidence": selection["outside_evidence"],
        "selected_standards": {k: v["layers"] for k, v in selection["standards"].items()},
        "unmatched_files": selection["unmatched_files"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--base")
    ap.add_argument("--work", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    v = build(a.repo, a.base, a.head, a.work)
    write_json(a.out or f"{a.work}/verdict.json", v)
    print(f"VERDICT: {v['verdict'].upper()}")
    for r in v.get("reasons", []) + v.get("incomplete", []):
        print(f"  incomplete: {r}")
    for f in v.get("blocking", []):
        print(f"  blocking [{f['severity']}] {f['id']}: {f['summary']}")
    for f in [x for x in v.get("open", []) if x not in v.get("blocking", [])]:
        print(f"  open [{f['severity']}] {f['id']}: {f['summary']}")
    for f in v.get("accepted", []):
        print(f"  accepted {f['id']} by {f['accepted_by']}: {f['reason']} (fix by {f['fix_by']})")


if __name__ == "__main__":
    main()
