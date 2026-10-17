QA checked step 1 and returned FAIL. Fix the items below in the real suite folder, then run the checks listed at the end. Same rules as before (no default parameter values, never print a secret, do not edit the plan).

## Blockers

1. Bare-401 case has no test (test_status_matrix.py:301). Add case 5b: HTTP fake in a mode that returns a bare 401 with no OAuth metadata, no header configured. Assert the documented `! Needs authentication` (mcp.md:762), marked `xfail(strict=True)` with a reason that quotes the observed 2.1.296 line `✘ Failed to connect — Dynamic Client Registration rejected (HTTP 404)` and cites mcp.md:762 and the spec's PRM MUST (basic__authorization.md:65). Also assert from the fake's log what the client requested (discover 401, the metadata GETs, `POST /register`), so the observation is recorded.
2. The copy step can crash after tests pass (entrypoint.py:39-51, 84): `FileNotFoundError: '/artifacts/junit.xml'` when `artifacts/` is deleted and created again at the same path between runs (Docker Desktop bind mount). pytest gave 0 but `run.sh` returned 1, and `secret-scan.json` was not written. Fix it at the root: do not delete and re-create the mounted folder itself; empty its contents instead, or write to a fresh per-run subfolder (`artifacts/<run-id>/`) plus an `artifacts/latest` pointer file (not a symlink). The scan result must always be written. Prove it: 5× `rm -rf artifacts && ./run.sh` and 5× `./run.sh` in a row, all exit 0.

## Majors

3. `claude mcp get` prints the configured Authorization header in plain text; changelog.md:5864 (2.1.161) says it is redacted. Add an assert that the header value is not in `mcp get` output, `xfail(strict=True)` with the changelog line as the reason. Also assert the value is not in case 4's failure detail.
4. The first client message is recorded but not asserted (doc 12:11 and doc 11: with negotiation unset, the first message must be `server/discover`). Assert it in every case where the fake receives anything. QA showed that with `MCP_PROTOCOL_NEGOTIATION=legacy` all 5 cases still pass; after your fix, that change must make the tests fail.

## Minors (do them, they are cheap)

5. Bearer values in plain text in artifacts (claude_cli.py:73, conftest.py:151): record `--header` and `--env` values as hash + length in `commands.jsonl`; add each test's own generated secrets to the artifact scan's list of values to look for, and redact or drop `.claude.json` and `.credentials.json` from kept artifacts if they hold them.
6. The whole-run cap is soft (pytest.ini:10). Wrap pytest inside the container with coreutils `timeout` (the host may be a Mac, which has no `timeout`).
7. Linux host with uid ≠ 1000: run the container with `--user "$(id -u):$(id -g)"` and make the image work with any uid (HOME and writable dirs).
8. `run.sh` must refuse to run if `artifacts` is a symlink, and must never chmod outside the suite folder.
9. Add the base-image digest to `run.json` (doc 11:23).
10. No-default rule, borderline fallbacks in bodies: wire.py:9-10 (missing log returns `[]`: make a missing log a clear failure, "fake log missing: <path>"), http_fake.py:185, :294-295, conftest.py:35, test_status_matrix.py:79-81, :104-105. Remove each hidden fallback or make the value explicit at the call site.
11. Case 5: also assert no `Issue:` line beyond the expected one and record whether `/register` was requested.

## Record, do not assert

- `initialize` was cancelled at 12.0 s although `MCP_TIMEOUT=15000`.
- The client starts a dead stdio fake twice per command.
Write both into a short `observations.md` at the suite root (date, version, what, evidence path). Later steps add to it.

## Checks before you report

- `./run.sh` passes (xfails count as expected).
- The 10 runs from blocker 2 all exit 0.
- `MCP_PROTOCOL_NEGOTIATION=legacy` makes the first-message asserts fail (do it in a scratch copy, then delete the copy).
- grep shows no default values in any `def` and no hidden fallbacks.

Report under 250 words: what changed (file list), the run results, anything you could not fix.
