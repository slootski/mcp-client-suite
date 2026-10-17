"""Checks shared by every model test (doc 11, doc 22): the connected gate,
the run stops (model_rejected, key_rejected), the D checks (hard asserts:
d_passthrough, assert_every_call_has_a_tool_use, assert_era,
assert_tool_search_tool, assert_tools_advertised) and the S input (s_input,
recorded only). A tools/call is paired with its tool_use as
pair_calls_to_uses says (docs/flake-policy.md, the toolUseId row).
"""

import json
import logging

import pytest

from harness.check import expect_equal, expect_in, expect_not_in, expect_true, got
from harness.constants import (API_KEY_REJECTED_STATUSES, API_RETRY_AUTH_FAILED, FIRST_MESSAGE_NEGOTIATION_UNSET,
                               LEGACY_PROTOCOL_VERSION, NEGOTIATION_LEGACY)
from harness.wire import message_method

logger = logging.getLogger(__name__)

CONNECTED = "connected"
TOOL_USE_ID_META = "claudecode/toolUseId"  # observed on 2.1.296, undocumented
TOOLS_CALL = "tools/call"
INITIALIZE = "initialize"
MCP_PREFIX = "mcp__"
# headless.md "Handle API retries": the error category of a rejected model.
MODEL_NOT_FOUND = "model_not_found"
TOOL_SEARCH_TOOL = "ToolSearch"
# The label of a run with MCP_PROTOCOL_NEGOTIATION removed from the env.
NEGOTIATION_UNSET_LABEL = "unset"


def mcp_tool_name(*, server, tool):
    """mcp__<server>__<tool> (R01, Tool naming)."""
    return "%s%s__%s" % (MCP_PREFIX, server, tool)


def server_statuses(*, init):
    return {entry["name"]: entry["status"] for entry in init["mcp_servers"]}


def gate_problem(*, stream, servers):
    """None when every named server is `connected` in system/init, else the
    inconclusive reason ("inconclusive: <server>=<status>")."""
    if stream.init is None:
        return "inconclusive: no system/init event in the stream"
    statuses = server_statuses(init=stream.init)
    bad = {name: (statuses[name] if name in statuses else "absent from mcp_servers") for name in servers
           if name not in statuses or statuses[name] != CONNECTED}
    if bad:
        return "inconclusive: %s" % ", ".join("%s=%s" % (name, bad[name]) for name in sorted(bad))
    return None


def gate(*, stream, servers):
    """Skip as inconclusive unless every named server is connected."""
    problem = gate_problem(stream=stream, servers=servers)
    if problem is not None:
        pytest.skip(problem)


def model_rejected(*, stream, model):
    """A reason string when the run shows MODEL_ID was not accepted, else None."""
    retries = stream.events_of(event_type="system", subtype="api_retry")
    if any(event["error"] == MODEL_NOT_FOUND for event in retries):
        return "api_retry error %s for --model %s" % (MODEL_NOT_FOUND, model)
    if stream.init is not None and stream.init["model"] != model:
        return "system/init model is %r, asked for %r" % (stream.init["model"], model)
    return None


def key_rejected(*, stream):
    """A reason when the API rejected the key, else None: result
    `api_error_status` (observed on 2.1.296, null on success; not in
    headless.md) or api_retry `error_status` (headless.md:247) is 401/403,
    or api_retry `error` is authentication_failed (headless.md:249)."""
    result = stream.result
    if result is not None and "api_error_status" in result and result["api_error_status"] in API_KEY_REJECTED_STATUSES:
        return "result api_error_status %s" % result["api_error_status"]
    # The first 401/403 api_retry stops the run, even if a later retry would pass: fine, the
    # suite sets ANTHROPIC_API_KEY, not apiKeyHelper (headless.md:238). A 403 billing_error lands here too.
    for event in stream.events_of(event_type="system", subtype="api_retry"):
        if "error" in event and event["error"] == API_RETRY_AUTH_FAILED:
            return "api_retry error %s" % API_RETRY_AUTH_FAILED
        if "error_status" in event and event["error_status"] in API_KEY_REJECTED_STATUSES:
            return "api_retry error_status %s" % event["error_status"]
    return None


def init_summary(*, stream):
    """The system/init fields the suite reads, for run.json."""
    init = stream.init
    if init is None:
        return None
    return {
        "model": init["model"],
        "mcp_servers": init["mcp_servers"],
        "mcp_server_errors": init["mcp_server_errors"] if "mcp_server_errors" in init else "(key omitted)",
        "mcp_tools": sorted(tool for tool in init["tools"] if tool.startswith(MCP_PREFIX)),
        "has_tool_search_tool": TOOL_SEARCH_TOOL in init["tools"],
    }


def result_summary(*, stream):
    result = stream.result
    if result is None:
        return None
    keys = ("subtype", "is_error", "num_turns", "total_cost_usd", "permission_denials", "result")
    return {key: result[key] for key in keys if key in result}


def received_messages(*, records):
    return [record["msg"] for record in records if record["event"] == "recv"]


def era_seen(*, records):
    """First message the fake received, and the protocolVersion asked in
    initialize (doc 11: run.json carries the era seen)."""
    messages = received_messages(records=records)
    if not messages:
        return {"first_message": None, "initialize_protocol_version": None}
    inits = [m for m in messages if message_method(message=m) == INITIALIZE]
    return {
        "first_message": message_method(message=messages[0]),
        "initialize_protocol_version": inits[0]["params"]["protocolVersion"] if inits else None,
    }


def tools_call_records(*, records):
    """The fake's `recv` records of tools/call requests (msg, pid, epoch)."""
    return [r for r in records if r["event"] == "recv" and message_method(message=r["msg"]) == TOOLS_CALL]


def tools_calls(*, records):
    return [record["msg"] for record in tools_call_records(records=records)]


def canonical(*, value):
    """Type-strict JSON form: 1, 1.0, true and "1" all differ; dict key order
    does not matter; list order does; an absent key differs from null."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def field_diff(*, expected, actual, path):
    """Paths where two JSON values differ, type-strict (canonical form).
    Lists by index, dicts by key; an absent key is reported as absent, not
    null. path: the prefix of the reported paths ("$" at the top)."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        out = []
        for key in sorted(set(expected) | set(actual)):
            where = "%s.%s" % (path, key)
            if key not in actual:
                out.append("%s: absent, expected %s" % (where, canonical(value=expected[key])))
            elif key not in expected:
                out.append("%s: %s, expected absent" % (where, canonical(value=actual[key])))
            else:
                out += field_diff(expected=expected[key], actual=actual[key], path=where)
        return out
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return ["%s: %s, expected %s" % (path, canonical(value=actual), canonical(value=expected))]
        out = []
        for index, (want, have) in enumerate(zip(expected, actual)):
            out += field_diff(expected=want, actual=have, path="%s[%d]" % (path, index))
        return out
    if canonical(value=expected) != canonical(value=actual):
        return ["%s: %s, expected %s" % (path, canonical(value=actual), canonical(value=expected))]
    return []


def call_arguments(*, call):
    """params.arguments of a tools/call message; None when the key is absent."""
    return call["params"]["arguments"] if "arguments" in call["params"] else None


def server_reply(*, records, call_record):
    """The fake's own `sent` record answering this tools/call: same JSON-RPC
    id, same fake process (ids restart in a new process)."""
    request_id = call_record["msg"]["id"]
    hits = [r for r in records if r["event"] == "sent" and r["pid"] == call_record["pid"]
            and isinstance(r["msg"], dict) and "id" in r["msg"] and r["msg"]["id"] == request_id
            and "method" not in r["msg"]]
    expect_equal(what="replies the fake sent to tools/call id %r" % (request_id,), expected=1, actual=len(hits))
    return hits[0]


def reply_text(*, sent):
    """The text a tools/call reply carries: its text blocks joined."""
    result = sent["msg"]["result"]
    return "".join(block["text"] for block in result["content"] if block["type"] == "text")


def has_tool_use_meta(*, call):
    params = call["params"]
    return "_meta" in params and TOOL_USE_ID_META in params["_meta"]


def pair_calls_to_uses(*, call_records, uses):
    """{tool_use id: tools/call record}. By `_meta["claudecode/toolUseId"]`
    when the call carries it (observed on 2.1.296); a call without it is
    paired with the one remaining tool_use whose input equals its arguments,
    and an ambiguous or missing match fails."""
    by_id = {use.id: use for use in uses}
    pairs = {}
    unpaired = []
    for record in call_records:
        if has_tool_use_meta(call=record["msg"]):
            use_id = record["msg"]["params"]["_meta"][TOOL_USE_ID_META]
            expect_in(what="tool_use ids of the stream, for the %s of tools/call id %r" % (
                TOOL_USE_ID_META, record["msg"]["id"]), item=use_id, container=sorted(by_id))
            expect_not_in(what="tool_use ids already paired with another tools/call", item=use_id,
                          container=sorted(pairs))
            pairs[use_id] = record
        else:
            unpaired.append(record)
    for record in unpaired:
        wire = canonical(value=call_arguments(call=record["msg"]))
        candidates = [use.id for use in uses if use.id not in pairs and canonical(value=use.input) == wire]
        expect_true(what="tool_use to pair with tools/call id %r (no %s)" % (record["msg"]["id"], TOOL_USE_ID_META),
                    expected="exactly 1 unpaired tool_use with input == the call's arguments",
                    actual="candidates %s" % candidates, holds=len(candidates) == 1)
        pairs[candidates[0]] = record
    return pairs


def d_passthrough(*, stream, records, server, tool):
    """Hard asserts of the D half for one server tool (doc 11, doc 22), for
    0..n tool_use blocks named mcp__<server>__<tool>:
      * the fake got exactly one tools/call per tool_use, under the tool's
        own name, and none when there is no tool_use (routing);
      * each call's arguments == its tool_use.input (canonical JSON, so an
        absent key, a null, a type change or a reorder all fail);
      * each tool_use has exactly one tool_result, it is not an error, and
        its text is the text the fake itself sent for that JSON-RPC id.
    Call only after the trigger happened (some tool_use exists in the run):
    with no tool_use at all, "no call" proves nothing. Returns the run.json
    view."""
    name = mcp_tool_name(server=server, tool=tool)
    uses = stream.tool_uses_named(name=name)
    call_records = [r for r in tools_call_records(records=records) if r["msg"]["params"]["name"] == tool]
    use_side = sorted(canonical(value=use.input) for use in uses)
    wire_side = sorted(canonical(value=call_arguments(call=r["msg"])) for r in call_records)
    got(what="%s: tool_use input(s) in the stream" % name, value=use_side)
    got(what="%s: tools/call arguments on the wire of %s" % (name, server), value=wire_side)
    expect_equal(what="tools/call for %r that reached server %s (one per %s tool_use)" % (tool, server, name),
                 expected=len(uses), actual=len(call_records))
    expect_equal(what="tools/call arguments on the wire vs tool_use.input of %s (canonical JSON, sorted)" % name,
                 expected=use_side, actual=wire_side)
    pairs = pair_calls_to_uses(call_records=call_records, uses=uses)
    results_view = []
    for use in uses:
        record = pairs[use.id]
        diff = field_diff(expected=use.input, actual=call_arguments(call=record["msg"]), path="$")
        expect_equal(what="fields where tools/call id %r differs from the input of tool_use %s" % (
            record["msg"]["id"], use.id), expected=[], actual=diff)
        results = stream.result_for(tool_use_id=use.id)
        expect_equal(what="tool_result blocks for tool_use %s" % use.id, expected=1, actual=len(results))
        sent = server_reply(records=records, call_record=record)
        sent_text = reply_text(sent=sent)
        text = results[0].text()
        got(what="tool_result of %s (is_error %r)" % (use.id, results[0].is_error), value=text)
        results_view.append({"tool_use_id": use.id, "rpc_id": record["msg"]["id"], "tool_result_index": results[0].index,
                             "is_error": results[0].is_error, "tool_result_text": text, "server_sent_text": sent_text})
        expect_equal(what="isError of the fake's reply to tools/call %r" % (record["msg"]["id"],), expected=False,
                     actual=sent["msg"]["result"]["isError"])
        expect_true(what="is_error of the tool_result for %s" % use.id, expected="not true (absent or false)",
                    actual=results[0].is_error, holds=results[0].is_error is not True)
        expect_equal(what="tool_result text for %s vs the text the fake sent for JSON-RPC id %r" % (
            use.id, record["msg"]["id"]), expected=sent_text, actual=text)
        expect_true(what="stream line of the tool_result for %s" % use.id,
                    expected="after its tool_use (line %d)" % use.index, actual="line %d" % results[0].index,
                    holds=use.index < results[0].index)
        logger.info("D %s: tool_use %s -> tools/call id %r on %s, args == tool_use.input, tool_result == server text",
                    name, use.id, record["msg"]["id"], server)
    logger.info("D %s: %d tool_use, %d tools/call on %s: one call per tool_use", name, len(uses), len(call_records), server)
    return {
        "server": server,
        "paired_by_meta_tool_use_id": sorted(use_id for use_id in pairs if has_tool_use_meta(call=pairs[use_id]["msg"])),
        "tool_use": [{"id": use.id, "name": use.name, "input": use.input, "index": use.index} for use in uses],
        "tools_call_wire": [record["msg"]["params"] for record in call_records],
        "results": results_view,
    }


def calls_without_tool_use(*, stream, records_by_server):
    """The tools/call records (per server) that no tool_use of the stream
    explains. A call carrying `_meta["claudecode/toolUseId"]` needs a
    tool_use with that id and the name mcp__<server>__<tool>; a call
    without it needs a tool_use of that name whose input equals its
    arguments (canonical JSON). Returns {server: [unexplained call msgs]}."""
    out = {}
    for server in records_by_server:
        unexplained = []
        for record in tools_call_records(records=records_by_server[server]):
            call = record["msg"]
            name = mcp_tool_name(server=server, tool=call["params"]["name"])
            if has_tool_use_meta(call=call):
                use_id = call["params"]["_meta"][TOOL_USE_ID_META]
                ok = any(use.id == use_id and use.name == name for use in stream.tool_uses)
            else:
                wire = canonical(value=call_arguments(call=call))
                ok = any(use.name == name and canonical(value=use.input) == wire for use in stream.tool_uses)
            if not ok:
                unexplained.append(call)
        if unexplained:
            out[server] = unexplained
    return out


def assert_every_call_has_a_tool_use(*, stream, records_by_server):
    """D (client fact, hard): every tools/call that reached a fake in this
    attempt belongs to a tool_use of this attempt's stream. Run on EVERY
    attempt, also one that is inconclusive (no trigger tool_use) and is
    about to be retried or skipped: a call without a tool_use is a D
    failure, not an S miss, and a retry must not hide it (QA step 4)."""
    unexplained = calls_without_tool_use(stream=stream, records_by_server=records_by_server)
    expect_equal(what="tools/call with no tool_use for it in the stream, per server", expected={}, actual={
        server: [{"id": call["id"], "params": call["params"]} for call in unexplained[server]]
        for server in unexplained})


def assert_era(*, records, negotiation):
    """D (client fact under a pin): the first message and the initialize
    revision. negotiation: NEGOTIATION_LEGACY (initialize first, no probe)
    or NEGOTIATION_UNSET_LABEL (server/discover first). Returns era_seen."""
    seen = era_seen(records=records)
    got(what="era seen by the fake (negotiation %s)" % negotiation, value=seen)
    if negotiation == NEGOTIATION_LEGACY:
        expect_equal(what="first message the fake got (negotiation=legacy)", expected=INITIALIZE,
                     actual=seen["first_message"])
    else:
        expect_equal(what="negotiation label of the run", expected=NEGOTIATION_UNSET_LABEL, actual=negotiation)
        expect_equal(what="first message the fake got (negotiation unset)", expected=FIRST_MESSAGE_NEGOTIATION_UNSET,
                     actual=seen["first_message"])
    expect_equal(what="protocolVersion the client asked in initialize", expected=LEGACY_PROTOCOL_VERSION,
                 actual=seen["initialize_protocol_version"])
    return seen


def assert_tool_search_tool(*, stream, expected):
    """D (client fact under the ENABLE_TOOL_SEARCH pin): system/init tools
    holds ToolSearch exactly when tool search is on."""
    present = TOOL_SEARCH_TOOL in stream.init["tools"]
    expect_equal(what="%s in system/init tools" % TOOL_SEARCH_TOOL, expected=expected, actual=present)


def assert_tools_advertised(*, stream, names):
    """D: the client lists each mcp__<server>__<tool> in system/init tools
    (the name the model must use; R01 tool naming)."""
    missing = [name for name in names if name not in stream.init["tools"]]
    expect_true(what="system/init tools list %s" % list(names), expected="none missing",
                actual="missing %s; system/init: %s" % (missing, init_summary(stream=stream)) if missing
                else "none missing", holds=not missing)


def s_input(*, stream, server, tool, expected_input):
    """S half: did the model pass the values the prompt fixed? Recorded only."""
    uses = stream.tool_uses_named(name=mcp_tool_name(server=server, tool=tool))
    return {
        "expected_input": expected_input,
        "inputs": [use.input for use in uses],
        "all_match": bool(uses) and all(canonical(value=use.input) == canonical(value=expected_input) for use in uses),
        "diffs": [field_diff(expected=expected_input, actual=use.input, path="$") for use in uses],
    }
