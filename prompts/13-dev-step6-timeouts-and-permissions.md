You are the Dev agent for step 6 of a take-home assignment: an automated black-box test suite for the MCP client inside Claude Code 2.1.296. Steps 1–5 are built (harness, free tier, model harness, D14, D15, D16, D20/T1, D22 repeats and flake policy). Step 5 QA failed on one medium item; fix it first (see "Fix first" at the end). A QA agent checks your work after you. This is the last test step; docs come next.

## Where things are

- Suite (edit here): `/Users/islootski/Documents/02-Personal/mcp-client-testing/mcp-client-suite/` (not a git repo). Read `observations.md`, `docs/flake-policy.md`, `harness/`, `fakes/`, and the existing model tests first, and reuse them.
- Earlier prompts: `mcp-client-suite/prompts/`.
- Plan (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/MCP-Client-Testing/` — docs `11` (the known-defect rule), `19` (tests 1, 2, 3), `23` (tests 9, 10), `24`, and `Documentation/R01…`, `R06…`.
- Public docs (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/reference/` — Claude Code `env-vars.md`, `mcp.md`, `hooks.md`, `permissions` / `iam` pages, changelog (lines cited in doc 23: changelog.md:212, :297); MCP spec 2025-11-25 cancellation and progress.
- Docker: `export PATH="$HOME/.docker/bin:$PATH"` first.
- API key: `~/.config/bay-mcp/key`, used only through `run.sh`. Never print it or write it anywhere.

## Money

Your budget: **$1.50** including retries. Targeted runs only. Report the exact sum of `total_cost_usd`.

## Scope

### A. D19/T1 + T3 — idle timeout and cancellation
1. T1: the fake receives `tools/call` and never answers, never sends progress. `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT=3000`, `MCP_TOOL_TIMEOUT=60000`, no per-server `timeout`. Assert on the fake's clock: the client gives up at ≥ 3 s and < 5 s (state the tolerance; QA found earlier that the fake's clock can lag under load — use the time the fake logged the request as the start). Check env-vars.md for the exact name and semantics first; if the name differs, follow the docs and say so.
2. T3: from the fake's log, `notifications/cancelled` arrives referencing the original request id after the client gives up, and no other message for that request follows. Under legacy negotiation this is a SHOULD: a miss is a warning in the report, not a failure (doc 19 test 3). Run once with negotiation unset too and record whether it differs.
3. Optional only if budget and time allow: T2 (progress resets the idle timer, not the wall-clock cap), gated on `params._meta.progressToken` being present, else inconclusive.
4. Repeat T1+T3 3 times; the bound must hold every time.

### B. D23/T9 (+T10 variant) — permission hooks and deny rules
1. T9: a command hook with matcher `mcp__guard__.*` that denies `delete_all` (passed with `--settings '<inline JSON>'`; the hook logs every call to a file). Gate: an allowed call to `list_items` on the same server reached the server first. Assert: a `tool_use` for `delete_all` exists; the server log has no `tools/call` for it; the hook log shows the deny. Variants: matcher `mcp__guard` (no `.*`) — record what it matches; a hook that exits 1 lets the call through unless `onFailure` is `block` (check hooks.md for the exact field).
2. T10: a deny rule for `mcp__guard__delete_all` plus an allow rule for the rest: the server never sees the call; record whether the tool is missing from `system/init` `tools` or listed in `permission_denials`. Then the two scoping variants from plan review 5, one check per bug, both strict xfails on 2.1.296 that cite the changelog line and the fixed version (doc 11 known-defect rule):
   - Variant A, allow scoping: second server named `guard__ops`, `--allowedTools "mcp__guard"` only; assert no call reaches `guard__ops` (changelog.md:212).
   - Variant B, deny scoping: `--allowedTools "mcp__guard__ops__*"` plus a server-level deny `mcp__guard__ops`; assert no call reaches `guard__ops` (changelog.md:297).
   Read those changelog lines first; if the observed 2.1.296 behavior already matches the fixed behavior, do not xfail — record it.

## Rules (same as before)

No default parameter values, no hidden fallbacks, keyword arguments, named constants. Black-box only. Never print a secret. Doc-vs-observed differences: strict xfail + an `observations.md` line. Free tier passes with no key. Add every new fact to `docs/flake-policy.md`.

## Fix first: QA findings from step 5

1. Medium — harness/model_flow.py:91-126; tests/test_crash.py:278: a client that exits after the error or the crash (stream has `system/init` and the first `tool_result`, no next `tool_use`, no `result` event) is reported as inconclusive, retried, then skipped. The D facts "the run ends with a `result` event" and "the next call works" are never checked, and the full suite exits 0. QA's offline mutation `client_died_after_*` made D16 T1, T2 and crash ×3 all SKIP. `run_print` accepts any return code and a missing `result`. Fix: before the retry decision, hard-assert `stream.result is not None` (same place as the check at :125). In test_crash, run the crashed-call asserts (`tool_result` exists, `is_error`, time bound) whenever the crash `tool_use` exists, before any skip. Prove it with the same offline mutation (no money): each case must FAIL, not skip. Add a flake-policy row.
2. Low — tests/test_crash.py:127: hardcoded `"claudecode/toolUseId"` and a KeyError when `_meta` lacks it. Use `TOOL_USE_ID_META` and `has_tool_use_meta`.
3. Nit — tests/test_right_tool_args.py:419: the comment points at the wrong line; the `canonical` compare is at :420-421.

## Report back (under 350 words)

Fix-first results (with the offline mutation for item 1); files changed/added; run results; measured idle-timeout times (3 runs); cancel seen yes/no per era; hook and deny results; which variants are xfail and why; exact money spent; anything not done.
