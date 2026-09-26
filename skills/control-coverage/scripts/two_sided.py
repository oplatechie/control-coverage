#!/usr/bin/env python3
"""Two-sided check for one agent-written control test.

1. Run the test on the release code.
2. Apply a patch (sandbox only), run the test again, then revert the patch.
   - test passed on release -> patch must BREAK the control -> test must now fail
   - test failed on release -> patch must FIX the control   -> test must now pass
3. Record both runs. Also records which trigger lines the test executed.

usage: two_sided.py --repo WORKTREE --test controls/tests/test_std_x_a.py --patch fix_or_break.diff
                    --out results/subagents/STD-X.a.json [--trigger-file app/x.py --trigger-lines 10,11]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from cc_lib import control_of_test, write_json


def run_test(repo, test):
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", test,
                        "--cov=app", "--cov-report=json:.cc_cov.json"],
                       cwd=repo, capture_output=True, text=True)
    cov = {}
    cov_file = Path(repo) / ".cc_cov.json"
    if cov_file.exists():
        cov = json.loads(cov_file.read_text()).get("files", {})
        cov_file.unlink()
    return ("passed" if p.returncode == 0 else "failed"), p.stdout[-1200:], cov


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--test", required=True)
    ap.add_argument("--patch", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--trigger-file")
    ap.add_argument("--trigger-lines", default="")
    a = ap.parse_args()

    release, release_out, cov = run_test(a.repo, a.test)
    patch = str(Path(a.patch).resolve())
    applied = subprocess.run(["git", "-C", a.repo, "apply", patch], capture_output=True, text=True)
    if applied.returncode != 0:
        sys.exit(f"patch did not apply: {applied.stderr}")
    try:
        counter, counter_out, _ = run_test(a.repo, a.test)
    finally:
        subprocess.run(["git", "-C", a.repo, "apply", "-R", patch], check=True)

    kind = "breaking" if release == "passed" else "fix"
    expected = "failed" if kind == "breaking" else "passed"
    ok = counter == expected
    status = ("proven-pass" if release == "passed" else "proven-fail") if ok else "unverified"

    executed = None
    if a.trigger_file:
        want = {int(x) for x in a.trigger_lines.split(",") if x}
        ran = set(cov.get(a.trigger_file, {}).get("executed_lines", []))
        executed = {"file": a.trigger_file, "wanted": sorted(want), "executed": sorted(want & ran)}

    result = {"control": control_of_test(a.test), "test": a.test, "status": status,
              "release_run": release, "counter_patch_kind": kind, "counter_run": counter,
              "patch": Path(a.patch).read_text(), "trigger_coverage": executed,
              "release_output": release_out, "counter_output": counter_out}
    write_json(a.out, result)
    print(f"{result['control']}: release={release}, {kind} patch -> {counter} => {status}")


if __name__ == "__main__":
    main()
