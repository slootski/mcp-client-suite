"""D15/T1 (right tool among near-duplicates), D15/T2+T3 (argument and return
value fidelity), run through the repeat harness of doc 22 (harness/repeat.py).

Model tier: needs ANTHROPIC_API_KEY, costs tokens (skipped without a key).
Each repeat is its own pytest item with a fresh sandbox (CLAUDE_CONFIG_DIR,
HOME, artifact folder) and fresh values; the `..._s_rate` item after the
repeats judges the S pass rate. docs/flake-policy.md lists every fact below
with its class.

D15/T1, servers `calc` (toolset calc) and `calc2` (toolset
calc_side_effect): both offer `add(a, b)` with the same schema, description
and reply (the sum); calc2 also logs a `side_effect` record per call, and
each fake logs `tool_executed` under its own server name. The prompt names
mcp__calc2__add and fixes a and b (fresh integers per repeat).
  D  both servers `connected` (gate, else inconclusive); legacy era on both
     fakes; no ToolSearch in system/init; both mcp__calc__add and
     mcp__calc2__add in system/init tools; both fakes served tools/list.
  D  routing, per server: the fake got exactly one tools/call per tool_use
     named for it, arguments == tool_use.input, and none without one. So
     once the model called only mcp__calc2__add once: exactly one tools/call
     reached calc2 and calc received no tools/call. A tool_use for
     mcp__calc__add would be an S miss (wrong tool), and the D check then
     requires that call to reach calc and not calc2.
  D  the fakes' own records: one `tool_executed` per call on the server that
     got it, with that server's name and JSON-RPC id; calc2 logs one
     `side_effect` per call, calc logs none.
  D  each tool_result text == the fake's `sent` text for that JSON-RPC id.
  S  rated: the model called mcp__calc2__add, exactly once, never
     mcp__calc__add, with input == {a, b} as prompted.
  S  recorded only: the final answer holds the sum.
  Era (doc 11): one extra run with MCP_PROTOCOL_NEGOTIATION unset
  (UNSET_ERA_RUNS = 1, not repeated): the same D asserts, plus the first
  message `server/discover` and initialize 2025-11-25; S recorded only.

D15/T2+T3, server `tickets` (toolset ticket): `create_ticket` with title
(non-ASCII), priority (enum), tags (array, with an empty string, in a
non-sorted order, plus a fresh tag per repeat), due (date string), meta
(nested object with an integer), and an optional `notes` the prompt leaves
out. The fake answers {"id": "TCK-<8 hex>", "echo": <arguments>}; the id is
fresh per call and appears nowhere in the prompt.
  D  gate, legacy era, no ToolSearch, the tool in system/init tools.
  D  one tools/call per tool_use; arguments == tool_use.input field for
     field (canonical JSON: array order, enum spelling, unicode code points,
     integer type, and an absent key is not null); in particular `notes` is
     absent on the wire whenever it is absent from tool_use.input.
  D  the tool_result text == the fake's `sent` text for that JSON-RPC id,
     and it holds the server-generated id.
  S  rated: the model called the tool exactly once with input == the
     prompt's values (per-field diffs kept in run.json).
  S  recorded only: the final answer holds the server-generated id.
"""

import json
import os
import secrets

import pytest

from harness.constants import (
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
    RATES_FILE_ENV,
    REPEATS,
    S_RATE_MIN_PASSES,
    TOOL_SEARCH_ENV,
    TOOL_SEARCH_OFF,
    TOOLSET_CALC,
    TOOLSET_CALC_SIDE_EFFECT,
    TOOLSET_TICKET,
    UNSET_ERA_RUNS,
)
from harness.check import expect_equal, expect_not_in, expect_true, got, record, step
from harness.fakes_ctl import STDIO_FAKE_SCRIPT
from harness.mcp_setup import PYTHON, stdio_fake_env
from harness.model_checks import (
    NEGOTIATION_UNSET_LABEL,
    assert_era,
    assert_tool_search_tool,
    assert_tools_advertised,
    canonical,
    d_passthrough,
    field_diff,
    mcp_tool_name,
    tools_call_records,
)
from harness.model_flow import run_until_triggered
from harness.model_run import allowed_tools_for, stdio_server_entry
from harness.repeat import evaluate_s_rate, record_s_sample, start_repeat
from harness.wire import message_method

pytestmark = [pytest.mark.model, pytest.mark.timeout(MODEL_TEST_TIMEOUT_S)]

# Not a secret: the canary of the smoke toolset; these fakes never return it.
UNUSED_CANARY = "canary-not-used-by-calc-or-ticket"

# ---------------------------------------------------------------- D15/T1
CALC = "calc"
CALC2 = "calc2"
ADD = "add"
CALC_SERVERS = (CALC, CALC2)
TARGET = CALC2
OPERAND_MIN = 100
OPERAND_SPAN = 900  # operands in 100..999
SIDE_EFFECT_EVENT = "side_effect"
TOOL_EXECUTED_EVENT = "tool_executed"
TOOLS_LIST = "tools/list"
GROUP_T1 = "D15/T1 right tool among near-duplicates"
CALC_PROMPT = (
    "Call the tool mcp__calc2__add exactly once, with a set to the integer {a} and b set to the integer {b}. "
    "Do not call any other tool. Then reply with only the number the tool returned."
)
CALC_RATED = ("called_mcp__calc2__add", "called_it_exactly_once", "never_called_mcp__calc__add",
              "input_as_prompted")

# ---------------------------------------------------------------- D15/T2+T3
TICKETS = "tickets"
CREATE_TICKET = "create_ticket"
GROUP_T2 = "D15/T2+T3 argument and return value fidelity"
TICKET_TITLE = "Café – 東京 ✓"  # é (U+00E9), en dash (U+2013), CJK, check mark (U+2713)
TICKET_PRIORITY = "medium"
TICKET_DUE = "2026-11-30"
TICKET_META = {"source": "qa-suite", "count": 3}
LEFT_OUT_FIELD = "notes"
FRESH_TAG_PREFIX = "run-"
FRESH_TAG_HEX_BYTES = 3
TICKET_ID_PREFIX = "TCK-"
TICKET_PROMPT = (
    "Call the tool mcp__tickets__create_ticket exactly once, with exactly these arguments (JSON, keep every "
    "value, character and array element exactly as written, in this order, including the empty string tag):\n"
    "{arguments}\n"
    "Do not add any other field; in particular do not set notes. Do not call any other tool. Then reply with "
    "the id of the created ticket exactly as the tool returned it."
)
TICKET_RATED = ("called_create_ticket_exactly_once", "input_as_prompted")


# --------------------------------------------------------------------------
# helpers


def fake_entry(*, sandbox, name, toolset):
    return stdio_server_entry(
        fake_script=STDIO_FAKE_SCRIPT,
        python=PYTHON,
        fake_env=stdio_fake_env(
            name=name, mode="normal", log_path=sandbox.wire_log_path(name=name),
            init_reply_delay_ms=INIT_REPLY_IMMEDIATE_MS, canary=UNUSED_CANARY, toolset=toolset,
        ),
    )


def run_model(*, sandbox, ledger, request, prompt, servers, trigger_names):
    names = sorted(servers)
    return run_until_triggered(
        sandbox=sandbox, ledger=ledger, test_id=request.node.nodeid, prompt=prompt, model=MODEL_ID,
        max_turns=MAX_TURNS, max_budget_usd=MAX_BUDGET_USD_PER_RUN, timeout_s=MODEL_CLI_TIMEOUT_S,
        servers=servers, allowed_tools=allowed_tools_for(servers=names), gate_servers=names, wire_servers=names,
        trigger_names=trigger_names, require_all_triggers=False, retries=INCONCLUSIVE_RETRIES,
        rejected_exit_code=MODEL_REJECTED_EXIT_CODE, extra_args=[], attempt_checks=[],
    )


def final_text(*, stream):
    if stream.result is None or "result" not in stream.result:
        return None
    return stream.result["result"]


def assert_served_tools_list(*, records, server):
    """D, the precondition of a 'must not call' check (doc 11): the fake
    answered tools/list in this run."""
    lists = [r for r in records if r["event"] == "recv" and message_method(message=r["msg"]) == TOOLS_LIST]
    expect_true(what="%s: tools/list requests received in this run" % server, expected="at least 1",
                actual=len(lists), holds=bool(lists))
    replied = [r for r in records if r["event"] == "sent" and r["pid"] == lists[0]["pid"]
               and "id" in r["msg"] and r["msg"]["id"] == lists[0]["msg"]["id"] and "result" in r["msg"]]
    expect_equal(what="%s: result replies to the first tools/list" % server, expected=1, actual=len(replied))


def assert_results_before_final(*, stream, d_views):
    expect_true(what="final result event in the stream", expected="present", actual="present"
                if stream.result is not None else "absent", holds=stream.result is not None)
    result_index = stream.events.index(stream.result)
    expect_equal(what="stream line of the result event", expected=len(stream.events) - 1, actual=result_index)
    for view in d_views:
        for row in view["results"]:
            expect_true(what="stream line of the tool_result of %s" % row["tool_use_id"],
                        expected="before the result event (line %d)" % result_index,
                        actual="line %d" % row["tool_result_index"], holds=row["tool_result_index"] < result_index)


def log_s_facts(*, rated, recorded, detail):
    """One log line per S fact (recorded or rated, never asserted here)."""
    for key in sorted(rated):
        record(what="%s (rated)" % key, value=rated[key])
    for key in sorted(recorded):
        record(what=key, value=recorded[key])
    got(what="final answer", value=detail["final_text"])


def assert_s_rate(*, summary, group):
    got(what="S rate of %s" % group, value="%d/%d passes, per fact %s" % (
        summary["passes"], summary["repeats_ran"], summary["per_rated_fact"]))
    expect_true(what="S pass rate of %s" % group, expected=">= %d of %d" % (S_RATE_MIN_PASSES, REPEATS),
                actual="%d of %d; runs %s" % (summary["passes"], summary["repeats_ran"], summary["runs"]),
                holds=summary["passes"] >= S_RATE_MIN_PASSES)


def item_rates_file():
    """The suite-level s-rates.json (set by harness.entrypoint)."""
    return os.environ[RATES_FILE_ENV]


def skip_inconclusive(*, request, group, repeat, rated_names, triggered):
    """Record the inconclusive repeat as an S miss, then skip it."""
    record_s_sample(config=request.config, group=group, repeat=repeat,
                    rated={name: False for name in rated_names}, recorded={}, inconclusive=triggered.inconclusive)
    record(what="repeat %d of %s" % (repeat, group), value="S miss: %s" % triggered.inconclusive)
    pytest.skip("%s (after %d attempt(s), retry logged in run.json)" % (triggered.inconclusive,
                                                                         len(triggered.attempts)))


# --------------------------------------------------------------------------
# D15/T1


def calc_servers(*, sandbox):
    return {
        CALC: fake_entry(sandbox=sandbox, name=CALC, toolset=TOOLSET_CALC),
        CALC2: fake_entry(sandbox=sandbox, name=CALC2, toolset=TOOLSET_CALC_SIDE_EFFECT),
    }


def fresh_operands():
    return OPERAND_MIN + secrets.randbelow(OPERAND_SPAN), OPERAND_MIN + secrets.randbelow(OPERAND_SPAN)


def calc_s_facts(*, stream, a, b):
    """(rated, recorded, detail) S facts of one D15/T1 run."""
    target = stream.tool_uses_named(name=mcp_tool_name(server=TARGET, tool=ADD))
    other = stream.tool_uses_named(name=mcp_tool_name(server=CALC, tool=ADD))
    expected = {"a": a, "b": b}
    text = final_text(stream=stream)
    rated = {
        "called_mcp__calc2__add": bool(target),
        "called_it_exactly_once": len(target) == 1,
        "never_called_mcp__calc__add": not other,
        "input_as_prompted": bool(target) and all(
            canonical(value=use.input) == canonical(value=expected) for use in target),
    }
    recorded = {"final_answer_has_sum": isinstance(text, str) and str(a + b) in text}
    detail = {
        "expected_input": expected,
        "tool_use_names": [use.name for use in stream.tool_uses],
        "inputs": [use.input for use in target + other],
        "input_diffs": [field_diff(expected=expected, actual=use.input, path="$") for use in target],
        "final_text": text,
    }
    return rated, recorded, detail


def calc_executions(*, records, event):
    return [r for r in records if r["event"] == event]


def check_calc_d(*, sandbox, triggered, negotiation):
    """Every D fact of one D15/T1 run (module docstring). Returns the view."""
    stream = triggered.run.stream
    records = triggered.records
    eras = {server: assert_era(records=records[server], negotiation=negotiation) for server in CALC_SERVERS}
    assert_tool_search_tool(stream=stream, expected=False)
    assert_tools_advertised(stream=stream, names=[mcp_tool_name(server=server, tool=ADD) for server in CALC_SERVERS])
    for server in CALC_SERVERS:
        assert_served_tools_list(records=records[server], server=server)

    # Routing: per server, tools/call == the tool_use blocks named for it.
    d_views = [d_passthrough(stream=stream, records=records[server], server=server, tool=ADD)
               for server in CALC_SERVERS]

    # The fakes' own execution records: which server really ran add.
    executed = {}
    for server in CALC_SERVERS:
        calls = tools_call_records(records=records[server])
        runs = calc_executions(records=records[server], event=TOOL_EXECUTED_EVENT)
        effects = calc_executions(records=records[server], event=SIDE_EFFECT_EVENT)
        call_ids = sorted(call["msg"]["id"] for call in calls)
        got(what="%s: tools/call ids, tool_executed records, side_effect records" % server,
            value=(call_ids, len(runs), len(effects)))
        expect_equal(what="%s: JSON-RPC ids of its tool_executed records vs its tools/call ids" % server,
                     expected=call_ids, actual=sorted(r["rpc_id"] for r in runs))
        expect_equal(what="%s: (server, tool) of its tool_executed records" % server,
                     expected=[(server, ADD)] * len(runs), actual=[(r["server"], r["tool"]) for r in runs])
        if server == CALC2:
            expect_equal(what="calc2: JSON-RPC ids of its side_effect records vs its tools/call ids",
                         expected=call_ids, actual=sorted(r["rpc_id"] for r in effects))
        else:
            expect_equal(what="%s: side_effect records" % server, expected=[], actual=effects)
        executed[server] = {"tools_call_ids": call_ids, "side_effects": len(effects)}
    assert_results_before_final(stream=stream, d_views=d_views)
    view = {"era_seen": eras, "d": d_views, "executed": executed}
    sandbox.record.observe(key="d_view", value=view)
    return view


def calc_run(*, sandbox, ledger, request):
    """One D15/T1 run with fresh operands. Returns (triggered, a, b)."""
    a, b = fresh_operands()
    sandbox.record.observe(key="operands", value={"a": a, "b": b})
    step(text="servers calc (toolset calc) and calc2 (toolset calc_side_effect), both with add(a, b); prompt names "
              "mcp__calc2__add with a=%d, b=%d" % (a, b))
    triggered = run_model(
        sandbox=sandbox, ledger=ledger, request=request, prompt=CALC_PROMPT.format(a=a, b=b),
        servers=calc_servers(sandbox=sandbox),
        trigger_names=[mcp_tool_name(server=server, tool=ADD) for server in CALC_SERVERS],
    )
    return triggered, a, b


@pytest.mark.parametrize("repeat", range(REPEATS))
def test_right_tool_among_near_duplicates(model_sandbox, cost_ledger, request, repeat):
    model_sandbox.set_env(name=TOOL_SEARCH_ENV, value=TOOL_SEARCH_OFF, secret=False)
    model_sandbox.record.observe(key="repeat", value={"index": repeat, "of": REPEATS, "group": GROUP_T1})
    start_repeat(config=request.config, group=GROUP_T1, repeat=repeat)
    triggered, a, b = calc_run(sandbox=model_sandbox, ledger=cost_ledger, request=request)
    if triggered.inconclusive is not None:
        skip_inconclusive(request=request, group=GROUP_T1, repeat=repeat, rated_names=CALC_RATED,
                          triggered=triggered)
    rated, recorded, detail = calc_s_facts(stream=triggered.run.stream, a=a, b=b)
    record_s_sample(config=request.config, group=GROUP_T1, repeat=repeat, rated=rated, recorded=recorded,
                    inconclusive=None)
    model_sandbox.record.observe(key="s_facts", value={"rated": rated, "recorded": recorded, "detail": detail})
    log_s_facts(rated=rated, recorded=recorded, detail=detail)
    check_calc_d(sandbox=model_sandbox, triggered=triggered, negotiation=NEGOTIATION_LEGACY)


# The rate item runs after its repeats because pytest runs the items of a
# file in definition order (parametrized repeats first). A plugin that
# reorders or distributes items (pytest-randomly, xdist) would break that;
# the suite uses neither. Run alone (`-k s_rate`), it sees 0 of REPEATS
# repeats and skips as inconclusive.
def test_right_tool_among_near_duplicates_s_rate(request, item_artifact_dir):
    summary = evaluate_s_rate(
        config=request.config, group=GROUP_T1, repeats=REPEATS, min_passes=S_RATE_MIN_PASSES,
        rates_file=item_rates_file(), artifact_dir=item_artifact_dir,
    )
    assert_s_rate(summary=summary, group=GROUP_T1)


@pytest.mark.parametrize("run_index", range(UNSET_ERA_RUNS))
def test_right_tool_among_near_duplicates_negotiation_unset(model_sandbox, cost_ledger, request, run_index):
    """Doc 11: P0 wire tests also run with MCP_PROTOCOL_NEGOTIATION unset.
    Once (UNSET_ERA_RUNS), not repeated: the D asserts are the same as in
    the legacy repeats; S is recorded only (no rate from one run)."""
    model_sandbox.set_env(name=TOOL_SEARCH_ENV, value=TOOL_SEARCH_OFF, secret=False)
    model_sandbox.unset_env(name=NEGOTIATION_ENV)
    triggered, a, b = calc_run(sandbox=model_sandbox, ledger=cost_ledger, request=request)
    if triggered.inconclusive is not None:
        pytest.skip("%s (after %d attempt(s))" % (triggered.inconclusive, len(triggered.attempts)))
    rated, recorded, detail = calc_s_facts(stream=triggered.run.stream, a=a, b=b)
    model_sandbox.record.observe(key="s_facts", value={"rated": rated, "recorded": recorded, "detail": detail})
    log_s_facts(rated=rated, recorded=recorded, detail=detail)
    check_calc_d(sandbox=model_sandbox, triggered=triggered, negotiation=NEGOTIATION_UNSET_LABEL)


# --------------------------------------------------------------------------
# D15/T2+T3


def ticket_arguments():
    """The values the prompt fixes; one tag is fresh per repeat."""
    return {
        "title": TICKET_TITLE,
        "priority": TICKET_PRIORITY,
        "tags": ["zeta", "", "alpha", FRESH_TAG_PREFIX + secrets.token_hex(FRESH_TAG_HEX_BYTES)],
        "due": TICKET_DUE,
        "meta": dict(TICKET_META),
    }


def ticket_s_facts(*, stream, expected, ticket_ids):
    uses = stream.tool_uses_named(name=mcp_tool_name(server=TICKETS, tool=CREATE_TICKET))
    text = final_text(stream=stream)
    first = uses[0].input if uses else {}
    rated = {
        "called_create_ticket_exactly_once": len(uses) == 1,
        "input_as_prompted": bool(uses) and all(
            canonical(value=use.input) == canonical(value=expected) for use in uses),
    }
    recorded = {
        "final_answer_has_server_id": isinstance(text, str) and bool(ticket_ids)
        and all(ticket_id in text for ticket_id in ticket_ids),
        "input_title_exact": "title" in first and first["title"] == expected["title"],
        "input_empty_tag_kept": "tags" in first and "" in first["tags"],
        "input_tag_order_kept": "tags" in first and first["tags"] == expected["tags"],
        "input_notes_absent": LEFT_OUT_FIELD not in first,
    }
    detail = {
        "expected_input": expected,
        "inputs": [use.input for use in uses],
        "input_diffs": [field_diff(expected=expected, actual=use.input, path="$") for use in uses],
        "server_ticket_ids": ticket_ids,
        "final_text": text,
    }
    return rated, recorded, detail


def server_ticket_ids(*, records):
    return [r["ticket_id"] for r in records if r["event"] == TOOL_EXECUTED_EVENT and r["tool"] == CREATE_TICKET]


def check_ticket_d(*, sandbox, triggered, prompt):
    stream = triggered.run.stream
    records = triggered.records[TICKETS]
    era = assert_era(records=records, negotiation=NEGOTIATION_LEGACY)
    assert_tool_search_tool(stream=stream, expected=False)
    assert_tools_advertised(stream=stream, names=[mcp_tool_name(server=TICKETS, tool=CREATE_TICKET)])

    # One call per tool_use; arguments field for field (canonical JSON);
    # tool_result text == the fake's own reply for that JSON-RPC id.
    d_view = d_passthrough(stream=stream, records=records, server=TICKETS, tool=CREATE_TICKET)
    uses = stream.tool_uses_named(name=mcp_tool_name(server=TICKETS, tool=CREATE_TICKET))
    calls = tools_call_records(records=records)
    by_rpc = {call["msg"]["id"]: call for call in calls}
    executions = [r for r in records if r["event"] == TOOL_EXECUTED_EVENT]
    for use, row in zip(uses, d_view["results"]):
        wire = by_rpc[row["rpc_id"]]["msg"]["params"]["arguments"]
        # The left-out field: absent on the wire, not null, whenever the
        # model left it out (field_diff in d_passthrough covers it too; this
        # names it).
        if LEFT_OUT_FIELD not in use.input:
            expect_not_in(what="argument names on the wire (%s is absent from tool_use.input)" % LEFT_OUT_FIELD,
                          item=LEFT_OUT_FIELD, container=sorted(wire))
        # The server-generated id flows back in the tool_result.
        executed = [r for r in executions if r["rpc_id"] == row["rpc_id"] and r["pid"] == by_rpc[row["rpc_id"]]["pid"]]
        expect_equal(what="tool_executed records for JSON-RPC id %r" % (row["rpc_id"],), expected=1,
                     actual=len(executed))
        ticket_id = executed[0]["ticket_id"]
        got(what="server-generated ticket id", value=ticket_id)
        expect_true(what="server-generated ticket id", expected="starts with %r and is not in the prompt"
                    % TICKET_ID_PREFIX, actual=ticket_id,
                    holds=ticket_id.startswith(TICKET_ID_PREFIX) and ticket_id not in prompt)
        expect_true(what="the server id %s in the tool_result text of %s" % (ticket_id, use.id),
                    expected="contained", actual=row["tool_result_text"], holds=ticket_id in row["tool_result_text"])
        # Type-strict (canonical JSON): a plain == would let 3 == 3.0 and True == 1 pass.
        expect_equal(what="the fake's echo of the arguments vs the arguments it logged (canonical JSON)",
                     expected=canonical(value=wire),
                     actual=canonical(value=json.loads(row["tool_result_text"])["echo"]))
    assert_results_before_final(stream=stream, d_views=[d_view])
    view = {"era_seen": era, "d": d_view}
    sandbox.record.observe(key="d_view", value=view)
    return view


@pytest.mark.parametrize("repeat", range(REPEATS))
def test_ticket_arguments_and_result_fidelity(model_sandbox, cost_ledger, request, repeat):
    model_sandbox.set_env(name=TOOL_SEARCH_ENV, value=TOOL_SEARCH_OFF, secret=False)
    model_sandbox.record.observe(key="repeat", value={"index": repeat, "of": REPEATS, "group": GROUP_T2})
    start_repeat(config=request.config, group=GROUP_T2, repeat=repeat)
    expected = ticket_arguments()
    prompt = TICKET_PROMPT.format(arguments=json.dumps(expected, ensure_ascii=False))
    model_sandbox.record.observe(key="prompt_arguments", value=expected)
    step(text="server tickets (toolset ticket); prompt fixes create_ticket arguments %s" % json.dumps(
        expected, ensure_ascii=False))
    triggered = run_model(
        sandbox=model_sandbox, ledger=cost_ledger, request=request, prompt=prompt,
        servers={TICKETS: fake_entry(sandbox=model_sandbox, name=TICKETS, toolset=TOOLSET_TICKET)},
        trigger_names=[mcp_tool_name(server=TICKETS, tool=CREATE_TICKET)],
    )
    if triggered.inconclusive is not None:
        skip_inconclusive(request=request, group=GROUP_T2, repeat=repeat, rated_names=TICKET_RATED,
                          triggered=triggered)
    rated, recorded, detail = ticket_s_facts(
        stream=triggered.run.stream, expected=expected, ticket_ids=server_ticket_ids(records=triggered.records[TICKETS])
    )
    record_s_sample(config=request.config, group=GROUP_T2, repeat=repeat, rated=rated, recorded=recorded,
                    inconclusive=None)
    model_sandbox.record.observe(key="s_facts", value={"rated": rated, "recorded": recorded, "detail": detail})
    log_s_facts(rated=rated, recorded=recorded, detail=detail)
    check_ticket_d(sandbox=model_sandbox, triggered=triggered, prompt=prompt)


# The rate item runs after its repeats because pytest runs the items of a
# file in definition order (parametrized repeats first). A plugin that
# reorders or distributes items (pytest-randomly, xdist) would break that;
# the suite uses neither. Run alone (`-k s_rate`), it sees 0 of REPEATS
# repeats and skips as inconclusive.
def test_ticket_arguments_and_result_fidelity_s_rate(request, item_artifact_dir):
    summary = evaluate_s_rate(
        config=request.config, group=GROUP_T2, repeats=REPEATS, min_passes=S_RATE_MIN_PASSES,
        rates_file=item_rates_file(), artifact_dir=item_artifact_dir,
    )
    assert_s_rate(summary=summary, group=GROUP_T2)
