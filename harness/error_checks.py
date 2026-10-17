"""Checks for failing tool calls (doc 16 tool errors, doc 20 crash).

  d_error_result   D: each tool_use of a failing tool reached the fake as
                   one tools/call (same name, arguments == input), the fake
                   answered it the expected way (an isError result, or a
                   JSON-RPC error object), and the tool_use got exactly one
                   tool_result with is_error true that holds the fresh token.
                   The exact content, and how it relates to the text the
                   fake sent (equal, prefix, suffix), is recorded.
  hook_failures_for  D: PostToolUseFailure fired exactly once for each
                   given tool_use (tool_use_id, tool_name, mcp_server.name),
                   and never for the given tool_use ids that succeeded.
  spawns           the number of fake processes started in a window (each
                   start writes one `started` record with its pid).
  event_epoch      wall-clock time of a stream event (its `timestamp`).
"""

from datetime import datetime

from harness.check import expect_equal, expect_in, expect_true, got
from harness.constants import HOOK_POST_TOOL_USE_FAILURE
from harness.hooks import hook_events
from harness.model_checks import (
    call_arguments,
    canonical,
    field_diff,
    mcp_tool_name,
    pair_calls_to_uses,
    server_reply,
    tools_call_records,
)

REPLY_IS_ERROR_RESULT = "result with isError: true"
REPLY_JSONRPC_ERROR = "JSON-RPC error object"


def event_epoch(*, event):
    """The stream event's `timestamp` (ISO 8601, ms, `Z`) as epoch seconds."""
    return datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00")).timestamp()


def reply_kind(*, sent):
    msg = sent["msg"]
    if "error" in msg:
        return REPLY_JSONRPC_ERROR
    if "result" in msg and "isError" in msg["result"] and msg["result"]["isError"] is True:
        return REPLY_IS_ERROR_RESULT
    return "other: %s" % canonical(value=msg)


def fake_error_text(*, sent):
    """The error text the fake sent: error.message, or the result's text blocks."""
    msg = sent["msg"]
    if "error" in msg:
        return msg["error"]["message"]
    return "".join(block["text"] for block in msg["result"]["content"] if block["type"] == "text")


def relation(*, shown, sent):
    """How the tool_result text relates to the fake's own error text."""
    if shown == sent:
        return {"kind": "equal", "prefix": "", "suffix": ""}
    at = shown.find(sent)
    if at < 0:
        return {"kind": "fake text not contained", "prefix": None, "suffix": None}
    return {"kind": "contains", "prefix": shown[:at], "suffix": shown[at + len(sent):]}


def d_error_result(*, stream, records, server, tool, token, expected_reply):
    """Hard asserts for every tool_use of mcp__<server>__<tool>, a tool the
    fake always fails. expected_reply: REPLY_IS_ERROR_RESULT or
    REPLY_JSONRPC_ERROR. Returns the run.json view (exact stream content)."""
    name = mcp_tool_name(server=server, tool=tool)
    uses = stream.tool_uses_named(name=name)
    call_records = [r for r in tools_call_records(records=records) if r["msg"]["params"]["name"] == tool]
    expect_equal(what="tools/call for %r that reached %s (one per %s tool_use)" % (tool, server, name),
                 expected=len(uses), actual=len(call_records))
    expect_equal(what="tools/call arguments on the wire vs tool_use.input of %s (canonical JSON, sorted)" % name,
                 expected=sorted(canonical(value=u.input) for u in uses),
                 actual=sorted(canonical(value=call_arguments(call=r["msg"])) for r in call_records))
    pairs = pair_calls_to_uses(call_records=call_records, uses=uses)
    view = []
    for use in uses:
        record = pairs[use.id]
        diff = field_diff(expected=use.input, actual=call_arguments(call=record["msg"]), path="$")
        expect_equal(what="fields where tools/call id %r differs from the input of tool_use %s" % (
            record["msg"]["id"], use.id), expected=[], actual=diff)
        sent = server_reply(records=records, call_record=record)
        kind = reply_kind(sent=sent)
        expect_equal(what="kind of the fake's reply to tools/call %r" % (record["msg"]["id"],), expected=expected_reply,
                     actual=kind)
        results = stream.result_for(tool_use_id=use.id)
        expect_equal(what="tool_result blocks for tool_use %s" % use.id, expected=1, actual=len(results))
        result = results[0]
        text = result.text()
        got(what="error tool_result of %s (is_error %r)" % (use.id, result.is_error), value=text)
        sent_text = fake_error_text(sent=sent)
        view.append({
            "tool_use_id": use.id,
            "rpc_id": record["msg"]["id"],
            "fake_reply_kind": kind,
            "fake_sent": sent["msg"],
            "tool_result_index": result.index,
            "tool_result_is_error": result.is_error,
            "tool_result_content": result.content,
            "tool_result_content_is_string": isinstance(result.content, str),
            "tool_result_text": text,
            "relation_to_fake_text": relation(shown=text, sent=sent_text),
            "tool_use_result": stream.events[result.index]["tool_use_result"]
            if "tool_use_result" in stream.events[result.index] else "(key absent)",
        })
        expect_true(what="is_error of the tool_result for %s" % use.id, expected="True",
                    actual="%r (text %r)" % (result.is_error, text), holds=result.is_error is True)
        expect_in(what="the fresh token in the tool_result text of %s" % use.id, item=token, container=text)
        expect_true(what="stream line of the tool_result for %s" % use.id,
                    expected="after its tool_use (line %d)" % use.index, actual="line %d" % result.index,
                    holds=use.index < result.index)
    return view


def hook_failures_for(*, entries, server, failed_uses, succeeded_use_ids):
    """D: one PostToolUseFailure per failed tool_use (matching id and name,
    and the `mcp_server` object of an MCP tool naming the server,
    hooks.md:2261), none for a succeeded tool_use id. Returns the view."""
    failures = hook_events(entries=entries, event_name=HOOK_POST_TOOL_USE_FAILURE)
    view = []
    for use in failed_uses:
        hits = [e for e in failures if e["input"]["tool_use_id"] == use.id]
        view.append({"tool_use_id": use.id, "fired": len(hits), "inputs": [e["input"] for e in hits],
                     "epochs": [e["epoch"] for e in hits]})
        expect_equal(what="PostToolUseFailure hook runs for tool_use %s (%s)" % (use.id, use.name), expected=1,
                     actual=len(hits))
        expect_equal(what="tool_name in the PostToolUseFailure input of %s" % use.id, expected=use.name,
                     actual=hits[0]["input"]["tool_name"])
        hook_input = hits[0]["input"]
        expect_equal(what="mcp_server.name in the PostToolUseFailure input of %s" % use.id, expected=server,
                     actual=hook_input["mcp_server"]["name"] if "mcp_server" in hook_input
                     else "(no mcp_server key; input %s)" % hook_input)
    stray = [e for e in failures if e["input"]["tool_use_id"] in succeeded_use_ids]
    expect_equal(what="PostToolUseFailure hook runs for tool calls that succeeded", expected=[], actual=stray)
    return view


def spawns(*, records):
    """[pid] of every `started` record, in order."""
    return [r["pid"] for r in records if r["event"] == "started"]
