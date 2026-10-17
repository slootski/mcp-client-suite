# MCP client test suite for Claude Code 2.1.296

A black-box test suite for the MCP client inside Claude Code 2.1.296. Claude
Code runs in Docker. Small fake MCP servers log every message they get, and
the tests check that log, the `claude` CLI output and the `claude -p`
stream. The plan is in [PLAN.md](PLAN.md), the prompts in
[PROMPTS.md](PROMPTS.md).

## Run it

You need Docker, git, and network access (the image build pulls a base
image and `npm install`s Claude Code; model tests call the Anthropic API).

```bash
git clone <this repo> mcp-client-suite
cd mcp-client-suite
export ANTHROPIC_API_KEY=...        # the key you were given
./run.sh
```

`./run.sh` builds the image, runs every test in a container, copies the
results out, and exits with the suite's exit code.

| What | Command |
|---|---|
| Everything | `./run.sh` |
| No key: free tests only | `unset ANTHROPIC_API_KEY; ./run.sh` (the `model` tests are skipped, not failed) |
| Free tests only, key set | `./run.sh -m free` |
| One test | `./run.sh -k test_round_trip_echo_canary` (any pytest arguments after `./run.sh` go to pytest) |

Notes on `-k`: an S-rate item (`..._s_rate`) needs all 5 repeats in the
same run; with fewer it is skipped as inconclusive, and a run where every
model item was inconclusive exits 13.

**Results.** Each run gets a new folder `artifacts/<run-id>/` (`<run-id>` =
UTC time + pid). `artifacts/latest` is a plain file that holds the newest
complete `<run-id>`. In the folder:

- `junit.xml`: the pytest result, JUnit XML.
- `report.html`: the same result as a pytest-html page (one file, open it in a browser). Each test row shows its log lines, links to its artifact files, and its `run.json`.
- `suite.log`: every log line of the run, in the format `12:37:32.90 2026-10-17 [INFO    ] claude_cli.py:122 run_claude() - waiting done (0.13 s): exit 0, stdout 300 bytes: ...` (host time zone; `harness/log_format.py`). Log lines hold redacted text only: commands with `--env`/`--header` values as hash + length, and the first 200 chars of each CLI output after every test credential and the API key are replaced.
- `cost.json`: every model run with its `total_cost_usd`, per test and in
  total. `s-rates.json`: the S pass rates of repeated tests.
- `secret-scan.json`: the result of the scan for the API key and test
  credentials (a file that holds one is not kept).
- `tests/<test id>/` (e.g. `tests/tests_test_crash.py_test_stdio_crash_mid_call_0/`): per test: `run.json` (version, image digest, model, env
  pins, era seen, the facts the test saw), `commands.jsonl` (every `claude`
  command with its output), `wire-<server>.jsonl` (the fake server's log),
  `stream-attemptN.jsonl` and `debug-attemptN.log` (`claude -p` runs), and
  the copied `claude-config/`.

**Reading a test's log.** Each test row in `report.html` (and `suite.log`)
tells what the test did and what it got back, through `harness/check.py`:
`step:` is an action (add a server, start a fake, run a command, mutate a
recording); `start waiting for:` / `waiting done (<s> s):` frame every wait
(each `claude` command, the HTTP fake's start and stop) with what came back;
`got` is a status, field, count or timing read back; `S recorded:` is a model
fact kept, not asserted; `check <what>: Expected: ..., Actual: ... -> OK`
(or `-> FAIL`, ERROR level) is a check. A failed check raises
`AssertionError("<what>: Expected: <e>. Actual: <a>.")`; a documented
behavior that 2.1.296 does not show logs a WARNING with the doc line as
Expected and raises `DocumentedBehaviorMismatch` (the strict xfails). Long
values are cut in the log line only (300 chars, around the first
difference). Ten lines of `test_stdio_crash_mid_call[0]` from run
`20261017T094227Z-47669` (lines over 200 chars cut here, marked `[...]`):

```
12:37:20.74 2026-10-17 [INFO    ] test_crash.py:332 crash_run() - step: stdio server crashy (FAKE_MODE=exit_on_first_tools_call): exits with code 3 on the first tools/call; prompt: mcp__crashy__echo_c [...]
12:37:20.74 2026-10-17 [INFO    ] claude_cli.py:92 run_claude() - start waiting for: claude -p Step 1: call the tool mcp__crashy__echo_canary exactly once, with request_id set to exactly "crash-req-4b [...]
12:37:24.74 2026-10-17 [INFO    ] claude_cli.py:122 run_claude() - waiting done (4.00 s): exit 0, stdout 8401 bytes: {"type":"system","subtype":"init","cwd":"/tmp/pytest-of-unknown/pytest-0/test_stdio [...]
12:37:24.74 2026-10-17 [INFO    ] model_run.py:225 run_print() - got attempt0 stream: 7 events, tool_use ['mcp__crashy__echo_canary', 'mcp__crashy__echo'], 2 tool_result, result event present, total_c [...]
12:37:24.74 2026-10-17 [INFO    ] test_crash.py:166 crashed_call_facts() - check tools/call the first fake process got: Expected: 1, Actual: 1 -> OK
12:37:24.74 2026-10-17 [INFO    ] test_crash.py:194 assert_crashed_call() - check is_error of the crashed call's tool_result: Expected: True, Actual: True (text 'Connection closed') -> OK
12:37:24.74 2026-10-17 [INFO    ] test_crash.py:198 assert_crashed_call() - check time from the fake's exit to the error tool_result: Expected: <= 5.0 s, Actual: 0.023 s -> OK
12:37:24.74 2026-10-17 [INFO    ] test_crash.py:276 check_d() - got spawns (pid, methods): [(36, ['initialize', 'notifications/initialized', 'tools/list', 'tools/call']), (48, ['initialize', 'notifica [...]
12:37:24.74 2026-10-17 [INFO    ] test_crash.py:283 check_d() - check fake processes started between the crash and the next tool_use (pids): Expected: [], Actual: [] -> OK
12:37:24.74 2026-10-17 [WARNING ] test_crash.py:356 crash_run() - check stdio fake processes started in the run (documented behavior): Expected: 1: no restart (mcp.md:377: "Stdio servers are local pro [...]
```

**Time and cost** (measured on this machine, Docker Desktop on an Apple
silicon Mac, image layers cached): `./run.sh` with the key,
97 tests: 86 passed, 11 xfailed (findings 1-6 below, over 11 items), 0
skipped, 0 failed, exit 0. 5 min 19 s wall time (pytest 5 min 18 s; the
4 idle-timeout runs take ~35 s each, since 2.1.296 aborts at 30 s). 39
`claude -p` runs, no inconclusive retry, $0.0708 total (sum of
`total_cost_usd`, run `20261017T075254Z-97188`; a second full run by the
final QA cost $0.0840, so expect about $0.07-0.09). Without a key (a fresh
copy of the repo): 51 passed, 2 xfailed, 44 skipped, exit 0, 56 s. A build
with `--no-cache` took 18 s here once the base image was pulled.

**Budget.** The suite adds up `total_cost_usd` from every `claude -p` run.
Before each run it checks that the total plus the per-run cap ($0.25) stays
under `SUITE_BUDGET_USD` ($5.00, `harness/constants.py`); if not, it stops
with exit 11. Far below the $50 key cap.

**Exit codes.**

| Code | Meaning | Where |
|---|---|---|
| 0 | All tests passed (skips and expected failures included) | pytest |
| 1 | A test failed, or a strict xfail passed (XPASS), or the pytest session timeout (1500 s) was hit; also: a file held the API key or a test credential, an artifact copy failed, or no complete artifacts came out of the container | pytest, `harness/entrypoint.py`, `run.sh` |
| 2 | `./artifacts` is a symlink (`run.sh`); the key hand-off failed or the container was not started by `run.sh` (entrypoint); pytest was interrupted | `run.sh`, entrypoint, pytest |
| 3, 4 | pytest internal error, usage error (e.g. a bad option) | pytest |
| 5 | No test selected (e.g. a `-k` that matches nothing) | pytest |
| 10 | `claude --version` is not 2.1.296, or cannot run; no test runs | `tests/conftest.py` |
| 11 | The suite budget would be passed; the run stops before the next model run | `harness/cost_ledger.py` |
| 12 | The model id was not accepted | `harness/model_flow.py` |
| 13 | The key is set and every model test of the run was inconclusive | `tests/conftest.py` |
| 124, 137 | The whole-run cap (1800 s, coreutils `timeout`) stopped pytest; 137 if it had to be killed after the 30 s grace | entrypoint |
| other | `docker build` or `docker create` failed; `run.sh` exits with Docker's code | `run.sh` (`set -e`) |

## What it found

Facts about Claude Code 2.1.296 that differ from its docs or changelog.
The first six are strict xfails: the test fails the run on the day the
documented behavior appears. Details and evidence: [observations.md](observations.md).

| # | Finding | Test | Differs from |
|---|---|---|---|
| 1 | `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT=3000` aborts a silent stdio tool call after 30 s, not 3 s. The value is read (debug log: "for 30s (idle timeout 3s)"); the check runs on a 30 s tick (an idle of 31 s aborts at 60 s). | `tests/test_idle_timeout.py::test_idle_timeout_aborts_hung_call` | env-vars.md:337 |
| 2 | A stdio server that crashes mid-call is started again on the next call to it. (A literal reading: the doc line sits under "Automatic reconnection" for mid-session drops; the restart here is lazy, on the next call, not a background reconnect. The xfail records the gap between the line and the behavior.) | `tests/test_crash.py::test_stdio_crash_mid_call` | mcp.md:377 ("doesn't reconnect them automatically") |
| 3 | `--allowedTools "mcp__guard"` also allows the tools of a server named `guard__ops`. | `tests/test_permissions.py::test_server_allow_rule_does_not_reach_double_underscore_server` | changelog.md:212 (fixed in 2.1.299) |
| 4 | A server-level deny `--disallowedTools "mcp__guard__ops"` does not stop `guard__ops`'s tools. | `tests/test_permissions.py::test_server_deny_rule_stops_double_underscore_server` | changelog.md:297 (fixed in 2.1.299) |
| 5 | `claude mcp get` prints a configured `Authorization` header in clear text. | `tests/test_status_matrix.py::test_http_configured_header_is_redacted_in_cli_output` | changelog.md:5864 (2.1.161: credential headers are redacted) |
| 6 | An HTTP server that answers a bare 401 (no OAuth metadata) shows `✘ Failed to connect — Dynamic Client Registration rejected (HTTP 404)`, not `! Needs authentication`. (The server breaks the spec's MUST to publish resource metadata.) | `tests/test_status_matrix.py::test_http_bare_401_no_header_needs_authentication` | mcp.md:762 |
| 7 | No `notifications/cancelled` is sent after the idle abort, in either era (a SHOULD in 2025-11-25): a warning, not a failure. | `tests/test_idle_timeout.py` (warnings summary) | 2025-11-25 basic__lifecycle.md:249-253 |
| 8 | A tool's `isError: true` result and a JSON-RPC error look the same in the stream (`is_error: true`, same text shape); the JSON-RPC code is dropped. | `tests/test_tool_errors.py` (both pass; shape in `run.json`) | spec server__tools.md:472-475 (not a defect; worth knowing) |
| 9 | Every stdio MCP server gets the user's `ANTHROPIC_API_KEY` unless `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`; the scrub needs `bubblewrap` on Linux (not in the docs), and 2.1.296 only checks that `bwrap` exists, it never runs it. | `tests/test_credentials.py::test_stdio_inherits_credentials_by_default`, `::test_stdio_env_scrub_strips_inherited_credentials` | env-vars.md:406 (documented opt-in); the bubblewrap need is not documented |
| 10 | A PreToolUse matcher `mcp__guard` (no `.*`) silently matches nothing, so the call goes through. | `tests/test_permissions.py::test_pre_tool_use_hook_guards_mcp_tool[matcher_without_wildcard]` | matches hooks.md:365; a policy trap |

## Choices made

- **Black-box only.** Only the released 2.1.296 package and the public
  docs. No source, no internal flags. Every expected value cites a doc or
  changelog line.
- **Fake MCP servers that log every message.** `fakes/stdio_fake.py` and
  `fakes/http_fake.py` are scriptable (hang, crash, error, 401, ...). They
  log every message they receive and send, with timestamps. The oracle is
  the server's log, not the model's words: "the right tool ran with the
  right arguments" is read from the `tools/call` the server got, and
  compared to the `tool_use` in the stream. Values of env vars and headers
  are logged as a hash and a length, never in clear.
- **D vs S, N = 5.** D (deterministic) = a client or protocol fact: hard
  assert, every run, 5 of 5 repeats, never retried. S = the model's choice
  (did it call the tool, with which values): a pass rate over 5 repeats,
  fail below 4 of 5. 5 is the doc 22 number: enough to see a broken tool
  pipeline, cheap enough (each run costs ~$0.001-0.004). The full table is
  in [docs/flake-policy.md](docs/flake-policy.md).
- **The gate: inconclusive is never a pass.** Before any tool assert, each
  server must be `connected` in `system/init`, and the model must have made
  the call the D check needs. If not, the attempt is inconclusive: one retry
  in a fresh config dir, then skip. A `tools/call` with no `tool_use`, or a
  stream with no `result` event, fails at once on any attempt.
  `tests/test_harness_offline.py` replays recorded runs with one fact broken
  at a time to prove each check fails, without a model call.
- **Strict xfail for known defects.** A documented behavior that 2.1.296
  does not show is `xfail(strict=True, raises=DocumentedBehaviorMismatch)`
  with the doc line. Only that exception is accepted, raised after every
  hard assert, so a broken wire fact still fails. `xfail_strict = true` in
  `pytest.ini`: when the product starts to match the docs, the run fails
  (XPASS) and someone removes the mark.
- **Pinned version and image.** `npm install -g
  @anthropic-ai/claude-code@2.1.296` on `node:22-bookworm-slim` pinned by
  its multi-arch index digest (`Dockerfile`), the autoupdater off, pytest
  versions pinned. The version gate stops the run (exit 10) if `claude
  --version` is not 2.1.296. Each `run.json` records the image id and base
  digest.
- **Model and caps.** `claude-haiku-5-5` (cheap, fast, enough to make a
  named tool call). Every `claude -p` run has `--max-turns 4` and
  `--max-budget-usd 0.25`; the suite stops at `SUITE_BUDGET_USD` $5.00.
  Per-test pytest timeout 120 s (360 s for model tests), a session timeout
  of 1500 s, and a hard cap of 1800 s on the whole run.
- **A fresh config dir per test.** Each test gets its own
  `CLAUDE_CONFIG_DIR` and `HOME`. 2.1.296 keeps the protocol-era memory in
  `$CLAUDE_CONFIG_DIR/state/` (observations.md), so this alone isolates
  tests; the order of tests does not matter.
- **Legacy protocol negotiation as the default era.** Model tests pin
  `MCP_PROTOCOL_NEGOTIATION=legacy`, so every run starts with the same
  `initialize` handshake. The user default (unset: probe `server/discover`
  first) runs in the free tests that start a server, except the
  `test_handshake_on_the_wire[legacy-*]` cases (so: status matrix,
  credentials, `test_handshake_on_the_wire[unset-*]`, the two
  discover-fallback tests)
  and in the model items named `..._negotiation_unset` (D15/T1, D19). Both
  eras end at 2025-11-25, because the fakes speak only that revision.
- **The key goes in by `docker cp`, not `docker run -e`.** With `-e`,
  `docker inspect` shows the key in the container config, and a `kill -9` of
  `run.sh` skips its cleanup and leaves that container behind. `run.sh`
  writes the key to a 0600 file in a private temp dir, `docker cp`s it into
  the created container, deletes the host file, then starts the container.
  The entrypoint reads the file, deletes it, and gives the key to the pytest
  process only. Residual risk: a `kill -9` of `run.sh` between that
  `docker cp` and `docker start` leaves the file in the stopped container
  until `docker rm`; and inside the running container the key is in the
  pytest process env, readable by the same uid. The entrypoint also scans
  every artifact for the key before keeping it.
- **Artifacts by `docker cp`, not a bind mount.** A bind mount of a
  just-created host folder failed now and then on Docker Desktop, and
  `docker cp` leaves the files owned by the host user. The container writes
  inside itself; `run.sh` copies the result out after it exits.
- **Non-root.** The image runs as `node` (uid 1000); `run.sh` passes
  `--user <host uid>:<host gid>`. No test uses bypass permission mode.

## How each requirement is met

| Requirement (from the mail) | Where |
|---|---|
| An automated test suite for the MCP client; Claude Code runs in Docker and is the system under test | `Dockerfile` (Claude Code 2.1.296), `tests/`, `harness/`, `fakes/` |
| Black-box: only the released 2.1.296 and the public docs | `Dockerfile` (npm package at the exact version), version gate in `tests/conftest.py`; the expectations cite the doc or changelog line they rest on |
| Start with a plan: everything you would test, one line each | [PLAN.md](PLAN.md): 76 ideas from docs 12-23, one line each, plus the doc 11 harness checks |
| The plan covers all five questions | PLAN.md, one table per question |
| The tests answer at least two questions in depth | Question 2, tool calls (D14, D15: the wire log proves which tool ran, with which arguments, and what came back; D15 runs 5 repeats) and question 3, errors (D16, D19, D20: tool errors, idle timeout, crash, with time bounds and strict xfails). Chosen because they can be proven from the server's own log, independent of the model, and because a client that gets these wrong is broken for every user. Question 1 is covered by free tests (`test_status_matrix.py`, `test_handshake.py`, `test_credentials.py`); question 5 by `test_permissions.py` |
| A few tests that check real behavior count for more than many that do not | Oracles are the fakes' logs (`fakes/`), not model text; `tests/test_harness_offline.py` proves the checks can fail; 10 product facts found (above), 6 of them strict xfails |
| Runs on a machine with only Docker and git | `run.sh` needs only Docker and bash; Python, pytest and Claude Code are inside the image |
| The API key in `ANTHROPIC_API_KEY` | `run.sh` reads it from the shell; without it the free tests still run |
| Starts with one command, no other setup | `./run.sh` |
| Runs locally now; can run in CI later, README says what that takes | [CI](#ci) below |
| A git repository with the suite | this folder |
| `PLAN.md`: the plan, with the full list and which items are implemented | [PLAN.md](PLAN.md), `Status` column |
| `PROMPTS.md`: the prompts given to AI tools, no transcripts | [PROMPTS.md](PROMPTS.md), files under `prompts/` |
| `README.md`: how to run, choices, how each requirement is met | this file |
| Tokens are limited: the key is capped at $50 | `SUITE_BUDGET_USD` $5.00 with a pre-check, `--max-budget-usd 0.25` per run, cost in `cost.json`; a full run costs about $0.07-0.09 |

## CI

What it would take, and what is already in the code:

| Need | State |
|---|---|
| JUnit XML for the CI's test view | **in the code**: `artifacts/<run-id>/junit.xml` (`--junitxml` in the entrypoint). JUnit has no xfail state: the 11 strict xfails show as `skipped` in a CI test view, so CI should read the pytest summary or `run.json` for the xfail count |
| Two jobs from the markers: `free` (no key, no cost, ~1 min, 53 items) on every change; `model` on a schedule (nightly) or a PR label | **markers in the code** (`pytest.ini`: `free`, `model`; `./run.sh -m free`, `./run.sh -m model`); the CI job definitions are not written |
| The key as a CI secret, exported as `ANTHROPIC_API_KEY` for the model job only | **in the code**: `run.sh` reads the env var and hands it in by `docker cp`; the secret itself is CI config |
| Budget guard | **in the code**: `SUITE_BUDGET_USD` (exit 11), `--max-budget-usd` per run, `cost.json`. CI would add a monthly cap across runs |
| Quarantine list for flaky S items: test id, owner, end date; a quarantined item runs and reports but does not fail the job | **not in the code**. Today an S rate under 4/5 fails the run |
| Docker layer cache (base image, apt, pip, npm layers change rarely) | **not in the code**: `run.sh` uses the local Docker cache only; CI would use `docker buildx --cache-from/--cache-to` |
| A job on the next Claude Code version | **not in the code**: the version is in two places, `Dockerfile` (`npm install ...@2.1.296`) and `harness/constants.py` (`EXPECTED_CLAUDE_VERSION`); a build arg would make it one. On the new version a strict XPASS fails the job: it means a known defect is fixed (2.1.299 should flip findings 3 and 4). Someone checks the changelog and turns the xfail into a plain assert. A new plain failure is a candidate regression, with its wire log in the artifacts |
| Upload of artifacts | **not in the code**: CI uploads `artifacts/<run-id>/` (already scanned for the key; leaking files are not kept) |
| Runner timeouts | **in the code**: per test 120 s / 360 s, session 1500 s, whole run 1800 s; the CI job timeout would sit above that (~40 min with the image build) |
| Parallel jobs on one runner | **mostly in the code**: per-test config dirs and fake ports; each `./run.sh` is its own container |

## Limits

- **Time box.** 27 of 76 plan ideas are built (PLAN.md). Not built, among
  others: pagination and `list_changed` (doc 18), junk on stdout (doc 17),
  wrong ids (doc 21), HTTP reconnect (D20/T3), output size (D23/T1).
- **Cost and statistics.** S facts get 5 repeats, enough to catch a broken
  pipeline, not to measure a small model regression. Only one model
  (`claude-haiku-5-5`); a bigger model may call tools differently.
- **Black-box.** Some facts can only be inferred: "the idle check runs on a
  30 s tick" comes from two probes (3 s and 31 s), not from code. Timing
  bounds use the container clock and are loose on purpose.
- **Protocol revision.** The fakes speak 2025-11-25 only. A full 2026-07-28
  session, and the 2026-07-28 MUST to cancel, are not tested.
- **Transports.** stdio in depth; HTTP only through `claude mcp list/get`
  (free); no SSE, WebSocket, or OAuth login flow (`-p` cannot open a
  browser).
- **Platform.** Linux container only. Seen on Docker Desktop for Mac
  (arm64); the base image pin is multi-arch, so amd64 should build too.

## Layout

```
.
├── run.sh              one command: build, run in a container, copy results out
├── Dockerfile          pinned base image, Claude Code 2.1.296, pytest, non-root
├── pytest.ini          markers (free, model), timeouts, strict xfail
├── harness/            run `claude`, the model-run flow, checks, cost ledger, secret scan, entrypoint
├── fakes/              scriptable stdio and HTTP MCP servers that log every message; hook scripts
├── tests/              the tests; tests/data/ holds recorded runs for the offline self-checks
├── docs/               flake-policy.md: every fact, its class (D / S / record / xfail) and treatment
├── evidence/           wire logs of one-off probes cited in observations.md
├── prompts/            the AI prompts: plan/, plan-review/, and the build prompts 01-18
├── observations.md     what 2.1.296 did, with dates and evidence
├── PLAN.md             every test idea, with its status
├── PROMPTS.md          the prompts, in order
└── artifacts/          run output (not in git)
```
