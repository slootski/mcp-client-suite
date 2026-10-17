You are the Dev agent for step 5 of a take-home assignment: an automated black-box test suite for the MCP client inside Claude Code 2.1.296. Steps 1–4 are built (harness, free tier, model harness, D14, D15, D22 repeats and flake policy). Step 4 QA failed on one medium item; fix it first (see "Fix first" at the end). A QA agent checks your work after you.

## Where things are

- Suite (edit here): `/Users/islootski/Documents/02-Personal/mcp-client-testing/mcp-client-suite/` (not a git repo). Read `observations.md`, `docs/flake-policy.md`, `harness/`, `fakes/`, and the existing model tests first, and reuse them.
- Earlier prompts: `mcp-client-suite/prompts/`.
- Plan (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/MCP-Client-Testing/` — docs `11`, `16` (tests 1, 2), `20` (test 1, and 2 for context), `21` (test 2, for context only), `22`, `24`.
- Public docs (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/reference/` — Claude Code `mcp.md`, `hooks.md` (`PostToolUseFailure`), changelog; MCP spec 2025-11-25 tools page (error handling) and transports (stdio termination).
- Docker: `export PATH="$HOME/.docker/bin:$PATH"` first.
- API key: `~/.config/bay-mcp/key`, used only through `run.sh` as before. Never print it or write it anywhere.

## Money

Your budget: **$1.00** including retries. Targeted runs only. Report the exact sum of `total_cost_usd`.

## Scope

### A. D16/T1 + T2 — tool execution error vs protocol error
Each case puts a fresh token in the error text.
1. T1, `isError: true`: the fake returns a normal result with `isError: true` and a text block holding the token. Assert (D): the `tool_result` is an error and holds the token; a `PostToolUseFailure` hook fires (a command hook passed with `--settings '<inline JSON>'` that appends the event to a file; check the hook docs for the event name and payload first); the run ends with a `result` event; the server stays connected and a next call in the same run works (the prompt asks for a second, different tool after the error, and the fake log shows it). The model's reply is S, recorded only.
2. T2, JSON-RPC error: the fake lists a tool in `tools/list`, then answers its `tools/call` with a JSON-RPC error (code -32602, message with the token). Assert the same D facts. Record exactly how the stream shows T1 vs T2 (is_error flag, content text, any prefix), side by side in `observations.md` — that comparison is the point of doc 16.
3. Repeat both with the D22 mechanism (N = 5, D 5/5).

### B. D20/T1 — stdio server crashes mid-call
The fake receives `tools/call`, logs it, then exits non-zero without replying. Assert (D): the run does not hang (a hard bound well under the test timeout, from the stream's timestamps or wall clock; state the bound and why); the `tool_use` gets a `tool_result` with `is_error: true` (record its text); the run ends with a `result` event. Settle the doc conflict empirically: does Claude Code restart the stdio server? Count spawns in the fake's own log (each start logs a line with its pid). Record the answer in `observations.md` with the spec line ("client SHOULD restart"?) and the Claude Code doc line. If you also see what doc 20 test 2 asks (crash while idle), record it, do not build it.
Run it 3 times; it must behave the same each time.

## Rules (same as before)

No default parameter values, no hidden fallbacks, keyword arguments, named constants. Black-box only. Never print a secret. Doc-vs-observed differences: strict xfail + an `observations.md` line. Free tier passes with no key. Add every new fact to `docs/flake-policy.md`.

## Fix first: QA findings from step 4

1. Medium — harness/model_flow.py:59-66, 87-88: when an attempt has no `tool_use`, the retry replaces `records` and nothing checks the dropped attempt. Break: attempt 0 has no `tool_use` but a `tools/call` reached calc2; attempt 1 is normal; `check_calc_d` passes. This breaks "a retry never hides a D failure". Fix: before a retry, assert that no `tools/call` reached any fake of that attempt (a call without a `tool_use` is a D failure, not an S miss). Keep the dropped attempt in the artifacts. Prove it with an offline break against a recorded run (no money). Add the rule to `docs/flake-policy.md`.
2. Low — run.sh:81-87: a `kill -9` between `docker cp` and `docker start` leaves the key file in a created container (`docker cp` can read it; `inspect` does not show it). Write it down as a residual risk in `docs/flake-policy.md` or a comment in run.sh; the README will cite it.
3. Low — docs/flake-policy.md:76, 84: the gate sits under "D, hard assert", but row 68 says inconclusive and retried. Give the gate its own row.
4. Low — docs/flake-policy.md: add rows for the version gate (exit 10), the `_meta["claudecode/toolUseId"]` pairing (undocumented; falls back to equal args), and `unparsed_stdout_lines`. Row 36 "exits 13" holds only with the key set; say so.
5. Low — tests/test_right_tool_args.py:419: Python `==` lets `3 == 3.0` and `True == 1` pass. Compare with `canonical` (type-strict).

## Report back (under 350 words)

Fix-first results (each item, with the offline break for item 1); files changed/added; run results; the T1-vs-T2 stream difference (quoted); restart yes/no with spawn counts; time to failure in the crash case; exact money spent; anything not done.
