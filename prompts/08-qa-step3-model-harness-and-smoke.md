You are the QA agent for step 3 of a take-home assignment: an automated black-box test suite for the MCP client inside Claude Code 2.1.296. Step 3 added the model-run harness and the first model tests. Check it hard; do not trust the Dev report.

## Where things are

- Suite: `/Users/islootski/Documents/02-Personal/mcp-client-testing/mcp-client-suite/` (not a git repo).
- The spec you check against: `mcp-client-suite/prompts/07-dev-step3-model-harness-and-smoke.md`. Read it first.
- Plan (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/MCP-Client-Testing/` docs `11`, `14`, `22`, `23` (test 2).
- Public docs (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/reference/claude-code-docs/` (`headless.md`, CLI reference, changelog).
- Docker: `export PATH="$HOME/.docker/bin:$PATH"` first.
- API key: `~/.config/bay-mcp/key`. Use only as `ANTHROPIC_API_KEY="$(cat ~/.config/bay-mcp/key)" ./run.sh …`. Never print it or write it anywhere.

## Money

Your budget: **$0.50** total. Run only targeted model tests (`-m model -k …`). Each break in B costs one run of one test. Report the exact sum of `total_cost_usd` you spent.

## Dev's claims

1. No key: 17 passed, 2 xfailed, 3 model tests skipped "key not set".
2. With key: D14/T1, D14/T2, D23/T2 pass; 6 model runs cost $0.0106; per run $0.0037 cold, $0.0006–0.0013 warm.
3. `SUITE_BUDGET_USD = 5.00`; the ledger stops the run when the sum passes it.
4. `system/init` fields: `mcp_servers[].{name,status}`, `mcp_server_errors[].{name,type,message}` with `url_missing_type`.
5. `tools/call` carries `_meta["claudecode/toolUseId"]` equal to `tool_use.id`.
6. The prompt is placed right after `-p` because `--mcp-config` / `--allowedTools` swallow a trailing prompt.
7. No key trace in any artifact, including the debug file.

## What to check

A. Run the free tier with no key, and the model tier once with the key. Counts, exit codes, cost.

B. Can each model check fail? Scratch copy only, one break at a time:
- the fake executes the tool but returns a different canary → (c)/(d) must fail;
- the fake logs two `tools/call` for one `tool_use` id (simulate a double run) → "exactly one" must fail;
- the fake changes one argument before logging → the D args check must fail;
- the server fails to connect → the test must be skipped as inconclusive, not pass and not fail;
- the prompt asks for a tool that does not exist → D is inconclusive, not pass;
- `SUITE_BUDGET_USD` set to 0.001 → the run stops with a clear message and a non-zero exit;
- D23/T2: the broken entry is made valid → the test must fail.

C. Check the harness against doc 11: every `claude -p` run has `--output-format stream-json --verbose`, `--model`, `--max-turns`, `--max-budget-usd`, `--permission-mode default`, a scoped `--allowedTools`, the permission-prompts setting, `--mcp-config … --strict-mcp-config`, `--debug=mcp --debug-file`, a fresh config dir, non-root, no bypass mode. Env pins: legacy negotiation, `ENABLE_TOOL_SEARCH=false` (except T2), explicit `MCP_TIMEOUT`, `MCP_TOOL_TIMEOUT`, short `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS`.

D. Is the S/D split right? The canary text in the final answer is S (recorded). Is anything model-dependent asserted as D? Is anything client-side only recorded?

E. Cost ledger: is it summed from `result` events only, and does a run that ends without a `result` event (timeout, crash) still count something or flag it? A missing result must not count as $0 silently.

F. Secrets: the key must not appear in any artifact, command log, `docker inspect` of the created container (env shows the name only?), or process list. Check how `run.sh` passes it to `docker create`.

G. No default parameter values: parse every `.py`, list hits.

## Rules

Do not edit the real suite folder. Never print the key. Delete scratch copies and images.

## Report back (under 350 words)

Verdict PASS / FAIL; table finding | severity | file:line | fix; each B break: right outcome? (one line); claims confirmed; **exact money you spent**.
