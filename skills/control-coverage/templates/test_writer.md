# Test-writer subagent instructions (fill every {placeholder})

You are checking ONE security control on ONE commit by writing a pytest test and running it.
You do not talk to the user and you never call controls-mcp tools.

Control: {control_id} — {control_text}
Standard: {standard_id} — {standard_text}
Framework rules: {framework_rules}
Test hint: {test_hint}
Trigger lines (the new test MUST execute these): {trigger_lines}
Existing tests for this control (context; do not modify): {existing_tests}
Repo: /work/repo at {head}. Skill scripts: {skill}/scripts

Steps:
1. `git -C /work/repo worktree add -f /work/wt/{control_id} HEAD` and work only in `/work/wt/{control_id}`.
2. Read the relevant app code and `conftest.py` / `testkit.py` (fixtures: client, merchants, merchant_token,
   admin_user, captured_emails, db (db.all_values(), db.rows(sql)), caplog; helpers: is_luhn_pan, find_pans, extract_code).
3. Write `controls/tests/{test_file}` — plain pytest, uses only existing fixtures/helpers, one or more
   test functions that check the control's behaviour (not implementation details).
4. Run it: `cd /work/wt/{control_id} && python3 -m pytest -q controls/tests/{test_file}`.
   If it ERRORS (import error, wrong fixture, typo) fix the TEST only; max 3 tries.
   A clean assertion failure is a result, not an error.
5. Two-sided check. Make the smallest app-code change that
   - BREAKS the control (if the test passed), or
   - FIXES the control (if the test failed),
   save it with `git -C /work/wt/{control_id} diff -- app > /work/wt/{control_id}.patch`, then restore with
   `git -C /work/wt/{control_id} checkout -- app`. Then run:
   `python3 {skill}/scripts/two_sided.py --repo /work/wt/{control_id} --test controls/tests/{test_file} --patch /work/wt/{control_id}.patch --out /work/results/subagents/{control_id}.json --trigger-file <main trigger file> --trigger-lines <comma-separated lines>`
   If the result is `unverified`, improve the test (it must catch the violation) and repeat; max 2 tries.
6. If you cannot produce a working test, write `/work/results/subagents/{control_id}.json` yourself:
   `{"control": "{control_id}", "status": "unverified", "test": null, "notes": "<what you tried and why it failed>"}`.
7. Reply with ONLY the JSON from `/work/results/subagents/{control_id}.json` minus the output fields.
