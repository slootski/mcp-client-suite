# Observations

Behavior of Claude Code seen while building the suite that no test asserts
(yet). One entry per item: date, version, what, evidence. Later steps add
to this file.

Evidence pointers of the form `artifacts/<run-id>/…` refer to runs on the
author's machine. `artifacts/` is not in the repo (it is in `.gitignore`):
run the named test with `./run.sh -k <test>` to get your own copy in
`artifacts/latest`. Files under `evidence/` are in the repo.

## 2026-10-17, Claude Code 2.1.296: `claude mcp list` cancels `initialize` at 12 s, below `MCP_TIMEOUT`

- What: a stdio server that never answers `initialize` gets
  `notifications/cancelled` with reason `SdkError: Request timed out` 12.0 s
  after `initialize`, although `MCP_TIMEOUT=15000`. `claude mcp list` then
  prints `✘ Failed to connect — Request timed out` (wall time 12.67 s).
  R01 says `MCP_TIMEOUT` is the server startup timeout, so either the health
  check uses its own shorter timer, or the variable is not applied there.
  The docs do not say which.
- Setup: one-off run, not a suite test. It used a scratch copy of
  `fakes/stdio_fake.py` with a `hang_initialize` mode that drops
  `initialize`, `MCP_PROTOCOL_NEGOTIATION` unset, fresh `CLAUDE_CONFIG_DIR`.
  It first answered `server/discover` with -32601, then `initialize` hung.
- Evidence: `evidence/2026-10-17-initialize-cancelled-12s.jsonl` (wire log:
  `recv initialize` at +0.018 s, `recv notifications/cancelled` at +12.023 s).
- Follow-up: doc 12 test 5 (startup slower than `MCP_TIMEOUT`) should
  measure this with `MCP_TIMEOUT` both above and below 12 s.

## 2026-10-17, Claude Code 2.1.296: a stdio server that dies at start is spawned twice per command

- What: with a stdio server that exits before reading stdin, `claude mcp list`
  starts it twice, about 15 ms apart, and `claude mcp get <name>` does the
  same. The status is `✘ Failed to connect — CONNECTION_CLOSED: Connection closed`.
  R01 says stdio servers are not reconnected automatically, and the docs do
  not mention a retry when a stdio server first starts.
- Evidence: every run of
  `tests/test_status_matrix.py::test_stdio_exit_at_start_is_failed_to_connect`.
  See `artifacts/<run-id>/tests/<test>/run.json`, key
  `observations.spawns_per_command` = `{"claude mcp list": 2, "claude mcp get": 2}`,
  and `wire-fake_stdio_dead.jsonl` (two `started`/`exit` pairs per command).

## 2026-10-17, Claude Code 2.1.296: handshake values measured by `tests/test_handshake.py`

- Probe: with `MCP_PROTOCOL_NEGOTIATION` unset, `server/discover` carries
  `params._meta["io.modelcontextprotocol/protocolVersion"] = "2026-07-28"`
  (the client's preferred revision; matches env-vars.md:495). `initialize`
  then asks `protocolVersion: "2025-11-25"`, `clientInfo` is
  `claude-code` / `2.1.296`. With `legacy`, the first message is `initialize`
  and no `server/discover` is sent.
- Fallback after a generic discover error (-32603): `initialize` arrives
  2.5-2.9 ms after the fake wrote the error (runs 20261016T222744Z-97694,
  20261016T222816Z-98037, 20261016T222835Z-98065). The test bound is 1.0 s.
- Fallback after a silent discover (never answered): `initialize` arrives
  3.009-3.018 s after the probe (same 3 runs), with no
  `notifications/cancelled` for the probe. Neither the spec ("a reasonable
  timeout", 2026-07-28 basic__transports__stdio.md:142) nor the Claude Code
  docs name this value. With `MCP_TIMEOUT=15000` it is 3 s, so it is not
  the startup timeout itself; whether it scales with `MCP_TIMEOUT` was not
  tested. The test bound was 3.0 +- 0.5 s; it is now 3.0 +- 1.0 s
  (2.0-4.0 s) after a QA run on amd64 with `--cpus 0.25` measured 2.49 s
  (both timestamps come from the fake, which the load slows too). The
  window still tells apart an immediate fallback (~3 ms), the 12 s cancel
  in `claude mcp list` and the 15 s `MCP_TIMEOUT`.
- Evidence: `artifacts/<run-id>/tests/tests_test_handshake.py_*/run.json`,
  keys `observations.era_seen`, `observations.fallback_delay_after_error_s`,
  `observations.silent_fallback_delay_s`, and the `wire-*.jsonl` next to them.

## 2026-10-17, Claude Code 2.1.296: where the 7-day era memory lives

- What: changelog.md:743 (2.1.292) says a stdio server that ignores the
  newer protocol check is "remembered for 7 days" after one slow connect;
  the docs do not say where. Observed: after a silent probe, 2.1.296 writes
  `$CLAUDE_CONFIG_DIR/state/mcp-discover-verdicts.json`, one entry per
  server, key `stdio:<32 hex>`, value `{observedAt, modernProtocolVersion:
  "2026-07-28"}`. The next command in the same config dir sends `initialize`
  first (no probe). A fresh `CLAUDE_CONFIG_DIR` with the same `HOME` and the
  same server config probes again. A fast -32601 or -32603 reply writes no
  entry. A one-off `find / -xdev -newer <marker>` in the container found no
  other new file outside the run's `CLAUDE_CONFIG_DIR` and `HOME`.
- Consequence: a fresh `CLAUDE_CONFIG_DIR` per test (conftest.py) is enough
  isolation; the silent case needs no container or marker of its own.
- Evidence: `test_discover_silent_falls_back_and_is_remembered_per_config_dir`,
  `run.json` keys `observations.era_verdicts_file` and
  `observations.fresh_config_dir_first_messages`; the copied
  `claude-config/state/mcp-discover-verdicts.json`.

## 2026-10-17, Claude Code 2.1.296: `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` needs bubblewrap on Linux

- What: in the suite image without `bubblewrap`, `claude mcp add` and
  `claude mcp list` exit 1 (`claude --version` still works) with `error: bubblewrap is required
  for subprocess env scrubbing and isolation. Install with: sudo apt-get
  install -y bubblewrap, set sandbox.bwrapPath in managed settings, or set
  CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=0 to disable (loses subprocess
  isolation).` env-vars.md:406 and 545-563 do not state this requirement
  (they mention only PID-namespace isolation for Bash on Linux). The
  Dockerfile now installs `bubblewrap=0.8.0-2+deb12u1`.
- With bubblewrap, the scrub matches the table at env-vars.md:553-558:
  `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `NPM_TOKEN`,
  `MY_INHERITED_TOKEN` and `CLAUDE_CONFIG_DIR` are removed from the stdio
  server's env, `GITHUB_TOKEN` stays.
- Not in the docs: a credential-named variable given to the server with
  `claude mcp add --env MY_SERVICE_TOKEN=...` still reaches it under the
  scrub. env-vars.md:406 (the scrub entry) does not exempt configured server
  env, and the table at 553-558 does not mention it; mcp.md:138 only says
  the server runs with `KEY=value` in its environment. So this is not a
  documented fact either way: the test records it (`run.json` key
  `observations.configured_env_under_scrub`) and asserts nothing about it.
- What was tested about bwrap: for stdio MCP spawns with `sandbox` off,
  2.1.296 checks that bwrap exists but does not run it. The probe
  `evidence/2026-10-17-bwrap-probe.sh` (output in
  `evidence/2026-10-17-bwrap-probe.txt`) puts a logging shim in place of
  `/usr/bin/bwrap`, checks the shim logs a call (`bwrap --version`), then
  runs `claude mcp add` and `claude mcp list` for a stdio fake in three
  cases: control (no setting), scrub (`CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`)
  and allowlist (`CLAUDE_CODE_MCP_ALLOWLIST_ENV=1`). The shim was called 0
  times in each, and in the scrub case `NPM_TOKEN` and
  `MY_INHERITED_TOKEN` were still gone from the server's env. Then it removes bwrap:
  the scrub case exits 1 with the error above; the allowlist case still
  connects. So the scrub is done by Claude Code itself in this setup, and
  the scrub test needs no extra container privileges.
- Not tested: Bash tool subprocesses, which env-vars.md:567 names for the
  PID-namespace isolation (no Bash tool runs in the probe), and anything
  with the `sandbox` setting on.
- Evidence: the probe above, and every run of
  `tests/test_credentials.py::test_stdio_env_scrub_strips_inherited_credentials`
  (`run.json` key `observations.credential_env_seen`).

## 2026-10-17, Claude Code 2.1.296: `CLAUDE_CODE_MCP_ALLOWLIST_ENV=1` does what env-vars.md:334 says

- Doc: env-vars.md:334: "spawn stdio MCP servers with only a safe baseline
  environment plus the server's configured `env`, instead of inheriting
  your shell environment". This is the MCP-specific control; the scrub
  (env-vars.md:406) covers all subprocesses.
- What the server got (one spawn each for `claude mcp list` and `claude
  mcp get`, same names in both): `CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`,
  `CLAUDE_PROJECT_DIR`, `HOME`, `LC_CTYPE`, `PATH` (the baseline), plus
  its configured `--env` values: the fake's own `FAKE_*` settings and
  `MY_SERVICE_TOKEN` (fingerprint equal to the value given).
- What was dropped: every inherited variable the test set:
  `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `NPM_TOKEN`,
  `MY_INHERITED_TOKEN`, the plain `MY_PLAIN_SETTING` (which the scrub
  keeps, so this tells the two apart), and also `GITHUB_TOKEN` and
  `CLAUDE_CONFIG_DIR`. The server shows `✔ Connected`.
- Needs no bubblewrap: in `evidence/2026-10-17-bwrap-probe.txt` (case
  `allowlist-no-bwrap`) the server connects with bwrap removed, with the
  same env names.
- Test: `tests/test_credentials.py::test_stdio_allowlist_env_passes_only_baseline_and_configured_env`
  (free). Asserted: connected, `MY_SERVICE_TOKEN` reaches the server, the
  five inherited names above are absent. Recorded, not asserted (the doc
  does not list the baseline): every env name (`run.json` key
  `observations.allowlist_env_names`), and whether `GITHUB_TOKEN` and
  `CLAUDE_CONFIG_DIR` are among them.
- Evidence: `artifacts/20261017T120316Z-26391/tests/tests_test_credentials.py_test_stdio_allowlist_env_passes_only_baseline_and_configured_env/run.json`
  (passed).

## 2026-10-17, Claude Code 2.1.296: credential variables in a remote url/header

- What: matches mcp.md:679-689. `Authorization: Bearer ${ANTHROPIC_API_KEY}`
  and `Bearer ${NPM_TOKEN}` reach the HTTP fake as `Bearer` with an empty
  credential (the fake strips header whitespace, so the trailing space of
  the doc's `Bearer ` is not visible), and the 401 shows as
  `✘ Failed to connect`. `?key=${ANTHROPIC_API_KEY}` in the url is sent as
  `key=` (length 0). `${MY_SERVICE_TOKEN}` expands in both places.
  `claude mcp list` / `get` print the `${VAR}` reference, not the value.
- Evidence: `tests/test_credentials.py::test_remote_*`, `run.json` keys
  `observations.authorization_sent` and `observations.query_sent`.

## 2026-10-17, Claude Code 2.1.296: `claude -p` flags as shipped

- `--max-turns` is not listed by `claude --help`, but is accepted: with it
  the run reaches the login check (`Not logged in`), while an unknown flag
  (`--bogus-flag`) is rejected at parse (`error: unknown option`).
  cli-reference.md documents it. All other flags of the model harness
  (`--output-format stream-json --verbose --model --max-budget-usd
  --permission-mode --permission-prompts --mcp-config --strict-mcp-config
  --debug --debug-file --allowedTools`) are listed by `--help`.
- `--permission-mode`: `--help` lists `manual` and not `default`
  (cli-reference.md: `manual` is an alias of `default`, both work). The
  suite passes `default`; every model run accepted it.
- `--mcp-config <configs...>` and `--allowedTools <tools...>` are variadic:
  a prompt placed after them is read as one more value and the run fails
  with `Input must be provided either through stdin or as a prompt
  argument`. harness/model_run.py puts the prompt right after `-p`.

## 2026-10-17, Claude Code 2.1.296: what a `claude -p` model run shows

- `tools/call` carries `params._meta = {"claudecode/toolUseId": <the
  stream's tool_use.id>, "progressToken": <n>}`. The docs do not name
  `claudecode/toolUseId`. `harness/model_checks.py` pairs a call with its
  tool_use by it when present; the hard D check is the (name, arguments)
  multiset, which does not need it.
- `system/init` `mcp_servers` entries carry `{"name", "status", "source":
  "dynamic"}`; `source` is not in headless.md's table. `mcp_server_errors`
  is omitted when empty (matches headless.md).
- Broken entry `{"url": ...}` with no `type`: `mcp_server_errors` =
  `[{"name": "broken_url", "type": "url_missing_type", "message": "Skipped —
  MCP server \"broken_url\" has a \"url\" but no \"type\"; add \"type\":
  \"http\" (or \"sse\" / \"ws\") to this entry"}]`. Type matches
  headless.md; the message is mcp.md:85's text with a `Skipped — ` prefix.
  The entry is absent from `mcp_servers`, the run ends `success`.
- A successful `tool_result` block has no `is_error` key at all.
- `--debug=mcp` writes connect, `protocolEra: "legacy"`,
  `negotiatedProtocolVersion: "2025-11-25"`, each `Calling MCP tool` line
  and shutdown (`Sending SIGINT to MCP server process`). The suite scan
  found no trace of the API key in it.
- Partial key check (one-off, the three keyed runs of step 3): no file in
  the artifacts, the copied `claude-config/.claude.json` and its
  `backups/` included, holds the key's first 12/20 or last 8/12/20/40
  characters. The suite scans look for the full value only; 2.1.296 wrote
  no `customApiKeyResponses` entry in these `-p` runs.
- Tool search at its default (on): `system/init` `tools` holds `ToolSearch`
  and still names the deferred MCP tools. Haiku called `ToolSearch` with
  `{"query": "select:mcp__smoke__echo_canary", "max_results": 1}`, got a
  `tool_reference` block, then called the tool (3 turns instead of 2).
- Evidence: `artifacts/20261016T230009Z-30443/` (full model tier), keys
  `observations.model_runs`, `observations.round_trip`,
  `observations.tool_search_uses` in each `run.json`.

## 2026-10-17, model run cost (`claude-haiku-5-5`, 2.1.296)

- Per run, from `result.total_cost_usd`: $0.0037 for the first run in a
  container (cache write of the ~27k-token system prompt), $0.0006-0.0013
  for later runs that hit the prompt cache. Each test is one run (no
  inconclusive retries happened), 2 turns, 3 with tool search.
  - D14/T1 `test_round_trip_echo_canary`: $0.0037 alone, $0.0006 in the tier.
  - D14/T2 `test_round_trip_with_tool_search_default`: $0.0013, $0.0007.
  - D23/T2 `test_broken_config_entry_...`: $0.0037, $0.0006.
  - Full model tier (3 tests): $0.0019 (`artifacts/20261016T230009Z-30443/cost.json`).
- Step 3 spend, all runs: $0.0106 (T1 alone $0.0037, T2+T3 $0.0050,
  full tier $0.0019).
- Proposed `SUITE_BUDGET_USD` = $5.00 (set in harness/constants.py):
  doc 24 lists about 16 model tests (D14/T1-T2, D15/T1-T3, D16/T1-T2,
  D19/T1+T3, D20/T1, D23/T2, D23/T9-T10 with variants), x 2 eras (doc 11:
  legacy and unset), x 5 repeats (doc 22), x 2 for one inconclusive retry
  = 320 runs. At $0.01 per run (2.7x the worst measured run, room for
  longer tool output and more turns) that is $3.20; +50% margin gives
  $5.00. The per-run cap stays `--max-budget-usd 0.25`, so the ledger's
  pre-check stops before a run that could take the total past $5.00.

## 2026-10-17, Claude Code 2.1.296: the prompt-cache hit depends on the system prompt, not the container

- What: the first `claude -p` run with a given set of MCP servers writes
  ~27k tokens to the prompt cache ($0.0037 with `claude-haiku-5-5`); a
  later run with the same server names reads them ($0.0010-0.0014), also
  from a NEW container, as long as it comes within the cache lifetime.
  A run with other server names writes again, even in the same container.
  So the cost of a run depends on which server names (and tools) were run
  shortly before, not on a warm container. The system prompt names the MCP
  servers and their tools, which explains it.
- Evidence (usage of the `result` event, `stream-attempt0.jsonl`):
  `artifacts/20261016T233014Z-56742/` (fresh container): D15/T1 `calc`+`calc2`
  write 27262 / read 27129, $0.0037; D15/T2 `tickets` write 27714, $0.0038.
  `artifacts/20261016T233158Z-57265/` (another fresh container, 2 min later):
  D15/T1 repeat 0 write 3537 / read 50854, $0.0010; D15/T2 repeat 0 write
  3887 / read 51193, $0.0011; but D14/T1 (`smoke`) and D23/T2 (`healthy` +
  `broken_url`), not run in the last 30 min, write 27237 and 27242, $0.0037
  each.
- Consequence: the cost of a run is not fixed. Budget on the cold value
  ($0.0037-0.0038) for the first run of each server set.

## 2026-10-17, Claude Code 2.1.296: `ANTHROPIC_API_KEY` reaches stdio MCP servers by default

- What: in a `claude -p` model run (no `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`),
  every stdio fake's `started` record lists `ANTHROPIC_API_KEY` in its env,
  and its sha8 equals the sha8 of the real key (length 106). So any stdio
  MCP server a user configures gets the user's API key unless the scrub is
  on. This matches env-vars.md:406 (the scrub is opt-in) and the free test
  `test_stdio_inherits_credentials_by_default` (a dummy key), now seen with
  the real key under `-p`. The fakes also get `CLAUDE_CODE_MESSAGING_TOKEN`
  (length 32), which no doc names.
- Evidence: `artifacts/20261016T233158Z-57265/tests/*right_tool*_0/wire-calc*.jsonl`,
  record `started`, key `credential_env` (fingerprints only; the value is
  never logged).
- Since commit 4188004 the suite no longer writes a fingerprint of the
  live key: model runs record it as `{"set": true}` only, so a new run
  shows the key's presence, not its sha8. The run cited above predates
  that.

## 2026-10-17, suite: the API key no longer goes into the container config

- QA (step 3) found `docker inspect` of the suite container showed
  `ANTHROPIC_API_KEY=<value>` (run.sh used `docker create -e
  ANTHROPIC_API_KEY`), and a `kill -9` of run.sh skips its cleanup trap and
  leaves that container. Now run.sh writes the key to a 0600 file in a
  private temp dir, `docker cp -a`s it to `/tmp/suite-api-key` in the
  created container before `docker start`, and deletes the host file at
  once. The entrypoint reads the file, deletes it, and passes the key to
  the pytest process env only. This deviates from the mail's literal
  `docker run -e ANTHROPIC_API_KEY`; the reviewer still only sets the env
  var on the host.
- Proof (dummy key `sk-ant-dummy-<24 hex>`, never the real one): `docker
  inspect` of the created (not started) container: 0 hits for the dummy in
  the full JSON; `Config.Env` holds `SUITE_API_KEY_FILE=/tmp/suite-api-key`
  only. In the file: `-rw------- 501 20` (the host uid the container runs
  as). During a `./run.sh -m free` run: `/tmp/suite-api-key` is gone, PID 1
  (the entrypoint) has no `ANTHROPIC_API_KEY`, only `timeout` and pytest
  have it. A container started with `SUITE_API_KEY_FILE` but no file, or
  with `-e ANTHROPIC_API_KEY`, exits 2 with a message (a silent "no key"
  would skip the model tier and pass).
- Left: a `kill -9` between `docker cp` and `docker start` leaves the file
  in the created container (a window of one `docker cp`). The key is in the
  environ of the running pytest process, readable by the same uid inside
  the container, as with any env var.

## 2026-10-17, Claude Code 2.1.296: D15 model runs (right tool, argument fidelity)

- `-p` with `MCP_PROTOCOL_NEGOTIATION` unset probes too: both fakes got
  `server/discover` (id `server-discover-probe-1`, `_meta` with client
  capabilities) first, then `initialize` 2025-11-25 after the -32601 reply.
  Same as `claude mcp list` (test_handshake.py).
- `tools/call` arguments matched `tool_use.input` exactly in all 13 D15
  runs (7 calc, 6 ticket): non-ASCII title (`Café – 東京 ✓`), an
  empty-string tag, tag order, enum spelling, nested `meta` with an
  integer, and the left-out `notes` absent (not `null`). The fake compares
  the decoded JSON (code points, no normalization); how the client escapes
  non-ASCII on the stdio line is not checked.
- Haiku called exactly the named tool `mcp__calc2__add` once in 7 of 7
  runs, never the near-duplicate `mcp__calc__add`, and copied every ticket
  value exactly in 6 of 6; every final answer held the sum or the
  server-generated id (S rates of the 5-repeat run in
  `artifacts/20261016T233158Z-57265/s-rates.json`: 5/5 and 5/5).
- Cost per run: $0.0010-0.0014 warm, $0.0037-0.0038 cold. Full suite with
  the key (`artifacts/20261016T233619Z-58597/`, 49 passed, 2 xfailed): 14
  model runs, $0.0133, all warm. Step 4 spend, all runs: $0.043462.

## 2026-10-17, Claude Code 2.1.296: D16 tool execution error (T1) vs protocol error (T2) in the stream

- Setup: `tests/test_tool_errors.py`, legacy era, tool search off, a fresh
  token `errtok-<16 hex>` per repeat. T1: `validate_booking` answers a
  normal result `{"content":[{"type":"text","text":"Invalid date: must be
  in the future. Error token: <tok>"}],"isError":true}`. T2:
  `lookup_order` is listed in `tools/list`, and its `tools/call` gets
  `{"error":{"code":-32602,"message":"Unknown tool: lookup_order (error
  token: <tok>)"}}`.
- Side by side (same in 5/5 repeats of each, plus one probe each):

  | | T1, `isError: true` | T2, JSON-RPC error -32602 |
  |---|---|---|
  | `tool_result.is_error` | `true` | `true` |
  | `tool_result.content` | a plain string, `"Invalid date: must be in the future. Error token: <tok>"` | a plain string, `"Unknown tool: lookup_order (error token: <tok>)"` |
  | prefix / suffix added | none (equal to the fake's text) | none (equal to `error.message`); the code -32602 is not shown |
  | user event `tool_use_result` | `"Error: Invalid date: must be in the future. Error token: <tok>"` | `"Error: Unknown tool: lookup_order (error token: <tok>)"` |
  | `PostToolUseFailure` | fires once, `error` == the content, `is_interrupt: false`, `mcp_server` `{"name":"booking","source":"dynamic"}` | the same (`orders`) |
  | `--debug=mcp` log | `[ERROR] MCP server "booking" <text>` plus `[DEBUG] ... Tool 'validate_booking' failed after 0s: <text>` | only `[DEBUG] ... Tool 'lookup_order' failed after 0s: <text>` (no `[ERROR]` line) |
  | the server afterwards | connected; `echo` works on the same process | the same |

- So the stream does not tell the two error channels apart: the model and a
  `-p` consumer see the same `is_error: true` string, and the JSON-RPC code
  is dropped everywhere (stream, hook input, debug log). The only
  difference is the debug log's `[ERROR]` line for T1. A successful
  `tool_result` differs in form: `content` is a list of blocks and has no
  `is_error` key. Spec 2025-11-25 server__tools.md:472-475: clients SHOULD
  give tool execution errors to the model, MAY give protocol errors;
  2.1.296 gives both, with no marker of which one it was.
- hooks.md:2251 ("an MCP tool returned an error result") matches T1; T2
  (a JSON-RPC error) fires the hook too. hooks.md:2256 (no hook for an
  unknown tool name) is about a tool name the client itself does not know;
  T2's tool is listed, so it does not apply.
- The `--debug=mcp` log replaces the token after `token: ` with
  `[REDACTED]` (`Error token: [REDACTED]`); the suite's own redaction
  holds only the API key, so Claude Code does this itself. The stream and
  the hook input keep the token.
- Evidence: `artifacts/20261017T062932Z-22649/tests/tests_test_tool_errors.py_*`
  (`run.json` keys `observations.error_result`, `observations.hooks`,
  `observations.d_view`; `stream-attempt0.jsonl`, `hooks.jsonl`,
  `debug-attempt0.log`); probe run `artifacts/20261017T062420Z-15418/`.

## 2026-10-17, Claude Code 2.1.296: D20/T1 a stdio server that crashes mid-call is started again on the next call

- Setup: `tests/test_crash.py`, fake mode `exit_on_first_tools_call`: on
  the first `tools/call` of the client it logs the call and an `exit`
  record, then exits 3 with no reply; a process the same client starts
  again serves normally. The prompt asks for `echo_canary`, then, after
  its result, for `echo` on the same server.
- In flight: the `echo_canary` `tool_result` is `is_error: true`, content
  the string `"Connection closed"` (`tool_use_result` `"Error: Connection
  closed"`), 23-24 ms after the fake's exit (stream `timestamp` minus the
  fake's `exit` epoch; 37-40 ms from `tool_use` to `tool_result`).
  `PostToolUseFailure` fires with `error: "Connection closed"`,
  `is_interrupt: false`. The run ends with `result` `success`. The debug
  log says `STDIO connection closed after 1s (cleanly)` and `Cleared
  connection cache for reconnection`, although the exit code was 3.
- Restart: yes, on demand. 2 spawns per run in 3 of 3 runs (pids 37/48,
  77/89, 118/131), both with the same parent pid (the same `claude`
  process). No process starts between the crash and the next `tool_use`
  (no eager restart). The second process starts 12-27 ms after the next
  `tool_use`, gets `initialize`, `notifications/initialized` and the
  `tools/call` for `echo`, but no `tools/list` (the client keeps the old
  tool list), and the call succeeds (`content` the echoed text, no
  `is_error`). In the probe run, where the fake crashed on every process,
  the second call failed with the same `Connection closed`.
- Docs: Claude Code mcp.md:377: "Stdio servers are local processes, and
  Claude Code doesn't reconnect them automatically." (R01 the same). The
  2026-07-28 spec, basic__transports__stdio.md:116: "If the server
  process exits unexpectedly, the client **SHOULD** restart it." The run
  uses the legacy 2025-11-25 era, whose transports page has no such line.
  So 2.1.296 does what the new spec asks (lazily, on the next call) and
  not what its own doc says. Test: strict xfail on "one spawn"
  (`DocumentedBehaviorMismatch`), after every hard assert.
- Now recorded, not xfailed (commit 4188004): mcp.md:377 sits under
  "Automatic reconnection", so it is about eager reconnects, which 2.1.296
  does not do; the lazy restart is what the 2026-07-28 spec asks. A doc
  gap, not a defect: a strict xfail would only pass if the client got
  worse. `run.json` key `observations.documented_no_restart`. The later
  call's success on a new process is a hard assert, so a client that
  stops restarting fails; the doc line's spawn count is recorded.
- Doc 20 test 2 (a crash while idle) was not seen: the fake only exits
  with a call in flight.
- Evidence: `artifacts/20261017T062932Z-22649/tests/tests_test_crash.py_*`
  (`run.json` key `observations.d_view`: `spawns`, `crashed_call`,
  `started_between_exit_and_next_tool_use`, `respawn_after_next_tool_use_s`,
  `later_calls`, `hooks`; `wire-crashy.jsonl`, `debug-attempt0.log`).

## 2026-10-17, step 5 model spend

- Probe (T1, T2, crash once each, the crash fake then exited on every
  process): $0.012189 (`artifacts/20261017T062420Z-15418/cost.json`).
- D16/T1 x5, D16/T2 x5, D20/T1 x3: $0.020189, 13 runs, no retry
  (`artifacts/20261017T062932Z-22649/cost.json`). $0.0013-0.0017 per run.
- Regression check of the changed harness (D14/T1, D15/T1 repeat 0,
  D15/T2+T3 repeat 0, all cold): $0.011277
  (`artifacts/20261017T063224Z-24250/cost.json`).
- Step 5 total: $0.043655 (sum of `total_cost_usd` over 19 runs).

## 2026-10-17, suite: a client that dies after an error or a crash now fails the test (QA step 5)

- QA found that a stream with `system/init` and a first `tool_result`, then
  no next `tool_use` and no `result` event, was reported as inconclusive,
  retried, then skipped (D16/T1, T2 and the 3 crash runs all SKIP, suite
  exit 0). Now `harness/model_flow.py` asserts the `result` event on every
  attempt before the retry decision, and runs each test's `attempt_checks`
  there too (D16: the error `tool_result` of the failing tool; D20/T1: the
  crashed call's one `tool_result`, `is_error`, 5 s bound, whenever the
  crash `tool_use` exists).
- Proof, offline, no model call: `tests/test_harness_offline.py` replays the
  recorded D16/T1, D16/T2 and D20/T1 run 0 of
  `artifacts/20261017T062932Z-22649` (copied to `tests/data/recorded-d16-*`
  and `recorded-d20-t1`, env fingerprints dropped) cut after the first
  `tool_result`: each case FAILS with a plain `AssertionError` ("the stream
  has no result event"), no retry starts. A crash run with its error
  `tool_result` removed (but a `result` kept) fails on the attempt check.
  With both checks removed (scratch copy) the same 4 cases skip or return
  as inconclusive. The unmutated recordings pass every D check; the crash
  one ends at its documented strict xfail (since commit 4188004 it records
  the restart instead: `test_crash_recorded_run_passes_and_records_the_restart`).

## 2026-10-17, Claude Code 2.1.296: D19 the MCP tool idle timeout fires on a 30 s tick, and no cancel is sent

- Setup: `tests/test_idle_timeout.py`, stdio fake mode `hang_on_tools_call`
  (logs the `tools/call`, never answers, never sends progress, keeps
  reading stdin), `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT=3000`,
  `MCP_TOOL_TIMEOUT=60000`, no per-server `timeout`. The name and meaning
  match env-vars.md:337 (checked before building).
- Observed: the client gives up 30.009-30.018 s after the fake logged the
  `tools/call` (8 of 8 runs: 3 + 3 legacy, 1 + 1 unset, two suite runs),
  not after 3 s. The `tool_result` is `is_error: true`: `MCP server
  "slowpoke" tool "echo_canary" sent no response or progress for 30s;
  aborting. If this server is configured in your MCP settings, set a
  per-server "timeout" (ms) ...; otherwise set
  CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT (ms) globally (0 disables).` The
  debug log: `Tool 'echo_canary' aborting: no response or progress
  notification for 30s (idle timeout 3s)`. So the value is read (3 s), but
  the check runs only every 30 s.
- Probe (one-off, scratch copy, not a suite test): idle 31000, wall clock
  120000: abort at 60.023 s, debug `... for 60s (idle timeout 31s)`. A
  30 s floor would give 31 s; a 30 s check tick gives 60 s. So the abort
  comes at the first 30 s tick after the idle window has passed. Evidence:
  `evidence/2026-10-17-idle-timeout-31s-probe.jsonl` (wire log plus the
  two debug lines).
- Docs: env-vars.md:337 "When a stdio ... MCP server sends no response
  and no progress notification for this long, the tool call aborts with
  an error". The documented window [2.75 s, 5 s) is a strict xfail
  (`DocumentedBehaviorMismatch`, raised last); the hard D window is
  [2.75 s, 50 s): after the idle window, well before the 60 s wall clock.
- T3: no `notifications/cancelled` reached the fake in any run, in either
  era; after the `tools/call` the next record is the `signal` at shutdown.
  Both eras negotiate 2025-11-25 (the unset run probes `server/discover`,
  gets -32601, then `initialize`), where the cancel is a SHOULD
  (basic__lifecycle.md:249-253): a warning in the pytest summary and
  `cancel_should_misses` in `run.json`, not a failure. No difference
  between the eras. No other message for the request id followed either.
- The `tools/call` carries `params._meta.progressToken` (2 in every run).
  T2 (progress resets the idle timer, not the wall clock) was not built:
  with a 30 s tick, the planned 3 s idle / 8 s wall clock cannot tell a
  progress reset from "idle not checked yet"; a meaningful T2 needs idle
  windows of 30 s or more (runs of 1-2 min each).
- Evidence: `artifacts/20261017T070833Z-57323` and
  `artifacts/20261017T071415Z-64962`, `tests/*idle_timeout*/run.json`
  (`observations.d_view.calls[]`: `give_up_after_s`, `cancels`,
  `progress_token`, `tool_results`), `wire-slowpoke.jsonl`,
  `debug-attempt0.log`.

## 2026-10-17, Claude Code 2.1.296: D23/T9 PreToolUse hooks on an MCP tool match the docs

- `tests/test_permissions.py::test_pre_tool_use_hook_guards_mcp_tool`, one
  run per case, two suite runs, same result both times. Hook given with
  `--settings '<inline JSON>'`, `--allowedTools "mcp__guard__*"`.
- `deny` (matcher `mcp__guard__.*`): `delete_all` never reached the fake;
  its `tool_result` is `is_error: true`, text `PreToolUse:mcp__guard__delete_all
  hook error: <permissionDecisionReason>` (the reason reaches Claude, as
  hooks.md:1934 says, but labeled "hook error"); `result.permission_denials`
  lists the call (`tool_name`, `tool_use_id`, `tool_input`); the hook logged
  `pass` for `list_items` and `deny` for `delete_all`.
- `matcher_without_wildcard` (matcher `mcp__guard`): the hook never ran,
  `delete_all` reached the fake and returned `deleted 3 items`. Matches
  hooks.md:365 ("matches no tool"): a policy hook written this way guards
  nothing, silently.
- `exit1_default`: the hook ran and exited 1; `delete_all` reached the fake
  (hooks.md:786, non-blocking error). No marker in the stream: the
  `tool_result` is the fake's text and `permission_denials` is empty.
- `exit1_on_failure_block` (`"onFailure": "block"`): `delete_all` never
  reached the fake; `tool_result` `PreToolUse:mcp__guard__delete_all hook
  error: [<command>]: failed; blocking because onFailure is "block"` plus
  the hook's stderr line; listed in `permission_denials`.
- No `permission_denied` system event appeared in any stream; the only
  system events besides `init` were `thinking_tokens`. headless.md:333
  ("denials appear as `permission_denied` system messages") is about
  requests that would prompt and are denied under `--permission-prompts
  none`. A hook deny and an `onFailure: "block"` are not such requests, so
  that line does not cover them (they show only in `permission_denials`).
  Step 7 added the prompt-denial case (next entry), where the event does
  appear and is asserted.

## 2026-10-17, Claude Code 2.1.296: D23/T10 deny rules, and the `__` scoping defects

- Base (`--allowedTools "mcp__guard__*"`, `--disallowedTools
  "mcp__guard__delete_all"`): `delete_all` is absent from `system/init`
  `tools` (cli-reference.md:87, a bare tool name is removed from context)
  and never reached the fake. In one of two runs the model still guessed
  the name: its `tool_result` was `<tool_use_error>Error: No such tool
  available: mcp__guard__delete_all</tool_use_error>`, and the call was
  NOT in `permission_denials` (it is "no such tool", not a denial).
- Variant A (`--allowedTools "mcp__guard"` only, servers `guard` and
  `guard__ops`): `mcp__guard__ops__rotate_logs` reached `guard__ops` and
  succeeded, 2 of 2 runs. Known defect, changelog.md:212 (fixed in
  2.1.299): strict xfail.
- Variant B (`--allowedTools "mcp__guard__ops__*"`, `--disallowedTools
  "mcp__guard__ops"`): `rotate_logs` stayed in `system/init` tools,
  reached `guard__ops` and succeeded, 2 of 2 runs: the server-level deny
  did nothing. Known defect, changelog.md:297 (fixed in 2.1.299): strict
  xfail. Neither defect is already fixed in 2.1.296.
- Evidence: `artifacts/20261017T070833Z-57323`,
  `artifacts/20261017T071415Z-64962`, `tests/*permissions*/run.json`
  (`observations.d_view`), `guard-hook.jsonl`, `wire-guard*.jsonl`.

## 2026-10-17, Claude Code 2.1.296: a tool with no allow rule is denied, with a `permission_denied` event

- Setup: `tests/test_permissions.py::test_tool_without_allow_rule_is_denied`
  (QA step 6: variant A assumed this and nothing checked it). Servers
  `guard` and `guard__ops`, `--allowedTools "mcp__guard__list_items"` only,
  `--permission-mode default --permission-prompts none`. Prompt:
  `list_items`, then `mcp__guard__ops__rotate_logs`.
- Observed (2 runs, `artifacts/20261017T074052Z-93766`,
  `artifacts/20261017T074628Z-94794`): `rotate_logs` is offered in
  `system/init` tools; its `tool_use` never reaches `guard__ops`; its
  `tool_result` is `is_error: true` with the text "Permission for this
  tool use was denied. It requires approval, and this session has no
  approval surface ..."; `result.permission_denials` lists it
  (`tool_name`, `tool_use_id`, `tool_input`); and the stream has one
  system event `{"type": "system", "subtype": "permission_denied",
  "tool_name": "mcp__guard__ops__rotate_logs", "tool_use_id": ...,
  "decision_reason": "no approval surface in this session; permission
  request denied automatically", "decision_reason_type": "asyncAgent",
  "message": ...}`. This matches headless.md:323 and 333; the test
  asserts the denial, the `permission_denials` entry and the event.
- So a hook deny and `onFailure: "block"` (previous entry) show only in
  `permission_denials`, while a denied prompt shows in both.

## 2026-10-17, step 6 model spend

- Probe of every new model item (11 runs): $0.0260156
  (`artifacts/20261017T070833Z-57323/cost.json`).
- Idle probe, 31 s idle (1 run, scratch copy, deleted): $0.00102645.
- Final run: new items, D20/T1 x3, D16/T1 and T2 repeat 0 (16 runs):
  $0.037671555 (`artifacts/20261017T071415Z-64962/cost.json`).
- Variant B again after its gate fix (1 run): $0.00374838
  (`artifacts/20261017T071910Z-72942/cost.json`), still xfailed.
- Step 6 total: $0.068461985 (sum of `total_cost_usd` over 29 runs, no
  retries).

## 2026-10-17, step 7 model spend and the full run

- Probe of the new control test (1 run): $0.00411143
  (`artifacts/20261017T074052Z-93766/cost.json`).
- Targeted run, D19 x4 and D23/T9-T10 x8 with the step 6 fixes (12 runs):
  $0.02765306 (`artifacts/20261017T074628Z-94794/cost.json`).
- Full run, `./run.sh` with the key: 97 items, 86 passed, 11 xfailed,
  exit 0, 319 s wall time with the image cached; 39 model runs, no
  inconclusive retry, $0.07084632
  (`artifacts/20261017T075254Z-97188/cost.json`).
- Step 7 total: $0.10261081.

## 2026-10-17, Claude Code 2.1.296: `claude mcp get` prints a configured `Authorization` header in clear text

- What: an HTTP server added with `--header "Authorization: Bearer <value>"`.
  `claude mcp add` and `claude mcp list` do not print the value.
  `claude mcp get <name>` prints it in clear text.
- Differs from: changelog.md:5864 (2.1.161): "credential headers and URL
  secrets are redacted" for `claude mcp` list/get/add. So `get` regressed.
- Test: `tests/test_status_matrix.py::test_http_configured_header_is_redacted_in_cli_output`.
  `add` and `list` are plain asserts; `get` is a strict xfail. The value is a
  fresh test bearer made by the test, never a real secret. The test records
  `header_value_printed_by` in `run.json`.

## 2026-10-17, Claude Code 2.1.296: a bare 401 shows "Failed to connect", not "Needs authentication"

- What: an HTTP server with no configured header answers every request on
  the MCP path with a bare `401` and publishes no OAuth metadata (it breaks
  the spec's MUST to publish protected resource metadata). `claude mcp list`
  and `get` show `✘ Failed to connect — Dynamic Client Registration rejected
  (HTTP 404)`, not `! Needs authentication`.
- Differs from: mcp.md:764 ("either status code flags it in `/mcp`"), which
  does not depend on OAuth metadata.
- Test: `tests/test_status_matrix.py::test_http_bare_401_out_of_spec_server_status_recorded`
  (named `test_http_bare_401_no_header_needs_authentication` before commit
  4188004).
  The wire facts are plain asserts (the `server/discover` probe first, a
  `401` with no auth on every MCP request). The OAuth discovery paths the
  client then tries are recorded in `run.json`
  (`oauth_discovery_paths_requested`), not asserted.
- Now recorded, not xfailed (commit 4188004): the server breaks the spec
  MUST to publish Protected Resource Metadata (2025-11-25
  basic__authorization.md:65), and the client follows the spec's fallback
  and reports what it got. mcp.md:764 assumes an OAuth server. So the
  status is compared with the doc line record-only (`run.json` key
  `observations.documented_bare_401_status`); a compliant server (401 with
  metadata) gets `! Needs authentication` and
  `test_http_no_header_needs_authentication` passes.

