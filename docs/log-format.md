# Reading the logs

For a maintainer. The README links here; the CTO-level summary is there.

## `suite.log`

Every log line of the run, in the format

```
12:37:32.90 2026-10-17 [INFO    ] claude_cli.py:122 run_claude() - waiting done (0.13 s): exit 0, stdout 300 bytes: ...
```

(host time zone; `harness/log_format.py`). Log lines hold redacted text
only: commands with `--env`/`--header` values as hash + length, and the
first 200 chars of each `claude mcp ...` command's output after every test
credential and the API key are replaced. A `claude -p` run logs exit code,
time and byte counts only; its stream is summarized on the next
`got ... stream` line and kept in `stream-attemptN.jsonl`.

## One test's log

Each test row in `report.html` (and `suite.log`) tells what the test did
and what it got back, through `harness/check.py`:

| Line | Meaning |
|---|---|
| `step: ...` | an action: add a server, start a fake, run a command, mutate a recording |
| `start waiting for: ...` / `waiting done (<s> s): ...` | frame every wait (each `claude` command, the HTTP fake's start and stop) with what came back |
| `got <what>: ...` | a status, field, count or timing read back |
| `S recorded: ...` | a model fact kept, not asserted |
| `check <what>: Expected: ..., Actual: ... -> OK` | a check; `-> FAIL` at ERROR level on a miss |
| `record <what> (documented behavior, record-only): Expected: ..., Actual: ... -> MATCHES` / `-> DIFFERS` | a documented behavior that is recorded, never asserted (`harness/known_defects.py` `record_documented`); `DIFFERS` is a WARNING |

A failed check raises `AssertionError("<what>: Expected: <e>. Actual:
<a>.")`. A documented behavior that 2.1.296 does not show, in a strict
xfail test, logs a WARNING with the doc line as Expected and raises
`DocumentedBehaviorMismatch`. Long values are cut in the log line only
(300 chars, around the first difference).

An ERROR line inside a passing `test_harness_offline.py` test is expected:
those tests replay a mutated recording to provoke a failure on purpose,
and then check that failure.

A line `attempt check d_error_result for <tool>: N checks OK (logged in
full on the final attempt)` stands for checks that run on every attempt
and are logged in full once, on the final attempt (`harness/check.py`
`checks_logged_once`).

## Example

Ten lines of `test_stdio_crash_mid_call[0]` from run
`20261017T094227Z-47669` (lines over 200 chars cut here, marked `[...]`).
The `waiting done` line of a `claude -p` run shows byte counts only, e.g.
`exit 0, stdout 8401 bytes, stderr 0 bytes`. In that run the last line was
still the strict-xfail check; the test now records it instead (a `record
... -> DIFFERS` line).

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
