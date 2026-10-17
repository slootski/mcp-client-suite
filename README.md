# MCP client test suite for Claude Code 2.1.296

A black-box test suite for the MCP client inside Claude Code 2.1.296. Claude
Code runs in Docker. Small fake MCP servers log every message they get, and
the tests check that log, the `claude` CLI output and the `claude -p`
stream. The plan is in [PLAN.md](PLAN.md), the prompts in
[PROMPTS.md](PROMPTS.md).

## Run it

You need Docker, git, and network access (the build pulls a base image
and Claude Code; model tests call the Anthropic API).

```bash
git clone https://github.com/slootski/mcp-client-suite.git
cd mcp-client-suite
export ANTHROPIC_API_KEY=...        # the key you were given
./run.sh
```

`./run.sh` builds the image, runs the tests in a container, copies the
results out, and exits with the suite's exit code.

| What | Command |
|---|---|
| Everything | `./run.sh` |
| No key: free tests only | `unset ANTHROPIC_API_KEY; ./run.sh` (the `model` tests are skipped, not failed) |
| Free tests only, key set | `./run.sh -m free` |
| One test | `./run.sh -k test_round_trip_echo_canary` (pytest arguments after `./run.sh` go to pytest). A model test: with no key it exits 14 |

With `-k`, an S rate item (`..._s_rate`) needs all 5 repeats in the same
run; with fewer, it is skipped as inconclusive. Results: [Results](#results).

## How it checks

- **The oracle is the fake server's own log** (the wire log). The fakes
  (`fakes/`) are scriptable (hang, crash, error, 401, ...) and log every
  message. "The right tool ran with the right arguments" is read from the
  `tools/call` the server got, compared to the `tool_use` in the stream,
  not from the model's words.
- **D vs S.** D = a client or protocol fact: hard assert on every run and
  in every repeat, never retried. S = the model's choice, as a rate over
  5 repeats (the S rate) that fails below 4 of 5. Full table:
  [docs/flake-policy.md](docs/flake-policy.md).
- **The gate: inconclusive is never a pass.** Each server must be
  `connected` in `system/init`, and the model must have made the call the
  D check needs; if not, one retry in a fresh config dir, then skip. A
  `tools/call` with no `tool_use`, or no `result` event, fails at once. An
  S rate item tolerates 1 wrong call in 5, but a repeat with no call even
  after its retry proved nothing: it is inconclusive, and with the key set
  the run exits 13.
- **Self-tests.** `tests/test_harness_offline.py` replays recorded runs
  with one fact broken at a time, to prove each check can fail.
  `tests/test_gate.py` checks exits 13, 14 and 15 (pytest inside pytest,
  and replays with the API's rejection written in).
  `tests/test_secret_controls.py` does the same for the secret controls.
- **Host pauses.** A model attempt whose wall and monotonic spans differ
  by more than 5 s (e.g. a Mac that sleeps) is inconclusive and retried;
  its non-timing D checks still run.

## What the suite shows

Ten facts about Claude Code 2.1.296. Four are strict xfails: expected
failures that fail the run on the day the documented behavior appears
(an XPASS). Six are recorded, not failures. Evidence:
[observations.md](observations.md), which uses the same numbers.

**Defects** (strict xfail; the run fails when they are fixed):

| # | Finding | Test | Doc |
|---|---|---|---|
| 1 | `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT=3000` aborts a silent stdio tool call after 30 s, not 3 s. The value is read (debug log: "idle timeout 3s"); the check seems to run on a 30 s tick (two probes, not code). | `tests/test_idle_timeout.py::test_idle_timeout_aborts_hung_call` (3 runs), `::..._negotiation_unset` | env-vars.md:337 |
| 5 | `claude mcp get` prints a configured `Authorization` header in clear text. A regression: 2.1.161 fixed it. | `tests/test_status_matrix.py::test_http_configured_header_is_redacted_in_cli_output` | changelog.md:5864 |

**Known in the 2.1.299 changelog, kept as regression guards** (strict
xfail; read in the changelog, proven on 2.1.296; they should XPASS on
2.1.299, which was not run):

| # | Finding | Test | Doc |
|---|---|---|---|
| 3 | `--allowedTools "mcp__guard"` also allows the tools of a server named `guard__ops`. | `tests/test_permissions.py::test_server_allow_rule_does_not_reach_double_underscore_server` | changelog.md:212 |
| 4 | A server-level deny `--disallowedTools "mcp__guard__ops"` does not stop `guard__ops`'s tools. | `tests/test_permissions.py::test_server_deny_rule_stops_double_underscore_server` | changelog.md:297 |

**Observations** (recorded, not failures):

| # | Finding | Test | Doc |
|---|---|---|---|
| 2 | A doc gap. mcp.md:377: stdio servers are not reconnected "automatically". 2.1.296 starts a crashed one again on the next call, as only the 2026-07-28 spec asks (a SHOULD). The test hard-asserts that restart, so a client that stops restarting fails; the doc line is recorded. | `tests/test_crash.py::test_stdio_crash_mid_call` | mcp.md:377; 2026-07-28 basic__transports__stdio.md:116 |
| 6 | An out-of-spec server (a bare 401, no OAuth metadata) shows `✘ Failed to connect — Dynamic Client Registration rejected (HTTP 404)`, not `! Needs authentication`. Recorded only, since the server breaks a spec MUST; a compliant server passes. | `tests/test_status_matrix.py::test_http_bare_401_out_of_spec_server_status_recorded`; `::test_http_no_header_needs_authentication` | mcp.md:764; 2025-11-25 basic__authorization.md:65 |
| 7 | No `notifications/cancelled` is sent after the idle abort, in either negotiation mode (a SHOULD in 2025-11-25): a warning, not a failure. | `tests/test_idle_timeout.py` (warnings summary) | 2025-11-25 basic__lifecycle.md:249-253 |
| 8 | A tool's `isError: true` result and a JSON-RPC error look the same in the stream (`is_error: true`, same text shape); the JSON-RPC code is dropped. Not a defect. | `tests/test_tool_errors.py` (both pass; shape in `run.json`) | 2025-11-25 server__tools.md:472-475 |
| 9 | Every stdio MCP server gets the user's `ANTHROPIC_API_KEY` by default. Both documented controls work; on Linux the scrub needs `bubblewrap`, which env-vars.md does not say. | `tests/test_credentials.py` (3 tests: default, scrub, allowlist) | env-vars.md:406, 334; sandboxing.md:243 |
| 10 | A PreToolUse matcher `mcp__guard` (no `.*`) silently matches nothing, so the call goes through. As documented; a policy trap. | `tests/test_permissions.py::test_pre_tool_use_hook_guards_mcp_tool[matcher_without_wildcard]` | hooks.md:365 |

## Time and cost

Measured on an Apple silicon Mac with Docker Desktop, image layers cached.

- **With the key** (run `20261017T161458Z-93821`): 159 items: 84 run
  Claude Code, 75 self-test the harness. 152 passed, 7 xfailed
  (findings 1, 3, 4, 5), 0 skipped, 0 failed, exit 0. pytest
  took 5 min 25 s (the 4 idle-timeout items 33-35 s each). 43 `claude -p`
  runs cost $0.090 (sum of `total_cost_usd`).
- **Without a key** (run `20261017T161832Z-1138`): 110 passed, 1 xfailed
  (finding 5), 48 model items skipped, exit 0; pytest took 56 s.
- **Budget.** Before each `claude -p` run: if the costs so far plus the
  per-run cap ($0.25) would pass `SUITE_BUDGET_USD` ($5.00), the run
  stops with exit 11.

**Time spent.** Longer than the 2-3 h box. About 7 h of session time by
the PROMPTS.md timestamps (10-16 17:55-21:46; 10-17 00:05-00:58,
11:43-13:21, 13:45-14:13), not all hands-on: review agents ran while the
candidate steered. Plus writing the plan on 10-14 to 10-16, which was
not timed. Not counted: the agents' build overnight and the fix rounds
after the panel reviews, each run from one prompt. The extra time went
into proving the checks can fail.

A 3-hour cut would have kept: the two fake servers and the wire-log
oracle, the round trip, the right tool among two near-duplicates, and a
server crash mid-call. It would have dropped the offline replays, the
permission and hook tests, and the repeats.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | All tests passed (skips and expected failures included) |
| 1 | A test failed, a strict xfail passed (XPASS), or a file held the API key or a test credential |
| 13 | The key is set and at least one model item was skipped as inconclusive |
| 14 | No key, but model items were asked for (`SUITE_REQUIRE_KEY=1`, a `-m` that selects a model item, or only model items selected); no test runs |
| 15 | The Anthropic API rejected the key or the account (HTTP 401 or 403); the run stops at the first model run, no retry |

10 (wrong version), 11 (budget) and the rest: [docs/exit-codes.md](docs/exit-codes.md).

## Results

Each run gets a new folder `artifacts/<run-id>/`; `artifacts/latest` names
the newest one in which a test ran. Open `report.html` first: each test
row shows its log lines and links its files. Every file of a run folder,
and the log format: [docs/log-format.md](docs/log-format.md).

## Choices made

- **Strict xfail only for documented behavior that a fix would flip**
  (findings 1, 3, 4, 5), raised after every hard assert, so a broken wire
  fact still fails. A doc gap or an out-of-spec server (findings 2, 6) is
  record-only, with its wire asserts kept hard.
- **Pinned.** Claude Code 2.1.296 on `node:22-bookworm-slim` pinned by
  digest, autoupdater off, pytest plugins pinned; exit 10 on another
  version. Model `claude-haiku-5-5`, `--max-turns 4`, `--max-budget-usd
  0.25` per run. Timeouts: 120 s per test (360 s for model tests), 1500 s
  per session, 1800 s per run. Model tests pin
  `MCP_PROTOCOL_NEGOTIATION=legacy`; most free tests use the user default.
- **A fresh config dir per test** (`CLAUDE_CONFIG_DIR` and `HOME`). The S
  rate items and `test_stdio_crash_mid_call_same_every_run` read earlier
  items' results, so tests run in file order, not in parallel.
- **The key goes in by `docker cp`, not `docker run -e`**, so `docker
  inspect` never shows it; only pytest gets it, and artifacts record it
  as "set". Every kept file is scanned for it; self-tests plant dummy
  keys to prove the scan and the redaction catch them. Residual risks:
  [docs/flake-policy.md](docs/flake-policy.md#residual-risks).
- **Not the MCP conformance runner**: it speaks Streamable HTTP only and
  does not cover Claude Code's config, permissions, hooks or model path.
- **Why not a scripted model.** S facts (which tool the model picks, with
  which values) need the real model. D facts could move to a scripted
  model behind `ANTHROPIC_BASE_URL`; the suite already runs with tool
  search off, so the scripted model would see the same configuration
  (mcp.md:313). Not built for time; it is the per-change tier a team
  version would add first, with the live model nightly.

## How each requirement is met

| Requirement (from the mail) | Where |
|---|---|
| A test suite for the MCP client; Claude Code in Docker | `Dockerfile` (Claude Code 2.1.296), `tests/`, `harness/`, `fakes/` |
| Black-box: only the released 2.1.296 and the public docs | the npm package at the exact version; expectations cite their doc line |
| A plan: everything you would test, all five questions | [PLAN.md](PLAN.md): 76 ideas plus 9 harness checks, one table per question, `Status` column |
| At least two questions in depth | Question 2, tool calls (round trip, right tool and arguments) and question 3, errors (tool errors, idle timeout, crash). Question 1 by free tests; question 5 by `test_permissions.py` |
| Tests that check real behavior | The fakes' logs, not model text; replays prove the checks can fail |
| Only Docker and git; one command; the key in `ANTHROPIC_API_KEY` | `./run.sh`; without a key the free tests still run |
| Runs in CI later | [CI](#ci) below |
| The key is capped at $50 | `SUITE_BUDGET_USD` $5.00 with a pre-check, `--max-budget-usd 0.25` per run; a full run costs about $0.07-0.09 |

## CI

| Need | State |
|---|---|
| A test view | **in the code**: `junit.xml` (strict xfails show as `skipped`); `outcomes.json` keeps them apart |
| Two jobs: `free` (no key, about 1 min, 111 items) on every change; `model` nightly or on a PR label | **markers in the code** (`-m free`, `-m model`); the job definitions are not written |
| The key as a secret of the model job only; a missing one must not go green | **in the code**: with `SUITE_REQUIRE_KEY=1` a missing key exits 14; a rejected key exits 15 |
| Budget guard | **in the code** (exit 11); CI would add a monthly cap |
| Quarantine for flaky S items (test id, owner, end date) | **not in the code**: an S rate under 4/5 fails the run |
| A job on the next Claude Code version | **not in the code**: the version is in `Dockerfile` and `harness/constants.py`; one build arg would set both. On 2.1.299, findings 3 and 4 should XPASS and fail the job |
| Layer cache, artifact upload, job timeout | **not in the code**: `docker buildx --cache-from/--cache-to`; upload `artifacts/<run-id>/` (already scanned); a job timeout of about 40 min |
| Parallel jobs on one runner | **in the code**: per-test config dirs and fake ports, one container per `./run.sh` |

## Limits

- **Scope.** 28 of 76 plan ideas are built (4 only in part); PLAN.md
  gives the reason for the rest, e.g. pagination, `list_changed`, junk on
  stdout, wrong ids, HTTP reconnect, output size.
- **Permissions and MCP policy.** Tested: hook `deny`, `ask` and `allow`
  (`ask` and `deny` both stop the call; only `ask` adds a
  `permission_denied` event, headless.md:333), allow and deny rules, and
  `deniedMcpServers` / `allowedMcpServers` given in inline `--settings`, on
  `--mcp-config` servers (`test_mcp_server_policy_in_user_settings[denied]`
  and `[allowed_only]`; managed-mcp.md:251, :259). Not tested: Ask permission
  rules, an Ask host (`--permission-prompt-tool`), and `managed-mcp.json`,
  the first next item. Only `managed-mcp.json` needs its own container: a
  deployed one makes every `--mcp-config` run exit (managed-mcp.md:105).
- **Doc versions.** The cited Claude Code docs are the current online
  docs, newer than 2.1.296. A cited line counts as holding for 2.1.296
  only where a test checks it.
- **Cost and statistics.** 5 repeats catch a broken pipeline, not a small
  model regression. One model only (`claude-haiku-5-5`).
- **Protocol and transports.** The fakes speak 2025-11-25 only, so a full
  2026-07-28 session and its MUST to cancel are not tested. stdio in
  depth; HTTP only through `claude mcp list/get`; no SSE, WebSocket, or
  OAuth login flow (`-p` cannot open a browser).
- **Platform.** Linux container only, seen on Docker Desktop for Mac
  (arm64); the base image pin is multi-arch.

## Layout

```
.
├── run.sh              build, run, copy results out
├── Dockerfile          pinned image, Claude Code 2.1.296, non-root
├── pytest.ini          markers (free, model), timeouts, strict xfail
├── harness/            run `claude`, model-run flow, checks, cost, secret scan
├── fakes/              scriptable stdio and HTTP MCP servers; hook scripts
├── tests/              the tests; tests/data/ holds recorded runs
├── docs/               flake policy, log format, exit codes
├── evidence/           one-off probes cited in observations.md
├── prompts/            plan/, plan-review/, repo-review/, build prompts 01-19
├── observations.md     what 2.1.296 did, with dates and evidence
└── artifacts/          run output (not in git)
```

The first commit's message was reworded on 10-17 after the first review;
git was added at the end of the build.
