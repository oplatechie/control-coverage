#!/usr/bin/env python3
"""Select the standards and controls a release affects (layers 1, 2, 3, 5; layer 4 = --added).

Uses the UNION of per-app config at base and head, so narrowing config inside a release
cannot hide anything in that release. Records the trigger lines for every selection.

usage: select_controls.py --repo PATH --head REV [--base REV] [--added added_controls.json] --out selection.json
       --base omitted  -> setup mode (whole repo, all standards)
"""
import argparse
import re
from collections import defaultdict

import rules
from cc_lib import (CONFIG_DIR, TESTS_DIR, all_controls, changed_lines, file_at, label, load_app_config,
                    load_standards, match_globs, read_json, write_json)

TYPE_STANDARDS = {"PAN": ["STD-CRYPTO-02", "STD-LOG-01"], "PII": ["STD-LOG-01", "STD-DP-01"]}
# not app code: control files (handled by check_control_changes), CI, docs, and the team's own tests/fixtures
IGNORE = re.compile(r"^(controls/|tests/|\.github/|README|LICENSE|docs/)|\.md$|(^|/)(conftest|testkit)\.py$|pytest\.ini$")


def select(repo, base, head, added=None):
    standards = load_standards()
    controls = all_controls(standards)
    head_cfg = load_app_config(repo, head)
    base_cfg = load_app_config(repo, base) if base else None
    setup = head_cfg is None
    changes = changed_lines(repo, None if setup else base, head)
    code_changes = {f: ls for f, ls in changes.items() if not IGNORE.search(f)}

    picked = defaultdict(lambda: {"layers": set(), "trigger_lines": defaultdict(set), "reasons": []})

    def add(std, layer, path=None, lines=(), reason=None):
        if std not in standards:
            return
        entry = picked[std]
        entry["layers"].add(layer)
        if path:
            entry["trigger_lines"][path].update(lines)
        if reason and reason not in entry["reasons"]:
            entry["reasons"].append(reason)

    if setup:
        for std in standards:
            add(std, "setup")
    else:
        configs = [c for c in (base_cfg, head_cfg) if c]
        for cfg in configs:
            # layer 1: paths
            for std, globs in (cfg["paths"] or {}).items():
                for path, lines in code_changes.items():
                    if match_globs(path, globs):
                        add(std, "paths", path, lines)
            # layer 2: data classification (field names used in changed functions / lines)
            fields = (cfg["data"] or {}).get("fields", {})
            for path, lines in code_changes.items():
                source = file_at(repo, head, path) or ""
                src_lines = source.splitlines()
                for field, meta in fields.items():
                    stds = meta.get("standards") or TYPE_STANDARDS.get(meta.get("type"), [])
                    column = field.split(".")[-1]
                    hit = [n for n in lines if 0 < n <= len(src_lines)
                           and re.search(rf"\b{re.escape(column)}\b", src_lines[n - 1])]
                    for std in stds:
                        if hit:
                            add(std, "data", path, hit, f"{path} uses {field}")
            # layer 5: tier default
            app = cfg["app"]
            for std in app.get("always_apply", []):
                add(std, "tier")
            if app.get("tier") == 1:
                for std, s in standards.items():
                    if s["severity"] == "critical":
                        add(std, "tier")
        # layer 3: code-structure rules (on head code)
        for path, lines in code_changes.items():
            for rule_id, std in rules.file_rules(path):
                add(std, "rules", path, lines, rule_id)
            for rule_id, std, trig in rules.scan(path, file_at(repo, head, path), lines):
                add(std, "rules", path, trig, rule_id)

    # layer 4: model additions (add only)
    for item in added or []:
        for path, lines in (item.get("lines") or {}).items():
            add(item["standard"], "model", path, lines, item.get("reason"))
        if not item.get("lines"):
            add(item["standard"], "model", reason=item.get("reason"))

    # standards marked not applicable in BOTH configs (a new not_applicable is a narrowing)
    na_sets = [set((c["app"].get("not_applicable") or {}).keys()) for c in (base_cfg, head_cfg) if c]
    not_applicable = set.intersection(*na_sets) if na_sets else set()

    covered_files = {p for e in picked.values() for p in e["trigger_lines"]}
    out_standards, out_controls, outside = {}, [], []
    for std, entry in sorted(picked.items()):
        if std in not_applicable:
            continue
        trig = {p: sorted(ls) for p, ls in entry["trigger_lines"].items()}
        out_standards[std] = {"title": standards[std]["title"], "layers": sorted(entry["layers"]),
                              "trigger_lines": trig, "reasons": entry["reasons"]}
        for c in standards[std]["controls"]:
            row = {"control": c["id"], "name": c.get("name", ""), "text": c["text"],
                   "standard": std, "method": c["method"],
                   "severity": controls[c["id"]]["severity"], "trigger_lines": trig}
            (outside if c["method"] == "outside_evidence" else out_controls).append(row)

    return {
        "mode": "setup" if setup else "release",
        "base": base, "head": head,
        "standards": out_standards,
        "controls": out_controls,
        "outside_evidence": [r["control"] for r in outside],
        "not_applicable": sorted(not_applicable),
        "changed_files": sorted(changes),
        "unmatched_files": sorted(f for f in code_changes if f not in covered_files) if not setup else [],
        "app": (head_cfg or {}).get("app", {}),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--base")
    ap.add_argument("--added")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    result = select(a.repo, a.base, a.head, read_json(a.added, []) if a.added else None)
    write_json(a.out, result)
    print(f"mode={result['mode']} standards={len(result['standards'])} controls={len(result['controls'])} "
          f"outside_evidence={len(result['outside_evidence'])} unmatched_files={result['unmatched_files']}")
    for std, e in result["standards"].items():
        why = "; ".join(e["reasons"][:2])
        print(f"  {std} {e['title']}: layers={','.join(e['layers'])} files={list(e['trigger_lines'])}"
              + (f" ({why})" if why else ""))
    for c in result["controls"]:
        print(f"    - {c['control']} {c['name']} [{c['method']}]")


if __name__ == "__main__":
    main()
