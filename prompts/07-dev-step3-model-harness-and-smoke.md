You are the Dev agent for step 3 of a take-home assignment: an automated black-box test suite for the MCP client inside Claude Code 2.1.296. Steps 1 and 2 (harness, `claude mcp list` status matrix, handshake and credential tests, all `free`) are built and passed QA. This is the first step that calls the model, so it costs real money. A QA agent checks your work after you.

## Where things are

- Suite (edit here): `/Users/islootski/Documents/02-Personal/mcp-client-testing/mcp-client-suite/` (not a git repo). Read `observations.md`, `run.sh`, `harness/`, `fakes/`, `tests/` first and reuse them.
- Earlier prompts: `mcp-client-suite/prompts/`.
- Plan (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/MCP-Client-Testing/` — docs `11` (all of it again: the model-run rules), `14`, `22`, `23` (test 2), `24`, and `Documentation/R01…`, `R06…`.
- Public docs (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/reference/claude-code-docs/` — read `headless.md`, the `-p`/CLI flag reference, and the stream-json event shapes before writing code. Check every flag you use exists in 2.1.296 (changelog).
- Docker: `export PATH="$HOME/.docker/bin:$PATH"` first.
- API key: a real key is in `~/.config/bay-mcp/key`. Pass it only as `ANTHROPIC_API_KEY="$(cat ~/.config/bay-mcp/key)" ./run.sh …`. Never print it, never write it to a file, never put it in a command line that gets logged.

## Money rules (hard)

- The owner allows at most $20 in total for the whole night, for all agents, and asked to spend as little as possible. Your budget for this step: **$1.50**, including retries.
- Model: one pinned model by full id, `claude-haiku-5-5` (check it is accepted; if not, report and stop).
- Every `claude -p` run: `--max-turns` (4) and `--max-budget-usd` (0.25); check both flags exist in 2.1.296.
- Run only the model tests you are working on (`-m model -k <name>`). Do not run the full model tier more than twice.
- The suite keeps a cost ledger: sum `total_cost_usd` from every `result` event; stop the run (fail, with a clear message) when the sum passes `SUITE_BUDGET_USD`. Print the per-test cost and the total at the end and write it to `artifacts/<run-id>/cost.json`.

## Scope

### A. The model-run harness (doc 11), reused by all later model tests

- One helper that runs `claude -p` with: `--output-format stream-json --verbose`, `--model`, `--max-turns`, `--max-budget-usd`, `--permission-mode default`, `--allowedTools "mcp__<server>__*"` for the test's servers, `--permission-prompts none` (or the 2.1.296 equivalent — check the docs), `--mcp-config <file> --strict-mcp-config`, `--debug=mcp --debug-file <path>`, a fresh `CLAUDE_CONFIG_DIR`, non-root, never bypass mode. Every value passed explicitly (no defaults).
- Env pins from doc 11: `MCP_PROTOCOL_NEGOTIATION=legacy` for the bulk; `ENABLE_TOOL_SEARCH=false` for wire tests; explicit `MCP_TIMEOUT` and `MCP_TOOL_TIMEOUT`; `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS` short.
- A stream parser: `system/init` (servers + status, tools, `mcp_server_errors`), `tool_use` blocks (id, name, input), `tool_result` blocks (tool_use_id, content, is_error), the final `result` event (`total_cost_usd`, `is_error`, `num_turns`).
- The gate (doc 11): before any tool assert, every server of the test is `connected` in `system/init`, else the test is **inconclusive** (pytest skip with reason "inconclusive: <status>"), never pass.
- The D/S split (doc 11, doc 22): for every `tool_use` id, exactly one `tools/call` in the fake's log with the same name; server args == `tool_use.input` (D, hard assert); `tool_use.input` == the values fixed in the prompt (S, recorded). If the model did not call the tool, D is inconclusive.
- `run.json` adds: model id, era seen (first message, `protocolVersion`), `total_cost_usd`.
- The artifact scan covers the debug file; it must find no trace of the real key.
- Markers: `model` tests skip with a clear reason when `ANTHROPIC_API_KEY` is unset, so `./run.sh` with no key still passes the free tier.

### B. Tests

1. D14/T1 — minimal round trip. Tool `echo_canary` returns a canary generated fresh per run. Assert: (a) the final `result` text contains the exact canary (S, recorded: the model may paraphrase — decide and state the oracle), (b) a `tool_use` named exactly `mcp__<server>__echo_canary`, (c) a `tool_result` with the canary comes before the final message, (d) the fake log has exactly one `tools/call` for that id with the same args. (b)–(d) are D.
2. D14/T2 — variant with tool search at its default (on): the tool is still called (a `ToolSearch` call before it is allowed and recorded).
3. D23/T2 — broken config entry next to a healthy server (for example `{"type": …}` missing, or a `url` with no `type`): the run continues, the broken entry appears in `system/init` `mcp_server_errors` with its category, the healthy server's tool still works. Check the docs for the exact field and category names first.

### C. Measure and set the cap

After the tests pass, run the model tier once more, read `cost.json`, and write in `observations.md`: cost per test, cost per model run, and a proposed `SUITE_BUDGET_USD` for the full suite (estimate: number of model tests in doc 24 × eras × repeats × measured cost, with a margin; must stay far below $50). Set that value as the constant.

## Rules (same as before)

No default parameter values, no hidden fallbacks; keyword arguments; named constants. Black-box only. Never print a secret. Doc-vs-observed differences: strict xfail with the doc line + an `observations.md` line. Free tier must still pass with no key.

## Fix first: QA findings from step 2 (free tier, no key needed)

1. tests/test_handshake.py:165 — the "early request" filter counts the client's responses (an `id` but no `method`); a legal pong to a fake ping fails as `[None]`. Add `"method" in r["msg"]` to the filter.
2. tests/test_handshake.py:72 — the silent-fallback bound 3.0 ± 0.5 s failed once at 2.49 s on amd64 with `--cpus 0.25` (both timestamps come from a fake slowed by load). Use 3.0 ± 1.0 s (2.0–4.0) and state why it is still meaningful (immediate fallback ~3 ms, 12 s cancel, 15 s `MCP_TIMEOUT`).
3. Dockerfile:21-27 — bubblewrap is only checked for presence; QA showed claude never runs bwrap in this container (a logging shim was never called; an `exit 1` stub still gave a scrubbed env). Correct the comment and add the fact to `observations.md`.
4. tests/test_handshake.py:137 — assert `"clientInfo" in params` with a message before reading it.
5. tests/test_handshake.py docstring — the cross-test leak guard can never fire (the era key hashes command+env; each test has its own `FAKE_LOG`). Say so; isolation rests on the per-test config dir.
6. tests/test_credentials.py:154 — env-vars.md:404 does not exempt server-configured env, so `--env MY_SERVICE_TOKEN` surviving the scrub is not a documented fact. Record it in `observations.md` and assert nothing hard about it (keep the value logged).

## Report back (under 350 words)

Files changed/added; run results; **exact money spent in this step** (sum of `total_cost_usd`); cost per model run; the proposed suite cap; observed `system/init` fields used; any flag that does not exist in 2.1.296; anything not done.
