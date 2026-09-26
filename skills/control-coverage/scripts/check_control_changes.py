#!/usr/bin/env python3
"""Detect weakened control tests and narrowed per-app config between two revisions.

Tests: for every control test modified or deleted since base, run the BASE version of the
test against the HEAD code (with --runxfail, so removing an xfail marker is not a weakening).
If the old version fails, the test was weakened.

Config: compare controls/config at base and head. Removing paths, fields or always_apply
entries, lowering the tier, or adding not_applicable entries is a narrowing.

usage: check_control_changes.py --repo PATH --base REV --head REV --out control_changes.json
(the repo working tree must be checked out at HEAD)
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from cc_lib import CONFIG_DIR, TESTS_DIR, control_of_test, file_at, git, load_app_config, write_json


def run_old_test(repo, path, source):
    tmp = Path(repo) / ".cc_previous"
    tmp.mkdir(exist_ok=True)
    target = tmp / Path(path).name
    target.write_text(source)
    try:
        p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--runxfail",
                            str(target)], cwd=repo, capture_output=True, text=True)
        return ("passed" if p.returncode == 0 else "failed"), p.stdout[-800:]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def config_narrowing(base_cfg, head_cfg):
    if base_cfg is None:
        return []
    if head_cfg is None:
        return ["controls/config was removed"]
    out = []
    for std, globs in (base_cfg["paths"] or {}).items():
        removed = set(globs) - set((head_cfg["paths"] or {}).get(std, []))
        if removed:
            out.append(f"paths.yaml: {std} lost {sorted(removed)}")
    base_fields = (base_cfg["data"] or {}).get("fields", {})
    head_fields = (head_cfg["data"] or {}).get("fields", {})
    for field, meta in base_fields.items():
        if field not in head_fields:
            out.append(f"data-classification.yaml: {field} removed")
        elif head_fields[field] != meta:
            out.append(f"data-classification.yaml: {field} changed {meta} -> {head_fields[field]}")
    b, h = base_cfg["app"], head_cfg["app"]
    removed = set(b.get("always_apply", [])) - set(h.get("always_apply", []))
    if removed:
        out.append(f"app.yaml: always_apply lost {sorted(removed)}")
    if (h.get("tier") or 99) > (b.get("tier") or 99):
        out.append(f"app.yaml: tier lowered {b.get('tier')} -> {h.get('tier')}")
    added_na = set((h.get("not_applicable") or {})) - set((b.get("not_applicable") or {}))
    if added_na:
        out.append(f"app.yaml: new not_applicable {sorted(added_na)}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    tests = []
    for line in git(a.repo, "diff", "--name-status", a.base, a.head, "--", TESTS_DIR).splitlines():
        status, path = line.split("\t")[0], line.split("\t")[-1]
        if status[0] not in "MD" or not path.endswith(".py"):
            continue
        old = file_at(a.repo, a.base, path)
        result, tail = run_old_test(a.repo, path, old)
        tests.append({"path": path, "change": "deleted" if status[0] == "D" else "modified",
                      "control": control_of_test(path), "previous_version_on_head": result,
                      "weakened": result == "failed", "output_tail": tail})

    narrowed = config_narrowing(load_app_config(a.repo, a.base), load_app_config(a.repo, a.head))
    result = {"base": a.base, "head": a.head, "tests_changed": tests, "config_narrowed": narrowed}
    write_json(a.out, result)
    for t in tests:
        print(f"{t['path']}: {t['change']}, previous version on head = {t['previous_version_on_head']}"
              f"{'  -> WEAKENED' if t['weakened'] else ''}")
    for n in narrowed:
        print(f"config narrowed: {n}")
    if not tests and not narrowed:
        print("no control test or config changes")


if __name__ == "__main__":
    main()
