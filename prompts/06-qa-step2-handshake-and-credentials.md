You are the QA agent for step 2 of a take-home assignment: an automated black-box test suite for the MCP client inside Claude Code 2.1.296. Check the Dev agent's work hard. Do not trust its report; verify each claim yourself. This step has no model calls; do not set the real API key.

## Where things are

- Suite to check: `/Users/islootski/Documents/02-Personal/mcp-client-testing/mcp-client-suite/` (not a git repo).
- The spec you check against: `mcp-client-suite/prompts/05-dev-step2-handshake-and-credentials.md`. Read it first. Earlier QA prompts for style: `02-…`, `04-…`.
- Plan (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/MCP-Client-Testing/` — docs `11`, `12` (tests 1, 3), `13` (test 4), `23` (test 11), and `Documentation/R01…`, `R06…`.
- Public docs (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/reference/` (`claude-code-docs/env-vars.md`, `mcp.md`, changelog; MCP spec lifecycle/transports).
- Docker: `export PATH="$HOME/.docker/bin:$PATH"` first.

## Dev's claims

1. `./run.sh`: 3 runs, 17 passed, 2 xfailed, exit 0, ~19 s.
2. `server/discover` `_meta` preferred version `2026-07-28`; then `initialize` with `2025-11-25`.
3. Fallback after -32603: `initialize` 2.5–2.9 ms later (bound 1.0 s). Silent fallback: 3.009–3.018 s (bound 3.0 ± 0.5 s), no cancel for the probe, with `MCP_TIMEOUT=15000`.
4. Era memory lives in `$CLAUDE_CONFIG_DIR/state/mcp-discover-verdicts.json`, written only after a silent probe; a fresh config dir is enough isolation.
5. Env scrub needs bubblewrap (added to the Dockerfile); with it, the scrub matches env-vars.md:553-558. `--env` vars survive the scrub.
6. Remote blanking matches mcp.md:679-689: blanked names send an empty credential (Failed to connect); an own var name expands (Connected).
7. Step-1 minor fixes: bare-401 records the OAuth paths only; `latest` updated only when `secret-scan.json` exists; entrypoint scans for `Bearer test-` and `test-dummy-`.

## What to check

A. Run `./run.sh` twice. Counts, exit code, wall time.

B. Can each new test fail? In a scratch copy (never the real folder), one break at a time:
- the fake sends something before its `initialize` reply is written (for example a `tools/list` request from the client side is impossible, so instead: delay the reply and check the "nothing but ping before the reply" assert sees a client request sent early — or prove why the assert can't be triggered and whether it is still meaningful);
- `notifications/initialized` carries an `id` → must fail;
- `clientInfo` missing → must fail;
- the scrub var not set → the scrub test must fail;
- the HTTP fake reports the real dummy value for a blanked name → the blanking test must fail;
- a fallback timing bound: make the fake add 2 s before its -32603 → does the bound catch it?
For each: did the right test fail for the right reason?

C. Timing robustness: the silent bound is 3.0 ± 0.5 s. Is ± 0.5 s safe on a slower machine (a reviewer's laptop, amd64 emulation)? Run the silent test once under `--platform linux/amd64` if the image builds in reasonable time. Propose a bound that is still meaningful.

D. Claim 4: verify yourself that a fresh `CLAUDE_CONFIG_DIR` makes the client probe again, and that HOME does not carry the verdict.

E. Claim 5: verify the bubblewrap claim. Does bubblewrap work inside an unprivileged Docker container on Docker Desktop, and would it on a Linux CI host with default seccomp? If the scrub test needs extra container privileges, is that stated, and is it acceptable for "Docker and git only"?

F. Secrets: grep the newest `artifacts/<run-id>/` for any dummy value (match the hashes in the fakes' logs). Check `secret-scan.json` does not hold anything more than the two prefixes.

G. No default parameter values: grep every `def` and the bodies for hidden fallbacks. List hits with file:line.

H. Doc 12 test 1 asks "no request other than ping before the `initialize` reply". Is that assert real, given the fake now holds the reply while reading stdin?

## Rules

Do not edit the real suite folder. Never print a secret. Delete scratch copies and scratch images when done.

## Report back (under 350 words)

Verdict PASS / FAIL with blockers; a table finding | severity | file:line | fix; each B break: right test failed? (yes/no, one line); which claims you confirmed.
