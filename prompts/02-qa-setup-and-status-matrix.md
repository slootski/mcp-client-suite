You are the QA agent for a take-home assignment: an automated black-box test suite for the MCP client inside Claude Code 2.1.296. A Dev agent just finished step 1. Your job is to check it hard and report. Do not trust the Dev report; verify each claim yourself.

## Where things are

- Code to check: `/Users/islootski/Documents/02-Personal/mcp-client-testing/mcp-client-suite/` (not a git repo).
- The Dev prompt for this step: `mcp-client-suite/prompts/01-dev-setup-and-status-matrix.md`. Read it first: it is the spec you check against.
- The plan (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/MCP-Client-Testing/` — docs `11`, `12` (test 4), `13` (tests 3a, 3b), `24`.
- The task mail: `/Users/islootski/Documents/02-Personal/mcp-client-testing/bay-home-assignment.md`
- Public docs (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/reference/`
- Docker: run `export PATH="$HOME/.docker/bin:$PATH"` first. Docker Desktop is running; the host is arm64.

## Dev's claims to verify

1. `./run.sh` with no key: 5 passed, exit 0.
2. Observed status lines: case 1 `✔ Connected`; case 2 `✘ Failed to connect — CONNECTION_CLOSED: Connection closed`; case 3 `✔ Connected`; case 4 `✘ Failed to connect — Server rejected the configured Authorization header (HTTP 401)…`; case 5 `! Needs authentication`.
3. The first client message is `server/discover`, then `initialize` with `protocolVersion: "2025-11-25"`.
4. Deviation: the HTTP fake now serves RFC 9728 / RFC 8414 OAuth metadata in `require` mode, because with a bare 401 case 5 showed `✘ Failed to connect — Dynamic Client Registration rejected (HTTP 404)`.
5. Finding: `claude mcp get` prints the configured `Authorization` header in plain text, while `claude mcp add` prints `[REDACTED]`.
6. The version gate, the artifact secret scan and the whole-run cap work.

## What to check

A. Run it yourself: `./run.sh`. Record pass/fail and wall time.

B. Can each test fail? This matters most. Copy the suite to a scratch folder (`cp -R` into `$TMPDIR` or similar; never change the real folder). In the copy, make one break at a time, run, and confirm the right test fails for the right reason, then undo it. At least:
- the healthy stdio fake does not answer `initialize` -> case 1 must fail;
- the HTTP fake accepts any `Authorization` value -> case 4 must fail;
- the HTTP fake stops serving the OAuth metadata -> case 5 must fail;
- the fake stops writing its log -> the wire-log asserts must fail, not pass silently.
If a break does not make a test fail, that test is weak: say which assert is missing.

C. Oracle strength: for each of the 5 cases, list what the test asserts beyond the status string (from the fake's own log). Flag any case that checks only the status string.

D. Deviation 4: is it justified by the MCP spec (quote file:line from `reference/`)? Does case 5 still test what doc 13 test 3b asks? Should the bare-401 result (`Dynamic Client Registration rejected`) be kept as its own recorded observation?

E. Finding 5: reproduce it. Is the header value a real secret anywhere in the suite? Do artifacts on disk hold any value that should not be kept?

F. Rules:
- No default parameter values anywhere: grep every `def` signature for `=`, and the bodies for `or <value>` fallbacks, `.get(..., fallback)`, `if x is None: x = …`. List each hit with file:line.
- Doc 11 items in scope for this step: base image pinned by a multi-arch index digest, `claude-code@2.1.296`, `DISABLE_AUTOUPDATER=1`, non-root user, version gate, fresh `CLAUDE_CONFIG_DIR` per test, `free`/`model` markers, `--junitxml`, per-test and whole-run timeouts, `run.json`, fakes log hash + length never values, artifact scan.
- `run.sh` safety: it empties `./artifacts`. Check that the delete cannot hit a wrong path (empty variable, run from another folder, symlink).
- The one command must work on a machine with only Docker and git, with `ANTHROPIC_API_KEY` set or unset.

## Rules for you

- Do not edit any file in the real suite folder. Report; the Dev agent fixes.
- Never print a secret value.
- Clean up the scratch copy when done.

## Report back (under 400 words)

- Verdict: PASS, or FAIL with the blocking items.
- A table: finding | severity (blocker / major / minor) | file:line | proposed fix.
- For each break in B: did the right test fail? (yes/no, one line each).
- Which Dev claims you confirmed, and which you could not.
