# Test-writer subagent instructions (fill every {placeholder})

You check ONE security control on ONE commit by writing a pytest test and PROVING it with a script.
You never talk to the user and never call controls-mcp tools.
**Only the file written by `two_sided.py` counts. Your own reply is not used as evidence.**

Control: {control_id} {control_name} — {control_text}
Standard: {standard_id} {standard_title}
Test hint: {test_hint}
Code the test MUST execute: {trigger_file} lines {trigger_lines}
Existing tests for this control (read for style; do not modify): {existing_tests}
Test file to create: controls/tests/{test_file}
Skill scripts: {skill}/scripts

Do exactly these steps:

1. Create your own checkout:
   `git -C /work/repo worktree add -f /work/wt/{control_id} HEAD && cd /work/wt/{control_id}`
2. Read `{trigger_file}`, `conftest.py` and `testkit.py`. Fixtures: client, merchants, merchant_token,
   admin_user, admin_session, captured_emails, db (db.all_values(), db.rows(sql, params)), caplog.
   Helpers: is_luhn_pan, find_pans, totp_code.
3. Write `controls/tests/{test_file}`: plain pytest, existing fixtures only, checks the control's
   behaviour through the API, and exercises the code above.
4. Run `python3 -m pytest -q controls/tests/{test_file}`.
   - Errors (import error, wrong fixture, typo): fix the TEST, re-run. Max 3 tries.
   - A clean assertion failure is a RESULT (the app breaks the control). Keep the test as is.
5. Make the counter patch in app code (never in controls/ or tests/):
   - test PASSED → the smallest change that BREAKS the control (e.g. remove the audit call, store the raw number);
   - test FAILED → the smallest change that FIXES the control (e.g. add the missing audit call).
   Save it and restore the code:
   `git diff -- app > /work/wt/{control_id}.patch && git checkout -- app`
6. Prove it (required):
   `python3 {skill}/scripts/two_sided.py --repo /work/wt/{control_id} --test controls/tests/{test_file} --patch /work/wt/{control_id}.patch --out /work/results/subagents/{control_id}.json --trigger-file {trigger_file} --trigger-lines {trigger_lines}`
   It prints `proven-pass`, `proven-fail` or `unverified`. If `unverified`, improve the test or the
   patch and run step 6 again (max 2 tries).
7. Only if you could not get a result from step 6, write
   `/work/results/subagents/{control_id}.json` = `{"control": "{control_id}", "status": "unverified", "notes": "<what failed>"}`.
8. Reply with one line: `<control_id> <status from two_sided.py>`.
