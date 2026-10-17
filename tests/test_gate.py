"""Self-test of the run-level gate (free: no model call, no real key).

Exits 13 and 14 (tests/conftest.py): an inner pytest session, in a
subprocess (pytester), loads the real tests/conftest.py and runs three
tiny items: a free pass, a model item that skips as inconclusive, and a
model strict xfail. Its cost, rates, outcomes and artifact files go to
pytester.path, never to the outer run's, and it never gets the real key.

Exit 15 (harness/model_flow.py, model_checks.key_rejected): the recorded
D15/T1 attempt (tests/test_harness_offline.py) is replayed through
run_until_triggered with the API's rejection written into its stream. The
run must stop with exit 15 after attempt0, with no retry.

Clock step and skip reason: the recorded D19/T1 run, replayed through the
real test body with run 88362's clocks, is inconclusive and retried, not
failed; two inconclusive attempts skip with the mark exit 13 counts; a
timed-out command records both clocks.
"""

import dataclasses
import json
import os
import sys
import time
import types

import pytest

import harness.claude_cli as claude_cli
import harness.model_flow as model_flow
import test_crash
import test_idle_timeout
from conftest import INCONCLUSIVE_MARK, SKIPPED_PREFIX, is_inconclusive
from harness.check import expect_equal, expect_in, expect_true, got, step
from harness.claude_cli import OUTPUT_PREVIEW_HIDDEN, CommandLog, run_claude
from harness.constants import (
    API_KEY_ENV,
    API_KEY_REJECTED_EXIT_CODE,
    API_RETRY_AUTH_FAILED,
    ARTIFACT_DIR_ENV,
    COST_FILE_ENV,
    INCONCLUSIVE_EXIT_CODE,
    MODEL_TESTS_NEED_KEY_EXIT_CODE,
    OUTCOMES_FILE_ENV,
    RATES_FILE_ENV,
    REQUIRE_KEY_ENV,
)
from harness.known_defects import DocumentedBehaviorMismatch
from harness.model_checks import TOOLS_CALL, key_rejected, mcp_tool_name
from harness.model_run import parse_stream
from harness.redact import SecretRegistry
from harness.wire import message_method
from test_harness_offline import (
    ATTEMPT0_SHIFT_S,
    CRASH_RECORDING,
    StubRunPrint,
    crash_result_dropped,
    idle_call,
    idle_recording,
    recorded_attempt,
    recorded_stream_text,
    recorded_wire,
    recording,
    replay,
    rewrite_tool_result,
    run_stubbed,
    shifted,
)
from test_right_tool_args import CALC_SERVERS

pytestmark = [pytest.mark.free]

SUITE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFTEST_PATH = os.path.join(SUITE_ROOT, "tests", "conftest.py")
DUMMY_KEY = "dummy-key-for-gate-self-test"  # never the real key; not a SECRET_SCAN_MARKERS prefix
NO_KEY = {}
WITH_DUMMY_KEY = {API_KEY_ENV: DUMMY_KEY}
INNER_RUN_TIMEOUT_S = 60
INNER_FILES = {COST_FILE_ENV: "cost.json", RATES_FILE_ENV: "s-rates.json", OUTCOMES_FILE_ENV: "outcomes.json",
               ARTIFACT_DIR_ENV: "artifacts"}
INNER_FREE = "test_inner.py::test_free_passes"
INNER_INCONCLUSIVE = "test_inner.py::test_model_inconclusive"
INNER_XFAIL = "test_inner.py::test_model_xfails"
INNER_INI = """[pytest]
addopts = -p no:cacheprovider
markers =
    free: makes no model call
    model: calls the model
"""
INNER_TESTS = '''
import pytest
from harness.known_defects import DocumentedBehaviorMismatch

FORCED = "forced by the gate self-test"


@pytest.mark.free
def test_free_passes():
    pass


@pytest.mark.model
def test_model_inconclusive():
    pytest.skip("inconclusive: " + FORCED)


@pytest.mark.model
@pytest.mark.xfail(strict=True, raises=DocumentedBehaviorMismatch, reason=FORCED)
def test_model_xfails():
    raise DocumentedBehaviorMismatch(FORCED)
'''
REJECTED_RESULT = {"api_error_status": 401, "is_error": True}
RESULT_AS_RECORDED = {}
NO_RETRY_EVENTS = []


def api_retry(*, error, error_status):
    """A system/api_retry event (fields: headless.md:240-251)."""
    return {"type": "system", "subtype": "api_retry", "attempt": 1, "max_retries": 10, "retry_delay_ms": 500,
            "error_status": error_status, "error": error}

def inner_run(*, pytester, monkeypatch, env, args):
    """Run the inner session in a subprocess: (exit code, outcomes.json, stdout)."""
    for name in (API_KEY_ENV, REQUIRE_KEY_ENV):
        monkeypatch.delenv(name, raising=False)
    for name in env:
        monkeypatch.setenv(name, env[name])
    for name in INNER_FILES:
        monkeypatch.setenv(name, str(pytester.path / INNER_FILES[name]))
    os.makedirs(str(pytester.path / INNER_FILES[ARTIFACT_DIR_ENV]))
    monkeypatch.setenv("PYTHONPATH", SUITE_ROOT)
    with open(CONFTEST_PATH, encoding="utf-8") as handle:
        pytester.makeconftest(handle.read())
    pytester.makeini(INNER_INI)
    pytester.makepyfile(test_inner=INNER_TESTS)
    step(text="inner pytest %s, %s, %s unset" % (
        " ".join(args) if args else "(all items)", "%s=<dummy>" % API_KEY_ENV if env else "no key", REQUIRE_KEY_ENV))
    result = pytester.runpytest_subprocess(*args, timeout=INNER_RUN_TIMEOUT_S)
    got(what="inner run: exit code", value=int(result.ret))
    with open(str(pytester.path / INNER_FILES[OUTCOMES_FILE_ENV]), encoding="utf-8") as handle:
        outcomes = json.load(handle)
    got(what="inner run: outcomes.json counts", value=outcomes["counts"])
    return int(result.ret), outcomes, result.stdout.str()


def test_inconclusive_model_item_with_key_exits_13(pytester, monkeypatch):
    ret, outcomes, _ = inner_run(pytester=pytester, monkeypatch=monkeypatch, env=WITH_DUMMY_KEY, args=[])
    expect_equal(what="inner exit code (key set, one model item inconclusive)", expected=INCONCLUSIVE_EXIT_CODE,
                 actual=ret)
    expect_equal(what="outcomes.json inconclusive_model_items", expected=[INNER_INCONCLUSIVE],
                 actual=outcomes["inconclusive_model_items"])


def test_model_marker_without_key_exits_14(pytester, monkeypatch):
    ret, _, stdout = inner_run(pytester=pytester, monkeypatch=monkeypatch, env=NO_KEY, args=["-m", "model"])
    expect_equal(what="inner exit code (no key, -m model)", expected=MODEL_TESTS_NEED_KEY_EXIT_CODE, actual=ret)
    expect_in(what="inner run output", item="selects 2 model item(s)", container=stdout)


def test_only_model_items_selected_without_key_exits_14(pytester, monkeypatch):
    ret, outcomes, stdout = inner_run(pytester=pytester, monkeypatch=monkeypatch, env=NO_KEY,
                                      args=["-k", "model_inconclusive or model_xfails"])
    expect_equal(what="inner exit code (no key, -k selects only model items)", expected=MODEL_TESTS_NEED_KEY_EXIT_CODE,
                 actual=ret)
    expect_in(what="inner run output", item="all 2 selected item(s) are model items", container=stdout)
    expect_equal(what="items that reported an outcome (none ran)", expected=0, actual=sum(outcomes["counts"].values()))


def test_mixed_selection_without_key_skips_model_items(pytester, monkeypatch):
    ret, outcomes, _ = inner_run(pytester=pytester, monkeypatch=monkeypatch, env=NO_KEY, args=[])
    expect_equal(what="inner exit code (no key, free and model items selected)", expected=0, actual=ret)
    expect_equal(what="outcomes.json passed", expected=[INNER_FREE], actual=outcomes["groups"]["passed"])
    expect_equal(what="outcomes.json skipped_no_key", expected=sorted([INNER_INCONCLUSIVE, INNER_XFAIL]),
                 actual=sorted(outcomes["groups"]["skipped_no_key"]))


def test_xfail_counted_apart_from_skips(pytester, monkeypatch):
    ret, outcomes, _ = inner_run(pytester=pytester, monkeypatch=monkeypatch, env=WITH_DUMMY_KEY,
                                 args=["-k", "free_passes or model_xfails"])
    expect_equal(what="inner exit code (key set, a pass and a strict xfail)", expected=0, actual=ret)
    groups = outcomes["groups"]
    expect_equal(what="outcomes.json xfailed_known_defects", expected=[INNER_XFAIL],
                 actual=groups["xfailed_known_defects"])
    expect_equal(what="outcomes.json skip groups", expected={"skipped_inconclusive": [], "skipped_no_key": [],
                                                             "skipped_other": []},
                 actual={name: groups[name] for name in ("skipped_inconclusive", "skipped_no_key", "skipped_other")})


# ---------------------------------------------------------------- exit 15
def rejected_stream(*, text, drop_tool_use, result_fields, retry_events):
    """The recorded stream with result_fields merged into its result event
    and retry_events inserted after system/init; drop_tool_use: every
    tool_use and tool_result block removed too."""
    lines = []
    for line in text.splitlines():
        event = json.loads(line)
        if event["type"] == "result":
            event.update(result_fields)
        if drop_tool_use and event["type"] in ("assistant", "user") and isinstance(event["message"]["content"], list):
            event["message"]["content"] = [block for block in event["message"]["content"]
                                           if block["type"] not in ("tool_use", "tool_result")]
            if not event["message"]["content"]:
                continue
        lines.append(json.dumps(event, ensure_ascii=False))
        if event["type"] == "system" and "subtype" in event and event["subtype"] == "init":
            lines += [json.dumps(retry) for retry in retry_events]
    return "\n".join(lines) + "\n"


def handshake_only(*, records):
    """Wire records before the first tools/call: the client connected, the
    model never turned (what a rejected key gives)."""
    calls = [index for index, record in enumerate(records)
             if record["event"] == "recv" and message_method(message=record["msg"]) == TOOLS_CALL]
    return records[:calls[0]] if calls else records


def stub_flow(*, sandbox, request, monkeypatch, text, drop_tool_use):
    """Replay `text` as attempt0 (the recorded run is queued as attempt1)."""
    records = {server: recorded_wire(server=server) for server in CALC_SERVERS}
    if drop_tool_use:
        records = {server: handshake_only(records=records[server]) for server in records}
    attempt0 = replay(stream_text=text, records_by_server={
        server: shifted(records=records[server], by_s=-ATTEMPT0_SHIFT_S) for server in records})
    stub = StubRunPrint(attempts=[attempt0, recorded_attempt()])
    monkeypatch.setattr(model_flow, "run_print", stub)
    got(what="key_rejected on attempt0's stream", value=key_rejected(stream=parse_stream(text=text)))
    return stub


# Each case drives one branch of key_rejected only.
@pytest.mark.parametrize("result_fields, retry_events, drop_tool_use", [
    (REJECTED_RESULT, NO_RETRY_EVENTS, False),
    (REJECTED_RESULT, NO_RETRY_EVENTS, True),
    (RESULT_AS_RECORDED, [api_retry(error="unknown", error_status=403)], False),
    (RESULT_AS_RECORDED, [api_retry(error=API_RETRY_AUTH_FAILED, error_status=None)], False),
], ids=["result_401", "result_401_no_tool_use", "api_retry_error_status_403", "api_retry_authentication_failed"])
def test_key_rejected_stops_the_run_with_15(free_sandbox, request, monkeypatch, result_fields, retry_events,
                                            drop_tool_use):
    text = rejected_stream(text=recorded_stream_text(), drop_tool_use=drop_tool_use, result_fields=result_fields,
                           retry_events=retry_events)
    stub = stub_flow(sandbox=free_sandbox, request=request, monkeypatch=monkeypatch, text=text,
                     drop_tool_use=drop_tool_use)
    step(text="replay: attempt0 = the recorded D15/T1 run with result fields %s, api_retry events %s (tool_use %s); "
              "attempt1 = the recorded run" % (result_fields, retry_events, "removed" if drop_tool_use else "kept"))
    with pytest.raises(pytest.exit.Exception) as caught:
        run_stubbed(sandbox=free_sandbox, request=request, stub=stub)
    got(what="pytest.exit message", value=str(caught.value))
    expect_equal(what="pytest.exit returncode", expected=API_KEY_REJECTED_EXIT_CODE, actual=caught.value.returncode)
    expect_true(what="pytest.exit message", expected="starts with 'API key rejected:'", actual=str(caught.value),
                holds=str(caught.value).startswith("API key rejected:"))
    expect_equal(what="attempts the harness started (no retry)", expected=["attempt0"], actual=stub.labels)


# Controls: retries that are not a key rejection must not stop the run.
@pytest.mark.parametrize("retry_events", [
    NO_RETRY_EVENTS,
    [api_retry(error="rate_limit", error_status=429)],
    [api_retry(error="overloaded", error_status=529)],
    [api_retry(error="server_error", error_status=None)],
], ids=["as_recorded", "api_retry_429_rate_limit", "api_retry_529_overloaded", "api_retry_null_status"])
def test_key_accepted_recording_does_not_stop(free_sandbox, request, monkeypatch, retry_events):
    text = rejected_stream(text=recorded_stream_text(), drop_tool_use=False, result_fields=RESULT_AS_RECORDED,
                           retry_events=retry_events)
    result = parse_stream(text=text).result
    expect_equal(what="recorded result event: api_error_status", expected=(True, None),
                 actual=("api_error_status" in result, result["api_error_status"]))
    stub = stub_flow(sandbox=free_sandbox, request=request, monkeypatch=monkeypatch, text=text, drop_tool_use=False)
    step(text="replay: attempt0 = the recorded D15/T1 run with api_retry events %s" % retry_events)
    triggered = run_stubbed(sandbox=free_sandbox, request=request, stub=stub)
    expect_equal(what="attempts the harness started", expected=["attempt0"], actual=stub.labels)
    expect_equal(what="inconclusive reason of the flow", expected=None, actual=triggered.inconclusive)


# ---------------------------------------------------------------- clock step, skip reason (exit 13)
# Run 88362 (artifacts/20261017T140840Z-88362, test_idle_timeout_aborts_hung_call[0]): the host paused; the
# fake's log spans 252.7 s of wall clock and 33.2 s of monotonic clock, and the give-up came 249.535 s (wall)
# after the call, so the hard window (< 50 s) failed and the run exited 1.
PAUSED_CLOCKS = (252.7, 33.2)  # (wall span, monotonic span) of the attempt, in s
PAUSED_GIVE_UP_S = 249.535
STEP_BACK_S = 30.0  # a backward wall-clock step: the monotonic span is this much longer than the wall one
IDLE_SERVER = test_idle_timeout.SERVER
IDLE_TOOL = mcp_tool_name(server=IDLE_SERVER, tool=test_idle_timeout.TOOL)
GATE_STATUS = "failed"
TIMEOUT_S = 0.5  # run_claude's limit for a child that sleeps CHILD_SLEEP_S
CHILD_SLEEP_S = 30
WALL_START_EPOCH = 1792244840.0
WALL_STEP_S = 200.0  # the wall clock moves this far during the timed-out command


class ClockedStub(StubRunPrint):
    """StubRunPrint whose attempt i reports clocks[i] = (wall span, monotonic
    span) in its CliResult, as run_claude measures them."""

    def __init__(self, *, attempts, clocks):
        super().__init__(attempts=attempts)
        self.clocks = list(clocks)

    def __call__(self, **kwargs):
        run = super().__call__(**kwargs)
        wall_s, mono_s = self.clocks[len(self.labels) - 1]
        return dataclasses.replace(run, cli=dataclasses.replace(run.cli, end_epoch=run.cli.start_epoch + wall_s,
                                                                duration_s=mono_s))


def honest_clocks(*, attempt):
    """Wall span = monotonic span = the replay's window."""
    span = attempt["end_epoch"] - attempt["start_epoch"]
    return span, span


def paused_clocks(*, attempt):
    return PAUSED_CLOCKS


def stepped_back_clocks(*, attempt):
    span = attempt["end_epoch"] - attempt["start_epoch"]
    return span, span + STEP_BACK_S


def idle_attempts(*, text, records, clocks_of):
    """ClockedStub with attempt0 (wire records moved ATTEMPT0_SHIFT_S earlier,
    so the two windows do not overlap) and attempt1 of one D19/T1 replay;
    clocks_of: honest_clocks or paused_clocks."""
    early = shifted(records=records, by_s=-ATTEMPT0_SHIFT_S)
    attempts = [replay(stream_text=text, records_by_server={IDLE_SERVER: wire}) for wire in (early, records)]
    return ClockedStub(attempts=attempts, clocks=[clocks_of(attempt=attempt) for attempt in attempts])


def with_server_status(*, text, server, status):
    """The stream with `server`'s status in system/init set to `status`."""
    events = [json.loads(line) for line in text.splitlines()]
    for event in events:
        if event["type"] == "system" and "subtype" in event and event["subtype"] == "init":
            for entry in event["mcp_servers"]:
                if entry["name"] == server:
                    entry["status"] = status
    return "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n"


def test_host_clock_jump_is_inconclusive_and_retried(free_sandbox, request, monkeypatch):
    """attempt0 = run 88362's shape: its clocks and its give-up 249.535 s
    after the call (a hard-window failure when judged); attempt1 = the
    recorded run on honest clocks. attempt0 must be inconclusive and
    retried, and attempt1 end at the documented xfail as usual."""
    text, records, call = idle_recording()
    use_id = call["msg"]["params"]["_meta"]["claudecode/toolUseId"]
    give_up = call["epoch"] - ATTEMPT0_SHIFT_S + PAUSED_GIVE_UP_S  # attempt0's wire records move ATTEMPT0_SHIFT_S
    paused = replay(stream_text=rewrite_tool_result(text=text, tool_use_id=use_id, epoch=give_up, content=None,
                                                    is_error=True),
                    records_by_server={IDLE_SERVER: shifted(records=records, by_s=-ATTEMPT0_SHIFT_S)})
    recorded = replay(stream_text=text, records_by_server={IDLE_SERVER: records})
    stub = ClockedStub(attempts=[paused, recorded], clocks=[PAUSED_CLOCKS, honest_clocks(attempt=recorded)])
    monkeypatch.setattr(model_flow, "run_print", stub)
    step(text="replay: attempt0 = the recorded D19/T1 run with run 88362's clocks (wall %.1f s, monotonic %.1f s) "
              "and give-up %.3f s after the call; attempt1 = the recorded run, honest clocks" % (
                  PAUSED_CLOCKS + (PAUSED_GIVE_UP_S,)))
    with pytest.raises(DocumentedBehaviorMismatch):
        idle_call(sandbox=free_sandbox, request=request)()
    expect_equal(what="attempts the harness started", expected=["attempt0", "attempt1"], actual=stub.labels)
    attempts = free_sandbox.record.observation(key="model_runs")
    expect_equal(what="inconclusive reasons of (attempt0, attempt1)",
                 expected=(model_flow.CLOCK_STEP_REASON % PAUSED_CLOCKS, None),
                 actual=(attempts[0]["inconclusive"], attempts[1]["inconclusive"]))


# id: (the skip reason, given the last attempt's clocks; the clocks of each attempt)
SKIP_CASES = {
    "no_trigger": (lambda clocks: "inconclusive: the model made no tool_use named %s" % IDLE_TOOL, honest_clocks),
    "gate": (lambda clocks: "inconclusive: %s=%s" % (IDLE_SERVER, GATE_STATUS), honest_clocks),
    "clock_jump": (lambda clocks: model_flow.CLOCK_STEP_REASON % clocks, paused_clocks),
    "clock_step_back": (lambda clocks: model_flow.CLOCK_STEP_REASON % clocks, stepped_back_clocks),
}


@pytest.mark.parametrize("case_id", list(SKIP_CASES))
def test_two_inconclusive_attempts_skip_with_the_exit_13_mark(free_sandbox, request, monkeypatch, case_id):
    """Both attempts inconclusive (no trigger tool_use, the gate, or the
    clock): the real D19/T1 test body skips, and conftest counts the skip
    as inconclusive (INCONCLUSIVE_MARK), which is what makes a keyed run
    exit 13."""
    reason_of, clocks_of = SKIP_CASES[case_id]
    text, records, _call = idle_recording()
    if case_id == "no_trigger":
        text = rejected_stream(text=text, drop_tool_use=True, result_fields=RESULT_AS_RECORDED,
                               retry_events=NO_RETRY_EVENTS)
        records = handshake_only(records=records)
    if case_id == "gate":
        text = with_server_status(text=text, server=IDLE_SERVER, status=GATE_STATUS)
    stub = idle_attempts(text=text, records=records, clocks_of=clocks_of)
    monkeypatch.setattr(model_flow, "run_print", stub)
    step(text="replay: the recorded D19/T1 run twice, %s" % case_id)
    with pytest.raises(pytest.skip.Exception) as caught:
        idle_call(sandbox=free_sandbox, request=request)()
    message = str(caught.value)
    got(what="skip reason", value=message)
    expect_equal(what="attempts the harness started", expected=["attempt0", "attempt1"], actual=stub.labels)
    expect_equal(what="the skip reason", expected="%s (after 2 attempt(s))" % reason_of(clocks=stub.clocks[-1]),
                 actual=message)
    expect_in(what="the skip reason (tests/conftest.py INCONCLUSIVE_MARK)", item=INCONCLUSIVE_MARK, container=message)
    expect_true(what="conftest.is_inconclusive of the item's outcome", expected="True",
                actual=is_inconclusive(outcome="%s: %s" % (SKIPPED_PREFIX, message)),
                holds=is_inconclusive(outcome="%s: %s" % (SKIPPED_PREFIX, message)))


def test_timed_out_command_records_both_clocks(tmp_path, monkeypatch):
    """run_claude's timeout branch: commands.jsonl holds the monotonic and
    the wall-clock time, so a host pause during a hung run can be told apart
    from a client hang. The wall clock is stepped WALL_STEP_S on purpose."""
    readings = iter([WALL_START_EPOCH, WALL_START_EPOCH + WALL_STEP_S])
    stepped = types.SimpleNamespace(time=lambda: next(readings), monotonic=time.monotonic)
    monkeypatch.setattr(claude_cli, "time", stepped)
    monkeypatch.setattr(claude_cli, "CLAUDE_BIN", sys.executable)
    path = str(tmp_path / "commands.jsonl")
    step(text="run_claude: a child that sleeps %d s, limit %.1f s, wall clock stepped %.0f s" % (
        CHILD_SLEEP_S, TIMEOUT_S, WALL_STEP_S))
    with pytest.raises(AssertionError, match="finished within the limit"):
        run_claude(args=["-c", "import time; time.sleep(%d)" % CHILD_SLEEP_S], env={}, cwd=str(tmp_path),
                   timeout_s=TIMEOUT_S, command_log=CommandLog(path=path, registry=SecretRegistry()),
                   show_output_preview=OUTPUT_PREVIEW_HIDDEN)
    with open(path, encoding="utf-8") as handle:
        record = json.loads(handle.readlines()[-1])
    got(what="the timeout record's clocks", value={key: record[key] for key in record if key.endswith("_s")})
    expect_equal(what="(timed_out, wall_s) of the timeout record", expected=(True, WALL_STEP_S),
                 actual=(record["timed_out"], record["wall_s"]))
    expect_true(what="mono_s of the timeout record", expected="in [%.1f, %.1f) s" % (TIMEOUT_S, CHILD_SLEEP_S),
                actual=record["mono_s"], holds=TIMEOUT_S <= record["mono_s"] < CHILD_SLEEP_S)


def test_clock_jump_does_not_hide_a_crash_d_failure(free_sandbox, request, monkeypatch):
    """QA probe: attempt0 = the recorded D20/T1 run with no tool_result for
    the crashed call (crash_result_dropped) and run 88362's clocks; attempt1
    = the recorded run. The crashed-call D facts are checked on every
    attempt, clock jump or not, so attempt0 fails with a plain AssertionError
    and attempt1 never starts."""
    text, records, hooks = recording(folder=CRASH_RECORDING, server=test_crash.SERVER)
    dropped_text, dropped_records = crash_result_dropped(text=text, records=records)
    attempt0 = replay(stream_text=dropped_text, records_by_server={
        test_crash.SERVER: shifted(records=dropped_records, by_s=-ATTEMPT0_SHIFT_S)})
    attempt1 = replay(stream_text=text, records_by_server={test_crash.SERVER: records})
    stub = ClockedStub(attempts=[attempt0, attempt1], clocks=[PAUSED_CLOCKS, honest_clocks(attempt=attempt1)])
    monkeypatch.setattr(model_flow, "run_print", stub)
    with open(os.path.join(free_sandbox.artifact_dir, test_crash.HOOK_LOG_NAME), "w", encoding="utf-8") as handle:
        handle.write(hooks)
    step(text="replay: attempt0 = %s with no tool_result for the crashed call and run 88362's clocks (wall %.1f s, "
              "monotonic %.1f s); attempt1 = the recorded run" % ((CRASH_RECORDING,) + PAUSED_CLOCKS))
    with pytest.raises(AssertionError, match="tool_result blocks for the crashed tool_use") as caught:
        test_crash.crash_run(sandbox=free_sandbox, ledger=None, request=request, run_index=0, signatures={})
    expect_equal(what="the failure hid under the xfail (DocumentedBehaviorMismatch)", expected=False,
                 actual=isinstance(caught.value, DocumentedBehaviorMismatch))
    expect_equal(what="attempts the harness started (no retry after the D failure)", expected=["attempt0"],
                 actual=stub.labels)
