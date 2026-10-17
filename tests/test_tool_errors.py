"""D16/T1 (tool execution error, isError: true) and D16/T2 (protocol error,
a JSON-RPC error object), through the repeat harness of doc 22.

Model tier: needs ANTHROPIC_API_KEY, costs tokens (skipped without a key).
Each repeat is its own pytest item with a fresh sandbox and a fresh token;
the `..._s_rate` item after the repeats judges the S pass rate.
docs/flake-policy.md lists every fact below with its class.

Servers (stdio fake, legacy era, tool search off):
  T1 `booking`, toolset tool_error: `validate_booking(date)` always answers
     a normal result with isError: true and the fresh token in its text;
     `echo(text)` works.
  T2 `orders`, toolset protocol_error: `lookup_order(order_id)` is listed in
     tools/list, but its tools/call is answered with a JSON-RPC error, code
     -32602, the fresh token in error.message (doc 16 test 2: a tool the
     server lists and then refuses); `echo(text)` works.
The prompt asks for the failing tool once, then, after its result, for
`echo` once (a second, different tool), then a short reply.
Hooks: `--settings '<inline JSON>'` registers fakes/hook_logger.py for
PostToolUse and PostToolUseFailure (no matcher), logging each hook input.

  D  gate (server connected, else inconclusive), legacy era, no ToolSearch,
     both tools in system/init tools.
  D  the failing tool (harness/error_checks.py d_error_result): one
     tools/call per tool_use with arguments == input, the fake's reply is
     the expected kind, and the tool_use has exactly one tool_result with
     is_error true holding the token. The exact content is recorded.
  D  PostToolUseFailure fired exactly once per failing tool_use (same
     tool_use_id and tool_name), never for echo (hooks.md:2251).
  D  the server stays connected and a next call works: echo's tools/call
     reached the same fake process (one spawn in the run), and its
     tool_result is not an error and equals the fake's sent text
     (d_passthrough).
  D  the run ends with a `result` event, the last line.
  S  rated: the failing tool called exactly once; echo called exactly once,
     after the failing tool's tool_result.
  S  recorded only: the final answer quotes the token; result subtype.
"""

import json
import os
import secrets

import pytest

from harness.constants import (
    HOOK_POST_TOOL_USE,
    HOOK_POST_TOOL_USE_FAILURE,
    INCONCLUSIVE_RETRIES,
    INIT_REPLY_IMMEDIATE_MS,
    MAX_BUDGET_USD_PER_RUN,
    MAX_TURNS,
    MODEL_CLI_TIMEOUT_S,
    MODEL_ID,
    MODEL_REJECTED_EXIT_CODE,
    MODEL_TEST_TIMEOUT_S,
    NEGOTIATION_LEGACY,
    RATES_FILE_ENV,
    REPEATS,
    S_RATE_MIN_PASSES,
    TOOL_SEARCH_ENV,
    TOOL_SEARCH_OFF,
    TOOLSET_PROTOCOL_ERROR,
    TOOLSET_TOOL_ERROR,
    FAKE_MODE_NORMAL,
)
from harness.check import checks_logged_once, expect_equal, expect_true, got, record, step
from harness.error_checks import (
    REPLY_IS_ERROR_RESULT,
    REPLY_JSONRPC_ERROR,
    d_error_result,
    hook_failures_for,
    spawns,
)
from harness.fakes_ctl import STDIO_FAKE_SCRIPT
from harness.hooks import check_hook_log, hook_events, hook_settings_args, read_hook_log
from harness.mcp_setup import PYTHON, stdio_fake_env
from harness.model_checks import (
    assert_era,
    assert_tool_search_tool,
    assert_tools_advertised,
    d_passthrough,
    mcp_tool_name,
)
from harness.model_flow import run_until_triggered
from harness.model_run import allowed_tools_for, stdio_server_entry
from harness.repeat import evaluate_s_rate, per_repeat_outcomes, record_s_sample, start_repeat

pytestmark = [pytest.mark.model, pytest.mark.timeout(MODEL_TEST_TIMEOUT_S)]

ECHO = "echo"
TOKEN_PREFIX = "errtok-"
TOKEN_HEX_BYTES = 8
ECHO_TEXT_PREFIX = "after-error-"
ECHO_TEXT_HEX_BYTES = 4
HOOK_LOG_NAME = "hooks.jsonl"
HOOK_EVENTS = (HOOK_POST_TOOL_USE, HOOK_POST_TOOL_USE_FAILURE)
SUCCESS = "success"

# The two cases: server, toolset, failing tool, its arguments, the fake's reply kind.
CASES = {
    "T1": {"server": "booking", "toolset": TOOLSET_TOOL_ERROR, "tool": "validate_booking",
           "arguments": {"date": "2020-01-01"}, "reply": REPLY_IS_ERROR_RESULT,
           "group": "D16/T1 tool execution error (isError)"},
    "T2": {"server": "orders", "toolset": TOOLSET_PROTOCOL_ERROR, "tool": "lookup_order",
           "arguments": {"order_id": "ORD-1001"}, "reply": REPLY_JSONRPC_ERROR,
           "group": "D16/T2 protocol error (JSON-RPC error)"},
}
PROMPT = (
    "Step 1: call the tool {failing} exactly once, with arguments {arguments}. It will fail; that is expected. "
    "Do not call it again. Step 2: after you have seen its result, call the tool {echo} exactly once, with text "
    "set to exactly \"{echo_text}\". Do not call any other tool. Then reply in one short sentence that quotes "
    "the exact error message step 1 returned."
)
RATED = ("failing_tool_called_exactly_once", "echo_called_exactly_once", "echo_after_failing_result")


def token_value():
    return TOKEN_PREFIX + secrets.token_hex(TOKEN_HEX_BYTES)


def fake_entry(*, sandbox, server, toolset, token):
    return stdio_server_entry(
        fake_script=STDIO_FAKE_SCRIPT,
        python=PYTHON,
        fake_env=stdio_fake_env(
            name=server, mode=FAKE_MODE_NORMAL, log_path=sandbox.wire_log_path(name=server),
            init_reply_delay_ms=INIT_REPLY_IMMEDIATE_MS, canary=token, toolset=toolset,
        ),
    )


def s_facts(*, stream, failing_name, echo_name, token):
    failing = stream.tool_uses_named(name=failing_name)
    echoes = stream.tool_uses_named(name=echo_name)
    failing_result_indexes = [r.index for use in failing for r in stream.result_for(tool_use_id=use.id)]
    final = stream.result["result"] if stream.result is not None and "result" in stream.result else None
    rated = {
        "failing_tool_called_exactly_once": len(failing) == 1,
        "echo_called_exactly_once": len(echoes) == 1,
        "echo_after_failing_result": bool(echoes) and bool(failing_result_indexes)
        and min(use.index for use in echoes) > min(failing_result_indexes),
    }
    recorded = {
        "final_answer_has_token": isinstance(final, str) and token in final,
        "result_subtype_success": stream.result is not None and "subtype" in stream.result
        and stream.result["subtype"] == SUCCESS,
    }
    detail = {"tool_use_names": [use.name for use in stream.tool_uses], "final_text": final,
              "num_turns": stream.result["num_turns"] if stream.result is not None and "num_turns" in stream.result
              else None}
    return rated, recorded, detail


def check_d(*, sandbox, triggered, case, token, hook_log):
    """Every D fact of one D16 run (module docstring). Returns the view."""
    server = case["server"]
    stream = triggered.run.stream
    records = triggered.records[server]
    failing_name = mcp_tool_name(server=server, tool=case["tool"])
    echo_name = mcp_tool_name(server=server, tool=ECHO)
    era = assert_era(records=records, negotiation=NEGOTIATION_LEGACY)
    assert_tool_search_tool(stream=stream, expected=False)
    assert_tools_advertised(stream=stream, names=[failing_name, echo_name])

    error_view = d_error_result(stream=stream, records=records, server=server, tool=case["tool"], token=token,
                                expected_reply=case["reply"])
    sandbox.record.observe(key="error_result", value=error_view)

    entries = read_hook_log(path=hook_log)
    check_hook_log(entries=entries)
    echo_uses = stream.tool_uses_named(name=echo_name)
    hook_view = {
        "post_tool_use_failure": [e["input"] for e in hook_events(entries=entries, event_name=HOOK_POST_TOOL_USE_FAILURE)],
        "post_tool_use": [e["input"] for e in hook_events(entries=entries, event_name=HOOK_POST_TOOL_USE)],
    }
    sandbox.record.observe(key="hooks", value=hook_view)
    hook_view["failure_per_tool_use"] = hook_failures_for(
        entries=entries, server=server, failed_uses=stream.tool_uses_named(name=failing_name),
        succeeded_use_ids=[use.id for use in echo_uses])
    sandbox.record.observe(key="hooks", value=hook_view)

    # The server stays connected: the next call (echo) works on the same process.
    echo_view = d_passthrough(stream=stream, records=records, server=server, tool=ECHO)
    pids = spawns(records=records)
    expect_equal(what="fake processes started in the run (pids %s)" % pids, expected=1, actual=len(pids))
    call_pids = sorted({r["pid"] for r in records if r["event"] == "recv" and "method" in r["msg"]
                        and r["msg"]["method"] == "tools/call"})
    expect_equal(what="pids that got a tools/call vs the pids the run spawned", expected=pids, actual=call_pids)

    expect_true(what="final result event in the stream", expected="present", actual="present"
                if stream.result is not None else "absent", holds=stream.result is not None)
    result_index = stream.events.index(stream.result)
    expect_equal(what="stream line of the result event", expected=len(stream.events) - 1, actual=result_index)
    view = {"era_seen": era, "error_result": error_view, "echo": echo_view, "spawns": pids,
            "result": {k: stream.result[k] for k in ("subtype", "is_error", "num_turns") if k in stream.result}}
    sandbox.record.observe(key="d_view", value=view)
    return view


def error_attempt_check(*, case, token):
    """A D check for every attempt (harness/model_flow.py attempt_checks):
    as soon as the failing tool has a tool_use, its tools/call, the fake's
    reply and the error tool_result are judged (d_error_result), also on an
    attempt that is about to be retried or skipped as inconclusive. Its OK
    lines are counted, not logged: check_d logs the same checks in full on
    the final attempt (a failure is logged here as always)."""
    server = case["server"]
    name = mcp_tool_name(server=server, tool=case["tool"])

    def check(*, stream, records):
        if stream.tool_uses_named(name=name):
            with checks_logged_once(what="attempt check d_error_result for %s" % name):
                d_error_result(stream=stream, records=records[server], server=server, tool=case["tool"],
                               token=token, expected_reply=case["reply"])
    return check


def run_flow(*, sandbox, ledger, request, case, token, prompt, hook_log):
    """run_until_triggered with this test's servers, triggers, hooks and
    attempt check (also driven offline by tests/test_harness_offline.py)."""
    server = case["server"]
    return run_until_triggered(
        sandbox=sandbox, ledger=ledger, test_id=request.node.nodeid, prompt=prompt, model=MODEL_ID,
        max_turns=MAX_TURNS, max_budget_usd=MAX_BUDGET_USD_PER_RUN, timeout_s=MODEL_CLI_TIMEOUT_S,
        servers={server: fake_entry(sandbox=sandbox, server=server, toolset=case["toolset"], token=token)},
        allowed_tools=allowed_tools_for(servers=[server]), gate_servers=[server], wire_servers=[server],
        trigger_names=[mcp_tool_name(server=server, tool=case["tool"]), mcp_tool_name(server=server, tool=ECHO)],
        require_all_triggers=True, retries=INCONCLUSIVE_RETRIES, rejected_exit_code=MODEL_REJECTED_EXIT_CODE,
        extra_args=hook_settings_args(python=PYTHON, log_path=hook_log, events=HOOK_EVENTS),
        attempt_checks=[error_attempt_check(case=case, token=token)],
    )


def run_case(*, sandbox, ledger, request, case_id, repeat):
    case = CASES[case_id]
    sandbox.set_env(name=TOOL_SEARCH_ENV, value=TOOL_SEARCH_OFF, secret=False)
    sandbox.record.observe(key="repeat", value={"index": repeat, "of": REPEATS, "group": case["group"]})
    start_repeat(config=request.config, group=case["group"], repeat=repeat)
    server = case["server"]
    token = token_value()
    echo_text = ECHO_TEXT_PREFIX + secrets.token_hex(ECHO_TEXT_HEX_BYTES)
    failing_name = mcp_tool_name(server=server, tool=case["tool"])
    echo_name = mcp_tool_name(server=server, tool=ECHO)
    prompt = PROMPT.format(failing=failing_name, arguments=canonical_arguments(case=case), echo=echo_name,
                           echo_text=echo_text)
    hook_log = os.path.join(sandbox.artifact_dir, HOOK_LOG_NAME)
    sandbox.record.observe(key="token", value=token)
    step(text="stdio server %s (toolset %s): %s fails with the fresh token %s (%s); echo works; hooks %s logged" % (
        server, case["toolset"], case["tool"], token, case["reply"], list(HOOK_EVENTS)))
    triggered = run_flow(sandbox=sandbox, ledger=ledger, request=request, case=case, token=token, prompt=prompt,
                         hook_log=hook_log)
    if triggered.inconclusive is not None:
        record_s_sample(config=request.config, group=case["group"], repeat=repeat,
                        rated={name: False for name in RATED}, recorded={}, inconclusive=triggered.inconclusive)
        record(what="repeat %d of %s" % (repeat, case["group"]), value="S miss: %s" % triggered.inconclusive)
        pytest.skip("%s (after %d attempt(s), retry logged in run.json)" % (triggered.inconclusive,
                                                                             len(triggered.attempts)))
    rated, recorded, detail = s_facts(stream=triggered.run.stream, failing_name=failing_name, echo_name=echo_name,
                                      token=token)
    record_s_sample(config=request.config, group=case["group"], repeat=repeat, rated=rated, recorded=recorded,
                    inconclusive=None)
    sandbox.record.observe(key="s_facts", value={"rated": rated, "recorded": recorded, "detail": detail})
    for key in sorted(rated):
        record(what="%s (rated)" % key, value=rated[key])
    for key in sorted(recorded):
        record(what=key, value=recorded[key])
    got(what="tool_use names", value=detail["tool_use_names"])
    got(what="final answer", value=detail["final_text"])
    check_d(sandbox=sandbox, triggered=triggered, case=case, token=token, hook_log=hook_log)


def canonical_arguments(*, case):
    """The failing tool's arguments as JSON text for the prompt."""
    return json.dumps(case["arguments"], sort_keys=True)


def s_rate(*, request, item_artifact_dir, case_id):
    step(text="read the S samples of the %d repeats of %s" % (REPEATS, CASES[case_id]["group"]))
    summary = evaluate_s_rate(
        config=request.config, group=CASES[case_id]["group"], repeats=REPEATS, min_passes=S_RATE_MIN_PASSES,
        rates_file=os.environ[RATES_FILE_ENV], artifact_dir=item_artifact_dir,
    )
    got(what="S rate of %s" % CASES[case_id]["group"], value="%d/%d passes, per fact %s" % (
        summary["passes"], summary["repeats_ran"], summary["per_rated_fact"]))
    expect_true(what="S pass rate of %s" % CASES[case_id]["group"],
                expected=">= %d of %d" % (S_RATE_MIN_PASSES, REPEATS),
                actual="%d of %d; per repeat %s" % (summary["passes"], summary["repeats_ran"],
                                                    per_repeat_outcomes(summary=summary)),
                holds=summary["passes"] >= S_RATE_MIN_PASSES)


@pytest.mark.parametrize("repeat", range(REPEATS))
def test_tool_execution_error_is_error_result(model_sandbox, cost_ledger, request, repeat):
    run_case(sandbox=model_sandbox, ledger=cost_ledger, request=request, case_id="T1", repeat=repeat)


# The rate item runs after its repeats (pytest keeps definition order; see
# tests/test_right_tool_args.py for why no reordering plugin is used).
def test_tool_execution_error_is_error_result_s_rate(request, item_artifact_dir):
    s_rate(request=request, item_artifact_dir=item_artifact_dir, case_id="T1")


@pytest.mark.parametrize("repeat", range(REPEATS))
def test_protocol_error_is_error_result(model_sandbox, cost_ledger, request, repeat):
    run_case(sandbox=model_sandbox, ledger=cost_ledger, request=request, case_id="T2", repeat=repeat)


def test_protocol_error_is_error_result_s_rate(request, item_artifact_dir):
    s_rate(request=request, item_artifact_dir=item_artifact_dir, case_id="T2")
