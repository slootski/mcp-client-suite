You are the Dev agent for step 4 of a take-home assignment: an automated black-box test suite for the MCP client inside Claude Code 2.1.296. Steps 1–3 are built and passed QA: the harness, the free tier (status matrix, handshake, credentials) and the model-run harness with D14/T1, D14/T2, D23/T2. A QA agent checks your work after you.

## Where things are

- Suite (edit here): `/Users/islootski/Documents/02-Personal/mcp-client-testing/mcp-client-suite/` (not a git repo). Read `observations.md`, `harness/model_run.py`, `harness/model_checks.py`, `harness/cost_ledger.py`, `tests/test_model_smoke.py` first and reuse them. Do not build a second harness.
- Earlier prompts: `mcp-client-suite/prompts/` (07 and 08 describe the model harness and what QA checked).
- Plan (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/MCP-Client-Testing/` — docs `11`, `15` (tests 1, 2, 3), `22` (all), `24`.
- Public docs (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/reference/`.
- Docker: `export PATH="$HOME/.docker/bin:$PATH"` first.
- API key: `~/.config/bay-mcp/key`, used only as `ANTHROPIC_API_KEY="$(cat ~/.config/bay-mcp/key)" ./run.sh …`. Never print it or write it anywhere.

## Money

Measured in step 3: $0.001–0.004 per model run. Your budget for this step: **$1.00** including retries and the repeat runs. Run targeted tests only (`-m model -k …`). Report the exact sum of `total_cost_usd`.

## Scope

### A. D15/T1 — the right tool among near-duplicates
Two servers, `calc` and `calc2`, both with `add(a, b)`. They return the same sum, but each fake logs its own server name, and `calc2` also adds a side-effect marker to its log. The prompt names one tool explicitly (`mcp__calc2__add`) and fixes `a` and `b`. Assert from the fakes' logs: exactly one `tools/call` reached `calc2` with `{a, b}` equal to `tool_use.input` (D); `calc` received no `tools/call` (D, but only after the gate shows both servers connected and a `tool_use` exists); `tool_use.name` is `mcp__calc2__add` and the input equals the prompt values (S, recorded).

### B. D15/T2 + T3 — argument fidelity and return value
A `create_ticket` tool with `title: string`, `priority: enum[low, medium, high]`, `tags: array[string]`, `due: string (date)`, plus (from plan review 5) an optional `notes` field left out, a non-ASCII title (e.g. `Café – 東京 ✓`), an empty-string tag, and a nested object `meta: {source: string, count: integer}`. The prompt fixes every value. Assert: server args == `tool_use.input`, field for field, array order, enum spelling, unicode unchanged, the left-out field absent (not `null`) (D); `tool_use.input` == the prompt's values (S). The fake returns a server-generated id (fresh random, e.g. `TCK-<8 hex>`) that appears nowhere in the prompt; assert the `tool_result` holds it (D) and record whether the final answer holds it (S).

### C. D22 — the repeat harness and the flake policy
- A repeat mechanism: a test marked as repeated runs N times (`REPEATS`, a named constant, 5). Each run is a separate `claude -p` with a fresh config dir and fresh canary/ids.
- D facts must hold in N of N runs. S facts are a pass rate; the test fails only if the rate is below the threshold (4 of 5), and the rate is written to the artifacts and printed.
- An S trigger that did not happen (no `tool_use`) makes that run's D check inconclusive; it is retried once, and the retry is logged. Retries never hide a D failure.
- Apply it to D15/T1 and D15/T2+T3 with the key. Apply it to the free handshake tests (D12/T1, T3) too: 5 of 5.
- Write the flake-policy table to `docs/flake-policy.md` (fact → expected variance → how the suite treats it: hard assert / pass rate / record only), covering every fact the suite checks so far. This table goes into PLAN.md and README.md later.

### D. Era
Doc 11 says P0 wire tests run twice: `MCP_PROTOCOL_NEGOTIATION=legacy` and unset. Run D15/T1 once with negotiation unset and confirm the D asserts hold the same way (record the first message). Do not repeat the unset era 5 times; one run is enough, and say so in the flake table.

## Fix first: QA findings from step 3

1. Medium — run.sh:42: `docker inspect .Config.Env` shows `ANTHROPIC_API_KEY=<value>`; a `kill -9` of `run.sh` skips the trap and leaves a container holding the key. Do not pass the key with `-e` or `--env-file`. Instead `docker cp` a 0600 file into the created container before `docker start`; the entrypoint reads it into the env of the pytest process only, then deletes the file. Prove it: `docker inspect` of the created container shows no key value (use a dummy value for the proof). The README later explains this deviation from the mail's literal `docker run -e ANTHROPIC_API_KEY`; the reviewer still only sets the env var on the host.
2. tests/test_model_smoke.py:188 — compare the `tool_result` text to the fake's own `sent` record for that JSON-RPC id, not to the canary the test set.
3. test_model_smoke.py:169, :290 — do not assert model-made facts as D: check the tool name against `init.tools`; record (do not assert) `subtype == "success"`.
4. test_model_smoke.py:157; model_checks.py:77 — assert the client facts that prove the pins worked: `era_seen` (`initialize` / `2025-11-25` under legacy) and `has_tool_search_tool` (false in T1, true in T2).
5. harness/model_run.py:191, 198 — charge the per-run cap on any exception (catch `BaseException`, charge, re-raise), and check `total_cost_usd` is present explicitly.
6. harness/cost_ledger.py:49 — print the budget with `%.4f`.
7. Policy: when the key is set and every model test of the run is inconclusive, the run exits non-zero with "all model tests inconclusive". Document this in `docs/flake-policy.md`.
8. Record in `observations.md`: the prompt-cache hit depends on the system prompt (server names), not the container; and 2.1.296 passes `ANTHROPIC_API_KEY` into stdio MCP servers by default.

## Rules (same as before)

No default parameter values, no hidden fallbacks, keyword arguments, named constants. Black-box only. Never print a secret. Doc-vs-observed differences: strict xfail + an `observations.md` line. Free tier passes with no key.

## Report back (under 350 words)

Files changed/added; run results; S pass rates per test; any D failure seen in any repeat (must be none, or it is a candidate product bug — keep its wire log); exact money spent; anything not done.
