You are the Dev agent for step 2 of a take-home assignment: an automated black-box test suite for the MCP client inside Claude Code 2.1.296. Step 1 (the harness and the status-matrix test) is built and passed QA. A QA agent will check your work after you. Build only what this prompt asks. This step uses no model calls and costs nothing.

## Where things are

- Suite (edit here): `/Users/islootski/Documents/02-Personal/mcp-client-testing/mcp-client-suite/` (not a git repo; do not `git init`). Read `observations.md`, `harness/`, `fakes/`, `tests/` and `run.sh` first and reuse them; do not build a second harness.
- Earlier prompts for context: `mcp-client-suite/prompts/01-…` to `04-…`.
- Plan (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/MCP-Client-Testing/` — read docs `11`, `12` (tests 1, 3), `13` (test 4), `23` (test 11), `24`, and `Documentation/R01…`, `R06…`.
- Public docs (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/reference/` (Claude Code docs incl. `env-vars.md`, `mcp.md`, changelog; MCP spec 2025-11-25 lifecycle and transports; 2026-07-28 versioning).
- Docker: `export PATH="$HOME/.docker/bin:$PATH"` first.

## Known from step 1 (verified)

- `claude mcp list` / `claude mcp get` really connect (`initialize`, `notifications/initialized`, `tools/list` reach the fakes), need no key and no login.
- With `MCP_PROTOCOL_NEGOTIATION` unset, the first message to a stdio fake is `server/discover`; after the fake's -32601 the client sends `initialize` with `protocolVersion: "2025-11-25"`.
- The client cancels `initialize` at about 12 s even with `MCP_TIMEOUT=15000` (in `observations.md`).

## Scope: two test items, marker `free`, driven by `claude mcp list` / `get`

### Item A — D12/T1 + T3: handshake on the wire

1. Legacy handshake (doc 12 test 1), run with `MCP_PROTOCOL_NEGOTIATION=legacy`. From the fake's own log assert: the first message is `initialize`; it has `jsonrpc: "2.0"`, an `id`, `params.protocolVersion`, `params.capabilities`, `params.clientInfo` (name + version); `notifications/initialized` follows and has no `id`; no request other than `ping` is sent before the fake's `initialize` reply was written (compare timestamps: the fake must log when it wrote its reply, not just when it received requests).
2. Run the same asserts with negotiation unset (doc 11: P0 wire tests run twice). In the unset run, the first message is `server/discover` with the client's preferred version in `_meta` (record which version), then the same `initialize` asserts.
3. Fallback (doc 12 test 3): the fake answers `server/discover` with a generic JSON-RPC error that is not -32601 (for example -32603). Assert `initialize` follows, and measure the delay between the discover error and `initialize` from the fake's clock. Record the value.
4. Silent fallback (doc 12 test 3, silent variant): the fake never answers `server/discover`. Measure how long until `initialize` arrives (or record that it never does, within an explicit test timeout). The plan says run this last, in its own container, because of the 7-day era memory: check in the docs where that memory lives; if it lives under `CLAUDE_CONFIG_DIR`, a fresh config dir per test is enough isolation — say which and why. If you cannot isolate it, put this case behind its own marker and run it last.
5. Also assert the version the fake answers in `initialize` is echoed correctly: the fake replies with `protocolVersion: "2025-11-25"`; the server shows `Connected`.

### Item B — D13/T4 + D23/T11: credentials that reach a server

Use dummy values generated per test (`secrets.token_hex`), never the real key. Set `ANTHROPIC_API_KEY` to a dummy in the container env for these tests only.
1. stdio env inheritance (doc 23 test 11): the stdio fake logs the names of credential-like env vars it received (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, a differently named var like `MY_SERVICE_TOKEN` passed with `--env`) with an 8-char hash and the length. Assert `ANTHROPIC_API_KEY` reaches the fake by default, and does not with `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`. Check the docs for the exact var name and behavior first; if the docs differ from this prompt, follow the docs and say so.
2. Remote blanking (doc 13 test 4): an HTTP server whose `headers.Authorization` uses `${ANTHROPIC_API_KEY}`, and one whose `url` uses it. Assert from the HTTP fake's log that the value sent is empty (hash of the empty string, or length 0), not the dummy key. Then the control: the same config with a differently named var (`${MY_SERVICE_TOKEN}`) sends the value (hash matches). Check R01 for the exact list of blanked names and test one more name from it.
3. `claude mcp add --env KEY=value` for stdio: the fake receives the value (hash matches) — doc 13 test 1, connect part only.

## Rules (same as step 1)

- No default parameter values, no hidden fallbacks in bodies. Keyword arguments at call sites. Named constants for shared values.
- Black-box only. Never print a secret value; dummies are logged as hash + length only.
- Every observed fact that differs from the docs: do not bend the test; strict xfail with the doc line and the observed value, and a line in `observations.md`.
- Every new measured value (fallback delays, versions) goes into `observations.md` with the evidence path.
- Run `./run.sh` and make it pass (xfails expected are fine). Run it 3 times; timing asserts must hold every time with a stated tolerance.

## Also fix first: three minor QA findings from step 1

1. test_status_matrix.py:439-446: the bare-401 wire asserts require `POST /register` → 404, so a product fix would fail as "not requested" instead of XPASS. Record those 3 paths only; keep the discover-probe and 401 asserts.
2. run.sh:56-57: after an entrypoint crash, `artifacts/latest` points to an empty run folder. Update `latest` only when `secret-scan.json` exists.
3. entrypoint.py:115: a hard timeout (exit 124) skips the per-test credential scan. In the entrypoint scan, also look for the `Bearer test-` pattern.

## Report back (under 350 words)

Files changed/added; run results (counts, wall time, 3 runs); the measured values (fallback delay for the error and the silent case, preferred version in `_meta`); where the era memory lives and how you isolated it; any doc-vs-observed differences; anything not done.
