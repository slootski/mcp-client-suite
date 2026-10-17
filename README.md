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
git clone https://github.com/slootski/mcp-client-suite.git
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

With `-k`, an S rate item (`..._s_rate`; the S rate is the share of 5
repeats in which the model made the expected call) needs all 5 repeats in
the same run. With fewer, it is skipped as inconclusive, and with the key set the
run exits 13.

Results go to a new folder `artifacts/<run-id>/` per run; see
[Results](#results).

## What the suite shows

Ten facts about Claude Code 2.1.296. Four are strict xfails: expected
failures that fail the run when they start to pass (an XPASS), on the day
the documented behavior appears. The other six are
recorded, not failures. Details and evidence: [observations.md](observations.md).

**Defects** (strict xfail; the run fails when they are fixed):

| # | Finding | Test | Doc |
|---|---|---|---|
| 1 | `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT=3000` aborts a silent stdio tool call after 30 s, not 3 s. The value is read (debug log: "for 30s (idle timeout 3s)"); the check runs on a 30 s tick (an idle of 31 s aborts at 60 s). | `tests/test_idle_timeout.py::test_idle_timeout_aborts_hung_call` (3 runs), `::test_idle_timeout_aborts_hung_call_negotiation_unset` | env-vars.md:337 |
| 5 | `claude mcp get` prints a configured `Authorization` header in clear text. A regression: 2.1.161 fixed it. | `tests/test_status_matrix.py::test_http_configured_header_is_redacted_in_cli_output` | changelog.md:5864 |

**Known in the 2.1.299 changelog, kept as regression guards** (strict
xfail; they should turn into XPASS on 2.1.299, which was not run). These two were read in the
changelog, then proven on 2.1.296:

| # | Finding | Test | Doc |
|---|---|---|---|
| 3 | `--allowedTools "mcp__guard"` also allows the tools of a server named `guard__ops`. | `tests/test_permissions.py::test_server_allow_rule_does_not_reach_double_underscore_server` | changelog.md:212 |
| 4 | A server-level deny `--disallowedTools "mcp__guard__ops"` does not stop `guard__ops`'s tools. | `tests/test_permissions.py::test_server_deny_rule_stops_double_underscore_server` | changelog.md:297 |

**Observations** (recorded, not failures):

| # | Finding | Test | Doc |
|---|---|---|---|
| 2 | A doc gap. A stdio server that crashes mid-call is started again lazily, on the next call to it. mcp.md:377 ("doesn't reconnect them automatically") sits under "Automatic reconnection"; the 2026-07-28 spec says the client SHOULD restart it. The spawn count is recorded; the crash's wire facts stay hard asserts. | `tests/test_crash.py::test_stdio_crash_mid_call` | mcp.md:377; 2026-07-28 basic__transports__stdio.md:116 |
| 6 | An out-of-spec server: a bare 401 with no OAuth metadata shows `✘ Failed to connect — Dynamic Client Registration rejected (HTTP 404)`, not `! Needs authentication`. The server breaks the MUST to publish Protected Resource Metadata, so the status is recorded only. A compliant server (401 with metadata) gets `! Needs authentication` and passes. | `tests/test_status_matrix.py::test_http_bare_401_out_of_spec_server_status_recorded`; `::test_http_no_header_needs_authentication` | mcp.md:762; 2025-11-25 basic__authorization.md:65 |
| 7 | No `notifications/cancelled` is sent after the idle abort, in either negotiation mode (a SHOULD in 2025-11-25): a warning, not a failure. | `tests/test_idle_timeout.py` (warnings summary) | 2025-11-25 basic__lifecycle.md:249-253 |
| 8 | A tool's `isError: true` result and a JSON-RPC error look the same in the stream (`is_error: true`, same text shape); the JSON-RPC code is dropped. Not a defect. | `tests/test_tool_errors.py` (both pass; shape in `run.json`) | 2025-11-25 server__tools.md:472-475 |
| 9 | Every stdio MCP server gets the user's `ANTHROPIC_API_KEY` by default. Two documented controls work: `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` (env-vars.md:406), which needs `bubblewrap` installed on Linux (env-vars.md:406 and 543-567 do not say it; sandboxing.md mentions bubblewrap only for the sandbox), and `CLAUDE_CODE_MCP_ALLOWLIST_ENV=1` (env-vars.md:334). The bwrap probe and its limits: observations.md. | `tests/test_credentials.py::test_stdio_inherits_credentials_by_default`, `::test_stdio_env_scrub_strips_inherited_credentials`, `::test_stdio_allowlist_env_passes_only_baseline_and_configured_env` | env-vars.md:406, 334 |
| 10 | A PreToolUse matcher `mcp__guard` (no `.*`) silently matches nothing, so the call goes through. As documented; a policy trap. | `tests/test_permissions.py::test_pre_tool_use_hook_guards_mcp_tool[matcher_without_wildcard]` | hooks.md:365 |

## Time and cost

Measured on an Apple silicon Mac with Docker Desktop, image layers cached.

- **With the key** (run `20261017T120316Z-26391`): 98 items: 91 passed,
  7 xfailed (findings 1, 3, 4, 5), 0 skipped, 0 failed, exit 0. pytest
  took 5 min 15 s; the 4 idle-timeout items take 33-35 s each, since
  2.1.296 aborts at 30 s. 39 `claude -p` runs cost $0.084 (sum of
  `total_cost_usd`). Earlier full runs cost $0.071, $0.084 and $0.084, so
  expect about $0.07-0.09.
- **Without a key** (run `20261017T115200Z-25898`): 53 passed, 1 xfailed
  (finding 5), 44 model items skipped, exit 0; pytest took 55 s.
- **Budget.** The suite adds up `total_cost_usd` from every `claude -p`
  run. Before each run it checks that the total plus the per-run cap
  ($0.25) stays under `SUITE_BUDGET_USD` ($5.00, `harness/constants.py`);
  if not, it stops with exit 11. Far below the $50 key cap.

**Time spent.** Longer than the 2-3 h box. Wall clock from the first plan
file to the last commit of the original build: 2026-10-14 09:22 to
2026-10-17 13:50 (local time), about 3 days 4 h, with nights and gaps in
between. That is wall clock, not hours worked. The extra time went
into proving the checks can fail (offline replays), and the build was cut
to 10 items ([PLAN.md](PLAN.md)).

A 3-hour cut would have kept: the two fake servers and the wire-log
oracle, the round trip (D14/T1), the right tool among two near-duplicates
(D15/T1), and a server crash mid-call (D20/T1). It would have dropped the
offline replays, the permission and hook tests, and the repeats.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | All tests passed (skips and expected failures included) |
| 1 | A test failed, a strict xfail passed (XPASS), or a file held the API key or a test credential |
| 10 | `claude --version` is not 2.1.296; no test runs |
| 11 | The suite budget would be passed; the run stops before the next model run |
| 13 | The key is set and at least one model item was skipped as inconclusive |
| 14 | No key, but model items were asked for on purpose (`SUITE_REQUIRE_KEY=1`, or `-m` selects a model item); no test runs |

The full table (2-5, 12, 124, 137, Docker errors): [docs/exit-codes.md](docs/exit-codes.md).

## Results

Each run gets a new folder `artifacts/<run-id>/` (`<run-id>` =
UTC time + pid). `artifacts/latest` holds the newest complete `<run-id>`.
In the folder:

- `junit.xml` and `report.html` (pytest-html, one file): the result; each
  test row in the HTML shows its log lines and links to its files.
- `outcomes.json`: counts and node ids per outcome, with xfails (known
  defects) apart from each kind of skip (inconclusive, no key, other).
- `suite.log`: every log line of the run, redacted. How to read it:
  [docs/log-format.md](docs/log-format.md).
- `cost.json`: `total_cost_usd` per model run, per test and in total.
  `s-rates.json`: the S rates of repeated tests.
- `secret-scan.json`: the scan for the API key and test credentials (a
  file that holds one is not kept).
- `tests/<test id>/`: `run.json` (version, image id, env pins, the facts
  the test saw), `commands.jsonl`, `wire-<server>.jsonl` (the fake
  server's log), and `stream-attemptN.jsonl` / `debug-attemptN.log` for
  `claude -p` runs.

## Choices made

- **Black-box only.** Only the released 2.1.296 package and the public
  docs. Checks of documented behavior cite the doc or changelog line.
- **The oracle is the fake server's own log.** `fakes/stdio_fake.py` and
  `fakes/http_fake.py` are scriptable (hang, crash, error, 401, ...) and
  log every message they receive and send. "The right tool ran with the
  right arguments" is read from the `tools/call` the server got and
  compared to the `tool_use` in the stream, not from the model's words.
  Env and header values are logged as a hash and a length.
- **D vs S.** D (deterministic) = a client or protocol fact: hard assert
  on every run and in every repeat, never retried. S = the model's choice.
  The S rate is the share of 5 repeats in which the model made the
  expected call with the expected values; it fails below 4 of 5. Five
  repeats catch a broken tool pipeline at about $0.001-0.004 per run.
  Handshake, right-tool and tool-error tests run 5 repeats, crash and
  idle-timeout 3, permissions once. Full table:
  [docs/flake-policy.md](docs/flake-policy.md).
- **The gate: inconclusive is never a pass.** Per test: each server must be
  `connected` in `system/init`, and the model must have made the call the D
  check needs. If not, the attempt is inconclusive: one retry in a fresh
  config dir, then skip. A `tools/call` with no `tool_use`, or a stream
  with no `result` event, fails at once. Per run: with the key set, any
  inconclusive model item makes the run exit 13; model items asked for
  with no key exit 14. `tests/test_harness_offline.py` replays recorded
  runs with one fact broken at a time to prove the checks fail, with no
  model call.
- **Strict xfail only for documented behavior that a fix would flip**
  (findings 1, 3, 4, 5): `xfail(strict=True,
  raises=DocumentedBehaviorMismatch)`, raised after every hard assert, so a
  broken wire fact still fails; `xfail_strict = true`, so an XPASS fails
  the run. A doc gap or an out-of-spec server (findings 2, 6) is
  record-only: a `record ... -> DIFFERS` log line and a `run.json` key,
  with its wire asserts kept hard.
- **Pinned.** `@anthropic-ai/claude-code@2.1.296` on
  `node:22-bookworm-slim` pinned by digest, autoupdater off, pytest
  plugins pinned; exit 10 if `claude --version` is not 2.1.296. Model
  `claude-haiku-5-5` (cheap, enough to make a named tool call), with
  `--max-turns 4` and `--max-budget-usd 0.25` per run. Timeouts: 120 s
  per test (360 s for model tests), 1500 s per session, 1800 s per run.
- **A fresh config dir per test** (`CLAUDE_CONFIG_DIR` and `HOME`), so
  tests share no client state. One order dependency remains: the S rate
  items and `test_stdio_crash_mid_call_same_every_run` read the results
  of earlier items in the same session, so they need those items to run
  first, in file order (no reordering plugin, no parallel workers).
- **Protocol version negotiation.** Model tests pin
  `MCP_PROTOCOL_NEGOTIATION=legacy`, so every run starts with the same
  `initialize` handshake. The user default (unset: probe
  `server/discover` first) runs in the free tests that start a server
  (except `test_handshake_on_the_wire[legacy-*]`) and in the model items
  named `..._negotiation_unset`. Both end at 2025-11-25, the only revision
  the fakes speak.
- **The key goes in by `docker cp`, not `docker run -e`**, so `docker
  inspect` never shows it. `run.sh` copies a 0600 key file into the
  created container and deletes the host copy; the entrypoint reads and
  deletes it and gives the key to pytest only. Artifacts record the live
  key as "set", never as a hash. Residual risk: a `kill -9` of `run.sh`
  between that copy and `docker start` leaves the file in the stopped
  container until `docker rm`.
- **Why not the official MCP conformance runner.** It drives a client as
  one command per scenario, over Streamable HTTP only (no stdio scenario).
  `claude -p` would need a wrapper script and a longer timeout, and most
  tool scenarios still need a model. It does not cover Claude Code's
  config, permissions, hooks or model path, which this suite tests.
- **Why not a scripted model behind `ANTHROPIC_BASE_URL`** (PLAN D22/T5).
  With a fake model, tool search turns off, Claude waits with
  `WaitForMcpServers`, and failed servers are not reported to it: the fake
  model changes the behavior under test.
- **What would change that.** In a team version, the scripted model
  becomes the per-change tier for wire facts and the live model runs
  nightly. The conformance runner's handshake and auth scenarios become an
  extra HTTP job, with a wrapper.

## How each requirement is met

| Requirement (from the mail) | Where |
|---|---|
| An automated test suite for the MCP client; Claude Code runs in Docker and is the system under test | `Dockerfile` (Claude Code 2.1.296), `tests/`, `harness/`, `fakes/` |
| Black-box: only the released 2.1.296 and the public docs | `Dockerfile` (npm package at the exact version), version gate in `tests/conftest.py`; documented expectations cite their doc or changelog line |
| Start with a plan: everything you would test, one line each | [PLAN.md](PLAN.md): 76 ideas, one line each, plus 9 harness checks |
| The plan covers all five questions | PLAN.md, one table per question |
| The tests answer at least two questions in depth | Question 2, tool calls (D14, D15: the wire log proves which tool ran, with which arguments, and what came back) and question 3, errors (D16, D19, D20: tool errors, idle timeout, crash, with time bounds). Both can be proven from the server's own log, and a client that gets them wrong is broken for every user. Question 1 is covered by free tests (`test_status_matrix.py`, `test_handshake.py`, `test_credentials.py`, including the `CLAUDE_CODE_MCP_ALLOWLIST_ENV` test); question 5 by `test_permissions.py` |
| A few tests that check real behavior count for more than many that do not | Oracles are the fakes' logs (`fakes/`), not model text; `tests/test_harness_offline.py` proves the checks can fail; 10 product facts: 2 defects and 2 regression guards as strict xfails (7 items), 6 observations recorded |
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
| A test view | **in the code**: `junit.xml`. JUnit has no xfail state, so the 7 strict xfails show as `skipped`; `outcomes.json` lists xfails apart from skips |
| Two jobs from the markers: `free` (no key, no cost, about 1 min, 54 items) on every change; `model` nightly or on a PR label | **markers in the code** (`./run.sh -m free`, `./run.sh -m model`); the CI job definitions are not written |
| The key as a CI secret for the model job only; a missing secret must not go green | **in the code**: `run.sh` reads the env var and hands it in by `docker cp`. The model job sets `SUITE_REQUIRE_KEY=1`, so a missing secret exits 14 |
| Budget guard | **in the code**: `SUITE_BUDGET_USD` (exit 11), `--max-budget-usd` per run, `cost.json`. CI would add a monthly cap |
| Quarantine list for flaky S items (test id, owner, end date) | **not in the code**. Today an S rate under 4/5 fails the run |
| Docker layer cache | **not in the code**: CI would use `docker buildx --cache-from/--cache-to` |
| A job on the next Claude Code version | **not in the code**: the version is in `Dockerfile` and `harness/constants.py`; a build arg would make it one. On 2.1.299 (not run here), findings 3 and 4 should XPASS and fail the job; someone then turns the xfail into a plain assert |
| Upload of artifacts | **not in the code**: CI uploads `artifacts/<run-id>/` (already scanned for the key) |
| Runner timeouts | **in the code**: per test 120 s / 360 s, session 1500 s, whole run 1800 s; the job timeout would sit above that (about 40 min with the build) |
| Parallel jobs on one runner | **in the code**: per-test config dirs and fake ports, one container per `./run.sh`. The image tag is shared, but `run.sh` creates the container from the image ID its own build wrote (`--iidfile`), so a parallel build cannot swap the image |

## Limits

- **Scope.** 27 of 76 plan ideas are built; PLAN.md gives the reason for
  each one that is not (most share one footnote: the cut to 10 items).
  Not built, among others: pagination and `list_changed`, junk on stdout,
  wrong ids, HTTP reconnect, output size.
- **No Ask path.** Every model run uses `--permission-prompts none`, so
  Ask acts as deny. The guard hook answers only deny or fails; there is no
  `"ask"` or `"allow"` case, and no hook `"ask"` test was added.
- **No managed MCP policy.** `allowedMcpServers` / `deniedMcpServers` and
  `managed-mcp.json` are not tested (PLAN D23/T13): a deployed
  `managed-mcp.json` makes every `--mcp-config` run exit at startup
  (managed-mcp.md:105), so it needs its own container. This and the Ask path are the first additions.
- **Cost and statistics.** 5 repeats catch a broken pipeline, not a small
  model regression. One model only (`claude-haiku-5-5`).
- **Black-box.** Some facts are inferred: "the idle check runs on a 30 s
  tick" comes from two probes (3 s and 31 s), not from code.
- **Protocol revision.** The fakes speak 2025-11-25 only. A full
  2026-07-28 session, and its MUST to cancel, are not tested.
- **Transports.** stdio in depth; HTTP only through `claude mcp list/get`
  (free); no SSE, WebSocket, or OAuth login flow (`-p` cannot open a
  browser).
- **Platform.** Linux container only, seen on Docker Desktop for Mac
  (arm64); the base image pin is multi-arch.

## Layout

```
.
├── run.sh              one command: build, run in a container, copy results out
├── Dockerfile          pinned base image, Claude Code 2.1.296, pytest, non-root
├── pytest.ini          markers (free, model), timeouts, strict xfail
├── harness/            run `claude`, the model-run flow, checks, cost ledger, secret scan, entrypoint
├── fakes/              scriptable stdio and HTTP MCP servers that log every message; hook scripts
├── tests/              the tests; tests/data/ holds recorded runs for the offline self-checks
├── docs/               flake-policy.md (every fact and its treatment), log-format.md, exit-codes.md
├── evidence/           one-off probes cited in observations.md (wire logs, the bwrap probe)
├── prompts/            the AI prompts: plan/, plan-review/, and the build prompts 01-19
├── observations.md     what 2.1.296 did, with dates and evidence
├── PLAN.md             every test idea, with its status
├── PROMPTS.md          the prompts, in order
└── artifacts/          run output (not in git)
```
