You are the QA agent for step 6 of a take-home assignment: an automated black-box test suite for the MCP client inside Claude Code 2.1.296. This is the last test step. Check the Dev agent's work hard; do not trust its report.

## Where things are

- Suite: `/Users/islootski/Documents/02-Personal/mcp-client-testing/mcp-client-suite/` (not a git repo).
- The spec you check against: `mcp-client-suite/prompts/13-dev-step6-timeouts-and-permissions.md`. Read it first, including "Fix first". The previous QA prompt `12-…` shows the style.
- Plan (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/MCP-Client-Testing/` docs `11` (known-defect rule), `19`, `22`, `23`.
- Public docs (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/reference/` — Claude Code `env-vars.md`, `hooks.md`, `permissions` / `iam` pages, `mcp.md`, changelog (lines 212, 297); MCP spec 2025-11-25 cancellation.
- Docker: `export PATH="$HOME/.docker/bin:$PATH"` first.
- API key: `~/.config/bay-mcp/key`, only as `ANTHROPIC_API_KEY="$(cat ~/.config/bay-mcp/key)" ./run.sh …`. Never print it or write it anywhere.

## Money

Your budget: **$0.60**. Prefer offline breaks against recorded runs where they prove the same thing; spend on live runs only where a live run is needed. Report the exact sum of `total_cost_usd`.

## Dev's claims

Confirm or refute each.

1. Fix-first 1: every attempt hard-asserts the `result` event before the retry decision, and runs a new `attempt_checks` list (D16 error `tool_result`; `test_crash.crash_attempt_check`: one `tool_result`, `is_error`, 5 s bound). Offline proof in `tests/test_harness_offline.py` with mutations `client_died_after_first_tool_result` and `crash_result_dropped`: 4 cases FAIL with `AssertionError`, no retry. Item 2 done; item 3 left (comment sits above :420-421). Signature `allowed_servers` → `allowed_tools`, `attempt_checks` added, every call site updated.
2. D19/T1 with `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT=3000`, `MCP_TOOL_TIMEOUT=60000`: the client gives up at 30.009–30.018 s (8 runs, both eras); debug log says "for 30s (idle timeout 3s)". A probe with idle 31 s gave up at 60.023 s, so the idle check runs on a 30 s tick. The hard window [2.75 s, 50 s) held 8/8; the documented window [2.75 s, 5 s) failed 8/8 and is a strict xfail citing env-vars.md:337.
3. D19/T3: `notifications/cancelled` never sent in either era (warning only); no other message for the request. Both eras negotiate 2025-11-25.
4. D23/T9: deny → `tool_result` `PreToolUse:mcp__guard__delete_all hook error: <reason>`; matcher `mcp__guard` → hook never runs, call reaches server; exit 1 without `onFailure` → call goes through; `onFailure: "block"` → blocked with `…failed; blocking because onFailure is "block"`. All match the docs.
5. D23/T10 base: `delete_all` missing from `system/init`; a guessed call gets "No such tool available" and is not in `permission_denials`. Variants A (changelog.md:212) and B (changelog.md:297) both still broken on 2.1.296, strict xfails citing "fixed in 2.1.299". Variant B skips when its servers are not connected.
6. No `permission_denied` system message in any stream; not xfailed (headless.md:333 covers prompt denials, not hook denials).
7. No key: 43 passed, 43 skipped, 2 xfailed, exit 0. Model run: 18 passed, 9 xfailed, exit 0. Spend $0.068461985 over 29 runs. T2 not done (30 s tick).

## What to check

A. **Fix first, item 1**: a client that dies after the error or crash (no `result` event, no next `tool_use`) must now FAIL the D16 and crash tests, not skip. Prove it with your own offline mutation. Items 2–3 done?

B. **D19/T1 idle timeout**: is the env var name and meaning taken from `env-vars.md`? Is the bound measured on the fake's clock from the logged request time, with a stated tolerance? Can it fail: offline breaks for "gave up too early" (< 3 s), "too late" (≥ 5 s) and "never gave up". Did it hold in all 3 runs? Is a pass not just the 60 s `MCP_TOOL_TIMEOUT` or a pytest timeout firing? **Key risk:** the Dev widened the hard window to [2.75 s, 50 s) after seeing 30 s. Is that window still a real test (would it catch "the idle timeout is ignored and the 60 s cap fires")? Would a tighter observed-behavior window (e.g. 30 s ± tolerance) be better, recorded as observed, with the documented 3–5 s as the strict xfail? Is the "30 s tick" reading backed by the 31 s probe, or could it be a 30 s floor? Read env-vars.md:337 yourself and judge whether the xfail claim is a fair reading of the doc.

C. **D19/T3 cancellation**: `notifications/cancelled` with the right `requestId`, after the give-up, and nothing for that id after it. Is a miss under legacy a warning (SHOULD), not a fail, and is that written down? Unset era recorded?

D. **D23/T9 hook deny**: the gate (an allowed `list_items` reached the server first) — if the gate fails, is the test inconclusive, never a pass? Assert: `delete_all` `tool_use` exists, no `tools/call` for it on the server, the hook log shows the deny. Offline breaks: the server gets the call; the hook log is empty; no `delete_all` `tool_use` (must be inconclusive/S miss, not pass). Are the matcher variant (`mcp__guard` without `.*`) and the hook-exit-1 / `onFailure` variant recorded with what `hooks.md` says?

E. **D23/T10 deny rule and variants A/B**: read changelog.md:212 and :297 yourself. Is each strict xfail tied to exactly one bug, citing the line and the fixed version? If 2.1.296 already behaves like the fixed version, the test must not be xfail. Does an XPASS fail the run (strict)? Are the "tool hidden from `system/init` tools" vs "listed in `permission_denials`" facts recorded from a real stream?

F. **Repeats and flake policy**: N from `REPEATS` where the spec asks; every new fact has a flake-policy row.

G. Run the free tier with no key (counts, exit 0) and the new model tests once with the key. Secrets: key absent from every new artifact and hook log (`grep -F -f`, never put the key in argv). No default parameter values: AST scan of every `.py`.

## Rules

Do not edit the real suite folder. Never print the key. Delete scratch copies and images. If you run `./run.sh` in the real folder, say which `artifacts/` dirs you created.

## Report back (under 350 words)

Verdict PASS / FAIL; table finding | severity | file:line | fix; claims confirmed; **exact money you spent**.
