# Flake policy

Which results are the same on every run, and how the suite treats each kind
(doc 22).

## Classes

- **D (deterministic)**: a client or protocol fact. It does not depend on the
  model. Hard assert: it must hold on every run, and in a repeated test in N
  of N repeats. A D failure is never retried. It is a candidate product bug,
  and its wire log stays in the artifacts of that repeat.
- **S (model behavior)**: what the model chose to do. A repeated test
  measures it as a pass rate. The test fails only when the rate is below the
  threshold (`S_RATE_MIN_PASSES` = 4 of `REPEATS` = 5). The rate is written
  to `s-rate.json` (per rate item), `s-rates.json` (per run) and printed in
  the terminal summary.
- **Record only**: kept in `run.json` or the rate files, never fails a test.
  Used for the model's wording, for undocumented client behavior that
  the docs do not promise either way, and for a doc line the product is
  not held to: a doc gap (a crashed stdio server is started again on the
  next call, mcp.md:377; the later call's success on a new process stays
  a hard assert) or an out-of-spec server (a bare 401 with no OAuth
  metadata, mcp.md:764). Those two are compared with the doc line by
  `record_documented` (`harness/known_defects.py`): a `record ... ->
  MATCHES` or `-> DIFFERS` log line and a `run.json` key, never a failure.
  The wire asserts of the same tests stay hard.
- **Strict xfail**: a documented behavior that 2.1.296 does not show and
  that a product fix would flip (`xfail(strict=True)` with the doc line,
  and an `observations.md` entry). It fails the run on the day it starts
  to pass. Seven items: the idle timeout (4 items), T10 variant A, T10
  variant B, and `claude mcp get` redaction.

"Era" in the tables below means the protocol version negotiation mode:
"legacy" = `MCP_PROTOCOL_NEGOTIATION=legacy` (`initialize` first, pinned in
model tests); "unset" = the user default (a `server/discover` probe
first). Both end at 2025-11-25, the only revision the fakes speak.

Sampling (temperature) cannot be set from outside the CLI. This is why the
in-depth tests check wire facts (D), and why model facts get a rate instead
of a hard assert (doc 22 test 3).

## Inconclusive runs

| Situation | What the suite does |
|---|---|
| A server of the test is not `connected` in `system/init` (the gate) | The attempt is inconclusive. It is retried once, in a fresh `CLAUDE_CONFIG_DIR`. The retry is logged in `run.json` (`observations.model_runs[].inconclusive`, `.retried`, `.config_dir`) and charged to the ledger. |
| The model made no `tool_use` with a trigger name (the S trigger did not happen; in D16 and D20 each of the two trigger names needs its own `tool_use`, `require_all_triggers`) | Same: inconclusive, one retry in a fresh config dir, logged. The D facts of the test are not checked on that attempt, because "no call" proves nothing, with one exception (next row). |
| Any attempt, before the retry decision: a `tools/call` reached a fake with no `tool_use` for it in that attempt's stream | D failure, never an S miss: the item fails at once and no retry runs (`harness/model_flow.py`, `model_checks.assert_every_call_has_a_tool_use`). A call is matched to a `tool_use` by `_meta["claudecode/toolUseId"]`, else by name and equal arguments. The attempt is written to `run.json` first (`observations.model_runs[]`, with `tools_call_count` per fake) and its `stream-attemptN.jsonl` and wire logs stay in the artifacts, so the dropped attempt is kept. Rule: a retry never replaces an attempt that was not checked (QA step 4). Proof: `tests/test_harness_offline.py` replays a recorded D15/T1 run with the `tool_use` cut out of attempt 0; it fails before attempt 1, and with the check removed it does not. |
| Any attempt, before the retry decision: the stream has no `result` event (the client ended the run after `system/init`, e.g. right after an error or a crash) | D failure, never inconclusive: the item fails at once, no retry (`harness/model_flow.py`, QA step 5). The same place runs each test's own `attempt_checks`: D16 judges the failing tool's error `tool_result` and D20/T1 the crashed call (one `tool_result`, `is_error`, the 5 s bound) on every attempt where that `tool_use` exists. Proof: `tests/test_harness_offline.py` replays recorded D16/T1, D16/T2 and D20/T1 runs cut after the first `tool_result` (QA's `client_died_after_*` mutation), plus a crash run with its error `tool_result` removed: each FAILS (a plain `AssertionError`, not a skip and not the crash test's `DocumentedBehaviorMismatch`); with the two checks removed the same cases skip or pass. |
| The host clock jumped during the attempt: its wall-clock span and its monotonic span (`duration_s`) differ by more than `CLOCK_STEP_TOLERANCE_S` = 5 s, either way (e.g. a sleeping Mac) | Inconclusive (`inconclusive: the host clock jumped during the run ...`), retried like any inconclusive attempt; the gate and trigger are not judged on it. Every D check still runs on it: the built-in ones and the test's own attempt checks, none of which compares two clocks (the crash test's 5 s bound runs only in its final check, on a conclusive attempt). Proof: `tests/test_gate.py::test_clock_jump_does_not_hide_a_crash_d_failure` and the `[clock_jump]` / `[clock_step_back]` skip cases. |
| Still inconclusive after the retry | The item is skipped with reason `inconclusive: ...`, never passed. In a repeated test that repeat counts as an S miss (all rated facts false). |
| A repeat ended (an exception) before it recorded its S facts | That repeat counts as an S miss, with the reason in `s-rate.json`. |
| Fewer than `REPEATS` repeats ran in this session (a `-k` subset) | The rate item is skipped as inconclusive: a partial sample is not judged. So a `-k` that selects only rate items exits 13 with the key set, 14 without it. The rate item relies on pytest's file order (repeats first); no reordering plugin is installed. |
| Every repeat of a test was inconclusive | The rate item is skipped as inconclusive. |
| The key is set, and any model item of the run was skipped as inconclusive (pytest itself returned 0) | The run exits 13 (`INCONCLUSIVE_EXIT_CODE`). The items are printed under "model tier verdict" and listed in `outcomes.json` (`inconclusive_model_items`). An S rate item tolerates 1 wrong call in 5. A repeat in which the model made no call at all, even after its retry, proved nothing: it is inconclusive, and with the key set the run exits 13. |
| No key, and model items were asked for: `SUITE_REQUIRE_KEY=1` (whatever is selected), a `-m` expression that selects a model item, or a selection in which every item is a model item | The run stops before any test with exit 14 (`MODEL_TESTS_NEED_KEY_EXIT_CODE`), so a CI model job whose secret is missing cannot go green. |
| The API rejects the key or the account (HTTP 401 or 403: the `result` event's `api_error_status`, seen on 2.1.296; or a `system/api_retry` event with `error` `authentication_failed` or `error_status` 401/403, headless.md:247, 249) | The run stops at the first model run with exit 15 (`API_KEY_REJECTED_EXIT_CODE`), no retry, so a bad key is not reported as a model miss. Proof: `tests/test_gate.py::test_key_rejected_stops_the_run_with_15` (a recorded run with the rejection written in: one attempt, exit 15). |
| A D assert fails | The item fails. It is not retried, and the other repeats still run. |
| The ledger total would pass `SUITE_BUDGET_USD` | The run stops with exit 11 before the next model run. |
| `MODEL_ID` is not accepted | The run stops with exit 12. |
| `claude --version` is not `EXPECTED_CLAUDE_VERSION` (2.1.296), or cannot run | The run stops with exit 10 (`VERSION_GATE_EXIT_CODE`) before any test, free tests included. |

## Every fact the suite checks (steps 1 to 7)

Runs: "1" is one run per suite run. "5/5" is a repeated test (`REPEATS` = 5,
one pytest item per repeat, each with a fresh config dir and fresh values).

| Test | Fact | Expected variance | Treatment | Runs |
|---|---|---|---|---|
| D12/T1 `test_handshake_on_the_wire[legacy]` | First message `initialize`, no `server/discover` | none | D, hard assert | 5/5 |
| D12/T1 both eras | `initialize`: `jsonrpc` 2.0, an id, `protocolVersion` 2025-11-25, `capabilities` object, `clientInfo` name and version | none | D, hard assert | 5/5 |
| D12/T1 both eras | The fake's reply echoes 2025-11-25; the client then shows `✔ Connected` | none | D, hard assert | 5/5 |
| D12/T1 both eras | `notifications/initialized` has no id and comes after the `initialize` reply | none | D, hard assert | 5/5 |
| D12/T1 both eras | No request other than ping before the `initialize` reply (the reply is held 300 ms) | none | D, hard assert | 5/5 |
| D12/T1 both eras | `clientInfo` values (`claude-code` / `2.1.296`) | none | Record only (`era_seen`) | 5/5 |
| D12/T1 `[unset]` | First message `server/discover`, `_meta` protocol version 2026-07-28, only the probe before `initialize`, -32601 reply | none | D, hard assert | 5/5 |
| D12/T3 `test_discover_generic_error_...` | After a -32603 reply to the probe, the next message is `initialize` | none | D, hard assert | 5/5 |
| D12/T3 | Delay from the error to `initialize` | ms jitter | D with a window: at most 1.0 s (measured 2-3 ms) | 5/5 |
| D12/T3s `test_discover_silent_...` | Silent probe: `initialize` follows after 3.0 s | jitter under load | D with a window: 3.0 +- 1.0 s | 5/5 |
| D12/T3s | The next command in the same config dir skips the probe; the verdict file is in `$CLAUDE_CONFIG_DIR/state/`; a fresh config dir probes again | none | D, hard assert | 5/5 |
| D12/T4 + D13/T3 status matrix | Status strings in `claude mcp list` and `get` (`✔ Connected`, `✘ Failed to connect`, `! Needs authentication`), the 401 detail, no `Issue` line when healthy | none | D, hard assert | 1 |
| status matrix | The wire log shows the real connection attempt (handshake order, header hash, no OAuth discovery with a working header, no Authorization sent when none is configured) | none | D, hard assert | 1 |
| status matrix | `claude mcp get` redacts a configured header (changelog.md:5864) | none | Strict xfail (2.1.296 prints it) | 1 |
| status matrix `test_http_bare_401_out_of_spec_server_status_recorded` | A bare 401 with no OAuth metadata shows `! Needs authentication` (mcp.md:764). The server breaks the spec MUST to publish Protected Resource Metadata (2025-11-25 basic__authorization.md:65) | none | Record only (`documented_bare_401_status`; 2.1.296 shows `✘ Failed to connect`). The probe and the 401 on the MCP path stay hard asserts | 1 |
| status matrix | A stdio server that dies at start is spawned twice per command | unknown | Record only (`spawns_per_command`) | 1 |
| D13/T4 + D23/T11 credentials | Inherited credentials reach a stdio server by default; under `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` the listed names are stripped and the table's exceptions kept; `--env` values reach it | none | D, hard assert (fingerprints) | 1 |
| credentials | A credential-named `--env` value survives the scrub | not documented | Record only (`configured_env_under_scrub`) | 1 |
| credentials `test_stdio_allowlist_env_passes_only_baseline_and_configured_env` | Under `CLAUDE_CODE_MCP_ALLOWLIST_ENV=1` (env-vars.md:334) the server connects; its configured `MY_SERVICE_TOKEN` reaches it; `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `NPM_TOKEN`, `MY_INHERITED_TOKEN` and the plain `MY_PLAIN_SETTING` do not | none | D, hard assert (fingerprints) | 1 |
| credentials (allowlist) | The env names the server got (the baseline), and whether `GITHUB_TOKEN` and `CLAUDE_CONFIG_DIR` are among them | not documented | Record only (`allowlist_env_names`) | 1 |
| credentials (remote) | `${ANTHROPIC_API_KEY}` / `${NPM_TOKEN}` in a header or url are sent empty; an own variable is expanded | none | D, hard assert | 1 |
| D14/T1, T2, D23/T2 smoke | Gate: the test's servers are `connected` in `system/init` | none, else inconclusive | Gate (inconclusive, retried once) | 1 |
| smoke | Pins took effect: first message `initialize` asking 2025-11-25; `ToolSearch` in `system/init` tools only with tool search on (T1, D23/T2: absent; T2: present) | none | D, hard assert | 1 |
| smoke | `mcp__<server>__echo_canary` is in `system/init` tools | none | D, hard assert | 1 |
| smoke | One `tools/call` per `tool_use`, same name, arguments == `tool_use.input` | none | D, hard assert | 1 |
| smoke | One `tool_result` per `tool_use`, not an error, text == the fake's own `sent` text for that JSON-RPC id, before the final `result` (the last line) | none | D, hard assert | 1 |
| smoke | The model called the tool (`tool_use` exists) | model | S trigger: missing means inconclusive, retried once | 1 |
| smoke | The `tool_use` name; `tool_use.input` == the prompt's values; the canary in the final answer; `result.subtype == "success"`; a `ToolSearch` call before the tool (T2) | model | Record only (`s_checks`, `tool_search_uses`) | 1 |
| D23/T2 | The broken entry is in `mcp_server_errors` with type `url_missing_type` and the mcp.md text, and absent from `mcp_servers`; the healthy server's tool still works | none | D, hard assert | 1 |
| D15/T1 `test_right_tool_among_near_duplicates` | Gate: both `calc` and `calc2` are `connected` in `system/init` | none, else inconclusive | Gate (inconclusive, retried once) | 5/5 |
| D15/T1 | Legacy era on both fakes; no `ToolSearch`; both `mcp__calc__add` and `mcp__calc2__add` in `system/init` tools; both fakes served `tools/list` | none | D, hard assert | 5/5 |
| D15/T1 | Routing per server: one `tools/call` per `tool_use` named for that server, arguments == `tool_use.input`, none without one (so `calc` gets no call when the model called only `mcp__calc2__add`) | none | D, hard assert | 5/5 |
| D15/T1 | The fakes' own records: one `tool_executed` per call on the server that got it, under its own name and JSON-RPC id; one `side_effect` per call on `calc2`, none on `calc` | none | D, hard assert | 5/5 |
| D15/T1 | `tool_result` text == the fake's `sent` text for that JSON-RPC id, before the final `result` | none | D, hard assert | 5/5 |
| D15/T1 | The model called `mcp__calc2__add`, exactly once, never `mcp__calc__add`, with `{a, b}` as prompted | model | S, rate >= 4/5 | 5 |
| D15/T1 | The final answer holds the sum | model | Record only (rate printed) | 5 |
| D15/T1 `..._negotiation_unset` | The same D facts with `MCP_PROTOCOL_NEGOTIATION` unset, plus first message `server/discover` and `initialize` 2025-11-25 | none | D, hard assert | 1 (not repeated: doc 11 asks for the second era once, and the era is a client fact, so one run shows it) |
| D15/T1 unset era | The S facts | model | Record only (no rate from one run) | 1 |
| D15/T2+T3 `test_ticket_arguments_and_result_fidelity` | Gate: `tickets` is `connected` in `system/init` | none, else inconclusive | Gate (inconclusive, retried once) | 5/5 |
| D15/T2+T3 | Legacy era; no `ToolSearch`; `mcp__tickets__create_ticket` in `system/init` tools | none | D, hard assert | 5/5 |
| D15/T2+T3 | The fake's echo of the arguments == the arguments it logged, compared as canonical JSON (type-strict: `3` vs `3.0` and `true` vs `1` differ) | none | D, hard assert | 5/5 |
| D15/T2+T3 | One `tools/call` per `tool_use`; arguments == `tool_use.input` field for field: array order, enum spelling, unicode code points (no normalization), integer type, nested object; an absent key is not `null` (`notes` absent on the wire whenever it is absent from `tool_use.input`) | none | D, hard assert (canonical JSON) | 5/5 |
| D15/T2+T3 | `tool_result` text == the fake's `sent` text, and holds the server-generated id `TCK-<8 hex>` (fresh per call, not in the prompt) | none | D, hard assert | 5/5 |
| D15/T2+T3 | The model called `create_ticket` exactly once with input == the prompt's values | model | S, rate >= 4/5 (per-field diffs in `run.json`) | 5 |
| D15/T2+T3 | The final answer holds the server id; title, empty tag, tag order, `notes` left out, each on its own | model | Record only (rates printed) | 5 |
| D16/T1 `test_tool_execution_error_is_error_result`, D16/T2 `test_protocol_error_is_error_result` | Gate: the server (`booking` / `orders`) is `connected` | none, else inconclusive | Gate (inconclusive, retried once) | 5/5 each |
| D16/T1, T2 | Legacy era; no `ToolSearch`; the failing tool and `echo` in `system/init` tools | none | D, hard assert | 5/5 each |
| D16/T1, T2 | The failing tool: one `tools/call` per `tool_use`, arguments == input; the fake answered it as set up (T1 a result with `isError: true`, T2 a JSON-RPC error -32602); exactly one `tool_result`, `is_error: true`, holding the fresh token | none | D, hard assert | 5/5 each |
| D16/T1, T2 | `PostToolUseFailure` fired exactly once per failing `tool_use` (same `tool_use_id`, `tool_name`, `mcp_server.name`), never for `echo` (hooks.md:2251, 2261). Hook given with `--settings '<inline JSON>'` | none | D, hard assert | 5/5 each |
| D16/T1, T2 | The server stays connected: `echo` after the error reached the same fake process (one spawn), its `tool_result` is not an error and == the fake's `sent` text; the `result` event is the last line | none | D, hard assert | 5/5 each |
| D16/T1, T2 | Exact stream shape of the error (`content` a string, no prefix, `tool_use_result` = `"Error: <text>"`), the hook's `error`, `is_interrupt`, `duration_ms`, `PostToolUse` for `echo` | none seen | Record only (`error_result`, `hooks` in `run.json`; observations.md) | 5/5 each |
| D16/T1, T2 | The model called the failing tool once, then `echo` once, after the error result | model | S, rate >= 4/5; both tool_uses are the trigger | 5 each |
| D16/T1, T2 | The final answer quotes the token; `result.subtype` | model | Record only (rates printed) | 5 each |
| D20/T1 `test_stdio_crash_mid_call` | Gate: `crashy` is `connected` | none, else inconclusive | Gate (inconclusive, retried once) | 3/3 |
| D20/T1 | The first fake process got one `tools/call` (`echo_canary`), logged `exit` (code 3) for it and sent no reply | none | D, hard assert | 3/3 |
| D20/T1 | No hang: the error `tool_result`'s stream `timestamp` is at most `CRASH_FAILURE_BOUND_S` = 5 s after the fake's `exit` epoch (measured 23-24 ms; a missed exit would wait for the 30 s `MCP_TOOL_TIMEOUT`) | ms jitter | D with a bound | 3/3 |
| D20/T1 | The crashed `tool_use` has exactly one `tool_result`, `is_error: true`; no process started between the crash and the next `tool_use` (no eager restart); every later call got one `tool_result`; the `result` event is the last line | none | D, hard assert | 3/3 |
| D20/T1 | Restart guard: the first later call of `crashy` gets a `tool_result` with `is_error` not true, served by a fake process other than the crashed one, so a client that stops restarting fails | none | D, hard assert | 3/3 |
| D20/T1 | One spawn in the whole run (mcp.md:377: stdio servers are not reconnected). 2.1.296 starts the server again on the next call, as the 2026-07-28 spec's SHOULD asks (basic__transports__stdio.md:116): a doc gap | none | Record only (`documented_no_restart`, recorded last, after every hard assert) | 3/3 |
| D20/T1 `..._same_every_run` | The 3 runs have the same signature: spawns (up to 2), same parent pid, methods per spawn, the crashed call's text and `is_error`, the first later call's result and process, the hook's `error` (ids masked; further model calls are S and left out) | none | D, hard assert (skipped as inconclusive when fewer than 3 runs finished) | 1 |
| D20/T1 | The model called `echo_canary`, then `echo` after the failure | model | S trigger (both needed), inconclusive otherwise; no rate | 3 |
| D20/T1 | Time values, the respawn delay, the hook inputs, the final answer | jitter / model | Record only (`d_view` in `run.json`) | 3 |
| every model attempt | `tools/call` matched to its `tool_use` by `params._meta["claudecode/toolUseId"]` (observed on 2.1.296, not in the docs); a call without it is matched by equal arguments when exactly one `tool_use` fits. The hard D check (multiset of name + arguments) does not need the id | undocumented | Used for pairing; a call whose id names no `tool_use` fails | every attempt |
| every model attempt | `unparsed_stdout_lines`: stdout lines of `claude -p` that are not JSON (none expected with `--verbose`) | none seen | Record only (count in `observations.model_runs[]`) | every attempt |
| D19/T1 `test_idle_timeout_aborts_hung_call` | Gate: `slowpoke` is `connected` | none, else inconclusive | Gate (inconclusive, retried once) | 3/3 |
| D19/T1 both eras | Legacy era (unset: `server/discover` first); no `ToolSearch`; one `tools/call` per `tool_use`; the fake sent nothing for it (`no_reply`, no reply, no progress) | none | D, hard assert | 3/3 + 1 |
| D19/T1 both eras | The timed-out call has exactly one `tool_result`, `is_error: true`, whose text holds the client's idle-abort text `sent no response or progress` (so the idle check caused the abort; the seconds are not pinned); the run ends with `result`, the last line | none | D, hard assert | 3/3 + 1 |
| D19/T1 both eras | Give-up (the `tool_result` stream `timestamp`) minus the fake's `recv` epoch of the `tools/call` is in [2.75 s, 50 s): after the idle window, before the 60 s `MCP_TOOL_TIMEOUT` (so the idle check aborted it, and the run does not hang). Measured 30.009-30.018 s (8 runs) | ms jitter; fake read lag (lower bound has 0.25 s tolerance) | D with a window | 3/3 + 1 |
| D19/T1 both eras | Give-up in [2.75 s, 5 s) with `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT=3000` (env-vars.md:337, doc 19 test 1). 2.1.296 aborts at 30 s | none seen | Strict xfail (`DocumentedBehaviorMismatch`, raised last) | 3/3 + 1 |
| D19/T3 both eras | No message about the request id reaches the fake after the `tools/call` other than one `notifications/cancelled`; at most one cancel; a cancel that comes lies in the same hard window | none | D, hard assert | 3/3 + 1 |
| D19/T3 both eras | A `notifications/cancelled` with `params.requestId` == the call's id after the client gives up (2025-11-25 basic__lifecycle.md:249-253, a SHOULD; both runs negotiate 2025-11-25). 2.1.296 sends none | none seen | Warning (pytest warnings summary) + record (`cancel_should_misses`), never a failure | 3/3 + 1 |
| D19/T1, T3 | The two spans, the error text, the progressToken the call carried, the final answer | jitter / model | Record only (`d_view`) | 3/3 + 1 |
| D19/T1 | The model called `echo_canary` | model | S trigger, inconclusive otherwise; no rate | 3 + 1 |
| D23/T9 `test_pre_tool_use_hook_guards_mcp_tool[*]` | Gate: `guard` connected; `list_items` reached the server before the `delete_all` `tool_use` (else inconclusive, no retry) | none / model order | Gate | 1 per case |
| D23/T9 all 6 cases | Legacy era; no `ToolSearch`; both tools in `system/init`; `list_items` passes through (`d_passthrough`); every hook line is `PreToolUse` | none | D, hard assert | 1 per case |
| D23/T9 `[deny]` | Matcher `mcp__guard__.*`: no `tools/call` for `delete_all`; its one `tool_result` is an error holding the hook's `permissionDecisionReason` token (hooks.md:1934); the hook logged `deny` for that `tool_use_id` and `pass` for `list_items` | none | D, hard assert | 1 |
| D23/T9 `[ask]` | The hook answers `permissionDecision` "ask" with a reason: no `tools/call` for `delete_all`; one error `tool_result` holding the reason (hooks.md:1934: in a `-p` run where no one can answer, Claude Code denies the call and Claude reads the reason in the tool result); the hook log has one `ask` line | none | D, hard assert | 1 |
| D23/T9 `[allow]` | The hook answers `permissionDecision` "allow" with a reason; `delete_all` has no allow rule (`--allowedTools "mcp__guard__list_items"` only): `delete_all` reaches the server (`d_passthrough`; hooks.md:1933: "allow" skips the permission prompt); the hook log has one `allow` line | none | D, hard assert | 1 |
| D23/T9 `[matcher_without_wildcard]` | Matcher `mcp__guard`: the hook never runs (hooks.md:365), `delete_all` reaches the server (allowed by rule) | none | D, hard assert | 1 |
| D23/T9 `[exit1_default]` | Hook exits 1, no `onFailure`: the hook ran (`exit1`), `delete_all` reaches the server (hooks.md:786) | none | D, hard assert | 1 |
| D23/T9 `[exit1_on_failure_block]` | Same with `"onFailure": "block"`: no `tools/call` for `delete_all`, its `tool_result` is an error (hooks.md:904) | none | D, hard assert | 1 |
| D23/T9 all 6 cases | `permission_denied` system events naming `delete_all` (headless.md:333): `ask` 1, every other case 0, so an Ask treated as Deny fails | none | D, hard assert | 1 per case |
| D23/T9 | `tool_result` texts, `result.permission_denials`, hook lines | none seen | Record only (`d_view`) | 1 per case |
| D23/T10 `test_deny_rule_keeps_call_from_server` | `--disallowedTools mcp__guard__delete_all` + allow `mcp__guard__*`: `list_items` passes through; no `tools/call` for `delete_all`; any `delete_all` `tool_use` gets one error `tool_result`; `mcp__guard__delete_all` is absent from `system/init` tools (cli-reference.md:87: a bare tool name removes the matching tools from Claude's context) | none | D, hard assert | 1 |
| D23/T10 | Where else the deny shows: not in `permission_denials`; a guessed `tool_use` gets `No such tool available` | none seen | Record only | 1 |
| D23/T10 `test_tool_without_allow_rule_is_denied` (control for variant A) | `--allowedTools "mcp__guard__list_items"` only: `list_items` passes through; no `tools/call` reaches `guard__ops`; the `rotate_logs` `tool_use` gets one error `tool_result`; `result.permission_denials` lists exactly it; one `permission_denied` system event names it (headless.md:323, 333). Gate: `list_items` reached `guard` first | none | D, hard assert | 1 |
| D23/T10 `test_server_allow_rule_does_not_reach_double_underscore_server` (variant A) | `--allowedTools "mcp__guard"` only: `list_items` reaches `guard` (D); no `tools/call` reaches `guard__ops` | none | D for `guard`; strict xfail for `guard__ops` (known defect, changelog.md:212, changed in 2.1.299) | 1 |
| D23/T10 `test_server_deny_rule_stops_double_underscore_server` (variant B) | Allow `mcp__guard__ops__*` + deny `mcp__guard__ops`: no `tools/call` reaches `guard__ops`. Conclusive when a `tool_use` exists or the tool is absent from `system/init` | none | Strict xfail (known defect, changelog.md:297, fixed 2.1.299) | 1 |
| D23/T13 `test_mcp_server_policy_in_user_settings[denied]`, `[allowed_only]` | Servers `guard` and `guard__ops` by `--mcp-config --strict-mcp-config`; inline `--settings` with `deniedMcpServers` `guard__ops`, or `allowedMcpServers` `guard`: `guard__ops` is never spawned (its wire log stays empty); `list_items` passes through on `guard` (settings-reference.md:4967-4969; managed-mcp.md:251, :259) | none | D, hard assert | 1 each |
| D23/T13 | How `guard__ops` shows in `system/init` `mcp_servers` | not documented | Record only | 1 each |
| D23/T9, T10, T13 | The model made the trigger `tool_use`s | model | S trigger, inconclusive otherwise; no rate | 1 per item |
| every run | `claude --version` == 2.1.296 (version gate) | none | Hard: the run stops with exit 10 before any test | every run |
| every model attempt | The stream ends with a `result` event (checked before the retry decision) | none | D, hard assert | every attempt |
| every model run | `total_cost_usd` is in the `result` event; a run with no `result`, no `total_cost_usd`, or an exception is charged the per-run cap | none | Hard (test fails when the key is missing from `result`) | every run |
| every run | No artifact holds the API key or a generated test credential (per-test scan and entrypoint scan, `--debug-file` included); the live key is recorded only as `{"set": true}`, never as a hash | none | Hard assert; a leaking file is not kept, and the run exits 1 | every run |

## Residual risks

- API key hand-off (run.sh): a `kill -9` of `run.sh` between `docker cp`
  of the key file and `docker start` leaves the key file
  (`/tmp/suite-api-key`, mode 0600) in the created, never started
  container until it is removed (`docker rm`). `docker inspect` does not
  show it, but `docker cp <container>:/tmp/suite-api-key -` can read it.
  The window is one `docker cp` call. Not fixed; run.sh has the same note.
- The same `kill -9` while the key is on the host (from its write to the
  `rm` after `docker cp`) skips the cleanup trap and leaves the 0600 key
  file in a private `mktemp -d` dir under `$TMPDIR`. Not fixed.
- In the model tests the live key is in the env of every stdio fake, since
  stdio servers inherit it by default (finding 9). The fakes log it only
  as `{"set": true}`, and the scan checks every kept file; a fake's
  process env is not scanned.
