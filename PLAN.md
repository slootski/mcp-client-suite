# PLAN

The plan was written as prompt files for an AI build agent (docs 00 and 11
to 24, verbatim in [`prompts/plan/`](prompts/plan/)). Docs 11 to 23 hold
every test idea, one per line, tagged P0, P1 or P2. The plan was reviewed
5 times ([`prompts/plan-review/`](prompts/plan-review/)). Doc 24 then cut
the build to 10 items: question 2 (tool calls) and question 3 (errors) in
depth, question 1 (connection and auth) by free `claude mcp` tests.

## The 10 built items

As decided in doc 24. "Strict xfail" = a documented behavior 2.1.296 does
not show, which a product fix would flip; the test fails the run the day it
starts to pass. "Recorded" = compared with the doc line and kept in
`run.json`, never a failure (a doc gap, or an out-of-spec server).

| # | Item | File | Variants and repeats | Strict xfails |
|---|---|---|---|---|
| 1 | D12/T1 + T3 handshake | `tests/test_handshake.py` | legacy and unset negotiation; discover answered with -32603; discover never answered (+ the 7-day memory of the result); 5 repeats each | none |
| 2 | D12/T4 + D13/T3 status matrix (+ D23/T2) | `tests/test_status_matrix.py`; D23/T2 in `tests/test_model_smoke.py` | 7 cases: stdio healthy, stdio dies at start, HTTP right header, header redaction, wrong header (401), no header + OAuth metadata, bare 401 | `claude mcp get` prints the configured header (changelog.md:5864). Recorded, not xfailed: a bare 401 from an out-of-spec server shows `✘ Failed to connect`, not `! Needs authentication` (mcp.md:762) |
| 3 | D13/T4 + D23/T11 credentials | `tests/test_credentials.py` | stdio default, stdio with scrub, stdio with `CLAUDE_CODE_MCP_ALLOWLIST_ENV=1`, `--env`; header with `${ANTHROPIC_API_KEY}`, `${NPM_TOKEN}`, an own variable; url blanked and expanded | none |
| 4 | D14/T1 (+ T2) smoke | `tests/test_model_smoke.py` | tool search off; tool search at its default | none |
| 5 | D15/T1 right tool | `tests/test_right_tool_args.py` | 5 repeats + S rate item; 1 run with negotiation unset | none |
| 6 | D15/T2 + T3 argument and result fidelity | `tests/test_right_tool_args.py` | 5 repeats + S rate item | none |
| 7 | D16/T1 + T2 tool errors | `tests/test_tool_errors.py` | `isError: true`; JSON-RPC -32602; 5 repeats each + S rate items | none |
| 8 | D19/T1 + T3 idle timeout and cancel | `tests/test_idle_timeout.py` | 3 runs legacy + 1 run unset | give-up in [2.75 s, 5 s) with idle 3000 (env-vars.md:337); 2.1.296 gives up at 30 s (4 items) |
| 9 | D20/T1 crash mid-call | `tests/test_crash.py` | 3 runs + one "same every run" item | none. Recorded: one spawn, no restart (mcp.md:377); 2.1.296 starts the server again on the next call, as the 2026-07-28 spec's SHOULD asks (a doc gap) |
| 10 | D23/T9 (+ T10) hooks and permission rules | `tests/test_permissions.py` | T9: deny, matcher without `.*`, exit 1, `onFailure: "block"`; T10: deny rule, no-allow-rule control, variant A, variant B | T10 A: `mcp__guard` also allows `guard__ops` (changelog.md:212, fixed 2.1.299); T10 B: deny `mcp__guard__ops` does not apply (changelog.md:297, fixed 2.1.299) |

Harness self-checks (free, no model call): `tests/test_harness_offline.py`
replays recorded model runs through the real test code with one fact
broken at a time, and checks that each break fails the test (not skip,
not xfail), and that a fixed-client shape of each strict xfail would
XPASS.

Totals: 76 test ideas in docs 12 to 23 (one of them, D13/T7, merged into
D20/T3), plus 9 harness checks from doc 11. 27 ideas are implemented (3
of them only in part: D12/T2, D13/T1, D19/T3); they run as 98 pytest
items (54 free, 44 model). The first item to build next is D23/T13
(managed MCP allow and deny lists).

## Columns

- **ID**: `D<nn>/T<n>` = doc nn, test n, as numbered in the doc. The docs'
  own gaps stay: doc 18 has no T2, doc 23 has no T3. Doc 13 has a T3a and
  a T3b.
- **Oracle**: how the test knows. "Wire log" is the fake MCP server's own
  log of every message it got and sent. "Stream" is the `claude -p
  --output-format stream-json` output.
- **D or S**: D = a client or protocol fact, hard assert, every run. S =
  model behavior, measured as a rate or used only as a trigger. "D (S
  trigger)" = the D facts are checked once the model made the call; if it
  did not, the run is inconclusive, retried once, then skipped, never
  passed. See the flake policy below.
- **Status**: `implemented: tests/<file>::<test>` (every name checked with
  `pytest --collect-only`) or `not implemented: <reason>`.

**Mapping.** Each doc goes to the question its first line names: docs
12-13 to question 1, docs 14-15 and 18 to question 2 (doc 18 is about the
tool list), docs 16, 17, 19, 20 and 21 to question 3, doc 22 to question
4, doc 23 to question 5. Doc 11 is the harness; its checks are listed
first.

## Harness (doc 11)

| ID | What it checks | Oracle | D or S | Priority | Status |
|---|---|---|---|---|---|
| D11/H1 | Claude Code is exactly 2.1.296 before any test | `claude --version` | D | P0 | implemented: `tests/conftest.py::pytest_sessionstart` (exit 10 otherwise) |
| D11/H2 | Pinned env: `MCP_PROTOCOL_NEGOTIATION=legacy` for model tests, unset for free tests and for the `_negotiation_unset` model items (D15/T1, D19); `ENABLE_TOOL_SEARCH=false` except D14/T2; `MCP_TIMEOUT`, `MCP_TOOL_TIMEOUT` set | `run.json` records every pin | D | P0 | implemented: `harness/constants.py` (`FREE_ENV_PINS`, `MODEL_ENV_PINS`), `tests/conftest.py` |
| D11/H3 | Every `claude -p` run: `--permission-mode default --permission-prompts none --allowedTools ...`, stream-json, `--max-turns`, `--max-budget-usd`, `--debug=mcp --debug-file`, `--mcp-config --strict-mcp-config` | the argv in `commands.jsonl` | D | P0 | implemented: `harness/model_run.py` |
| D11/H4 | A fresh `CLAUDE_CONFIG_DIR` and `HOME` per test | `run.json` | D | P0 | implemented: `tests/conftest.py` (`new_sandbox`) |
| D11/H5 | Gate: every server of the test is `connected` in `system/init`, else inconclusive | stream | D | P0 | implemented: `harness/model_flow.py`, `harness/model_checks.py::gate_problem` |
| D11/H6 | One `tools/call` per `tool_use`, same name, arguments == `tool_use.input`; no call without a `tool_use` | wire log vs stream | D | P0 | implemented: `harness/model_checks.py` (`d_passthrough`, `assert_every_call_has_a_tool_use`); proof `tests/test_harness_offline.py` |
| D11/H7 | Known product defect = `xfail(strict=True)` naming the doc or changelog line | pytest outcome | D | P0 | implemented: `harness/known_defects.py`, `pytest.ini` (`xfail_strict = true`) |
| D11/H8 | Suite cost cap: sum of `total_cost_usd`, stop at `SUITE_BUDGET_USD` ($5) | `cost.json` | D | P0 | implemented: `harness/cost_ledger.py` (exit 11) |
| D11/H9 | No artifact holds the API key or a test credential; fakes log only a hash and length of env and header values, and the live key only as "set" | scan of every kept file | D | P0 | implemented: `harness/entrypoint.py`, `harness/redact.py`, `fakes/wirelog.py` |

## Question 1: Connection and auth

| ID | What it checks | Oracle | D or S | Priority | Status |
|---|---|---|---|---|---|
| D12/T1 | Legacy handshake: `initialize` fields, reply, then `notifications/initialized` with no id; no request but ping before the `initialize` reply | wire log (the reply is held 300 ms) | D | P0 | implemented: `tests/test_handshake.py::test_handshake_on_the_wire` (both negotiation modes, 5 repeats each) |
| D12/T2 | Negotiation unset: `server/discover` before `initialize`, with the preferred version in `_meta`; then DiscoverResult, -32022 retry, -32601 fallback | wire log | D | P0 | partly implemented: `tests/test_handshake.py::test_handshake_on_the_wire[unset-*]` checks the probe, its `_meta` version and the -32601 fallback. Not implemented: the DiscoverResult and -32022 cases, and a full 2026-07-28 session (the fakes speak only 2025-11-25)[^scope] |
| D12/T3 | Fallback to `initialize` when discover fails (generic error, or silence); measure the delay; the 7-day memory of the negotiation result | wire log, `state/mcp-discover-verdicts.json` | D | P0 | implemented: `tests/test_handshake.py::test_discover_generic_error_falls_back_to_initialize`, `tests/test_handshake.py::test_discover_silent_falls_back_and_is_remembered_per_config_dir` |
| D12/T4 | `claude mcp list` / `get` status strings: `✔ Connected`, `✘ Failed to connect`, `! Needs authentication` | CLI output + wire log | D | P0 | implemented: `tests/test_status_matrix.py` (7 cases, e.g. `::test_stdio_healthy_is_connected`, `::test_stdio_exit_at_start_is_failed_to_connect`) |
| D12/T5 | Startup slower than `MCP_TIMEOUT`: status `pending`/`failed`, wall time | stream + wire log | D | P1 | not implemented[^scope]. Seen once by hand: `claude mcp list` cancels `initialize` at 12 s with `MCP_TIMEOUT=15000` (observations.md) |
| D12/T6 | Server capabilities match later behavior (e.g. `listChanged`) | wire log | D | P1 | not implemented: depends on doc 18, not built |
| D12/T7 | `roots/list` answered with the working directory | wire log | D | P2 | not implemented: observe-only, needs server-initiated requests |
| D12/T8 | Scope precedence: local beats user for the same name | `claude mcp get` + wire log | D | P2 | not implemented[^scope] |
| D12/T9 | Server answers `initialize` with an unsupported version: disconnect or failed | status + wire log | D | P2 | not implemented[^scope] |
| D13/T1 | stdio secret via `--env` reaches the server; without it, the server's own error reaches `tool_result` | wire log (hash of the value) | D | P0 | partly implemented: `tests/test_credentials.py::test_stdio_env_flag_value_reaches_server` (the value reaches the server). Not implemented: the "without `--env`" half (needs a model run)[^scope] |
| D13/T2 | HTTP static `Authorization` header, right key: `✔ Connected` | `claude mcp get` + HTTP fake log (header hash) | D | P0 | implemented: `tests/test_status_matrix.py::test_http_right_header_is_connected` |
| D13/T3a | Configured header gets 401: `✘ Failed to connect` with the 401 detail, not "needs authentication" | CLI output + HTTP fake log | D | P0 | implemented: `tests/test_status_matrix.py::test_http_wrong_header_is_failed_with_401_detail` |
| D13/T3b | No configured header, 401: `! Needs authentication` | CLI output + HTTP fake log | D | P0 | implemented: `tests/test_status_matrix.py::test_http_no_header_needs_authentication` (401 with OAuth metadata); `::test_http_bare_401_out_of_spec_server_status_recorded` (bare 401 from an out-of-spec server with no OAuth metadata: status recorded, not a strict xfail; the wire facts are hard asserts) |
| D13/T4 | `${ANTHROPIC_API_KEY}` / `${NPM_TOKEN}` in a remote header or url is sent empty; an own variable is expanded | HTTP fake log (length 0) | D | P0 | implemented: `tests/test_credentials.py::test_remote_header_credential_variable_is_sent_empty`, `::test_remote_header_own_variable_is_expanded`, `::test_remote_url_variable` |
| D13/T5 | OAuth 401 on a logged-in server: refresh, reconnect, retry once | HTTP fake log | D | P1 | not implemented: needs a scripted `claude mcp login` with a terminal and a fake authorization server |
| D13/T6 | `-p` cannot run the OAuth browser flow; the model is told the tools are unavailable | stream | D | P2 | not implemented: observe-only |
| D13/T7 | HTTP drop and backoff | - | - | - | merged into D20/T3 |
| D13/T8 | First-connect transient retry (503 then OK, up to 3 attempts); no retry on auth error or not-found | HTTP fake log | D | P1 | not implemented[^scope] |
| D13/T9 | HTTP `MCP-Protocol-Version` header and `Mcp-Session-Id` echo | HTTP fake log | D | P1 | not implemented[^scope] |
| D13/T10 | Project `.mcp.json` under `-p`, with and without `--strict-mcp-config` | marker server log | D | P1 | not implemented[^scope] |
| D13/T11 | `headersHelper` | - | D | P2 | not implemented: in `-p` it runs only after trust is set by hand; the static-header tests cover the auth path |

## Question 2: Tool calls

| ID | What it checks | Oracle | D or S | Priority | Status |
|---|---|---|---|---|---|
| D14/T1 | Round trip: `echo_canary` returns a fresh canary; one `tools/call`, `tool_result` == the server's text, canary in the answer | wire log + stream; the answer is S, recorded | D (S trigger) | P0 | implemented: `tests/test_model_smoke.py::test_round_trip_echo_canary` |
| D14/T2 | Tool search at its default (on): the tool is still called | stream (`ToolSearch` in `system/init`) + wire log | D (S trigger) | P0 | implemented: `tests/test_model_smoke.py::test_round_trip_with_tool_search_default` |
| D14/T3 | Tool name is `mcp__<server>__<tool>` | stream (`system/init` tools, `tool_use.name`) | D | P1 | implemented: `tests/test_right_tool_args.py::test_right_tool_among_near_duplicates` (asserts `mcp__calc__add` and `mcp__calc2__add` in `system/init` tools and routes each call by that name) |
| D15/T1 | Two near-duplicate `add` tools on `calc` and `calc2`; the named one ran, with the exact arguments | wire log of both fakes (`tool_executed`, `side_effect`) | D (S rated) | P0 | implemented: `tests/test_right_tool_args.py::test_right_tool_among_near_duplicates` (5 repeats), `::test_right_tool_among_near_duplicates_s_rate`, `::test_right_tool_among_near_duplicates_negotiation_unset` |
| D15/T2 | Argument fidelity on a rich schema (enum, array order, non-ASCII, nested object, absent optional key) | wire log vs `tool_use.input`, canonical JSON | D (S rated) | P0 | implemented: `tests/test_right_tool_args.py::test_ticket_arguments_and_result_fidelity` (5 repeats), `::test_ticket_arguments_and_result_fidelity_s_rate` |
| D15/T3 | Return value fidelity: the server-generated id reaches `tool_result` | wire log `sent` text == `tool_result` text; the answer is S, recorded | D (S trigger) | P0 | implemented: same tests as D15/T2 |
| D15/T4 | Chained calls: `get_ticket(id)` with the id `create_ticket` returned | wire log order and arguments | D (S trigger) | P1 | not implemented[^scope] |
| D15/T5 | Integer parameter given in words or as a string: what goes on the wire | wire log | D + S | P1 | not implemented[^scope] |
| D15/T6 | `outputSchema` + `structuredContent`, and data that does not match | stream | D | P2 | not implemented: observe-only |
| D18/T1 | `tools/list` pagination: the tool on page 2 is callable | wire log (cursor) + stream | D (S trigger) | P1 | not implemented[^scope] |
| D18/T3 | `list_changed` ordering: old tool gone, new tool callable after the notification | wire log order + stream | D (S trigger) | P0 | not implemented[^scope] (doc 24 kept two P0 areas in depth) |
| D18/T4 | `list_changed` with a failing refresh keeps the old tools | stream | D (S trigger) | P1 | not implemented[^scope] |
| D18/T5 | v2 held-open stream reconnect for `list_changed` | - | D | P2 | not implemented: cannot be triggered reliably in a short run[^scope] |

## Question 3: Errors

| ID | What it checks | Oracle | D or S | Priority | Status |
|---|---|---|---|---|---|
| D16/T1 | Tool execution error (`isError: true`): error `tool_result` with the fresh token, `PostToolUseFailure` fires, server stays connected, next call works | wire log + stream + hook log | D (S rated) | P0 | implemented: `tests/test_tool_errors.py::test_tool_execution_error_is_error_result` (5 repeats), `::test_tool_execution_error_is_error_result_s_rate` |
| D16/T2 | Protocol error (JSON-RPC -32602) for a listed tool: same asserts | wire log + stream + hook log | D (S rated) | P0 | implemented: `tests/test_tool_errors.py::test_protocol_error_is_error_result` (5 repeats), `::test_protocol_error_is_error_result_s_rate` |
| D16/T3 | A `tools/call` result with neither `content` nor `isError` | stream | D (S trigger) | P0 | not implemented[^scope] |
| D16/T4 | Compare `isError`, a crash mid-call and a bad envelope | stream | D | P1 | not implemented as a test: the T1 vs T2 side by side and the crash shape are in observations.md; the bad envelope (D21/T2) is not built |
| D17/T1 | Non-JSON line on stdout: `Connection closed` | status + stream | D | P1 | not implemented[^scope] |
| D17/T2 | JSON line with no trailing newline, newline sent late | wire log + stream | D | P1 | not implemented[^scope] |
| D17/T3 | Heavy stderr noise does not affect the connection | status + stream | D | P1 | not implemented[^scope] |
| D17/T4 | Very long single stdout line | stream | D | P2 | not implemented: observe-only |
| D19/T1 | Idle timeout: with `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT=3000`, a silent `tools/call` aborts at 3 s or later, before 5 s | fake's `recv` epoch vs `tool_result` timestamp; the client's idle-abort text | D (S trigger) | P0 | implemented: `tests/test_idle_timeout.py::test_idle_timeout_aborts_hung_call` (3 runs), `::test_idle_timeout_aborts_hung_call_negotiation_unset`. The 3-5 s window is a strict xfail: 2.1.296 aborts at 30 s |
| D19/T2 | Progress resets the idle timer, not the wall-clock cap | wire log + stream | D | P0 | not implemented: 2.1.296 checks the idle timer on a 30 s tick, so 3 s / 8 s cannot tell a reset from "not checked yet"; a real T2 needs runs of 1-2 min |
| D19/T3 | `notifications/cancelled` with the request id after the give-up, and nothing more for that request | wire log | D + SHOULD | P0 | partly implemented: same tests as D19/T1. The legacy negotiation (a SHOULD) is checked: a miss is a warning, "nothing more" is hard. Not implemented: the MUST case (default negotiation with a 2026-07-28 server): the fakes speak only 2025-11-25, so with negotiation unset the client falls back to 2025-11-25 too |
| D19/T4 | Auto-background threshold in `-p` | stream | D | P1 | not implemented: observe-only, no stream event is documented |
| D19/T5 | SIGINT / SIGTERM to `claude -p` mid-call: cancel or teardown, exit 143 | wire log + exit code | D | P1 | not implemented[^scope] |
| D19/T6 | HTTP per-request timer vs stdio none | wire log | D | P2 | not implemented: observe-only |
| D20/T1 | stdio server exits mid-call: error `tool_result` within 5 s, no hang; is it restarted? | wire log (`exit`, `started`) + stream timestamps | D (S trigger) | P0 | implemented: `tests/test_crash.py::test_stdio_crash_mid_call` (3 runs), `::test_stdio_crash_mid_call_same_every_run`. "No restart" (mcp.md:377) is recorded, not a strict xfail: 2.1.296 starts the server again on the next call, as the 2026-07-28 spec's SHOULD asks (basic__transports__stdio.md:116), so this is a doc gap |
| D20/T2 | Crash while idle: when does the client notice; spawn count | wire log | D | P0 | not implemented[^scope] |
| D20/T3 | HTTP server drops, comes back: backoff, reconnect; 5 failures mark it failed (merged D13/T7) | HTTP fake log | D | P0 | not implemented[^scope] |
| D20/T4 | stdio shutdown: SIGINT, SIGTERM after 100 ms, SIGKILL after 400 ms more; no orphan | fake's signal log + `ps` | D | P1 | not implemented[^scope] (the fake logs the SIGINT; nothing asserts it) |
| D20/T5 | Call during reconnect is held 10 s, then "No such tool available" | stream | D | P1 | not implemented[^scope] |
| D20/T6 | stdio server exits during the handshake: failed, no restart, `result` event | wire log + stream | D | P1 | not implemented as a model test. Close: `tests/test_status_matrix.py::test_stdio_exit_at_start_is_failed_to_connect` (via `claude mcp list`; 2 spawns per command, recorded) |
| D21/T1 | Orphan response id is ignored; the real reply is matched | stream | D | P1 | not implemented[^scope] |
| D21/T2 | Valid JSON with no JSON-RPC envelope | stream + status | D | P1 | not implemented[^scope] |
| D21/T3 | Two replies with the same id | stream | D | P1 | not implemented: observe-only, the spec does not say |
| D21/T4 | Late reply after the timeout | stream | D | P2 | not implemented: observe-only |

## Question 4: Determinism

| ID | What it checks | Oracle | D or S | Priority | Status |
|---|---|---|---|---|---|
| D22/T1 | Repeat harness: N = 5; D facts 5/5, S facts as a rate, fail under 4/5 | `s-rate.json`, `s-rates.json`, terminal summary | D + S | P0 | implemented: `harness/repeat.py`; `tests/test_right_tool_args.py::test_right_tool_among_near_duplicates_s_rate`, `::test_ticket_arguments_and_result_fidelity_s_rate`, `tests/test_tool_errors.py::test_tool_execution_error_is_error_result_s_rate`, `::test_protocol_error_is_error_result_s_rate`; the handshake tests run 5 repeats (all D) |
| D22/T2 | Flake policy table: fact, variance, treatment | the table | - | P0 | implemented: [`docs/flake-policy.md`](docs/flake-policy.md) |
| D22/T3 | Sampling cannot be set from outside: why the in-depth tests check wire facts | - | - | P1 | implemented: `docs/flake-policy.md` ("Classes") |
| D22/T4 | Tool order in `tools/list` does not change which tool is called | wire log | S | P1 | not implemented[^scope] |
| D22/T5 | Scripted fake model behind `ANTHROPIC_BASE_URL` | - | D | P2 | not implemented: tool search turns off, Claude waits with `WaitForMcpServers`, failed servers are not reported to Claude; the real-model tier is kept |

## Question 5: What else has to be true

| ID | What it checks | Oracle | D or S | Priority | Status |
|---|---|---|---|---|---|
| D23/T1 | Output over 25,000 tokens goes to a file under `tool-results`; 49,999 / 50,001 chars | stream + the file | D (S trigger) | P0 | not implemented[^scope] |
| D23/T2 | A broken `--mcp-config` entry is in `mcp_server_errors` with its type; the healthy server still works | stream (`system/init`) + wire log | D (S trigger) | P0 | implemented: `tests/test_model_smoke.py::test_broken_config_entry_is_reported_and_healthy_server_works` |
| D23/T4 | One server hangs, the other still works | wire log + stream | D (S trigger) | P1 | not implemented[^scope] |
| D23/T5 | `claude mcp list` 5 times gives the same status | CLI output | D | P1 | not implemented[^scope] (the status matrix runs once per case) |
| D23/T6 | Root-level `anyOf`/`oneOf`/`allOf` schema: flattened or skipped | stream | D | P2 | not implemented: observe-only |
| D23/T7 | Tool name over 128 chars is left out, the others stay | stream + debug log | D | P2 | not implemented: observe-only |
| D23/T8 | `requiresUserInteraction` tool under `--permission-prompts none` is denied | stream | D | P1 | not implemented[^scope] |
| D23/T9 | PreToolUse hook denies `delete_all`: no `tools/call` for it; variants: matcher without `.*`, hook exit 1, `onFailure: "block"` | wire log + hook log + stream | D (S trigger) | P0 | implemented: `tests/test_permissions.py::test_pre_tool_use_hook_guards_mcp_tool` (4 cases) |
| D23/T10 | Deny rule for one tool; least privilege for a server named `guard__ops` (server-level deny; allow on `mcp__guard`) | wire log of both fakes + stream (`permission_denials`, `permission_denied`) | D (S trigger) | P0 | implemented: `tests/test_permissions.py::test_deny_rule_keeps_call_from_server`, `::test_tool_without_allow_rule_is_denied` (control), `::test_server_allow_rule_does_not_reach_double_underscore_server` (strict xfail), `::test_server_deny_rule_stops_double_underscore_server` (strict xfail) |
| D23/T11 | `ANTHROPIC_API_KEY` reaches a stdio server by default, not with `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` or `CLAUDE_CODE_MCP_ALLOWLIST_ENV=1`; merged with D13/T4 | wire log (sha8 + length; env names) | D | P0 | implemented: `tests/test_credentials.py::test_stdio_inherits_credentials_by_default`, `::test_stdio_env_scrub_strips_inherited_credentials`, `::test_stdio_allowlist_env_passes_only_baseline_and_configured_env` (env-vars.md:334) |
| D23/T12 | Invalid input schema next to a good tool | stream | D | P1 | not implemented[^scope] |
| D23/T13 | Managed policy (`allowedMcpServers`, `deniedMcpServers`, `managed-mcp.json`) | - | D | P2 | not implemented: a deployed `managed-mcp.json` makes every `--mcp-config` run exit at startup, so it needs its own container. **First next item**: managed allow and deny lists are the policy Bay sells against |
| D23/T14 | `readOnlyHint: true` on a destructive tool with no allow rule: denied like any tool | stream | D | P2 | not implemented[^scope]. The plain "no allow rule, denied" case is checked by `tests/test_permissions.py::test_tool_without_allow_rule_is_denied` |

## Flake policy (summary)

The full table, one row per fact the suite checks, is in
[`docs/flake-policy.md`](docs/flake-policy.md).

1. D (client or protocol fact): hard assert on every run, 5 of 5 in a
   repeated test; never retried.
2. S (model behavior): a pass rate over 5 repeats; the test fails only
   below 4 of 5. The model's wording is recorded only.
3. If the model did not make the call that a D check needs (the S
   trigger), or a server is not `connected`, the attempt is inconclusive:
   one retry in a fresh config dir, then skip. Inconclusive is never a
   pass: with the key set, a run with any inconclusive model item exits
   13; model items asked for with no key (`SUITE_REQUIRE_KEY=1`, or `-m`
   selecting a model item) exit 14.
4. A `tools/call` with no `tool_use`, or a stream with no `result` event,
   is a D failure on any attempt, before the retry decision.
5. A documented behavior that a product fix would flip is a strict xfail
   citing the doc line; the run fails the day it passes. A doc gap or an
   out-of-spec server is recorded only (`run.json`), with its wire asserts
   kept hard.

[^scope]: Not built because the build was cut to the 10 items of doc 24
    (see "The 10 built items"), not because the idea was wrong. The mail
    asks for about 2-3 hours of work; this work took longer than that box
    (wall clock from the first plan file to the last commit of the
    original build: 2026-10-14 09:22 to 2026-10-17 13:50 (local time),
    about 3 days 4 h, with nights and gaps in between; wall clock, not
    hours worked). A row gives its own reason only when the reason is not
    this cut.
