"""D20/T1: the stdio server crashes with a tools/call in flight.

Model tier: needs ANTHROPIC_API_KEY, costs tokens (skipped without a key).
Run CRASH_RUNS times (one pytest item each, fresh sandbox); every run must
pass the same D asserts, and a trailing item checks that every run showed
the same client behavior (same signature).

Server `crashy`: stdio fake, mode exit_on_first_tools_call, toolset smoke
(echo_canary, echo). It serves the handshake and tools/list; on the first
tools/call of the client it logs the request (`recv`), logs an `exit`
record, and exits 3 without replying. A process the same client starts
again serves normally. Every start logs one `started` record (pid, ppid).
The prompt asks for echo_canary once and, after it fails, for echo once (a
later call to the same server: does the client start it again?). Both
tool_uses are the S trigger (require_all_triggers): without the later call
the restart question has no answer, so such an attempt is inconclusive.
Hooks are logged as in D16.

  D  gate, legacy era, both tools in system/init tools.
  D  the first process got exactly one tools/call (echo_canary), logged
     `exit` for that JSON-RPC id, and sent no reply to it.
  D  the run does not hang: the echo_canary tool_result's stream timestamp
     is at most CRASH_FAILURE_BOUND_S (5 s) after the fake's own `exit`
     epoch (one container clock). A client that missed the exit would wait
     for the 30 s tool timeout (MCP_TOOL_TIMEOUT_MS; stdio has no
     per-request timer, mcp.md:433). The measured delay is recorded.
  D  that tool_use has exactly one tool_result, is_error true (text recorded).
  D  no eager restart: no `started` record between the fake's exit and the
     next tool_use.
  D  the run ends with a `result` event, the last line.
  D  every run shows the same client behavior (trailing item).
  On every attempt, before the retry decision (harness/model_flow.py, QA
  step 5): the `result` event exists, and whenever the echo_canary
  tool_use exists the crashed-call facts above (one tools/call, its
  `exit`, no reply, exactly one tool_result, is_error true, the 5 s
  bound) are asserted (crash_attempt_check). A client that dies after the
  crash fails the item; it is never retried or skipped as inconclusive.
  Documented, record-only (not a strict xfail, not a defect): mcp.md:377
     says "Stdio servers are local processes, and Claude Code doesn't
     reconnect them automatically". That line sits under "Automatic
     reconnection", so it is about eager reconnects. 2.1.296 does not
     reconnect eagerly (the D check above); it starts the server again
     lazily, on the next call to it (observations.md). The 2026-07-28 spec
     says the client SHOULD restart a crashed stdio server
     (basic__transports__stdio.md:116; the run uses the legacy 2025-11-25
     era, whose transports page has no such line). So the lazy restart is a
     doc gap, recorded, not a defect: the spawn count is compared with the
     doc line by record_documented, and run.json key
     `observations.documented_no_restart` holds the doc line, the spawns
     and whether they match. A strict xfail here would only pass if the
     client got worse.
  Recorded: what the later call got (tool_result, the process that served
     it, whether tools/list was sent again), the hook inputs, the answer.
"""

import os
import re
import secrets

import pytest

from harness.constants import (
    CANARY_HEX_BYTES,
    CANARY_PREFIX,
    CRASH_FAILURE_BOUND_S,
    CRASH_RUNS,
    FAKE_MODE_EXIT_ON_FIRST_TOOLS_CALL,
    FAKE_PRESENCE_ONLY_MODEL,
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
    TOOL_SEARCH_ENV,
    TOOL_SEARCH_OFF,
    TOOLSET_SMOKE,
)
from harness.check import expect_equal, expect_true, got, record, step
from harness.error_checks import event_epoch, spawns
from harness.fakes_ctl import STDIO_FAKE_SCRIPT
from harness.hooks import check_hook_log, hook_events, hook_settings_args, read_hook_log
from harness.known_defects import record_documented
from harness.mcp_setup import PYTHON, stdio_fake_env
from harness.model_checks import (
    MCP_PREFIX,
    TOOL_USE_ID_META,
    assert_era,
    assert_tool_search_tool,
    assert_tools_advertised,
    has_tool_use_meta,
    mcp_tool_name,
    pair_calls_to_uses,
    tools_call_records,
)
from harness.model_flow import run_until_triggered
from harness.model_run import allowed_tools_for, stdio_server_entry
from harness.wire import message_method

pytestmark = [pytest.mark.model, pytest.mark.timeout(MODEL_TEST_TIMEOUT_S)]

SERVER = "crashy"
CRASH_TOOL = "echo_canary"
NEXT_TOOL = "echo"
REQUEST_ID_PREFIX = "crash-req-"
TEXT_PREFIX = "after-crash-"
HEX_BYTES = 4
HOOK_LOG_NAME = "hooks.jsonl"
HOOK_EVENTS = (HOOK_POST_TOOL_USE, HOOK_POST_TOOL_USE_FAILURE)
EXIT_EVENT = "exit"
TOOLS_LIST = "tools/list"
SIGNATURES_KEY = pytest.StashKey[dict]()  # {run index: signature}
# Ids that differ between runs, masked in the signature.
VOLATILE = re.compile(r"toolu_[A-Za-z0-9]+|%s[0-9a-f]+|%s[0-9a-f]+|%s[0-9a-f]+" % (
    CANARY_PREFIX, REQUEST_ID_PREFIX, TEXT_PREFIX))
NO_RESTART_DOC = ("mcp.md:377: \"Stdio servers are local processes, and Claude Code doesn't reconnect them "
                  "automatically\"")
DOC_SPAWNS = 1  # what a literal reading of NO_RESTART_DOC gives: the one spawn, never a second
PROMPT = (
    "Step 1: call the tool {crash} exactly once, with request_id set to exactly \"{request_id}\". Step 2: after "
    "you have seen its result, call the tool {next} exactly once, with text set to exactly \"{text}\", even if "
    "step 1 failed. Do not retry a failed call and do not call any other tool. Then reply in one short sentence "
    "saying what each call returned."
)


def masked(*, text):
    return VOLATILE.sub("<v>", text)


def methods_of(*, records, pid):
    return [message_method(message=r["msg"]) for r in records if r["event"] == "recv" and r["pid"] == pid]


def later_call_view(*, stream, records, use, first_pid):
    """What a later tool_use of the server got: its tool_result(s), and the
    tools/call that reached a fake for it (by toolUseId), if any."""
    got = stream.result_for(tool_use_id=use.id)
    calls = [r for r in tools_call_records(records=records)
             if has_tool_use_meta(call=r["msg"]) and r["msg"]["params"]["_meta"][TOOL_USE_ID_META] == use.id]
    replies = [r for c in calls for r in records if r["event"] == "sent" and r["pid"] == c["pid"]
               and "id" in r["msg"] and "method" not in r["msg"] and r["msg"]["id"] == c["msg"]["id"]]
    return {
        "name": use.name, "input": use.input, "index": use.index,
        "tool_use_timestamp": stream.events[use.index]["timestamp"],
        "tool_results": [{"is_error": r.is_error, "content": r.content, "text": r.text()} for r in got],
        "reached_pids": [c["pid"] for c in calls],
        "reached_first_pid": any(c["pid"] == first_pid for c in calls),
        "fake_replies": [r["msg"] for r in replies],
    }


def crashed_call_facts(*, stream, records):
    """The crashed call of one attempt, or None when the stream has no
    echo_canary tool_use. Asserts the wire of the first fake process (one
    tools/call, echo_canary, its `exit`, no reply) and pairs the call with
    its tool_use; the tool_result facts are assert_crashed_call's, so the
    caller can record them first."""
    crash_name = mcp_tool_name(server=SERVER, tool=CRASH_TOOL)
    uses = stream.tool_uses_named(name=crash_name)
    if not uses:
        return None
    pids = spawns(records=records)
    got(what="fake processes started in the attempt (pids)", value=pids)
    expect_true(what="fake processes started in an attempt with a %s tool_use" % crash_name, expected="at least 1",
                actual=len(pids), holds=bool(pids))
    first_pid = pids[0]
    # The wire of the first process: one tools/call, its exit, no reply.
    first_calls = [r for r in tools_call_records(records=records) if r["pid"] == first_pid]
    expect_equal(what="tools/call the first fake process got", expected=1, actual=len(first_calls))
    call = first_calls[0]
    expect_equal(what="tool of the crashed tools/call", expected=CRASH_TOOL, actual=call["msg"]["params"]["name"])
    exits = [r for r in records if r["event"] == EXIT_EVENT and r["pid"] == first_pid]
    expect_equal(what="JSON-RPC ids of the first process's `exit` records", expected=[call["msg"]["id"]],
                 actual=[r["rpc_id"] for r in exits])
    replies = [r for r in records if r["event"] == "sent" and r["pid"] == first_pid and "id" in r["msg"]
               and "method" not in r["msg"] and r["msg"]["id"] == call["msg"]["id"]]
    expect_equal(what="replies the fake sent to the tools/call it crashed on", expected=[],
                 actual=[r["msg"] for r in replies])
    # The tool_use of the crashed call (the flow already checked every call has one).
    pairs = pair_calls_to_uses(call_records=[call], uses=uses)
    crashed = [use for use in uses if use.id in pairs][0]
    results = stream.result_for(tool_use_id=crashed.id)
    exit_epoch = exits[0]["epoch"]
    delay = (round(event_epoch(event=stream.events[results[0].index]) - exit_epoch, 3)
             if len(results) == 1 else None)
    return {"first_pid": first_pid, "call": call, "exit": exits[0], "exit_epoch": exit_epoch, "crashed": crashed,
            "results": results, "failure_delay_s": delay}


def assert_crashed_call(*, facts):
    """D: the crashed tool_use got exactly one tool_result, after it, with
    is_error true, at most CRASH_FAILURE_BOUND_S after the fake's exit."""
    crashed = facts["crashed"]
    results = facts["results"]
    expect_equal(what="tool_result blocks for the crashed tool_use %s" % crashed.id, expected=1, actual=len(results))
    result = results[0]
    expect_true(what="is_error of the crashed call's tool_result", expected="True",
                actual="%r (text %r)" % (result.is_error, result.text()), holds=result.is_error is True)
    expect_true(what="stream line of the crashed call's tool_result", expected="after its tool_use (line %d)"
                % crashed.index, actual="line %d" % result.index, holds=result.index > crashed.index)
    expect_true(what="time from the fake's exit to the error tool_result", expected="<= %s s" % CRASH_FAILURE_BOUND_S,
                actual="%.3f s" % facts["failure_delay_s"], holds=facts["failure_delay_s"] <= CRASH_FAILURE_BOUND_S)


def crash_attempt_check(*, stream, records):
    """harness/model_flow.py attempt_checks: on every attempt, whenever the
    echo_canary tool_use exists, its crashed-call facts must hold, before
    any retry or inconclusive skip."""
    facts = crashed_call_facts(stream=stream, records=records[SERVER])
    if facts is not None:
        assert_crashed_call(facts=facts)


def check_d(*, sandbox, triggered, hook_log):
    """Hard D asserts; returns the view. The documented one-spawn check is
    the caller's, after this."""
    stream = triggered.run.stream
    records = triggered.records[SERVER]
    crash_name = mcp_tool_name(server=SERVER, tool=CRASH_TOOL)
    next_name = mcp_tool_name(server=SERVER, tool=NEXT_TOOL)
    era = assert_era(records=records, negotiation=NEGOTIATION_LEGACY)
    assert_tool_search_tool(stream=stream, expected=False)
    assert_tools_advertised(stream=stream, names=[crash_name, next_name])

    started = [r for r in records if r["event"] == "started"]
    facts = crashed_call_facts(stream=stream, records=records)
    expect_true(what="%s tool_use in the stream (the trigger required one)" % crash_name, expected="present",
                actual="present" if facts is not None else "absent", holds=facts is not None)
    first_pid = facts["first_pid"]
    call = facts["call"]
    exit_epoch = facts["exit_epoch"]
    crashed = facts["crashed"]
    expect_equal(what="tool_result blocks for the crashed tool_use %s" % crashed.id, expected=1,
                 actual=len(facts["results"]))
    result = facts["results"][0]
    result_event = stream.events[result.index]
    tool_use_event = stream.events[crashed.index]
    failure_delay_s = facts["failure_delay_s"]

    later = [u for u in stream.tool_uses if u.name.startswith("%s%s__" % (MCP_PREFIX, SERVER)) and u.id != crashed.id
             and u.index > crashed.index]
    later_views = [later_call_view(stream=stream, records=records, use=use, first_pid=first_pid) for use in later]
    next_use_epoch = event_epoch(event=stream.events[later[0].index]) if later else None
    eager = [r["pid"] for r in started if r["epoch"] > exit_epoch
             and (next_use_epoch is None or r["epoch"] < next_use_epoch)]
    entries = read_hook_log(path=hook_log)
    check_hook_log(entries=entries)
    view = {
        "era_seen": era,
        "spawns": [{"pid": r["pid"], "ppid": r["ppid"], "epoch": r["epoch"], "ts": r["ts"],
                    "methods": methods_of(records=records, pid=r["pid"])} for r in started],
        "same_ppid": len({r["ppid"] for r in started}) == 1,
        "crashed_call": {
            "tool_use_id": crashed.id, "rpc_id": call["msg"]["id"],
            "tool_result_is_error": result.is_error, "tool_result_content": result.content,
            "tool_result_text": result.text(),
            "tool_use_result": result_event["tool_use_result"] if "tool_use_result" in result_event
            else "(key absent)",
            "fake_exit_epoch": exit_epoch, "fake_exit_code": facts["exit"]["code"],
            "tool_use_timestamp": tool_use_event["timestamp"], "tool_result_timestamp": result_event["timestamp"],
            "failure_delay_after_exit_s": failure_delay_s,
            "tool_use_to_tool_result_s": round(event_epoch(event=result_event) - event_epoch(event=tool_use_event), 3),
        },
        "started_between_exit_and_next_tool_use": eager,
        "respawn_after_next_tool_use_s": [round(r["epoch"] - next_use_epoch, 3) for r in started
                                          if next_use_epoch is not None and r["epoch"] >= next_use_epoch],
        "later_calls": later_views,
        "hooks": {
            "post_tool_use_failure": [dict(e["input"], logged_epoch=e["epoch"]) for e in
                                      hook_events(entries=entries, event_name=HOOK_POST_TOOL_USE_FAILURE)],
            "post_tool_use": [e["input"] for e in hook_events(entries=entries, event_name=HOOK_POST_TOOL_USE)],
        },
        "cli_duration_s": triggered.run.cli.duration_s,
        "result": {k: stream.result[k] for k in ("subtype", "is_error", "num_turns", "result")
                   if stream.result is not None and k in stream.result},
    }
    sandbox.record.observe(key="d_view", value=view)
    got(what="crashed call", value={k: view["crashed_call"][k] for k in (
        "rpc_id", "fake_exit_code", "tool_result_is_error", "failure_delay_after_exit_s", "tool_result_text")})
    got(what="spawns (pid, methods)", value=[(row["pid"], row["methods"]) for row in view["spawns"]])
    got(what="later calls (name, tool_results, reached pids)",
        value=[(row["name"], row["tool_results"], row["reached_pids"]) for row in later_views])

    assert_crashed_call(facts=facts)
    expect_true(what="later tool_use of %s (the trigger required one)" % SERVER, expected="at least 1",
                actual=len(later), holds=bool(later))
    expect_equal(what="fake processes started between the crash and the next tool_use (pids)", expected=[],
                 actual=eager)
    for row in later_views:
        expect_equal(what="tool_result blocks for the later tool_use %s" % row["name"], expected=1,
                     actual=len(row["tool_results"]))
    expect_true(what="final result event in the stream", expected="present", actual="present"
                if stream.result is not None else "absent", holds=stream.result is not None)
    expect_equal(what="stream line of the result event", expected=len(stream.events) - 1,
                 actual=stream.events.index(stream.result))
    return view


def signature(*, view):
    """The client facts that must be the same in every run (ids masked).
    Only the first later call and the first two spawns count: a model that
    makes more calls in one run (S) must not fail this D check."""
    crashed_id = view["crashed_call"]["tool_use_id"]
    first_later = view["later_calls"][0]
    return {
        "spawns_up_to_first_later_call": min(len(view["spawns"]), 2),
        "same_ppid": view["same_ppid"],
        "methods_per_spawn": [row["methods"] for row in view["spawns"][:2]],
        "crashed_is_error": view["crashed_call"]["tool_result_is_error"],
        "crashed_text": masked(text=view["crashed_call"]["tool_result_text"]),
        "first_later_result": [(r["is_error"], masked(text=r["text"])) for r in first_later["tool_results"]],
        "first_later_reached_first_pid": first_later["reached_first_pid"],
        "post_tool_use_failure_for_crashed_call": [
            masked(text=h["error"]) for h in view["hooks"]["post_tool_use_failure"] if h["tool_use_id"] == crashed_id],
    }


def crash_run(*, sandbox, ledger, request, run_index, signatures):
    """One D20/T1 run (the body of test_stdio_crash_mid_call; also driven
    offline by tests/test_harness_offline.py). signatures: {run index:
    signature}, filled for the trailing same-every-run item. Last, after
    every hard assert, the documented one-spawn line is recorded (never
    raised): run.json `observations.documented_no_restart`."""
    sandbox.set_env(name=TOOL_SEARCH_ENV, value=TOOL_SEARCH_OFF, secret=False)
    canary = CANARY_PREFIX + secrets.token_hex(CANARY_HEX_BYTES)
    request_id = REQUEST_ID_PREFIX + secrets.token_hex(HEX_BYTES)
    text = TEXT_PREFIX + secrets.token_hex(HEX_BYTES)
    hook_log = os.path.join(sandbox.artifact_dir, HOOK_LOG_NAME)
    entry = stdio_server_entry(
        fake_script=STDIO_FAKE_SCRIPT, python=PYTHON,
        fake_env=stdio_fake_env(name=SERVER, mode=FAKE_MODE_EXIT_ON_FIRST_TOOLS_CALL,
                                log_path=sandbox.wire_log_path(name=SERVER),
                                init_reply_delay_ms=INIT_REPLY_IMMEDIATE_MS, canary=canary, toolset=TOOLSET_SMOKE,
                                presence_only_env=FAKE_PRESENCE_ONLY_MODEL),
    )
    crash_name = mcp_tool_name(server=SERVER, tool=CRASH_TOOL)
    next_name = mcp_tool_name(server=SERVER, tool=NEXT_TOOL)
    step(text="stdio server %s (FAKE_MODE=%s): exits with code 3 on the first tools/call; prompt: %s, then %s" % (
        SERVER, FAKE_MODE_EXIT_ON_FIRST_TOOLS_CALL, crash_name, next_name))
    triggered = run_until_triggered(
        sandbox=sandbox, ledger=ledger, test_id=request.node.nodeid,
        prompt=PROMPT.format(crash=crash_name, request_id=request_id, next=next_name, text=text),
        model=MODEL_ID, max_turns=MAX_TURNS, max_budget_usd=MAX_BUDGET_USD_PER_RUN, timeout_s=MODEL_CLI_TIMEOUT_S,
        servers={SERVER: entry}, allowed_tools=allowed_tools_for(servers=[SERVER]), gate_servers=[SERVER],
        wire_servers=[SERVER], trigger_names=[crash_name, next_name], require_all_triggers=True,
        retries=INCONCLUSIVE_RETRIES, rejected_exit_code=MODEL_REJECTED_EXIT_CODE,
        extra_args=hook_settings_args(python=PYTHON, log_path=hook_log, events=HOOK_EVENTS),
        attempt_checks=[crash_attempt_check],
    )
    if triggered.inconclusive is not None:
        step(text="skip as inconclusive: %s" % triggered.inconclusive)
        pytest.skip("%s (after %d attempt(s))" % (triggered.inconclusive, len(triggered.attempts)))
    view = check_d(sandbox=sandbox, triggered=triggered, hook_log=hook_log)
    sig = signature(view=view)
    sandbox.record.observe(key="signature", value=sig)
    final_text = view["result"]["result"] if "result" in view["result"] else None
    sandbox.record.observe(key="s_recorded", value={"final_text": final_text})
    record(what="final answer", value=final_text)
    got(what="signature of run %d" % run_index, value=sig)
    signatures[run_index] = sig
    # Last: the documented line, record-only (a doc gap, not a defect).
    spawn_pids = [row["pid"] for row in view["spawns"]]
    matches = record_documented(
        what="stdio fake processes started in the run",
        doc="%d: no restart (%s)" % (DOC_SPAWNS, NO_RESTART_DOC),
        actual="%d (pids %s)" % (len(spawn_pids), spawn_pids),
        holds=len(spawn_pids) == DOC_SPAWNS)
    sandbox.record.observe(key="documented_no_restart", value={
        "doc": NO_RESTART_DOC, "doc_spawns": DOC_SPAWNS, "spawns": len(spawn_pids), "pids": spawn_pids,
        "matches": matches})


@pytest.mark.parametrize("run_index", range(CRASH_RUNS))
def test_stdio_crash_mid_call(model_sandbox, cost_ledger, request, run_index):
    if SIGNATURES_KEY not in request.config.stash:
        request.config.stash[SIGNATURES_KEY] = {}
    crash_run(sandbox=model_sandbox, ledger=cost_ledger, request=request, run_index=run_index,
              signatures=request.config.stash[SIGNATURES_KEY])


# Runs after the CRASH_RUNS items (pytest keeps definition order).
def test_stdio_crash_mid_call_same_every_run(request):
    step(text="read the signatures of the %d crash runs of this session" % CRASH_RUNS)
    signatures = request.config.stash[SIGNATURES_KEY] if SIGNATURES_KEY in request.config.stash else {}
    if len(signatures) < CRASH_RUNS:
        pytest.skip("inconclusive: %d of %d crash runs completed in this session" % (len(signatures), CRASH_RUNS))
    distinct = {repr(sorted(sig.items())) for sig in signatures.values()}
    got(what="signatures of the %d crash runs" % len(signatures), value=signatures)
    expect_true(what="distinct signatures over the %d crash runs" % len(signatures), expected="1",
                actual="%d: %s" % (len(distinct), signatures), holds=len(distinct) == 1)
