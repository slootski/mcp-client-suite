"""Harness self-checks against a recorded model run (free: no model call, no key).

QA step 4 (medium): when an attempt had no tool_use, the retry replaced its
records and nothing checked them. Break: attempt 0 has no tool_use but a
tools/call reached calc2; attempt 1 is normal; check_calc_d passes on
attempt 1, so the stray call of attempt 0 was hidden.

Fix (harness/model_flow.py): every attempt runs
model_checks.assert_every_call_has_a_tool_use before the retry decision.
These tests replay a real recorded D15/T1 run (tests/data/recorded-d15-t1/,
copied from artifacts/20261016T233619Z-58597, repeat 0; the env
fingerprints of the fakes' `started` records were dropped) through
run_until_triggered with run_print replaced by a stub, so no claude process
runs and nothing is charged:

  * the break: attempt 0 = the recorded stream with its tool_use and
    tool_result blocks removed, but the recorded wire log (a tools/call
    reached calc2); attempt 1 = the recorded run. The harness must fail on
    attempt 0 and never start attempt 1.
  * the control: attempt 0 has no tool_use and no tools/call (an honest
    S miss); the harness retries and attempt 1 passes check_calc_d.
  * the pure check on the recorded stream, with and without its tool_use.

QA step 5 (medium): a client that exits after the error or the crash
(stream: system/init and the first tool_result, then no next tool_use and
no result event) was reported as inconclusive, retried, then skipped, and
the suite exited 0. Fix: model_flow asserts the `result` event on every
attempt before the retry decision, and test_crash runs its crashed-call
asserts whenever the crash tool_use exists (crash_attempt_check). The
same offline mutation, `client_died_after_first_tool_result`, is replayed
through the real test code (test_tool_errors.run_flow for D16/T1 and T2,
test_crash.crash_run for D20/T1) against recorded runs
(tests/data/recorded-d16-t1, -d16-t2, -d20-t1, copied from
artifacts/20261017T062932Z-22649, repeat / run 0; env fingerprints
dropped). Each case must raise a plain AssertionError: not a skip, and not
DocumentedBehaviorMismatch (the exception a strict xfail accepts). A second
crash mutation keeps the result event but drops the crashed call's
tool_result. Controls: the unmutated recordings pass every D check; the
crash one raises nothing at all (its documented one-spawn line is
record-only) and records 2 spawns, DIFFERS from the doc line, in run.json.

QA step 6 (low): the step 6 model tests (D19/T1, D23/T9, D23/T10 variant
A) had no offline breaks. Recorded runs of
artifacts/20261017T073250Z-84063 (D19/T1 run 0, D23/T9 `deny`, D23/T10
variant A; env fingerprints dropped) are replayed through the real test
code (test_idle_timeout.run_idle, test_permissions.run_hook_guard,
test_permissions.run_allow_scope):
  * D19/T1: the client gives up 1 s after the call (an early give-up), or
    at 30 s with an error that is not the idle abort: each FAILS with a
    plain AssertionError. A fixed-client shape (give-up 3.5 s after the
    call, same idle text) returns with no error, so the strict xfail of
    test_idle_timeout_aborts_hung_call XPASSes and fails the run. Control:
    the recording ends at DocumentedBehaviorMismatch.
  * D23/T9 `deny`: a tools/call for delete_all added to the server's log
    FAILS (plain AssertionError). Control: the recording passes.
  * D23/T10 variant A: a fixed-client shape (no tools/call on guard__ops,
    the rotate_logs tool_result an error) returns with no error, so the
    strict xfail XPASSes. Control: the recording ends at
    DocumentedBehaviorMismatch.

Review round 2: finding 2's restart guard (NO_RESTART_MUTATIONS: the
later call an error with no second process, or no second process alone,
each FAILS check_d); every D23/T9, T10 and MCP server policy case
(PERMISSION_RECORDINGS) passes as recorded and FAILS under at least one
mutation each (PERMISSION_MUTATIONS); fakes/guard_hook.py answers per mode.
"""

import functools
import json
import os
import re
import subprocess
from datetime import datetime, timezone

import pytest

import harness.model_flow as model_flow
from harness.check import expect_equal, expect_in, expect_true, got, step
from harness.claude_cli import CliResult
from harness.constants import MAX_BUDGET_USD_PER_RUN, MAX_TURNS, MODEL_CLI_TIMEOUT_S, MODEL_ID, NEGOTIATION_LEGACY
from harness.model_checks import TOOLS_CALL, calls_without_tool_use, mcp_tool_name
from harness.error_checks import event_epoch
from harness.hooks import GUARD_HOOK_SCRIPT, read_hook_log
from harness.known_defects import DocumentedBehaviorMismatch
from harness.mcp_setup import PYTHON
from harness.model_run import ModelRun, allowed_tools_for, parse_stream
from harness.wire import message_method
import test_crash
import test_idle_timeout
import test_permissions
import test_tool_errors
from test_right_tool_args import ADD, CALC_SERVERS, check_calc_d

pytestmark = [pytest.mark.free]

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "recorded-d15-t1")
STREAM_FILE = "stream-attempt0.jsonl"
# Attempt 0 is replayed this many seconds before the recording, so the two
# attempts' wire records fall into separate windows (records_between).
ATTEMPT0_SHIFT_S = 1000.0
WINDOW_MARGIN_S = 1.0
RETRIES = 1
STUB_PROMPT = "offline replay: no model call"
# Events a fake writes while it handles a tools/call (fakes/stdio_fake.py).
CALL_EVENTS = ("tool_executed", "side_effect")


def read_jsonl(*, path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def recorded_wire(*, server):
    return read_jsonl(path=os.path.join(DATA_DIR, "wire-%s.jsonl" % server))


def recorded_stream_text():
    with open(os.path.join(DATA_DIR, STREAM_FILE), encoding="utf-8") as handle:
        return handle.read()


def stream_without_tool_use(*, text):
    """The recorded stream with every tool_use and tool_result block
    removed (an event left with no content is dropped)."""
    lines = []
    for line in text.splitlines():
        event = json.loads(line)
        if event["type"] in ("assistant", "user") and isinstance(event["message"]["content"], list):
            kept = [block for block in event["message"]["content"]
                    if block["type"] not in ("tool_use", "tool_result")]
            if not kept:
                continue
            event["message"]["content"] = kept
        lines.append(json.dumps(event, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def without_calls(*, records):
    """Wire records with every tools/call, its reply and its execution
    records removed (an attempt where no call reached the fake)."""
    call_ids = {(r["pid"], r["msg"]["id"]) for r in records
                if r["event"] == "recv" and message_method(message=r["msg"]) == TOOLS_CALL}
    out = []
    for record in records:
        if record["event"] == "recv" and message_method(message=record["msg"]) == TOOLS_CALL:
            continue
        if record["event"] in CALL_EVENTS:
            continue
        if (record["event"] == "sent" and "id" in record["msg"] and "method" not in record["msg"]
                and (record["pid"], record["msg"]["id"]) in call_ids):
            continue
        out.append(record)
    return out


def shifted(*, records, by_s):
    out = []
    for record in records:
        moved = dict(record)
        moved["epoch"] = record["epoch"] + by_s
        out.append(moved)
    return out


def replay(*, stream_text, records_by_server):
    """One stubbed attempt: its stream text and its wire records."""
    epochs = [r["epoch"] for server in records_by_server for r in records_by_server[server]]
    return {"stream_text": stream_text, "records": records_by_server,
            "start_epoch": min(epochs) - WINDOW_MARGIN_S, "end_epoch": max(epochs) + WINDOW_MARGIN_S}


class StubRunPrint:
    """Stands in for harness.model_run.run_print: appends the attempt's
    wire records to the sandbox's wire logs, writes its stream file, and
    returns a ModelRun. Charges nothing. Its monotonic duration equals its
    wall-clock window, so a replay never reads as a host clock jump."""

    def __init__(self, *, attempts):
        self._attempts = list(attempts)
        self.labels = []

    def __call__(self, *, sandbox, env, ledger, test_id, label, prompt, model, max_turns, max_budget_usd, servers,
                 allowed_tools, timeout_s, extra_args):
        replay_data = self._attempts[len(self.labels)]
        self.labels.append(label)
        for server in replay_data["records"]:
            with open(sandbox.wire_log_path(name=server), "a", encoding="utf-8") as handle:
                for record in replay_data["records"][server]:
                    handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        stream_file = os.path.join(sandbox.artifact_dir, "stream-%s.jsonl" % label)
        with open(stream_file, "w", encoding="utf-8") as handle:
            handle.write(replay_data["stream_text"])
        cli = CliResult(argv=["claude", "-p", "(stub)"], returncode=0, stdout=replay_data["stream_text"], stderr="",
                        duration_s=replay_data["end_epoch"] - replay_data["start_epoch"],
                        start_epoch=replay_data["start_epoch"],
                        end_epoch=replay_data["end_epoch"])
        return ModelRun(label=label, cli=cli, stream=parse_stream(text=replay_data["stream_text"]),
                        debug_file=os.path.join(sandbox.artifact_dir, "debug-%s.log" % label),
                        stream_file=stream_file, charged_usd=0.0)


def run_stubbed(*, sandbox, request, stub):
    names = sorted(CALC_SERVERS)
    return model_flow.run_until_triggered(
        sandbox=sandbox, ledger=None, test_id=request.node.nodeid, prompt=STUB_PROMPT, model=MODEL_ID,
        max_turns=MAX_TURNS, max_budget_usd=MAX_BUDGET_USD_PER_RUN, timeout_s=MODEL_CLI_TIMEOUT_S,
        servers={}, allowed_tools=allowed_tools_for(servers=names), gate_servers=names, wire_servers=names,
        trigger_names=[mcp_tool_name(server=server, tool=ADD) for server in CALC_SERVERS],
        require_all_triggers=False, retries=RETRIES, rejected_exit_code=1, extra_args=[], attempt_checks=[],
    )


def recorded_attempt():
    return replay(stream_text=recorded_stream_text(),
                  records_by_server={server: recorded_wire(server=server) for server in CALC_SERVERS})


def test_recorded_run_pure_check():
    """The recorded stream explains its calls; without its tool_use it does not."""
    records = {server: recorded_wire(server=server) for server in CALC_SERVERS}
    text = recorded_stream_text()
    step(text="check the recorded D15/T1 stream against its wire logs, as recorded")
    as_recorded = calls_without_tool_use(stream=parse_stream(text=text), records_by_server=records)
    got(what="tools/call with no tool_use in the recorded run, per server", value=as_recorded)
    expect_equal(what="tools/call with no tool_use in the recorded run", expected={}, actual=as_recorded)
    step(text="check it again with every tool_use and tool_result removed from the stream")
    stray = calls_without_tool_use(stream=parse_stream(text=stream_without_tool_use(text=text)),
                                   records_by_server=records)
    stray_count = {server: len(stray[server]) for server in stray}
    got(what="tools/call with no tool_use once the tool_use blocks are removed, per server (count)", value=stray_count)
    expect_equal(what="tools/call with no tool_use, per server (count)", expected={"calc2": 1}, actual=stray_count)


def test_call_without_tool_use_fails_before_retry(free_sandbox, request, monkeypatch):
    """The QA break: attempt 0 no tool_use + a tools/call on calc2, attempt 1 normal."""
    attempt0 = replay(
        stream_text=stream_without_tool_use(text=recorded_stream_text()),
        records_by_server={server: shifted(records=recorded_wire(server=server), by_s=-ATTEMPT0_SHIFT_S)
                           for server in CALC_SERVERS},
    )
    stub = StubRunPrint(attempts=[attempt0, recorded_attempt()])
    monkeypatch.setattr(model_flow, "run_print", stub)
    step(text="replay: attempt0 = the recorded stream without tool_use, but a tools/call on calc2; attempt1 = the "
              "recorded run")
    with pytest.raises(AssertionError, match="tools/call with no tool_use for it in the stream"):
        run_stubbed(sandbox=free_sandbox, request=request, stub=stub)
    expect_equal(what="attempts the harness started (no retry after a stray call)", expected=["attempt0"],
                 actual=stub.labels)
    stream_file = os.path.join(free_sandbox.artifact_dir, "stream-attempt0.jsonl")
    expect_equal(what="stream-attempt0.jsonl kept in the artifacts", expected=True, actual=os.path.exists(stream_file))


def test_honest_s_miss_is_retried_and_attempt1_passes_d(free_sandbox, request, monkeypatch):
    """Control: attempt 0 with no tool_use and no tools/call is retried;
    attempt 1 (the recorded run) passes check_calc_d. The same attempt 1
    passed check_calc_d in the break above too, which is why the check on
    attempt 0 is needed."""
    attempt0 = replay(
        stream_text=stream_without_tool_use(text=recorded_stream_text()),
        records_by_server={server: shifted(records=without_calls(records=recorded_wire(server=server)),
                                           by_s=-ATTEMPT0_SHIFT_S)
                           for server in CALC_SERVERS},
    )
    stub = StubRunPrint(attempts=[attempt0, recorded_attempt()])
    monkeypatch.setattr(model_flow, "run_print", stub)
    step(text="replay: attempt0 = no tool_use and no tools/call (an honest S miss); attempt1 = the recorded run")
    triggered = run_stubbed(sandbox=free_sandbox, request=request, stub=stub)
    expect_equal(what="attempts the harness started", expected=["attempt0", "attempt1"], actual=stub.labels)
    expect_equal(what="inconclusive reason of the flow", expected=None, actual=triggered.inconclusive)
    expect_true(what="inconclusive reason of attempt0", expected="starts with 'inconclusive: the model made no tool_use'",
                actual=triggered.attempts[0]["inconclusive"],
                holds=triggered.attempts[0]["inconclusive"].startswith("inconclusive: the model made no tool_use"))
    expect_equal(what="tools/call per fake in attempt0", expected={"calc": 0, "calc2": 0},
                 actual=triggered.attempts[0]["tools_call_count"])
    expect_equal(what="tools/call per fake in attempt1", expected={"calc": 0, "calc2": 1},
                 actual=triggered.attempts[1]["tools_call_count"])
    check_calc_d(sandbox=free_sandbox, triggered=triggered, negotiation=NEGOTIATION_LEGACY)


# ---------------------------------------------------------------- QA step 5
D16_RECORDINGS = {"T1": "recorded-d16-t1", "T2": "recorded-d16-t2"}
CRASH_RECORDING = "recorded-d20-t1"
HOOKS_FILE = "hooks.jsonl"
D16_TOKEN = re.compile(r"%s[0-9a-f]{%d}" % (test_tool_errors.TOKEN_PREFIX, 2 * test_tool_errors.TOKEN_HEX_BYTES))
NO_RESULT_MESSAGE = "the stream has no result event"
CRASH_RUN_INDEX = 0
CRASH_TOOL_USE_ID = "toolu_01ASD9nz6Z8hdSiBCkzdpf6V"  # the crashed tool_use in CRASH_RECORDING's stream
RECORDED_CRASH_SPAWNS = 2  # CRASH_RECORDING: the first process, then the lazy restart on the next call


def recording(*, folder, server):
    """(stream text, wire records of `server`, hook log text) of a recorded run."""
    base = os.path.join(os.path.dirname(DATA_DIR), folder)
    with open(os.path.join(base, STREAM_FILE), encoding="utf-8") as handle:
        text = handle.read()
    with open(os.path.join(base, HOOKS_FILE), encoding="utf-8") as handle:
        hooks = handle.read()
    return text, read_jsonl(path=os.path.join(base, "wire-%s.jsonl" % server)), hooks


def first_tool_result_index(*, events):
    hits = [index for index, event in enumerate(events)
            if event["type"] == "user" and isinstance(event["message"]["content"], list) and any(
                block["type"] == "tool_result" for block in event["message"]["content"])]
    expect_true(what="user events with a tool_result in the recording", expected="at least one",
                actual="%d (stream lines %s)" % (len(hits), hits), holds=bool(hits))
    return hits[0]


def client_died_after_first_tool_result(*, text, records):
    """QA step 5 mutation: the stream keeps system/init, the first tool_use
    and its tool_result, then ends (no next tool_use, no result event); the
    wire log keeps what the fake logged up to that tool_result."""
    lines = text.splitlines()
    events = [json.loads(line) for line in lines]
    cut = first_tool_result_index(events=events)
    cut_epoch = event_epoch(event=events[cut])
    return "\n".join(lines[:cut + 1]) + "\n", [r for r in records if r["epoch"] <= cut_epoch]


def crash_result_dropped(*, text, records):
    """Second crash mutation: the crash tool_use, then straight to the
    result event (no tool_result for it, no later tool_use); the wire log
    keeps the first fake process up to the original tool_result."""
    lines = text.splitlines()
    events = [json.loads(line) for line in lines]
    cut = first_tool_result_index(events=events)
    cut_epoch = event_epoch(event=events[cut])
    kept = lines[:cut] + [lines[-1]]
    expect_equal(what="type of the recording's last event", expected="result", actual=events[-1]["type"])
    return "\n".join(kept) + "\n", [r for r in records if r["epoch"] <= cut_epoch]


def first_process_only(*, records):
    """The wire records of the first fake process (later processes dropped)."""
    first_pid = [r["pid"] for r in records if r["event"] == "started"][0]
    return [r for r in records if r["pid"] == first_pid]


def client_without_restart(*, text, records):
    """Finding 2 mutation, a client that does not restart the crashed server:
    the later echo call's tool_result becomes an error ("Connection closed",
    the crashed call's text) and the second fake process's records are dropped."""
    events = [json.loads(line) for line in text.splitlines()]
    _index, use = tool_use_of(events=events, name=mcp_tool_name(server=test_crash.SERVER, tool=test_crash.NEXT_TOOL))
    return (rewrite_tool_result(text=text, tool_use_id=use["id"], epoch=None, content=OTHER_ERROR_TEXT, is_error=True),
            first_process_only(records=records))


def second_process_dropped(*, text, records):
    """Finding 2 mutation: the stream as recorded (the later call succeeds),
    but no second fake process served it (its wire records are dropped)."""
    return text, first_process_only(records=records)


def raised_by(*, call):
    """The exception a call raised (BaseException: pytest's skip too), or None."""
    try:
        call()
    except BaseException as exc:  # noqa: B902 - the test inspects what was raised
        return exc
    return None


def assert_plain_failure(*, exc, match):
    """A D failure: an AssertionError that is neither a skip nor the
    DocumentedBehaviorMismatch a strict xfail accepts."""
    got(what="exception the mutated run raised", value=repr(exc))
    expect_true(what="outcome of the mutated run", expected="it raised (a D failure)",
                actual="raised nothing (it passed)" if exc is None else "raised %s" % type(exc).__name__,
                holds=exc is not None)
    expect_equal(what="the mutated run was skipped", expected=False, actual=isinstance(exc, pytest.skip.Exception))
    expect_equal(what="the mutated run hid under the xfail (DocumentedBehaviorMismatch)", expected=False,
                 actual=isinstance(exc, DocumentedBehaviorMismatch))
    expect_equal(what="the mutated run raised an AssertionError", expected=True, actual=isinstance(exc, AssertionError))
    expect_in(what="message of the mutated run's failure", item=match, container=str(exc))


def d16_flow(*, sandbox, request, case_id, text):
    case = test_tool_errors.CASES[case_id]
    token = D16_TOKEN.search(text).group(0)
    hook_log = os.path.join(sandbox.artifact_dir, HOOKS_FILE)
    return functools.partial(test_tool_errors.run_flow, sandbox=sandbox, ledger=None, request=request, case=case,
                             token=token, prompt=STUB_PROMPT, hook_log=hook_log), case, token, hook_log


@pytest.mark.parametrize("case_id", sorted(D16_RECORDINGS))
def test_d16_client_died_after_error_fails(free_sandbox, request, monkeypatch, case_id):
    """QA step 5 break for D16/T1 and T2: must FAIL, not skip."""
    server = test_tool_errors.CASES[case_id]["server"]
    text, records, _hooks = recording(folder=D16_RECORDINGS[case_id], server=server)
    mutated_text, mutated_records = client_died_after_first_tool_result(text=text, records=records)
    step(text="replay %s with the stream cut after the first tool_result (no result event)" % D16_RECORDINGS[case_id])
    attempt = replay(stream_text=mutated_text, records_by_server={server: mutated_records})
    stub = StubRunPrint(attempts=[attempt, attempt])
    monkeypatch.setattr(model_flow, "run_print", stub)
    flow, _case, _token, _hook_log = d16_flow(sandbox=free_sandbox, request=request, case_id=case_id, text=text)
    assert_plain_failure(exc=raised_by(call=flow), match=NO_RESULT_MESSAGE)
    expect_equal(what="attempts the harness started (no retry)", expected=["attempt0"], actual=stub.labels)


@pytest.mark.parametrize("case_id", sorted(D16_RECORDINGS))
def test_d16_recorded_run_passes_d(free_sandbox, request, monkeypatch, case_id):
    """Control: the unmutated recording passes the flow and every D16 D check."""
    server = test_tool_errors.CASES[case_id]["server"]
    text, records, hooks = recording(folder=D16_RECORDINGS[case_id], server=server)
    stub = StubRunPrint(attempts=[replay(stream_text=text, records_by_server={server: records})])
    monkeypatch.setattr(model_flow, "run_print", stub)
    flow, case, token, hook_log = d16_flow(sandbox=free_sandbox, request=request, case_id=case_id, text=text)
    with open(hook_log, "w", encoding="utf-8") as handle:
        handle.write(hooks)
    step(text="replay %s as recorded" % D16_RECORDINGS[case_id])
    triggered = flow()
    expect_equal(what="inconclusive reason of the flow", expected=None, actual=triggered.inconclusive)
    test_tool_errors.check_d(sandbox=free_sandbox, triggered=triggered, case=case, token=token, hook_log=hook_log)


def crash_call(*, sandbox, request, monkeypatch, attempts, hooks):
    stub = StubRunPrint(attempts=attempts)
    monkeypatch.setattr(model_flow, "run_print", stub)
    with open(os.path.join(sandbox.artifact_dir, test_crash.HOOK_LOG_NAME), "w", encoding="utf-8") as handle:
        handle.write(hooks)
    return stub, functools.partial(test_crash.crash_run, sandbox=sandbox, ledger=None, request=request,
                                   run_index=CRASH_RUN_INDEX, signatures={})


@pytest.mark.parametrize("mutation, match", [
    ("client_died_after_first_tool_result", NO_RESULT_MESSAGE),
    # The full check message pins the count (Expected 1, Actual 0); the id
    # keeps the test id of step 8.
    pytest.param("crash_result_dropped",
                 "tool_result blocks for the crashed tool_use %s: Expected: 1. Actual: 0." % CRASH_TOOL_USE_ID,
                 id="crash_result_dropped-tool_result blocks for the crashed tool_use"),
])
def test_crash_client_died_fails(free_sandbox, request, monkeypatch, mutation, match):
    """QA step 5 break for D20/T1: must FAIL, not skip and not xfail."""
    text, records, hooks = recording(folder=CRASH_RECORDING, server=test_crash.SERVER)
    mutate = {"client_died_after_first_tool_result": client_died_after_first_tool_result,
              "crash_result_dropped": crash_result_dropped}[mutation]
    mutated_text, mutated_records = mutate(text=text, records=records)
    step(text="replay %s with mutation %s" % (CRASH_RECORDING, mutation))
    attempt0 = replay(stream_text=mutated_text,
                      records_by_server={test_crash.SERVER: shifted(records=mutated_records, by_s=-ATTEMPT0_SHIFT_S)})
    attempt1 = replay(stream_text=mutated_text, records_by_server={test_crash.SERVER: mutated_records})
    stub, call = crash_call(sandbox=free_sandbox, request=request, monkeypatch=monkeypatch,
                            attempts=[attempt0, attempt1], hooks=hooks)
    assert_plain_failure(exc=raised_by(call=call), match=match)
    expect_equal(what="attempts the harness started (no retry)", expected=["attempt0"], actual=stub.labels)


# id: (mutation, the start of the failing check's message)
NO_RESTART_MUTATIONS = {
    "client_without_restart": (client_without_restart, "is_error of the first later call's tool_result"),
    "second_process_dropped": (second_process_dropped, "fake processes that got the first later call"),
}


@pytest.mark.parametrize("mutation_id", list(NO_RESTART_MUTATIONS))
def test_crash_client_without_restart_fails(free_sandbox, request, monkeypatch, mutation_id):
    """Finding 2 break: a client that stops restarting the crashed server
    must FAIL check_d (plain AssertionError), although the doc line holds."""
    mutate, match = NO_RESTART_MUTATIONS[mutation_id]
    text, records, hooks = recording(folder=CRASH_RECORDING, server=test_crash.SERVER)
    mutated_text, mutated_records = mutate(text=text, records=records)
    step(text="replay %s with mutation %s" % (CRASH_RECORDING, mutation_id))
    stub, call = crash_call(sandbox=free_sandbox, request=request, monkeypatch=monkeypatch, hooks=hooks,
                            attempts=[replay(stream_text=mutated_text,
                                             records_by_server={test_crash.SERVER: mutated_records})])
    assert_plain_failure(exc=raised_by(call=call), match=match)
    expect_equal(what="attempts the harness started", expected=["attempt0"], actual=stub.labels)


def test_crash_recorded_run_passes_and_records_the_restart(free_sandbox, request, monkeypatch):
    """Control: the unmutated crash recording passes every hard assert and
    raises nothing (the documented one-spawn line is record-only). run.json
    records the lazy restart: 2 spawns, the doc line DIFFERS."""
    text, records, hooks = recording(folder=CRASH_RECORDING, server=test_crash.SERVER)
    stub, call = crash_call(sandbox=free_sandbox, request=request, monkeypatch=monkeypatch,
                            attempts=[replay(stream_text=text, records_by_server={test_crash.SERVER: records})],
                            hooks=hooks)
    step(text="replay %s as recorded" % CRASH_RECORDING)
    exc = raised_by(call=call)
    expect_equal(what="exception the recorded crash run raised", expected=None,
                 actual=None if exc is None else repr(exc))
    documented = free_sandbox.record.observation(key="documented_no_restart")
    got(what="run.json documented_no_restart of the replay", value=documented)
    expect_equal(what="(spawns, matches the doc line) recorded in run.json", expected=(RECORDED_CRASH_SPAWNS, False),
                 actual=(documented["spawns"], documented["matches"]))


# ---------------------------------------------------------------- QA step 6
IDLE_RECORDING = "recorded-d19-t1"
T9_RECORDING = "recorded-d23-t9-deny"
T10A_RECORDING = "recorded-d23-t10-a"
EARLY_GIVE_UP_S = 1.0
FIXED_GIVE_UP_S = 3.5
DENY_REASON = re.compile(r"%s[0-9a-f]{%d}" % (test_permissions.DENY_REASON_PREFIX, 2 * test_permissions.HEX_BYTES))
CLEANUP_REASON = re.compile(r"%s[0-9a-f]{%d}" % (test_permissions.CLEANUP_PREFIX, 2 * test_permissions.HEX_BYTES))
INJECTED_RPC_ID = 9001
OTHER_ERROR_TEXT = "Connection closed"
FIXED_DENIAL_TEXT = "Permission for this tool use was denied (fixed-client shape, offline replay)"
OFFLINE_SERVICE = "svc-offline"


def read_recording(*, folder, names):
    """{file name: text} of a recorded run under tests/data/<folder>/."""
    base = os.path.join(os.path.dirname(DATA_DIR), folder)
    out = {}
    for name in names:
        with open(os.path.join(base, name), encoding="utf-8") as handle:
            out[name] = handle.read()
    return out


def wire_records(*, text):
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def iso_timestamp(*, epoch):
    """An epoch as the stream's `timestamp` format (ISO 8601, ms, `Z`)."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def tool_result_event(*, events, tool_use_id):
    """Index of the user event that holds the tool_result of tool_use_id."""
    hits = [index for index, event in enumerate(events)
            if event["type"] == "user" and isinstance(event["message"]["content"], list) and any(
                block["type"] == "tool_result" and block["tool_use_id"] == tool_use_id
                for block in event["message"]["content"])]
    expect_true(what="user events with the tool_result for %s in the recording" % tool_use_id,
                expected="at least one", actual="%d (stream lines %s)" % (len(hits), hits), holds=bool(hits))
    return hits[0]


def tool_use_of(*, events, name):
    """(event index, tool_use block) of the first tool_use named `name`."""
    hits = [(index, block) for index, event in enumerate(events) if event["type"] == "assistant"
            for block in event["message"]["content"] if block["type"] == "tool_use" and block["name"] == name]
    expect_true(what="tool_use blocks named %s in the recording" % name, expected="at least one",
                actual="%d (stream lines %s)" % (len(hits), [index for index, _block in hits]), holds=bool(hits))
    return hits[0]


def rewrite_tool_result(*, text, tool_use_id, epoch, content, is_error):
    """The stream with one tool_result changed: its event `timestamp` set to
    epoch (unchanged when None), its content to `content` (unchanged when
    None), its is_error to `is_error`."""
    events = [json.loads(line) for line in text.splitlines()]
    index = tool_result_event(events=events, tool_use_id=tool_use_id)
    event = events[index]
    if epoch is not None:
        event["timestamp"] = iso_timestamp(epoch=epoch)
    for block in event["message"]["content"]:
        if block["type"] == "tool_result" and block["tool_use_id"] == tool_use_id:
            if content is not None:
                block["content"] = content
            block["is_error"] = is_error
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n"


def stub_flow(*, monkeypatch, attempts):
    stub = StubRunPrint(attempts=attempts)
    monkeypatch.setattr(model_flow, "run_print", stub)
    return stub


def assert_strict_xfail(*, test):
    """The test carries xfail(strict=True, raises=DocumentedBehaviorMismatch),
    so a run that raises nothing is an XPASS, and pytest fails the run."""
    marks = [mark for mark in test.pytestmark if mark.name == "xfail"]
    expect_equal(what="xfail marks on %s" % test.__name__, expected=1, actual=len(marks))
    expect_equal(what="(strict, raises) of the xfail mark on %s" % test.__name__,
                 expected=(True, DocumentedBehaviorMismatch),
                 actual=(marks[0].kwargs["strict"], marks[0].kwargs["raises"]))


# D19/T1 --------------------------------------------------------------------
def idle_recording():
    files = read_recording(folder=IDLE_RECORDING, names=[STREAM_FILE, "wire-%s.jsonl" % test_idle_timeout.SERVER])
    records = wire_records(text=files["wire-%s.jsonl" % test_idle_timeout.SERVER])
    call = [r for r in records if r["event"] == "recv" and message_method(message=r["msg"]) == TOOLS_CALL]
    expect_equal(what="tools/call in the recorded D19/T1 wire log", expected=1, actual=len(call))
    return files[STREAM_FILE], records, call[0]


def idle_attempt(*, epoch_after_call_s, content):
    """The recorded D19/T1 run; when epoch_after_call_s is set, the hung
    call's tool_result is moved to that many seconds after the fake's
    `recv` of the tools/call (and its content replaced when content is set)."""
    text, records, call = idle_recording()
    if epoch_after_call_s is not None or content is not None:
        use_id = call["msg"]["params"]["_meta"]["claudecode/toolUseId"]
        epoch = call["epoch"] + epoch_after_call_s if epoch_after_call_s is not None else None
        text = rewrite_tool_result(text=text, tool_use_id=use_id, epoch=epoch, content=content, is_error=True)
    return replay(stream_text=text, records_by_server={test_idle_timeout.SERVER: records})


def idle_call(*, sandbox, request):
    return functools.partial(test_idle_timeout.run_idle, sandbox=sandbox, ledger=None, request=request,
                             negotiation=NEGOTIATION_LEGACY)


def recorded_idle_text():
    text, _records, call = idle_recording()
    events = [json.loads(line) for line in text.splitlines()]
    use_id = call["msg"]["params"]["_meta"]["claudecode/toolUseId"]
    event = events[tool_result_event(events=events, tool_use_id=use_id)]
    return [b["content"] for b in event["message"]["content"] if b["type"] == "tool_result"][0]


def test_idle_recorded_run_reaches_the_documented_xfail(free_sandbox, request, monkeypatch):
    """Control: the recorded run (abort at 30 s) passes every hard assert and
    ends at the documented 3-5 s check."""
    stub = stub_flow(monkeypatch=monkeypatch, attempts=[idle_attempt(epoch_after_call_s=None, content=None)])
    step(text="replay %s as recorded (abort at 30 s)" % IDLE_RECORDING)
    exc = raised_by(call=idle_call(sandbox=free_sandbox, request=request))
    expect_true(what="exception the recorded idle run raised", expected="DocumentedBehaviorMismatch",
                actual=repr(exc), holds=isinstance(exc, DocumentedBehaviorMismatch))
    expect_equal(what="attempts the harness started", expected=["attempt0"], actual=stub.labels)


def test_idle_early_give_up_fails(free_sandbox, request, monkeypatch):
    """Break: the client gives up 1 s after the call (before the 3 s idle window)."""
    stub_flow(monkeypatch=monkeypatch, attempts=[idle_attempt(epoch_after_call_s=EARLY_GIVE_UP_S, content=None)])
    step(text="replay %s with the give-up moved to %.1f s after the call" % (IDLE_RECORDING, EARLY_GIVE_UP_S))
    assert_plain_failure(exc=raised_by(call=idle_call(sandbox=free_sandbox, request=request)), match="hard window")


def test_idle_abort_by_another_error_fails(free_sandbox, request, monkeypatch):
    """Break: an error tool_result inside the hard window that is not the
    client's idle abort (QA step 6: the window alone did not prove the cause)."""
    stub_flow(monkeypatch=monkeypatch, attempts=[idle_attempt(epoch_after_call_s=None, content=OTHER_ERROR_TEXT)])
    step(text="replay %s with the error text replaced by %r" % (IDLE_RECORDING, OTHER_ERROR_TEXT))
    assert_plain_failure(exc=raised_by(call=idle_call(sandbox=free_sandbox, request=request)),
                         match="idle-abort text")


def test_idle_fixed_client_shape_xpasses(free_sandbox, request, monkeypatch):
    """A client that aborts 3.5 s after the call, with the same idle text
    (its seconds changed to 3), raises nothing: the strict xfail XPASSes."""
    fixed_text = recorded_idle_text().replace("for 30s;", "for 3s;")
    expect_true(what="the fixed-client error text", expected="holds %r and 'for 3s;'" % test_idle_timeout.IDLE_ABORT_TEXT,
                actual=fixed_text, holds=test_idle_timeout.IDLE_ABORT_TEXT in fixed_text and "for 3s;" in fixed_text)
    stub_flow(monkeypatch=monkeypatch, attempts=[idle_attempt(epoch_after_call_s=FIXED_GIVE_UP_S,
                                                              content=fixed_text)])
    step(text="replay %s as a fixed client: give-up %.1f s after the call, same idle text" % (
        IDLE_RECORDING, FIXED_GIVE_UP_S))
    expect_equal(what="exception the fixed-client replay raised", expected=None,
                 actual=raised_by(call=idle_call(sandbox=free_sandbox, request=request)))
    assert_strict_xfail(test=test_idle_timeout.test_idle_timeout_aborts_hung_call)
    assert_strict_xfail(test=test_idle_timeout.test_idle_timeout_aborts_hung_call_negotiation_unset)


# D23/T9 --------------------------------------------------------------------
def t9_recording():
    files = read_recording(folder=T9_RECORDING, names=[STREAM_FILE, "wire-guard.jsonl",
                                                       test_permissions.HOOK_LOG_NAME])
    return files[STREAM_FILE], wire_records(text=files["wire-guard.jsonl"]), files[test_permissions.HOOK_LOG_NAME]


def with_tools_call(*, text, records, server, tool):
    """The wire log of `server` plus a tools/call for `tool`, as if the client
    had sent the stopped call: it carries the tool_use id of the first
    mcp__<server>__<tool> tool_use, so the harness pairs it with that tool_use."""
    events = [json.loads(line) for line in text.splitlines()]
    index, use = tool_use_of(events=events, name=mcp_tool_name(server=server, tool=tool))
    pid = [r["pid"] for r in records if r["event"] == "started"][0]
    injected = {"epoch": event_epoch(event=events[index]) + 0.01, "event": "recv", "pid": pid, "source": server,
                "msg": {"id": INJECTED_RPC_ID, "jsonrpc": "2.0", "method": TOOLS_CALL,
                        "params": {"_meta": {"claudecode/toolUseId": use["id"]}, "arguments": use["input"],
                                   "name": tool}}}
    return sorted(records + [injected], key=lambda r: r["epoch"])


def t9_call(*, sandbox, request, case_id, text, hooks):
    with open(os.path.join(sandbox.artifact_dir, test_permissions.HOOK_LOG_NAME), "w", encoding="utf-8") as handle:
        handle.write(hooks)
    return functools.partial(test_permissions.run_hook_guard, sandbox=sandbox, ledger=None, request=request,
                             case_id=case_id, reason=CLEANUP_REASON.search(text).group(0),
                             deny_reason=DENY_REASON.search(text).group(0))


def test_t9_recorded_deny_passes(free_sandbox, request, monkeypatch):
    """Control: the recorded `deny` run passes every D23/T9 check."""
    text, records, hooks = t9_recording()
    stub_flow(monkeypatch=monkeypatch,
              attempts=[replay(stream_text=text, records_by_server={test_permissions.GUARD: records})])
    step(text="replay %s as recorded" % T9_RECORDING)
    expect_equal(what="exception the recorded deny run raised", expected=None, actual=raised_by(
        call=t9_call(sandbox=free_sandbox, request=request, case_id="deny", text=text, hooks=hooks)))


def test_t9_server_got_delete_all_fails(free_sandbox, request, monkeypatch):
    """Break: the denied delete_all reached the server anyway."""
    text, records, hooks = t9_recording()
    mutated = with_tools_call(text=text, records=records, server=test_permissions.GUARD, tool=test_permissions.DELETE)
    step(text="replay %s with a tools/call for delete_all added to the guard log" % T9_RECORDING)
    stub_flow(monkeypatch=monkeypatch,
              attempts=[replay(stream_text=text, records_by_server={test_permissions.GUARD: mutated})])
    assert_plain_failure(exc=raised_by(call=t9_call(sandbox=free_sandbox, request=request, case_id="deny",
                                                    text=text, hooks=hooks)),
                         match="delete_all reached the server 1 time(s) although the hook stopped it")


# D23/T10 variant A ---------------------------------------------------------
def t10a_attempt(*, fixed):
    files = read_recording(folder=T10A_RECORDING, names=[STREAM_FILE, "wire-guard.jsonl",
                                                         "wire-%s.jsonl" % test_permissions.OPS])
    text = files[STREAM_FILE]
    ops = wire_records(text=files["wire-%s.jsonl" % test_permissions.OPS])
    if fixed:
        events = [json.loads(line) for line in text.splitlines()]
        _index, use = tool_use_of(events=events, name=mcp_tool_name(server=test_permissions.OPS,
                                                                     tool=test_permissions.ROTATE))
        text = rewrite_tool_result(text=text, tool_use_id=use["id"], epoch=None, content=FIXED_DENIAL_TEXT,
                                   is_error=True)
        ops = without_calls(records=ops)
    return replay(stream_text=text, records_by_server={test_permissions.GUARD: wire_records(
        text=files["wire-guard.jsonl"]), test_permissions.OPS: ops})


def t10a_call(*, sandbox, request):
    return functools.partial(test_permissions.run_allow_scope, sandbox=sandbox, ledger=None, request=request,
                             service=OFFLINE_SERVICE)


def test_t10a_recorded_run_reaches_the_documented_xfail(free_sandbox, request, monkeypatch):
    """Control: 2.1.296 let rotate_logs reach guard__ops: the documented check fails."""
    stub_flow(monkeypatch=monkeypatch, attempts=[t10a_attempt(fixed=False)])
    step(text="replay %s as recorded" % T10A_RECORDING)
    exc = raised_by(call=t10a_call(sandbox=free_sandbox, request=request))
    expect_true(what="exception the recorded variant A run raised", expected="DocumentedBehaviorMismatch",
                actual=repr(exc), holds=isinstance(exc, DocumentedBehaviorMismatch))


def test_t10a_fixed_client_shape_xpasses(free_sandbox, request, monkeypatch):
    """A 2.1.299-like client (no tools/call on guard__ops, the rotate_logs
    tool_result an error) raises nothing: the strict xfail XPASSes."""
    stub_flow(monkeypatch=monkeypatch, attempts=[t10a_attempt(fixed=True)])
    step(text="replay %s as a fixed client: no tools/call on guard__ops, rotate_logs denied" % T10A_RECORDING)
    expect_equal(what="exception the fixed-client replay raised", expected=None,
                 actual=raised_by(call=t10a_call(sandbox=free_sandbox, request=request)))
    assert_strict_xfail(test=test_permissions.test_server_allow_rule_does_not_reach_double_underscore_server)


# D23/T9, D23/T10, MCP server policy: every permission case -----------------
# Recordings of run 20261017T123420Z-60563, `ask` of run 20261017T141534Z-2243
# (env fingerprints dropped). Not real runs of their case, built from another
# case's recording until a paid run records them: `allow` = exit1_default (run
# with --allowedTools "mcp__guard__*", not list_items only) with the hook's exit1
# rewritten to allow; `policy_*` = deny_rule (no --settings policy), guard__ops log empty.
OFFLINE_REASON = "cleanup-offline"
OFFLINE_DENY_REASON = "denied-by-guard-hook-offline"  # T9 cases that do not assert the reason
REASON_DROPPED_TEXT = "Permission for this tool use was denied (no hook reason, offline replay)"
GUARD_HOOK_TIMEOUT_S = 10
GUARD = test_permissions.GUARD
OPS = test_permissions.OPS
PERMISSION_RECORDINGS = {
    "deny_rule": {"folder": "recorded-d23-t10-deny-rule", "servers": [GUARD], "hook_log": False,
                  "rewrite_actions": {}},
    "no_rule": {"folder": "recorded-d23-t10-no-rule", "servers": [GUARD, OPS], "hook_log": False,
                "rewrite_actions": {}},
    "matcher_without_wildcard": {"folder": "recorded-d23-t9-matcher-without-wildcard", "servers": [GUARD],
                                 "hook_log": False, "rewrite_actions": {}},
    "exit1_default": {"folder": "recorded-d23-t9-exit1-default", "servers": [GUARD], "hook_log": True,
                      "rewrite_actions": {}},
    "exit1_on_failure_block": {"folder": "recorded-d23-t9-exit1-on-failure-block", "servers": [GUARD],
                               "hook_log": True, "rewrite_actions": {}},
    "ask": {"folder": "recorded-d23-t9-ask", "servers": [GUARD], "hook_log": True, "rewrite_actions": {}},
    "allow": {"folder": "recorded-d23-t9-exit1-default", "servers": [GUARD], "hook_log": True,
              "rewrite_actions": {test_permissions.ACTION_EXIT1: test_permissions.ACTION_ALLOW}},
    "policy_denied": {"folder": "recorded-d23-t10-deny-rule", "servers": [GUARD], "hook_log": False,
                      "rewrite_actions": {}},
    "policy_allowed_only": {"folder": "recorded-d23-t10-deny-rule", "servers": [GUARD], "hook_log": False,
                            "rewrite_actions": {}},
}
POLICY_IDS = {"policy_denied": "denied", "policy_allowed_only": "allowed_only"}  # row -> POLICIES key


def permission_recording(*, case_id):
    """(stream text, {server: wire records}, hook log text or None) of a case."""
    row = PERMISSION_RECORDINGS[case_id]
    wires = {server: "wire-%s.jsonl" % server for server in row["servers"]}
    hook_names = [test_permissions.HOOK_LOG_NAME] if row["hook_log"] else []
    files = read_recording(folder=row["folder"], names=[STREAM_FILE] + list(wires.values()) + hook_names)
    hooks = None
    if row["hook_log"]:
        entries = wire_records(text=files[test_permissions.HOOK_LOG_NAME])
        for entry in entries:
            if entry["action"] in row["rewrite_actions"]:
                entry["action"] = row["rewrite_actions"][entry["action"]]
        hooks = "".join(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n" for entry in entries)
    return files[STREAM_FILE], {server: wire_records(text=files[wires[server]]) for server in wires}, hooks


def permission_call(*, sandbox, request, case_id, text, hooks):
    """The real test body for the case (no hook log file when hooks is None)."""
    if hooks is not None:
        with open(os.path.join(sandbox.artifact_dir, test_permissions.HOOK_LOG_NAME), "w",
                  encoding="utf-8") as handle:
            handle.write(hooks)
    if case_id == "deny_rule":
        return functools.partial(test_permissions.run_deny_rule, sandbox=sandbox, ledger=None, request=request,
                                 reason=OFFLINE_REASON)
    if case_id == "no_rule":
        return functools.partial(test_permissions.run_no_rule, sandbox=sandbox, ledger=None, request=request,
                                 service=OFFLINE_SERVICE)
    if case_id in POLICY_IDS:
        return functools.partial(test_permissions.run_server_policy, sandbox=sandbox, ledger=None, request=request,
                                 policy_id=POLICY_IDS[case_id])
    reason_asserted = test_permissions.T9_CASES[case_id]["hook_action"] in (test_permissions.ACTION_DENY,
                                                                          test_permissions.ACTION_ASK)
    return functools.partial(test_permissions.run_hook_guard, sandbox=sandbox, ledger=None, request=request,
                             case_id=case_id, reason=OFFLINE_REASON,
                             deny_reason=DENY_REASON.search(text).group(0) if reason_asserted
                             else OFFLINE_DENY_REASON)


def init_lists_tool(*, text, name):
    """The stream with `name` added to the system/init tools."""
    events = [json.loads(line) for line in text.splitlines()]
    inits = [e for e in events if e["type"] == "system" and "subtype" in e and e["subtype"] == "init"]
    expect_equal(what="system/init events in the recording", expected=1, actual=len(inits))
    inits[0]["tools"].append(name)
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n"


def hook_line_for(*, text, server, tool, action):
    """One guard-hook log line for the first mcp__<server>__<tool> tool_use."""
    events = [json.loads(line) for line in text.splitlines()]
    index, use = tool_use_of(events=events, name=mcp_tool_name(server=server, tool=tool))
    entry = {"action": action, "epoch": event_epoch(event=events[index]),
             "input": {"hook_event_name": test_permissions.PRE_TOOL_USE, "tool_input": use["input"],
                       "tool_name": use["name"], "tool_use_id": use["id"]}}
    return json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n"


def without_calls_named(*, records, tool):
    """Wire records without the tools/call for `tool`, its reply and its `tool_executed`."""
    call_ids = {(r["pid"], r["msg"]["id"]) for r in records if r["event"] == "recv"
                and message_method(message=r["msg"]) == TOOLS_CALL and r["msg"]["params"]["name"] == tool}
    return [r for r in records
            if not (r["event"] == "recv" and "id" in r["msg"] and (r["pid"], r["msg"]["id"]) in call_ids)
            and not (r["event"] in CALL_EVENTS and (r["pid"], r["rpc_id"]) in call_ids)
            and not (r["event"] == "sent" and "id" in r["msg"] and "method" not in r["msg"]
                     and (r["pid"], r["msg"]["id"]) in call_ids)]


def mutate_permission(*, mutation, text, records, hooks):
    """(stream text, wire records, hook log) after one mutation."""
    delete_name = mcp_tool_name(server=GUARD, tool=test_permissions.DELETE)
    if mutation == "init_lists_delete_all":
        return init_lists_tool(text=text, name=delete_name), records, hooks
    if mutation == "hook_ran_for_delete_all":
        return text, records, hook_line_for(text=text, server=GUARD, tool=test_permissions.DELETE,
                                            action=test_permissions.ACTION_DENY)
    if mutation == "ops_got_rotate_logs":
        return text, dict(records, **{OPS: with_tools_call(text=text, records=records[OPS], server=OPS,
                                                           tool=test_permissions.ROTATE)}), hooks
    if mutation == "reason_dropped":
        events = [json.loads(line) for line in text.splitlines()]
        _index, use = tool_use_of(events=events, name=delete_name)
        return rewrite_tool_result(text=text, tool_use_id=use["id"], epoch=None, content=REASON_DROPPED_TEXT,
                                   is_error=True), records, hooks
    if mutation == "event_dropped":
        events = [json.loads(line) for line in text.splitlines()]
        return "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events if not (
            e["type"] == "system" and "subtype" in e and e["subtype"] == test_permissions.PERMISSION_DENIED_SUBTYPE
        )), records, hooks
    if mutation == "ops_started":
        started = [r for r in records[GUARD] if r["event"] == "started"][0]
        return text, dict(records, **{OPS: [dict(started, source=OPS, pid=started["pid"] + 1)]}), hooks
    if mutation == "delete_all_call_dropped":
        return text, dict(records, **{GUARD: without_calls_named(records=records[GUARD],
                                                                 tool=test_permissions.DELETE)}), hooks
    expect_equal(what="mutation name", expected="guard_got_delete_all", actual=mutation)
    return text, dict(records, **{GUARD: with_tools_call(text=text, records=records[GUARD], server=GUARD,
                                                         tool=test_permissions.DELETE)}), hooks


@pytest.mark.parametrize("case_id", sorted(PERMISSION_RECORDINGS))
def test_permission_recorded_run_passes(free_sandbox, request, monkeypatch, case_id):
    """Control: each recorded permission case passes its real test body."""
    text, records, hooks = permission_recording(case_id=case_id)
    stub_flow(monkeypatch=monkeypatch, attempts=[replay(stream_text=text, records_by_server=records)])
    step(text="replay %s as recorded (case %s)" % (PERMISSION_RECORDINGS[case_id]["folder"], case_id))
    exc = raised_by(call=permission_call(sandbox=free_sandbox, request=request, case_id=case_id, text=text,
                                         hooks=hooks))
    expect_equal(what="exception the recorded %s run raised" % case_id, expected=None,
                 actual=None if exc is None else repr(exc))


OPS_RECORDS_CHECK = "records in wire-guard__ops.jsonl, every attempt"
# id: (case, mutation, the start of the failing check's message)
PERMISSION_MUTATIONS = {
    "deny_rule-init_lists_delete_all": ("deny_rule", "init_lists_delete_all",
                                        "mcp__guard__delete_all in system/init tools under"),
    "deny_rule-guard_got_delete_all": ("deny_rule", "guard_got_delete_all",
                                       "delete_all tools/call that reached the server despite the deny rule"),
    "no_rule-ops_got_rotate_logs": ("no_rule", "ops_got_rotate_logs",
                                    "tools/call that reached guard__ops with no allow rule"),
    "matcher_without_wildcard-hook_ran_for_delete_all": ("matcher_without_wildcard", "hook_ran_for_delete_all",
                                                         "tools the hook ran for with matcher 'mcp__guard'"),
    "exit1_default-delete_all_call_dropped": ("exit1_default", "delete_all_call_dropped",
                                              "tools/call for 'delete_all' that reached server guard"),
    "exit1_on_failure_block-guard_got_delete_all": ("exit1_on_failure_block", "guard_got_delete_all",
                                                    "delete_all reached the server 1 time(s) although the hook"),
    "ask-guard_got_delete_all": ("ask", "guard_got_delete_all",
                                 "delete_all reached the server 1 time(s) although the hook"),
    "ask-reason_dropped": ("ask", "reason_dropped", "the hook's permissionDecisionReason in the denied tool_result"),
    "ask-event_dropped": ("ask", "event_dropped", "`permission_denied` system events (tool_name, tool_use_id), 1 per"),
    "allow-delete_all_call_dropped": ("allow", "delete_all_call_dropped",
                                      "tools/call for 'delete_all' that reached server guard"),
    "policy_denied-ops_started": ("policy_denied", "ops_started", OPS_RECORDS_CHECK),
    "policy_allowed_only-ops_started": ("policy_allowed_only", "ops_started", OPS_RECORDS_CHECK),
}


@pytest.mark.parametrize("mutation_id", list(PERMISSION_MUTATIONS))
def test_permission_mutation_fails(free_sandbox, request, monkeypatch, mutation_id):
    """Break: each mutation of a recorded permission case FAILS its real test
    body with a plain AssertionError (not a skip, not the xfail exception)."""
    case_id, mutation, match = PERMISSION_MUTATIONS[mutation_id]
    text, records, hooks = permission_recording(case_id=case_id)
    text, records, hooks = mutate_permission(mutation=mutation, text=text, records=records, hooks=hooks)
    stub_flow(monkeypatch=monkeypatch, attempts=[replay(stream_text=text, records_by_server=records)])
    step(text="replay %s (case %s) with mutation %s" % (PERMISSION_RECORDINGS[case_id]["folder"], case_id, mutation))
    assert_plain_failure(exc=raised_by(call=permission_call(sandbox=free_sandbox, request=request, case_id=case_id,
                                                            text=text, hooks=hooks)), match=match)


# fakes/guard_hook.py on its own (fakes/ cannot be imported, so its values are restated here).
HOOK_EXIT_OK = 0  # fakes/guard_hook.py: sys.exit(0) after pass, deny, ask or allow
HOOK_EXIT_FAIL = 1  # fakes/guard_hook.py FAIL_EXIT_CODE (mode fail)
DECISION_DENY = "deny"  # hooks.md:1933: the permissionDecision values
DECISION_ASK = "ask"
DECISION_ALLOW = "allow"
HOOK_TARGET = mcp_tool_name(server=GUARD, tool=test_permissions.DELETE)
HOOK_OTHER = mcp_tool_name(server=GUARD, tool=test_permissions.LIST)
# case id: (mode, tool name, exit code, permissionDecision on stdout or None for no stdout, logged action)
GUARD_HOOK_CASES = {
    "deny": (test_permissions.HOOK_MODE_DENY, HOOK_TARGET, HOOK_EXIT_OK, DECISION_DENY, test_permissions.ACTION_DENY),
    "ask": (test_permissions.HOOK_MODE_ASK, HOOK_TARGET, HOOK_EXIT_OK, DECISION_ASK, test_permissions.ACTION_ASK),
    "allow": (test_permissions.HOOK_MODE_ALLOW, HOOK_TARGET, HOOK_EXIT_OK, DECISION_ALLOW,
              test_permissions.ACTION_ALLOW),
    "fail": (test_permissions.HOOK_MODE_FAIL, HOOK_TARGET, HOOK_EXIT_FAIL, None, test_permissions.ACTION_EXIT1),
    "ask_other_tool": (test_permissions.HOOK_MODE_ASK, HOOK_OTHER, HOOK_EXIT_OK, None, test_permissions.ACTION_PASS),
}


@pytest.mark.parametrize("case_id", list(GUARD_HOOK_CASES))
def test_guard_hook_answers_per_mode(free_sandbox, case_id):
    """The hook prints the permissionDecision of its mode (hooks.md:1933-1934)
    for the target tool only, exits as documented, and logs its action."""
    mode, tool, exit_code, decision, action = GUARD_HOOK_CASES[case_id]
    expected = None if decision is None else {"hookSpecificOutput": {
        "hookEventName": test_permissions.PRE_TOOL_USE, "permissionDecision": decision,
        "permissionDecisionReason": OFFLINE_DENY_REASON}}
    log_path = os.path.join(free_sandbox.artifact_dir, test_permissions.HOOK_LOG_NAME)
    hook_input = {"hook_event_name": test_permissions.PRE_TOOL_USE, "tool_name": tool, "tool_input": {},
                  "tool_use_id": "toolu_offline"}
    step(text="run %s with mode %s for a %s hook input" % (GUARD_HOOK_SCRIPT, mode, tool))
    proc = subprocess.run([PYTHON, GUARD_HOOK_SCRIPT, log_path, mode, HOOK_TARGET, OFFLINE_DENY_REASON],
                          input=json.dumps(hook_input), capture_output=True, text=True, timeout=GUARD_HOOK_TIMEOUT_S,
                          check=False)
    got(what="guard hook (exit code, stdout, stderr)", value=(proc.returncode, proc.stdout, proc.stderr))
    expect_equal(what="exit code of the guard hook", expected=exit_code, actual=proc.returncode)
    expect_equal(what="stdout of the guard hook (JSON)", expected=expected,
                 actual=json.loads(proc.stdout) if proc.stdout else None)
    expect_equal(what="actions in the guard hook log", expected=[action],
                 actual=[entry["action"] for entry in read_hook_log(path=log_path)])
