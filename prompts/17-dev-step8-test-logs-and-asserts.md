You are the Dev agent for step 8 of a take-home assignment: an automated black-box test suite for the MCP client inside Claude Code 2.1.296. The suite is built, documented and passed a final QA. A QA agent checks your work after you.

## Why this step

The user opens `artifacts/<run-id>/report.html` (pytest-html) and reads each test's log. Today a test row shows a few harness lines, and a failed assert often shows a bare condition. The user's rule for logs, in their words:

> each test action should have log
> each status return status should have log
> when you wait - log like start waiting for ...command.. when the waiting is done -> waiting done the response is...
> the general idea is that the test tell what did he did and what did it receive for his request
> the assertion should be self explainable like Expected:... Actual:

## Where things are

- Suite (edit here): `/Users/islootski/Documents/02-Personal/mcp-client-testing/mcp-client-suite/` (not a git repo). Read `README.md`, `docs/flake-policy.md`, `harness/`, `fakes/`, `tests/` first.
- The logger is already in place: `harness/log_format.py` (the line format below), `pytest.ini` (`log_level = DEBUG`), `tests/conftest.py` (installs the format at session start; puts each test's artifact links and `run.json` into report.html), `harness/entrypoint.py` (`--log-file suite.log`), `run.sh` (passes the host `TZ`). Some log calls exist in `harness/claude_cli.py`, `model_run.py`, `model_flow.py`, `model_checks.py`, `mcp_status.py`, `fakes_ctl.py`, `cost_ledger.py`, `known_defects.py`. Keep the format exactly:
  `12:05:06.36 2026-10-17 [INFO    ] claude_cli.py:97 run_claude() - exit 0 in 0.094 s`
- Docker: `export PATH="$HOME/.docker/bin:$PATH"` first.
- API key: `~/.config/bay-mcp/key`, only as `ANTHROPIC_API_KEY="$(cat ~/.config/bay-mcp/key)" ./run.sh …`. Never print it or write it anywhere.

## Money

Your budget: **$0.30**: targeted model runs while you work, then exactly one full run with the key at the end. Report the exact sum of `total_cost_usd`.

## Scope

### A. A small check-and-log helper
Add `harness/check.py` (or similar), used by every test and harness check, for example:
- `step(*, text)`: INFO line for a test action ("add stdio server fake_x with --env FAKE_MODE=hang").
- `expect_equal(*, what, expected, actual)`, `expect_true(*, what, expected, actual, holds)`, `expect_in(...)` / `expect_not_in(...)` as needed: each logs one line `check <what>: Expected: <expected>, Actual: <actual> -> OK` (INFO) or `-> FAIL` (ERROR), then raises `AssertionError("<what>: Expected: <expected>. Actual: <actual>.")` on a miss. Long values are cut in the log line (a named constant), never in a way that hides the difference.
- `expect_documented` in `harness/known_defects.py` keeps raising `DocumentedBehaviorMismatch` (the strict xfails depend on that type), but its message and log line get the same Expected/Actual form, with the doc line as Expected.

### B. Waits: start and end
Every place the suite waits logs a start line and an end line with the response:
- `run_claude`: `start waiting for: claude mcp list` … `waiting done (0.43 s): exit 0, stdout: <first N chars, redacted>`; `claude -p` the same, with the stream summary (events, tool_use names, result present, cost).
- fake readiness (`fakes_ctl._wait_ready`), fake stop, and any poll loop or `sleep` in tests or harness (grep for `time.sleep`, `wait(`, `poll`): start, end, and what came back (or the timeout).

### C. Every test narrates itself
Go through every test in `tests/` (all 11 files, free and model, offline replays too):
- each action (add/remove server, start fake, write config, run a command, mutate a recording) gets a `step` line;
- each status or returned value it reads (status line, detail, era, tool_result text, hook log entry, spawn count, timing) gets a log line;
- every `assert` becomes an Expected/Actual check (via the helper, or a message in that form). No bare `assert x` left in `tests/` or in the harness checks; list any you leave and why (for example, a guard inside a helper that can never be reached by a test).
- The S facts that are recorded, not asserted, get a `record` log line ("S recorded: canary in answer: True").

### D. Secrets
Log lines must never hold a secret. Log only redacted text: `registry.redact_text`, `redact_argv`, fingerprints. Never log raw `claude mcp get` output (2.1.296 prints the configured header in clear: finding 5) without redaction. The entrypoint scans report.html and suite.log after the run; it must stay clean.

### E. Docs
README: a short "Reading a test's log" paragraph with 6–10 real lines from one test (copied from a real suite.log). PROMPTS.md: add rows for this prompt and the QA prompt `18-qa-step8-test-logs-and-asserts.md`.

## Rules (same as before)

No default parameter values (AST scan before you finish), keyword arguments, named constants, no hidden fallbacks. Black-box only. Do not change what any test checks: same asserts, same outcomes (86 passed, 11 xfailed with the key; free tier 51 passed, 2 xfailed, 44 skipped without). Prove it: compare the junit outcomes per test before and after.

## Report back (under 350 words)

Files changed; the helper's API; how many asserts converted, any left and why; one real test log (10–15 lines) from report.html; free and full run results (counts, exit, per-test outcome diff vs before); secret scan; exact money spent.
