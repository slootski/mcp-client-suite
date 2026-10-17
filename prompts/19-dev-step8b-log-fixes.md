You are the Dev agent for step 8b of a take-home assignment: an automated black-box test suite for the MCP client inside Claude Code 2.1.296. Step 8 (narrating logs, Expected/Actual asserts; spec `prompts/17-dev-step8-test-logs-and-asserts.md`) passed QA with low findings. Fix them.

## Where things are

- Suite (edit here): `/Users/islootski/Documents/02-Personal/mcp-client-testing/mcp-client-suite/`. The log helper is `harness/check.py`; the format is `harness/log_format.py`.
- Docker: `export PATH="$HOME/.docker/bin:$PATH"` first.
- No API key for this step: free runs and offline replays only. Money budget: **$0**.

## Fix: QA findings from step 8

1. Noise (worst first). suite.log grew 221 KB → 1,150 KB and report.html 1.38 MB → 2.52 MB.
   - `harness/claude_cli.py:122`: the `claude -p` "waiting done" line prints 200 chars of init JSON (48 KB in total); `model_run.py:225` already logs the stream summary. For `-p` runs, log exit code, time and byte counts only. Keep the stdout preview for the short `claude mcp …` commands.
   - Helpers that repeat the same block per test go to DEBUG or log once: the `d_error_result` block (logged twice per test), `harness/hooks.py:59` (×3), `tests/conftest.py:344` (~380 chars ×91: shorten it, e.g. the pins as a count plus the names that differ from the default set).
   - Report the new sizes on a free run vs the step 8 free run `artifacts/20261017T095016Z-72477`.
2. `tests/test_harness_offline.py:290, 460, 470`: three `raise AssertionError("the recording has no tool_result…")` are not in Expected/Actual form. Use `expect_true` (or the matching helper) with Expected/Actual.
3. Tests with no `step` line: the 4 `*_s_rate` tests (e.g. `test_right_tool_args.py:349`) and `test_stdio_crash_mid_call_same_every_run`; no `got` line in `test_recorded_run_pure_check`. Add a `step` ("read the S samples of the 5 repeats of …") and `got` lines. In the S-rate checks, make Actual short: the rate and the per-repeat values, not the whole runs list.
4. `tests/test_handshake.py:162`: the `clientInfo.version` check shows the whole dict and the 300-char cut hides the version. Use `actual=client_info["version"]`.
5. `tests/test_harness_offline.py:390`: the renamed match string no longer pins `Actual: 0`. Match on `"Expected: 1. Actual: 0"` (or the exact new text) so the test still proves the count.
6. Info: ERROR lines appear in passing offline mutation tests (they are the expected failures being provoked). Add one line to README "Reading a test's log" saying so.

## Rules

No default parameter values (AST scan), keyword arguments, named constants. Do not change what any test checks. Prove outcomes are unchanged: free run with no key, per-test junit outcomes vs `artifacts/20261017T095016Z-72477/junit.xml` — must be identical (51 passed, 2 xfailed, 44 skipped, exit 0). Secret scan clean.

## Report back (under 250 words)

Each fix done (file:line); new suite.log / report.html sizes vs before; junit diff (must be empty); secret scan; AST result.
