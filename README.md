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
| One test | `./run.sh -k test_round_trip_echo_canary` (pytest arguments after `./run.sh` go to pytest). A model test: with no key it exits 14 |

With `-k`, an S rate item (`..._s_rate`; the S rate is the share of 5
repeats in which the model made the expected call) needs all 5 repeats in
the same run; with fewer, it is skipped as inconclusive. An S rate item
tolerates 1 wrong call in 5. A repeat in which the model made no call at
all, even after its retry, proved nothing: it is inconclusive, and with
the key set the run exits 13. Results: [Results](#results).

## What the suite shows

Ten facts about Claude Code 2.1.296. Four are strict xfails: expected
failures that fail the run on the day the documented behavior appears
(an XPASS). The other six are recorded, not failures. Details and evidence: [observations.md](observations.md).
(The numbers are fixed ids, used in the rest of this README; the tables
group the findings by kind, so the numbers are not in order.)

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
| 2 | A doc gap. A stdio server that crashes mid-call is started again on the next call. mcp.md:377 ("doesn't reconnect them automatically") sits under "Automatic reconnection"; the 2026-07-28 spec says the client SHOULD restart it. The later call's success on a new process is a hard assert, so a client that stops restarting fails; the doc line's spawn count is recorded. | `tests/test_crash.py::test_stdio_crash_mid_call` | mcp.md:377; 2026-07-28 basic__transports__stdio.md:116 |
| 6 | An out-of-spec server: a bare 401 with no OAuth metadata shows `✘ Failed to connect — Dynamic Client Registration rejected (HTTP 404)`, not `! Needs authentication`. The server breaks the MUST to publish Protected Resource Metadata, so the status is recorded only; a compliant server gets `! Needs authentication` and passes. | `tests/test_status_matrix.py::test_http_bare_401_out_of_spec_server_status_recorded`; `::test_http_no_header_needs_authentication` | mcp.md:764; 2025-11-25 basic__authorization.md:65 |
| 7 | No `notifications/cancelled` is sent after the idle abort, in either negotiation mode (a SHOULD in 2025-11-25): a warning, not a failure. | `tests/test_idle_timeout.py` (warnings summary) | 2025-11-25 basic__lifecycle.md:249-253 |
| 8 | A tool's `isError: true` result and a JSON-RPC error look the same in the stream (`is_error: true`, same text shape); the JSON-RPC code is dropped. Not a defect. | `tests/test_tool_errors.py` (both pass; shape in `run.json`) | 2025-11-25 server__tools.md:472-475 |
| 9 | Every stdio MCP server gets the user's `ANTHROPIC_API_KEY` by default. Both documented controls work; the scrub needs `bubblewrap` on Linux, which env-vars.md does not say. Details: observations.md. | `tests/test_credentials.py::test_stdio_inherits_credentials_by_default`, `::test_stdio_env_scrub_strips_inherited_credentials`, `::test_stdio_allowlist_env_passes_only_baseline_and_configured_env` | env-vars.md:406, 334 |
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
- **Budget.** Before each `claude -p` run the suite checks that the sum
  of `total_cost_usd` plus the per-run cap ($0.25) stays under
  `SUITE_BUDGET_USD` ($5.00); if not, it stops with exit 11.

**Time spent.** Longer than the 2-3 h box. About 7 hours of the
candidate's time in the build and review sessions (PROMPTS.md timestamps:
10-16 17:55-21:46; 10-17 00:05-00:58, 11:43-13:21, 13:45-14:13), plus
writing the plan on 10-14 to 10-16, which was not timed. The agents built
overnight, unattended; the fix rounds after the panel reviews each ran
from one prompt. The extra time went into proving the checks can fail
(offline replays), and the build was cut to 10 items ([PLAN.md](PLAN.md)).

A 3-hour cut would have kept: the two fake servers and the wire-log
oracle, the round trip, the right tool among two near-duplicates, and a
server crash mid-call. It would have dropped the offline replays, the
permission and hook tests, and the repeats.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | All tests passed (skips and expected failures included) |
| 1 | A test failed, a strict xfail passed (XPASS), or a file held the API key or a test credential |
| 10 | `claude --version` is not 2.1.296; no test runs |
| 11 | The suite budget would be passed; the run stops before the next model run |
| 13 | The key is set and at least one model item was skipped as inconclusive |
| 14 | No key, but model items were asked for: `SUITE_REQUIRE_KEY=1`, a `-m` that selects a model item, or a selection of only model items (e.g. `-k test_round_trip_echo_canary`); no test runs |
| 15 | The Anthropic API rejected the key (HTTP 401 or 403); the run stops at the first model run, no retry |

The full table (2-5, 12, 124, 137, Docker errors): [docs/exit-codes.md](docs/exit-codes.md).

## Results

Each run gets a new folder `artifacts/<run-id>/` (`<run-id>` =
UTC time + pid). `artifacts/latest` holds the newest complete `<run-id>`
in which at least one test ran. In the folder:

- `junit.xml` and `report.html` (one file; each test row shows its log
  lines and links to its files).
- `outcomes.json`: counts and node ids per outcome, xfails (known
  defects) apart from each kind of skip (inconclusive, no key, other).
- `suite.log`: every log line, redacted ([docs/log-format.md](docs/log-format.md)).
- `cost.json` (`total_cost_usd` per model run, per test, in total) and
  `s-rates.json` (the S rates).
- `secret-scan.json`: the scan for the API key and test credentials (a
  file that holds one is not kept).
- `tests/<test id>/`: `run.json` (version, image id, env pins, the facts
  the test saw), `commands.jsonl`, `wire-<server>.jsonl` (the fake's log),
  and `stream-attemptN.jsonl` / `debug-attemptN.log` for `claude -p` runs.

## Choices made

- **Black-box only.** Only the released 2.1.296 package and the public
  docs. Checks of documented behavior cite the doc or changelog line.
- **The oracle is the fake server's own log.** The fakes (`fakes/`) are
  scriptable (hang, crash, error, 401, ...) and log every message. "The right tool ran with the right arguments" is
  read from the `tools/call` the server got, compared to the `tool_use`
  in the stream, not from the model's words. Env and header values are
  logged as a hash and a length.
- **D vs S.** D = a client or protocol fact: hard assert on every run and
  in every repeat, never retried. S = the model's choice, as a rate over
  5 repeats that fails below 4 of 5. Handshake, right-tool and tool-error
  tests run 5 repeats, crash and idle timeout 3, permissions once. Full
  table: [docs/flake-policy.md](docs/flake-policy.md).
- **The gate: inconclusive is never a pass.** Per test: each server must
  be `connected` in `system/init`, and the model must have made the call
  the D check needs; if not, one retry in a fresh config dir, then skip.
  A `tools/call` with no `tool_use`, or a stream with no `result` event,
  fails at once. Per run: with the key set, any inconclusive model item
  exits 13; model items asked for with no key exit 14; a key the API
  rejects exits 15. `tests/test_harness_offline.py` replays recorded runs
  with one fact broken at a time to prove the checks fail.
  `tests/test_gate.py` runs pytest inside pytest (pytester) to check exits
  13 and 14 and that xfails are counted apart from skips, and replays
  recorded 401 and `authentication_failed` runs to check exit 15, no retry. Both need no
  model call.
- **Strict xfail only for documented behavior that a fix would flip**
  (findings 1, 3, 4, 5), raised after every hard assert, so a broken wire
  fact still fails; an XPASS fails the run. A doc gap or an out-of-spec
  server (findings 2, 6) is record-only (`-> DIFFERS` in the log, a
  `run.json` key), with its wire asserts kept hard.
- **Pinned.** `@anthropic-ai/claude-code@2.1.296` on
  `node:22-bookworm-slim` pinned by digest, autoupdater off, pytest
  plugins pinned; exit 10 if `claude --version` is not 2.1.296. Model
  `claude-haiku-5-5` (cheap, enough for a named tool call), `--max-turns
  4`, `--max-budget-usd 0.25` per run. Timeouts: 120 s per test (360 s
  for model tests), 1500 s per session, 1800 s per run. Model tests pin
  `MCP_PROTOCOL_NEGOTIATION=legacy`; the user default (`server/discover`
  first) runs in most free tests and the `..._negotiation_unset` items.
  Both end at 2025-11-25, the only revision the fakes speak.
- **A fresh config dir per test** (`CLAUDE_CONFIG_DIR` and `HOME`). One
  order dependency remains: the S rate items and
  `test_stdio_crash_mid_call_same_every_run` read the results of earlier
  items, so they run in file order (no reordering plugin, no parallel
  workers).
- **The key goes in by `docker cp`, not `docker run -e`**, so `docker
  inspect` never shows it. The entrypoint reads and deletes the key file
  and gives the key to pytest only. Artifacts record the key as "set",
  never as a hash. Residual risk: a `kill -9` of `run.sh` between the copy
  and `docker start` leaves the file in the container until `docker rm`.
- **Why not the official MCP conformance runner.** It drives a client
  over Streamable HTTP only, one command per scenario; most tool
  scenarios still need a model, and it does not cover Claude Code's
  config, permissions, hooks or model path.
- **Why not a scripted model.** S facts (which tool the model picks, with
  which values) need the real model. D facts could move to a scripted
  model behind `ANTHROPIC_BASE_URL`; the suite already runs with tool
  search off (except the one tool-search test), so the scripted model
  would see the same configuration (mcp.md:313). Not built for time; it is
  the per-change tier a team version would add first, with the live model
  nightly.

## How each requirement is met

| Requirement (from the mail) | Where |
|---|---|
| An automated test suite for the MCP client; Claude Code runs in Docker | `Dockerfile` (Claude Code 2.1.296), `tests/`, `harness/`, `fakes/` |
| Black-box: only the released 2.1.296 and the public docs | npm package at the exact version, version gate in `tests/conftest.py`; expectations cite their doc line |
| A plan: everything you would test, one line each, all five questions | [PLAN.md](PLAN.md): 76 ideas plus 9 harness checks, one table per question, `Status` column |
| At least two questions in depth | Question 2, tool calls (D14, D15) and question 3, errors (D16, D19, D20), both proven from the server's own log. Question 1 by free tests; question 5 by `test_permissions.py` |
| A few tests that check real behavior | Oracles are the fakes' logs, not model text; offline replays prove the checks can fail; 10 product facts |
| Only Docker and git; one command; the key in `ANTHROPIC_API_KEY` | `./run.sh` needs Docker and bash; without a key the free tests still run |
| Runs in CI later; README says what that takes | [CI](#ci) below |
| A git repository; `PLAN.md`, `PROMPTS.md` (no transcripts), `README.md` | this folder |
| The key is capped at $50 | `SUITE_BUDGET_USD` $5.00 with a pre-check, `--max-budget-usd 0.25` per run, `cost.json`; a full run costs about $0.07-0.09 |

## CI

What it would take, and what is already in the code:

| Need | State |
|---|---|
| A test view | **in the code**: `junit.xml` (JUnit shows the strict xfails as `skipped`); `outcomes.json` lists xfails apart from skips |
| Two jobs from the markers: `free` (no key, no cost, about 1 min, 54 items) on every change; `model` nightly or on a PR label | **markers in the code** (`./run.sh -m free`, `./run.sh -m model`); the CI job definitions are not written |
| The key as a CI secret for the model job only; a missing secret must not go green | **in the code**: the model job sets `SUITE_REQUIRE_KEY=1`, so a missing secret exits 14; a wrong or expired key exits 15 |
| Budget guard | **in the code**: `SUITE_BUDGET_USD` (exit 11), `--max-budget-usd` per run, `cost.json`. CI would add a monthly cap |
| Quarantine list for flaky S items (test id, owner, end date) | **not in the code**. Today an S rate under 4/5 fails the run |
| Docker layer cache | **not in the code**: CI would use `docker buildx --cache-from/--cache-to` |
| A job on the next Claude Code version | **not in the code**: the version is in `Dockerfile` and `harness/constants.py`; a build arg would make it one. On 2.1.299, findings 3 and 4 should XPASS and fail the job |
| Upload of artifacts | **not in the code**: CI uploads `artifacts/<run-id>/` (already scanned for the key) |
| Runner timeouts | **in the code** (see Pinned); the job timeout would sit above them (about 40 min with the build) |
| Parallel jobs on one runner | **in the code**: per-test config dirs and fake ports, one container per `./run.sh`, created from the image ID its own build wrote (`--iidfile`) |

## Limits

- **Scope.** 27 of 76 plan ideas are built; PLAN.md gives the reason for
  each one that is not. Not built, among others: pagination and
  `list_changed`, junk on stdout, wrong ids, HTTP reconnect, output size.
- **Ask: only the hook case.** The hook `ask` case is tested
  (`tests/test_permissions.py::test_pre_tool_use_hook_guards_mcp_tool[ask]`):
  in `-p` with `--permission-prompts none`, a hook's `ask` is denied and
  its reason reaches the tool result (hooks.md:1934). Not tested: `ask`
  permission rules and an Ask host (`--permission-prompt-tool`).
- **No managed MCP policy.** `allowedMcpServers` / `deniedMcpServers` and
  `managed-mcp.json` are not tested (PLAN: managed policy): a deployed
  `managed-mcp.json` makes every `--mcp-config` run exit at startup
  (managed-mcp.md:105), so it needs its own container. This and Ask rules
  are the first additions.
- **Doc versions.** The cited Claude Code docs are the current online
  docs, newer than 2.1.296. A cited line counts as holding for 2.1.296
  only where a test checks it.
- **Cost and statistics.** 5 repeats catch a broken pipeline, not a small
  model regression. One model only (`claude-haiku-5-5`).
- **Black-box.** "The idle check runs on a 30 s tick" is inferred from
  two probes (3 s and 31 s), not from code.
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

The first commit's message was reworded on 10-17 after the first review;
git was added at the end of the build.
