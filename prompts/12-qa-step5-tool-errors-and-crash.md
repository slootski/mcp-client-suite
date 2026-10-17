You are the QA agent for step 5 of a take-home assignment: an automated black-box test suite for the MCP client inside Claude Code 2.1.296. Check the Dev agent's work hard; do not trust its report.

## Where things are

- Suite: `/Users/islootski/Documents/02-Personal/mcp-client-testing/mcp-client-suite/` (not a git repo).
- The spec you check against: `mcp-client-suite/prompts/11-dev-step5-tool-errors-and-crash.md`. Read it first, including "Fix first". The previous QA prompt `10-…` shows the style.
- Plan (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/MCP-Client-Testing/` docs `11`, `16`, `20`, `22`.
- Public docs (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/reference/` — Claude Code `hooks.md`, `mcp.md`, changelog; MCP spec 2025-11-25 tools page and transports.
- Docker: `export PATH="$HOME/.docker/bin:$PATH"` first.
- API key: `~/.config/bay-mcp/key`, only as `ANTHROPIC_API_KEY="$(cat ~/.config/bay-mcp/key)" ./run.sh …`. Never print it or write it anywhere.

## Money

Your budget: **$0.50**. Prefer offline breaks against recorded runs where they prove the same thing; spend on live runs only where a live run is needed. Report the exact sum of `total_cost_usd`.

## Dev's claims

Confirm or refute each.

1. Fix-first 1: `assert_every_call_has_a_tool_use` (model_checks.py) runs on every attempt before the retry decision; `tests/test_harness_offline.py` (3 free tests) replays `tests/data/recorded-d15-t1/` with `run_print` stubbed; without the check the break reports `DID NOT RAISE`. Items 2–5 done (run.sh comment + "Residual risks" section; gate rows split; version gate / `_meta` pairing / `unparsed_stdout_lines` rows; `canonical` compare at test_right_tool_args.py:419).
2. No key: 36 passed, 32 skipped, 2 xfailed. D16/T1 and T2: D 5/5, S 5/5, no retries. Regression of D14/T1, D15/T1[0], D15/T2[0] passes.
3. T1 vs T2 look the same in the stream: `is_error: true`, content a plain string equal to the fake's text, no prefix; `tool_use_result` = `"Error: <text>"`; code -32602 appears nowhere (stream, hook input, debug log); `PostToolUseFailure` fires once in both; only difference is a debug-log `[ERROR] MCP server "booking" ...` line for T1.
4. Crash: error `tool_result` `"Connection closed"` 23–24 ms after the fake exits; bound 5 s (else the 30 s `MCP_TOOL_TIMEOUT`). Claude Code restarts the stdio server lazily on the next call: 2 spawns per run in 3/3 runs, the new process starts 12–27 ms after the next `tool_use`, gets no `tools/list`, the call succeeds. This contradicts mcp.md:377 ("doesn't reconnect them automatically"), so the one-spawn check is a strict xfail; it matches spec 2026-07-28 `basic__transports__stdio.md:116` ("SHOULD restart"), absent from the 2025-11-25 transports page.
5. The crash cross-run signature was narrowed after the paid runs and checked only offline.
6. Spend $0.043655 over 19 runs. Not done: D16 with negotiation unset; doc 20 test 2.

## What to check

A. **Fix first, item 1**: a `tools/call` that reached a fake in an attempt with no `tool_use` must now fail the test as D, never be hidden by the retry. Prove it with your own offline break. Also check items 2–5 are done.

B. **D16/T1 vs T2**: is each D fact really the client's? Can each fail? Offline breaks: `tool_result` not an error; token missing; the hook log empty; no `result` event; the second tool call missing from the fake log. Is the hook event name and payload as `hooks.md` says? Is the T1-vs-T2 comparison in `observations.md` quoted from real stream output (check an artifact)?

C. **D20/T1**: is the "no hang" bound justified and enforced from timestamps, not only the pytest timeout? Is the restart answer backed by spawn lines with pids in the fake's log? Are the spec line and the Claude Code doc line quoted correctly? Same result in all 3 runs? **Key risk:** the crash test reports "xfailed" because of the one-spawn strict xfail. Prove that a broken hard assert (no error `tool_result`, no `result` event, over the time bound) makes the test FAIL, not hide under the xfail. Is the "restart" reading right — could the second spawn be something other than a restart (e.g. a fresh connect for a new turn)? Read mcp.md around line 377 and the spec line yourself.

D. **Repeats**: D16 runs N = 5 from the one `REPEATS` constant; D 5/5; S recorded as a rate.

E. `docs/flake-policy.md`: every new fact has a row (fact → expected variance → treatment).

F. Run the free tier with no key (counts, exit 0) and the new model tests once with the key.

G. Secrets: key absent from every new artifact and hook log. No default parameter values: parse every `.py` (AST), list hits.

## Rules

Do not edit the real suite folder. Never print the key. Delete scratch copies and images. If you run `./run.sh` in the real folder, say which `artifacts/` dirs you created.

## Report back (under 350 words)

Verdict PASS / FAIL; table finding | severity | file:line | fix; claims confirmed; **exact money you spent**.
