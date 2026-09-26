#!/usr/bin/env python3
"""Write the approver's decision to /work/answers.json using the exact finding ids from verdict.json.

usage: record_answers.py --work /work --decision accept|reject --approver NAME --reason TEXT --fix-by VERSION [--ids ID ...]
       (no --ids = every open item in verdict.json)
"""
import argparse
from pathlib import Path

from cc_lib import read_json, write_json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--decision", choices=["accept", "reject"], required=True)
    ap.add_argument("--approver", required=True)
    ap.add_argument("--reason", required=True)
    ap.add_argument("--fix-by", default="")
    ap.add_argument("--ids", nargs="*")
    a = ap.parse_args()
    verdict = read_json(Path(a.work) / "verdict.json", {})
    open_ids = [f["id"] for f in verdict.get("open", [])]
    ids = a.ids or open_ids
    unknown = [i for i in ids if i not in open_ids]
    if unknown:
        raise SystemExit(f"not open findings: {unknown}. Open: {open_ids}")
    answers = {x["id"]: x for x in read_json(Path(a.work) / "answers.json", [])}
    for i in ids:
        answers[i] = {"id": i, "decision": a.decision, "approver": a.approver, "reason": a.reason, "fix_by": a.fix_by}
    write_json(Path(a.work) / "answers.json", list(answers.values()))
    critical = [f["id"] for f in verdict.get("open", []) if f["id"] in ids and f["severity"] == "critical"]
    print(f"recorded {a.decision} for {len(ids)} finding(s) by {a.approver}")
    if a.decision == "accept" and critical:
        print(f"note: critical findings cannot be accepted and stay open: {critical}")


if __name__ == "__main__":
    main()
