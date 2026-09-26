#!/usr/bin/env python3
"""Bring subagent-written control tests into the release checkout.

Only results written by two_sided.py count (a subagent's own reply is ignored).
- proven-pass -> copy the test as is
- proven-fail -> copy the test, mark it xfail(strict=True) as a known gap, save the fix patch
                 to results/fixes/<control>.patch (for create_issue / propose_fix)
- unverified  -> not copied, listed

usage: collect_tests.py --work /work --repo /work/repo
       collect_tests.py --repo /work/repo --set-issue STD-LOG-01.a=https://github.com/.../issues/7
"""
import argparse
import re
import shutil
from pathlib import Path

from cc_lib import TESTS_DIR, read_json, test_prefix, write_json


def mark_xfail(path, reason):
    src = Path(path).read_text()
    if "xfail(strict=True" in src:
        return
    if not re.search(r"^import pytest", src, re.M):
        src = "import pytest\n" + src
    src = re.sub(r"^(def test_)", f'@pytest.mark.xfail(strict=True, reason="{reason}")\n\\1', src, flags=re.M)
    Path(path).write_text(src)


def set_issue(repo, control, url):
    for f in Path(repo, TESTS_DIR).glob(test_prefix(control) + "*.py"):
        text = f.read_text()
        new = re.sub(r'reason="control gap: ' + re.escape(control) + r'[^"]*"', f'reason="{url} {control}"', text)
        if new != text:
            f.write_text(new)
            print(f"{f.name}: xfail reason -> {url}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--set-issue", action="append", default=[])
    a = ap.parse_args()
    if a.set_issue:
        for item in a.set_issue:
            control, url = item.split("=", 1)
            set_issue(a.repo, control, url)
        return

    work = Path(a.work)
    fixes = work / "results/fixes"
    fixes.mkdir(parents=True, exist_ok=True)
    summary = {"proven_pass": [], "proven_fail": [], "unverified": []}
    for f in sorted((work / "results/subagents").glob("*.json")):
        r = read_json(f)
        control = r.get("control")
        if r.get("written_by") != "two_sided.py" or r.get("status") == "unverified":
            summary["unverified"].append({"control": control, "notes": r.get("notes", "no two_sided.py result")})
            continue
        src = Path(r["worktree"]) / r["test"]
        dst = Path(a.repo) / r["test"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if r["status"] == "proven-fail":
            mark_xfail(dst, f"control gap: {control} (issue pending)")
            patch = fixes / f"{control}.patch"
            patch.write_text(r["patch"])
            summary["proven_fail"].append({"control": control, "test": r["test"], "fix_patch": str(patch),
                                           "failing_output": r["release_output"][-800:]})
        else:
            summary["proven_pass"].append({"control": control, "test": r["test"]})
    write_json(work / "collected.json", summary)
    for k, items in summary.items():
        for i in items:
            print(f"{k}: {i['control']} {i.get('test', '')}")


if __name__ == "__main__":
    main()
