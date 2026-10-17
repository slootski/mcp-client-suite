"""D19/T1 (idle timeout with no response and no progress) and D19/T3
(cancellation when the client gives up).

Model tier: needs ANTHROPIC_API_KEY, costs tokens (skipped without a key).
Run IDLE_RUNS times with MCP_PROTOCOL_NEGOTIATION=legacy (one pytest item
each, fresh sandbox), plus one run with it unset (doc 11 era check).

Env (env-vars.md:337, 500; mcp.md:433-439): CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT
= 3000 and MCP_TOOL_TIMEOUT = 60000 (the suite pin of 30000 is overridden;
run.json records it), no per-server `timeout` in the --mcp-config entry
(env-vars.md:337 is quoted in IDLE_DOC).

Server `slowpoke`: stdio fake, mode hang_on_tools_call, toolset smoke. It
serves the handshake and tools/list; every tools/call is logged (`recv`)
plus a `no_reply` record, and gets nothing back: no reply, no progress.
The fake keeps reading stdin, so a notifications/cancelled is logged too.
The prompt asks for echo_canary once, no retry.

  D  gate (connected, else inconclusive), era (legacy: initialize first;
     unset: server/discover first, then initialize 2025-11-25), no
     ToolSearch, echo_canary in system/init tools.
  D  each echo_canary tool_use reached the fake as one tools/call; the
     fake sent nothing for it (a `no_reply` record, no `sent` reply, no
     progress).
  D  T1, the bound: the client gives up at >= IDLE_LOWER_S - tolerance and
     < IDLE_HARD_UPPER_S (50 s, 10 s under the 60 s wall-clock limit, so
     the abort is the idle check's and the run does not hang) after the
     fake's own `recv` epoch of the tools/call. "Gives up" = the stream
     `timestamp` of that tool_use's tool_result. Both are wall-clock times
     of one container: an attempt whose host clock jumped is inconclusive
     and retried (harness/model_flow.py; run 88362). The tool_result is
     exactly one, is_error true, and holds IDLE_ABORT_TEXT, so the abort is
     the idle check's and not some other error. IDLE_LOWER_TOLERANCE_S =
     0.25 s, lower bound only: the client's timer starts before the fake
     reads the request, so the span can be a little under 3 s.
  D  T3, part 1: no message for that request id reaches the fake after the
     cancel (or, with no cancel, after the give-up), other than that one
     cancel: no second tools/call, no second cancel.
  SHOULD, warning: T3, part 2: exactly one notifications/cancelled with
     params.requestId == the tools/call id reaches the fake, after the
     give-up, and also in [IDLE_LOWER_S - tolerance, IDLE_UPPER_S) from the
     start. 2025-11-25 basic__lifecycle.md:249-253: "the sender SHOULD issue
     a cancellation notification for that request and stop waiting for a
     response". Both runs negotiate 2025-11-25 (the unset run falls back to
     initialize after -32601), so it is a SHOULD in both: a miss is a
     warning (pytest warnings summary) and recorded, never a failure (doc
     19 test 3). The 2026-07-28 stdio MUST does not apply to these runs.
  D  the run ends with a `result` event, the last line.
  Documented, strict xfail (DocumentedBehaviorMismatch, raised last, after
     every hard assert and the T3 warning): the give-up is in
     [IDLE_LOWER_S - tolerance, IDLE_UPPER_S) = [2.75 s, 5 s), as asked by
     doc 19 test 1 and env-vars.md:337. 2.1.296 aborts after 30.0 s in
     every run, both eras; its debug log reads "no response or progress
     notification for 30s (idle timeout 3s)" (observations.md).
  Recorded: the two spans, the cancel reason, the tool_result text, the
     result, and the era; the unset run is compared in observations.md.
"""

import secrets
import warnings

import pytest

from harness.constants import (
    CANARY_HEX_BYTES,
    CANARY_PREFIX,
    FAKE_MODE_HANG_ON_TOOLS_CALL,
    FAKE_PRESENCE_ONLY_MODEL,
    IDLE_TIMEOUT_ENV,
    INCONCLUSIVE_RETRIES,
    INIT_REPLY_IMMEDIATE_MS,
    MAX_BUDGET_USD_PER_RUN,
    MAX_TURNS,
    MODEL_CLI_TIMEOUT_S,
    MODEL_ID,
    MODEL_REJECTED_EXIT_CODE,
    MODEL_TEST_TIMEOUT_S,
    NEGOTIATION_ENV,
    NEGOTIATION_LEGACY,
    TOOL_SEARCH_ENV,
    TOOL_SEARCH_OFF,
    TOOL_TIMEOUT_ENV,
    TOOLSET_SMOKE,
)
from harness.check import expect_equal, expect_in, expect_not_in, expect_true, got, step
from harness.error_checks import event_epoch
from harness.fakes_ctl import STDIO_FAKE_SCRIPT
from harness.known_defects import DocumentedBehaviorMismatch, expect_documented
from harness.mcp_setup import PYTHON, stdio_fake_env
from harness.model_checks import (
    NEGOTIATION_UNSET_LABEL,
    assert_era,
    assert_tool_search_tool,
    assert_tools_advertised,
    mcp_tool_name,
    pair_calls_to_uses,
    tools_call_records,
)
from harness.model_flow import run_until_triggered
from harness.model_run import allowed_tools_for, stdio_server_entry

pytestmark = [pytest.mark.model, pytest.mark.timeout(MODEL_TEST_TIMEOUT_S)]

SERVER = "slowpoke"
TOOL = "echo_canary"
IDLE_RUNS = 3  # doc 19, step 6: T1+T3 three times, the bound must hold each time
IDLE_TIMEOUT_MS = "3000"
WALL_CLOCK_TIMEOUT_MS = "60000"
IDLE_LOWER_S = 3.0
IDLE_UPPER_S = 5.0  # documented window: [3 s - tolerance, 5 s)
IDLE_LOWER_TOLERANCE_S = 0.25
# Hard D window: [3 s - tolerance, 50 s). 50 s is 10 s under the 60 s
# MCP_TOOL_TIMEOUT, so an abort inside it is the idle check's (the client's
# own error text names it), not the wall-clock limit's, and not a hang.
IDLE_HARD_UPPER_S = 50.0
IDLE_DOC = ("env-vars.md:337: CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT: \"When a stdio ... MCP server sends no response "
            "and no progress notification for this long, the tool call aborts with an error\"")
CANCELLED = "notifications/cancelled"
# The client's own idle-abort text, verbatim from the tool_result of every
# recorded run (artifacts/20261017T073250Z-84063): 'MCP server "slowpoke"
# tool "echo_canary" sent no response or progress for 30s; aborting. ...'.
# The number of seconds is left out on purpose, so a client that aborts at
# 3 s with the same text passes the hard assert (and XPASSes the xfail).
IDLE_ABORT_TEXT = "sent no response or progress"
NO_REPLY = "no_reply"
REQUEST_ID_PREFIX = "idle-req-"
HEX_BYTES = 4
CANCEL_SHOULD = ("2025-11-25 basic__lifecycle.md:249-253: the sender SHOULD issue a cancellation notification "
                 "for a request that timed out")
PROMPT = (
    "Call the tool {tool} exactly once, with request_id set to exactly \"{request_id}\". If it fails or times "
    "out, do not retry it and do not call any other tool. Then reply in one short sentence saying what it returned."
)


def referencing(*, record, rpc_id):
    """True when a fake `recv` record is a message about JSON-RPC id rpc_id:
    the request itself (same id) or a notification naming it in
    params.requestId."""
    msg = record["msg"]
    if not isinstance(msg, dict):
        return False
    if "id" in msg and msg["id"] == rpc_id:
        return True
    params = msg["params"] if "params" in msg and isinstance(msg["params"], dict) else None
    return params is not None and "requestId" in params and params["requestId"] == rpc_id


def call_view(*, stream, records, call, use):
    """The D facts of one hung tools/call (asserted by the caller after recording)."""
    rpc_id = call["msg"]["id"]
    start = call["epoch"]
    results = stream.result_for(tool_use_id=use.id)
    give_up = event_epoch(event=stream.events[results[0].index]) if len(results) == 1 else None
    after_call = [r for r in records if r["event"] == "recv" and r["epoch"] > start
                  and referencing(record=r, rpc_id=rpc_id)]
    cancels = [r for r in after_call if "method" in r["msg"] and r["msg"]["method"] == CANCELLED]
    no_reply = [r for r in records if r["event"] == NO_REPLY and r["id"] == rpc_id and r["pid"] == call["pid"]]
    sent = [r for r in records if r["event"] == "sent" and r["pid"] == call["pid"] and isinstance(r["msg"], dict)
            and "id" in r["msg"] and r["msg"]["id"] == rpc_id and "method" not in r["msg"]]
    progress_sent = [r for r in records if r["event"] == "sent" and isinstance(r["msg"], dict)
                     and "method" in r["msg"] and r["msg"]["method"] == "notifications/progress"]
    first_cancel = cancels[0] if cancels else None
    return {
        "tool_use_id": use.id,
        "rpc_id": rpc_id,
        "progress_token": call["msg"]["params"]["_meta"]["progressToken"]
        if "_meta" in call["msg"]["params"] and "progressToken" in call["msg"]["params"]["_meta"] else None,
        "fake_recv_epoch": start,
        "tool_results": [{"is_error": r.is_error, "text": r.text(), "timestamp": stream.events[r.index]["timestamp"]}
                         for r in results],
        "give_up_after_s": round(give_up - start, 3) if give_up is not None else None,
        "cancels": [{"epoch": r["epoch"], "after_s": round(r["epoch"] - start, 3), "params": r["msg"]["params"]}
                    for r in cancels],
        "cancel_after_give_up_s": round(first_cancel["epoch"] - give_up, 3)
        if first_cancel is not None and give_up is not None else None,
        "other_messages_for_request": [r["msg"] for r in after_call if r not in cancels],
        "messages_after_first_cancel": [r["msg"] for r in after_call
                                        if first_cancel is not None and r["epoch"] > first_cancel["epoch"]],
        "no_reply_records": len(no_reply),
        "fake_replies": [r["msg"] for r in sent],
        "fake_progress_sent": len(progress_sent),
    }


def in_window(*, span_s, upper_s):
    """span_s in [IDLE_LOWER_S - IDLE_LOWER_TOLERANCE_S, upper_s)."""
    return span_s is not None and IDLE_LOWER_S - IDLE_LOWER_TOLERANCE_S <= span_s < upper_s


def run_idle(*, sandbox, ledger, request, negotiation):
    sandbox.set_env(name=TOOL_SEARCH_ENV, value=TOOL_SEARCH_OFF, secret=False)
    sandbox.set_env(name=IDLE_TIMEOUT_ENV, value=IDLE_TIMEOUT_MS, secret=False)
    sandbox.set_env(name=TOOL_TIMEOUT_ENV, value=WALL_CLOCK_TIMEOUT_MS, secret=False)
    if negotiation == NEGOTIATION_UNSET_LABEL:
        sandbox.unset_env(name=NEGOTIATION_ENV)
    canary = CANARY_PREFIX + secrets.token_hex(CANARY_HEX_BYTES)
    request_id = REQUEST_ID_PREFIX + secrets.token_hex(HEX_BYTES)
    name = mcp_tool_name(server=SERVER, tool=TOOL)
    entry = stdio_server_entry(
        fake_script=STDIO_FAKE_SCRIPT, python=PYTHON,
        fake_env=stdio_fake_env(name=SERVER, mode=FAKE_MODE_HANG_ON_TOOLS_CALL,
                                log_path=sandbox.wire_log_path(name=SERVER),
                                init_reply_delay_ms=INIT_REPLY_IMMEDIATE_MS, canary=canary, toolset=TOOLSET_SMOKE,
                                presence_only_env=FAKE_PRESENCE_ONLY_MODEL),
    )
    sandbox.record.observe(key="bounds", value={
        "idle_timeout_ms": IDLE_TIMEOUT_MS, "mcp_tool_timeout_ms": WALL_CLOCK_TIMEOUT_MS,
        "per_server_timeout": "(not set)", "lower_s": IDLE_LOWER_S, "lower_tolerance_s": IDLE_LOWER_TOLERANCE_S,
        "documented_upper_s": IDLE_UPPER_S, "hard_upper_s": IDLE_HARD_UPPER_S, "negotiation": negotiation})
    expect_not_in(what="keys of the --mcp-config entry (no per-server timeout)", item="timeout", container=sorted(entry))
    step(text="stdio server %s (FAKE_MODE=%s): every tools/call gets no reply and no progress; %s=%s, %s=%s, "
              "negotiation %s" % (SERVER, FAKE_MODE_HANG_ON_TOOLS_CALL, IDLE_TIMEOUT_ENV, IDLE_TIMEOUT_MS,
                                  TOOL_TIMEOUT_ENV, WALL_CLOCK_TIMEOUT_MS, negotiation))
    triggered = run_until_triggered(
        sandbox=sandbox, ledger=ledger, test_id=request.node.nodeid,
        prompt=PROMPT.format(tool=name, request_id=request_id), model=MODEL_ID, max_turns=MAX_TURNS,
        max_budget_usd=MAX_BUDGET_USD_PER_RUN, timeout_s=MODEL_CLI_TIMEOUT_S, servers={SERVER: entry},
        allowed_tools=allowed_tools_for(servers=[SERVER]), gate_servers=[SERVER], wire_servers=[SERVER],
        trigger_names=[name], require_all_triggers=False, retries=INCONCLUSIVE_RETRIES,
        rejected_exit_code=MODEL_REJECTED_EXIT_CODE, extra_args=[], attempt_checks=[],
    )
    if triggered.inconclusive is not None:
        step(text="skip as inconclusive: %s" % triggered.inconclusive)
        pytest.skip("%s (after %d attempt(s))" % (triggered.inconclusive, len(triggered.attempts)))
    stream = triggered.run.stream
    records = triggered.records[SERVER]
    era = assert_era(records=records, negotiation=negotiation)
    assert_tool_search_tool(stream=stream, expected=False)
    assert_tools_advertised(stream=stream, names=[name])

    uses = stream.tool_uses_named(name=name)
    calls = tools_call_records(records=records)
    expect_equal(what="tools/call that reached the fake (one per %s tool_use)" % name, expected=len(uses),
                 actual=len(calls))
    pairs = pair_calls_to_uses(call_records=calls, uses=uses)
    views = [call_view(stream=stream, records=records, call=pairs[use.id], use=use) for use in uses]
    view = {"era_seen": era, "calls": views, "cli_duration_s": triggered.run.cli.duration_s,
            "result": {k: stream.result[k] for k in ("subtype", "is_error", "num_turns", "result")
                       if k in stream.result}}
    sandbox.record.observe(key="d_view", value=view)

    for row in views:
        got(what="tools/call %r: give-up after (s), tool_result(s), cancels" % (row["rpc_id"],),
            value=(row["give_up_after_s"], row["tool_results"], [c["after_s"] for c in row["cancels"]]))
        expect_equal(what="what the fake sent for tools/call %r: (no_reply records, replies, progress sent)" % (
            row["rpc_id"],), expected=(1, [], 0),
            actual=(row["no_reply_records"], row["fake_replies"], row["fake_progress_sent"]))
        expect_equal(what="tool_result blocks for tool_use %s" % row["tool_use_id"], expected=1,
                     actual=len(row["tool_results"]))
        expect_true(what="is_error of the timed-out call's tool_result", expected="True",
                    actual="%r (text %r)" % (row["tool_results"][0]["is_error"], row["tool_results"][0]["text"]),
                    holds=row["tool_results"][0]["is_error"] is True)
        expect_in(what="the client's idle-abort text in the timed-out call's tool_result (so the idle check caused "
                       "the abort)", item=IDLE_ABORT_TEXT, container=row["tool_results"][0]["text"])
        expect_true(what="time from the fake's recv of tools/call %r to the client's give-up (%s=%s, %s=%s)" % (
            row["rpc_id"], IDLE_TIMEOUT_ENV, IDLE_TIMEOUT_MS, TOOL_TIMEOUT_ENV, WALL_CLOCK_TIMEOUT_MS),
            expected="in the hard window [%.2f, %.2f) s" % (IDLE_LOWER_S - IDLE_LOWER_TOLERANCE_S, IDLE_HARD_UPPER_S),
            actual="%s s" % row["give_up_after_s"], holds=in_window(span_s=row["give_up_after_s"],
                                                                     upper_s=IDLE_HARD_UPPER_S))
        expect_equal(what="other messages for request %r after the tools/call (a cancel aside)" % (row["rpc_id"],),
                     expected=[], actual=row["other_messages_for_request"])
        expect_true(what="notifications/cancelled for request %r" % (row["rpc_id"],), expected="at most 1",
                    actual=len(row["cancels"]), holds=len(row["cancels"]) <= 1)
    expect_equal(what="stream line of the result event", expected=len(stream.events) - 1,
                 actual=stream.events.index(stream.result))

    # T3, the SHOULD: a miss is a warning, recorded; a cancel that comes is judged.
    misses = []
    for row in views:
        if not row["cancels"]:
            misses.append("no %s for tools/call %r after the idle timeout (%s)" % (CANCELLED, row["rpc_id"],
                                                                                   CANCEL_SHOULD))
            continue
        cancel = row["cancels"][0]
        # "After the client gives up" = after the idle window, on the fake's
        # clock (the same hard window as the give-up). The cancel may reach
        # the fake a few ms before the client writes the error tool_result
        # (cancel_after_give_up_s, recorded).
        expect_true(what="time from tools/call %r to its cancel at the fake" % (row["rpc_id"],),
                    expected="in the hard window [%.2f, %.2f) s" % (IDLE_LOWER_S - IDLE_LOWER_TOLERANCE_S,
                                                                    IDLE_HARD_UPPER_S),
                    actual="%.3f s" % cancel["after_s"], holds=in_window(span_s=cancel["after_s"],
                                                                         upper_s=IDLE_HARD_UPPER_S))
    sandbox.record.observe(key="cancel_should_misses", value=misses)
    got(what="SHOULD misses (%s after the give-up; a warning, never a failure)" % CANCELLED, value=misses)
    for miss in misses:
        warnings.warn(UserWarning("D19/T3 SHOULD missed (%s era): %s" % (negotiation, miss)))

    # Last: the documented window (strict xfail while 2.1.296 aborts at 30 s).
    spans = [row["give_up_after_s"] for row in views]
    expect_documented(
        what="give-up time of the hung call with %s=%s" % (IDLE_TIMEOUT_ENV, IDLE_TIMEOUT_MS),
        doc="in [%.2f, %.2f) s (%s)" % (IDLE_LOWER_S - IDLE_LOWER_TOLERANCE_S, IDLE_UPPER_S, IDLE_DOC),
        actual="the client gave up after %s s" % spans,
        holds=all(in_window(span_s=span, upper_s=IDLE_UPPER_S) for span in spans))
    return view


IDLE_XFAIL_REASON = (IDLE_DOC + "; 2.1.296 aborts after 30 s with the variable at 3000 (debug log: 'no response or "
                     "progress notification for 30s (idle timeout 3s)'; observations.md)")


@pytest.mark.xfail(strict=True, raises=DocumentedBehaviorMismatch, reason=IDLE_XFAIL_REASON)
@pytest.mark.parametrize("run_index", range(IDLE_RUNS))
def test_idle_timeout_aborts_hung_call(model_sandbox, cost_ledger, request, run_index):
    model_sandbox.record.observe(key="run", value={"index": run_index, "of": IDLE_RUNS})
    run_idle(sandbox=model_sandbox, ledger=cost_ledger, request=request, negotiation=NEGOTIATION_LEGACY)


@pytest.mark.xfail(strict=True, raises=DocumentedBehaviorMismatch, reason=IDLE_XFAIL_REASON)
def test_idle_timeout_aborts_hung_call_negotiation_unset(model_sandbox, cost_ledger, request):
    run_idle(sandbox=model_sandbox, ledger=cost_ledger, request=request, negotiation=NEGOTIATION_UNSET_LABEL)
