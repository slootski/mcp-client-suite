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
"""

import json
import os

import pytest

import harness.model_flow as model_flow
from harness.check import expect_equal, expect_in, expect_true, got, step
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
from harness.model_checks import TOOLS_CALL, key_rejected
from harness.model_run import parse_stream
from harness.wire import message_method
from test_harness_offline import (
    ATTEMPT0_SHIFT_S,
    StubRunPrint,
    recorded_attempt,
    recorded_stream_text,
    recorded_wire,
    replay,
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
REJECTED_STATUS = 401
API_RETRY_EVENT = {"type": "system", "subtype": "api_retry", "attempt": 1, "max_retries": 10, "retry_delay_ms": 500,
                   "error_status": REJECTED_STATUS, "error": API_RETRY_AUTH_FAILED}


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
def rejected_stream(*, text, drop_tool_use, rejection):
    """The recorded stream with the API's rejection written in. rejection
    "result": the result event gets api_error_status 401 and is_error true;
    "api_retry": an api_retry event (authentication_failed) after init.
    drop_tool_use: every tool_use and tool_result block removed too."""
    lines = []
    for line in text.splitlines():
        event = json.loads(line)
        if event["type"] == "result" and rejection == "result":
            event["api_error_status"] = REJECTED_STATUS
            event["is_error"] = True
        if drop_tool_use and event["type"] in ("assistant", "user") and isinstance(event["message"]["content"], list):
            event["message"]["content"] = [block for block in event["message"]["content"]
                                           if block["type"] not in ("tool_use", "tool_result")]
            if not event["message"]["content"]:
                continue
        lines.append(json.dumps(event, ensure_ascii=False))
        if event["type"] == "system" and "subtype" in event and event["subtype"] == "init" and rejection == "api_retry":
            lines.append(json.dumps(API_RETRY_EVENT))
    return "\n".join(lines) + "\n"


def handshake_only(*, records):
    """Wire records before the first tools/call: the client connected, the
    model never turned (what a rejected key gives)."""
    calls = [index for index, record in enumerate(records)
             if record["event"] == "recv" and message_method(message=record["msg"]) == TOOLS_CALL]
    return records[:calls[0]] if calls else records


@pytest.mark.parametrize("rejection, drop_tool_use", [
    ("result", False), ("result", True), ("api_retry", False),
], ids=["result_401", "result_401_no_tool_use", "api_retry_authentication_failed"])
def test_key_rejected_stops_the_run_with_15(free_sandbox, request, monkeypatch, rejection, drop_tool_use):
    text = rejected_stream(text=recorded_stream_text(), drop_tool_use=drop_tool_use, rejection=rejection)
    got(what="key_rejected on the mutated stream", value=key_rejected(stream=parse_stream(text=text)))
    records = {server: recorded_wire(server=server) for server in CALC_SERVERS}
    if drop_tool_use:
        records = {server: handshake_only(records=records[server]) for server in records}
    attempt0 = replay(stream_text=text, records_by_server={
        server: shifted(records=records[server], by_s=-ATTEMPT0_SHIFT_S) for server in records})
    stub = StubRunPrint(attempts=[attempt0, recorded_attempt()])
    monkeypatch.setattr(model_flow, "run_print", stub)
    step(text="replay: attempt0 = the recorded D15/T1 run, key rejected in its %s event (tool_use %s); attempt1 = "
              "the recorded run" % (rejection, "removed" if drop_tool_use else "kept"))
    with pytest.raises(pytest.exit.Exception) as caught:
        run_stubbed(sandbox=free_sandbox, request=request, stub=stub)
    got(what="pytest.exit message", value=str(caught.value))
    expect_equal(what="pytest.exit returncode", expected=API_KEY_REJECTED_EXIT_CODE, actual=caught.value.returncode)
    expect_true(what="pytest.exit message", expected="starts with 'API key rejected:'", actual=str(caught.value),
                holds=str(caught.value).startswith("API key rejected:"))
    expect_equal(what="attempts the harness started (no retry)", expected=["attempt0"], actual=stub.labels)


def test_key_accepted_recording_does_not_stop(free_sandbox, request, monkeypatch):
    """Control: the recording as it is (api_error_status null) runs to the end."""
    result = parse_stream(text=recorded_stream_text()).result
    expect_equal(what="recorded result event: api_error_status", expected=(True, None),
                 actual=("api_error_status" in result, result["api_error_status"]))
    stub = StubRunPrint(attempts=[recorded_attempt()])
    monkeypatch.setattr(model_flow, "run_print", stub)
    step(text="replay: attempt0 = the recorded D15/T1 run, unchanged")
    triggered = run_stubbed(sandbox=free_sandbox, request=request, stub=stub)
    expect_equal(what="attempts the harness started", expected=["attempt0"], actual=stub.labels)
    expect_equal(what="inconclusive reason of the flow", expected=None, actual=triggered.inconclusive)
