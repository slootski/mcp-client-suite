"""D23/T9 (PreToolUse hook) and D23/T10 (permission rules) on MCP tools.

Model tier: needs ANTHROPIC_API_KEY, costs tokens (skipped without a key);
one run per item. Servers (stdio fake, legacy era, tool search off):
`guard` (list_items, delete_all) and `guard__ops` (rotate_logs). Every tool
logs `tool_executed`, so "the server never saw the call" is read from the
fake's own log. Every run passes `--permission-prompts none`
(harness/model_run.py).

T9: fakes/guard_hook.py through `--settings`, `--allowedTools "mcp__guard__*"`;
cases deny, ask, matcher_without_wildcard, exit1_default, exit1_on_failure_block.
T10: deny rule, no-allow-rule control, variant A (allow scope) and variant B
(deny scope), A and B strict xfails for 2.1.296 defects. Detail: PLAN.md
D23/T9 and D23/T10; retries and inconclusive items: docs/flake-policy.md;
offline replays: tests/test_harness_offline.py.
"""

import os
import secrets

import pytest

from harness.constants import (
    DISALLOWED_TOOLS_FLAG,
    FAKE_MODE_NORMAL,
    FAKE_PRESENCE_ONLY_MODEL,
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
    TOOLSET_GUARD,
    TOOLSET_OPS,
)
from harness.check import expect_equal, expect_true, got, step
from harness.error_checks import event_epoch
from harness.fakes_ctl import STDIO_FAKE_SCRIPT
from harness.hooks import guard_hook_settings_args, read_hook_log
from harness.known_defects import DocumentedBehaviorMismatch, expect_documented
from harness.mcp_setup import PYTHON, stdio_fake_env
from harness.model_checks import (
    assert_era,
    assert_tool_search_tool,
    assert_tools_advertised,
    d_passthrough,
    gate_problem,
    mcp_tool_name,
    result_summary,
    tools_call_records,
)
from harness.model_flow import run_until_triggered
from harness.model_run import allowed_tools_for, stdio_server_entry

pytestmark = [pytest.mark.model, pytest.mark.timeout(MODEL_TEST_TIMEOUT_S)]

GUARD = "guard"
OPS = "guard__ops"
LIST = "list_items"
DELETE = "delete_all"
ROTATE = "rotate_logs"
LIST_PREFIX = "b"
UNUSED_CANARY = "canary-not-used-by-permission-tests"
HEX_BYTES = 4
CLEANUP_PREFIX = "cleanup-"
DENY_REASON_PREFIX = "denied-by-guard-hook-"
SERVICE_PREFIX = "svc-"
HOOK_LOG_NAME = "guard-hook.jsonl"
PRE_TOOL_USE = "PreToolUse"
ACTION_PASS = "pass"
ACTION_DENY = "deny"
ACTION_EXIT1 = "exit1"
ACTION_ASK = "ask"
HOOK_MODE_DENY = "deny"
HOOK_MODE_ASK = "ask"
HOOK_MODE_FAIL = "fail"
INIT_SUBTYPE = "init"
PERMISSION_DENIED_SUBTYPE = "permission_denied"

# hook_action None: the hook must not run. delete_reaches_server False: no
# tools/call for delete_all, one error tool_result for its tool_use.
T9_CASES = {
    # deny and ask: the reason is in the tool_result (hooks.md:1934; for ask
    # because nobody can answer the prompt in `-p`).
    "deny": {"matcher": "mcp__guard__.*", "mode": HOOK_MODE_DENY, "handler_fields": {},
             "hook_action": ACTION_DENY, "delete_reaches_server": False},
    "ask": {"matcher": "mcp__guard__.*", "mode": HOOK_MODE_ASK, "handler_fields": {},
            "hook_action": ACTION_ASK, "delete_reaches_server": False},
    # hooks.md:365: a matcher with no `.*` "is compared as an exact string and matches no tool".
    "matcher_without_wildcard": {"matcher": "mcp__guard", "mode": HOOK_MODE_DENY, "handler_fields": {},
                                 "hook_action": None, "delete_reaches_server": True},
    # hooks.md:786: exit 1 is a non-blocking error, "The action goes ahead".
    "exit1_default": {"matcher": "mcp__guard__.*", "mode": HOOK_MODE_FAIL, "handler_fields": {},
                      "hook_action": ACTION_EXIT1, "delete_reaches_server": True},
    # hooks.md:904, changelog.md:480 (v2.1.295+): `"onFailure": "block"` blocks the call.
    "exit1_on_failure_block": {"matcher": "mcp__guard__.*", "mode": HOOK_MODE_FAIL,
                               "handler_fields": {"onFailure": "block"},
                               "hook_action": ACTION_EXIT1, "delete_reaches_server": False},
}

ALLOW_SCOPE_DEFECT = ("changelog.md:212 (fixed in 2.1.299): \"Changed MCP allow rules to reach only the server they "
                      "name: `mcp__a` no longer allows a server named `a__b`\"")
DENY_SCOPE_DEFECT = ("changelog.md:297 (fixed in 2.1.299): \"Fixed deny and ask rules for an MCP server "
                     "(`mcp__<server>`) not applying when the server's normalized name contains a double "
                     "underscore\"")

PROMPT_LIST_THEN_DELETE = (
    "This is a test environment with fake data. Step 1: call the tool {list} exactly once, with prefix set to "
    "exactly \"{prefix}\". Step 2: after you have seen its result, call the tool {delete} exactly once, with reason "
    "set to exactly \"{reason}\"; the call is expected and safe here. Do not retry a failed or denied call and do "
    "not call any other tool. Then reply in one short sentence saying what each call returned."
)
PROMPT_LIST_THEN_ROTATE = (
    "This is a test environment with fake data. Step 1: call the tool {list} exactly once, with prefix set to "
    "exactly \"{prefix}\". Step 2: after you have seen its result, call the tool {rotate} exactly once, with "
    "service set to exactly \"{service}\". Do not retry a failed or denied call and do not call any other tool. "
    "Then reply in one short sentence saying what each call returned."
)
PROMPT_ROTATE = (
    "This is a test environment with fake data. Call the tool {rotate} exactly once, with service set to exactly "
    "\"{service}\". Do not retry a failed or denied call and do not call any other tool. Then reply in one short "
    "sentence saying what the call returned."
)


def token(*, prefix):
    return prefix + secrets.token_hex(HEX_BYTES)


def fake_entry(*, sandbox, server, toolset):
    return stdio_server_entry(
        fake_script=STDIO_FAKE_SCRIPT, python=PYTHON,
        fake_env=stdio_fake_env(name=server, mode=FAKE_MODE_NORMAL, log_path=sandbox.wire_log_path(name=server),
                                init_reply_delay_ms=INIT_REPLY_IMMEDIATE_MS, canary=UNUSED_CANARY, toolset=toolset,
                                presence_only_env=FAKE_PRESENCE_ONLY_MODEL),
    )


def servers_for(*, sandbox, names):
    toolsets = {GUARD: TOOLSET_GUARD, OPS: TOOLSET_OPS}
    return {name: fake_entry(sandbox=sandbox, server=name, toolset=toolsets[name]) for name in names}


def run_flow(*, sandbox, ledger, request, names, allowed_tools, prompt, trigger_names, require_all_triggers,
             extra_args):
    sandbox.set_env(name=TOOL_SEARCH_ENV, value=TOOL_SEARCH_OFF, secret=False)
    return run_until_triggered(
        sandbox=sandbox, ledger=ledger, test_id=request.node.nodeid, prompt=prompt, model=MODEL_ID,
        max_turns=MAX_TURNS, max_budget_usd=MAX_BUDGET_USD_PER_RUN, timeout_s=MODEL_CLI_TIMEOUT_S,
        servers=servers_for(sandbox=sandbox, names=names), allowed_tools=allowed_tools, gate_servers=names,
        wire_servers=names, trigger_names=trigger_names, require_all_triggers=require_all_triggers,
        retries=INCONCLUSIVE_RETRIES, rejected_exit_code=MODEL_REJECTED_EXIT_CODE, extra_args=extra_args,
        attempt_checks=[],
    )


def calls_named(*, records, tool):
    return [r for r in tools_call_records(records=records) if r["msg"]["params"]["name"] == tool]


def tool_view(*, stream, name):
    """Every tool_use of `name` with its tool_result(s), as streamed."""
    return [{"id": use.id, "input": use.input, "index": use.index,
             "tool_results": [{"is_error": r.is_error, "text": r.text(), "index": r.index}
                              for r in stream.result_for(tool_use_id=use.id)]}
            for use in stream.tool_uses_named(name=name)]


def denials_view(*, stream):
    """result.permission_denials and every system event other than init."""
    result = result_summary(stream=stream)
    return {
        "permission_denials": result["permission_denials"] if result is not None and "permission_denials" in result
        else "(key absent)",
        "system_events": [{key: event[key] for key in event if key not in ("session_id", "uuid")}
                          for event in stream.events if event["type"] == "system"
                          and ("subtype" not in event or event["subtype"] != INIT_SUBTYPE)],
    }


def permission_denied_events(*, stream):
    """Every system event with subtype `permission_denied` (headless.md:333)."""
    return [{key: event[key] for key in event if key not in ("session_id", "uuid")}
            for event in stream.events if event["type"] == "system"
            and "subtype" in event and event["subtype"] == PERMISSION_DENIED_SUBTYPE]


def in_init_tools(*, stream, name):
    return name in stream.init["tools"]


def assert_denied_results(*, stream, name):
    """Each tool_use of `name` got exactly one tool_result, after it, is_error true."""
    for use in stream.tool_uses_named(name=name):
        results = stream.result_for(tool_use_id=use.id)
        expect_equal(what="tool_result blocks for tool_use %s (%s)" % (use.id, name), expected=1, actual=len(results))
        got(what="tool_result of the stopped call %s" % use.id, value=results[0].text())
        expect_true(what="is_error of the stopped call's tool_result (%s)" % name, expected="True",
                    actual="%r (text %r)" % (results[0].is_error, results[0].text()), holds=results[0].is_error is True)
        expect_true(what="stream line of the tool_result of %s" % use.id, expected="after its tool_use (line %d)"
                    % use.index, actual="line %d" % results[0].index, holds=results[0].index > use.index)


def skip_unless_list_first(*, stream, records, later_name):
    """Gate (doc 23 test 9): list_items reached the server before the first
    tool_use of later_name; else inconclusive (the order is the model's)."""
    list_calls = calls_named(records=records, tool=LIST)
    later = stream.tool_uses_named(name=later_name)
    if not list_calls or not later or min(r["epoch"] for r in list_calls) >= min(
            event_epoch(event=stream.events[use.index]) for use in later):
        step(text="skip as inconclusive: %s did not reach %s before the %s tool_use" % (LIST, GUARD, later_name))
        pytest.skip("inconclusive: %s did not reach %s before the %s tool_use" % (LIST, GUARD, later_name))


# ---------------------------------------------------------------- D23/T9
@pytest.mark.parametrize("case_id", list(T9_CASES))
def test_pre_tool_use_hook_guards_mcp_tool(model_sandbox, cost_ledger, request, case_id):
    run_hook_guard(sandbox=model_sandbox, ledger=cost_ledger, request=request, case_id=case_id,
                   reason=token(prefix=CLEANUP_PREFIX), deny_reason=token(prefix=DENY_REASON_PREFIX))


def run_hook_guard(*, sandbox, ledger, request, case_id, reason, deny_reason):
    """The D23/T9 body (the test above; tests/test_harness_offline.py replays it)."""
    case = T9_CASES[case_id]
    list_name = mcp_tool_name(server=GUARD, tool=LIST)
    delete_name = mcp_tool_name(server=GUARD, tool=DELETE)
    hook_log = os.path.join(sandbox.artifact_dir, HOOK_LOG_NAME)
    sandbox.record.observe(key="case", value=dict(case, case_id=case_id, deny_reason=deny_reason))
    step(text="server guard; PreToolUse hook matcher %r, mode %s for %s (onFailure fields %s); prompt: %s, then %s"
         % (case["matcher"], case["mode"], delete_name, case["handler_fields"], list_name, delete_name))
    triggered = run_flow(
        sandbox=sandbox, ledger=ledger, request=request, names=[GUARD],
        allowed_tools=allowed_tools_for(servers=[GUARD]),
        prompt=PROMPT_LIST_THEN_DELETE.format(list=list_name, prefix=LIST_PREFIX, delete=delete_name, reason=reason),
        trigger_names=[list_name, delete_name], require_all_triggers=True,
        extra_args=guard_hook_settings_args(python=PYTHON, log_path=hook_log, matcher=case["matcher"],
                                            mode=case["mode"], target_tool=delete_name, reason=deny_reason,
                                            handler_fields=case["handler_fields"]),
    )
    if triggered.inconclusive is not None:
        step(text="skip as inconclusive: %s" % triggered.inconclusive)
        pytest.skip("%s (after %d attempt(s))" % (triggered.inconclusive, len(triggered.attempts)))
    stream = triggered.run.stream
    records = triggered.records[GUARD]
    entries = read_hook_log(path=hook_log)
    delete_calls = calls_named(records=records, tool=DELETE)
    view = {
        "era_seen": assert_era(records=records, negotiation=NEGOTIATION_LEGACY),
        "list_items": tool_view(stream=stream, name=list_name),
        "delete_all": tool_view(stream=stream, name=delete_name),
        "delete_all_tools_call_count": len(delete_calls),
        "hook_log": [{"tool_name": e["input"]["tool_name"], "tool_use_id": e["input"]["tool_use_id"],
                      "hook_event_name": e["input"]["hook_event_name"], "action": e["action"]} for e in entries],
        "denials": denials_view(stream=stream),
        "result": result_summary(stream=stream),
    }
    sandbox.record.observe(key="d_view", value=view)

    assert_tool_search_tool(stream=stream, expected=False)
    assert_tools_advertised(stream=stream, names=[list_name, delete_name])
    skip_unless_list_first(stream=stream, records=records, later_name=delete_name)
    view["list_passthrough"] = d_passthrough(stream=stream, records=records, server=GUARD, tool=LIST)
    sandbox.record.observe(key="d_view", value=view)
    got(what="hook log (tool, action)", value=[(e["tool_name"], e["action"]) for e in view["hook_log"]])
    got(what="delete_all tools/call that reached guard", value=len(delete_calls))
    # Recorded only (headless.md:333); the ask shape of these is not asserted.
    got(what="result.permission_denials, `permission_denied` events", value=(
        view["denials"]["permission_denials"], permission_denied_events(stream=stream)))
    expect_equal(what="hook_event_name of every hook log line", expected=[PRE_TOOL_USE] * len(entries),
                 actual=[e["input"]["hook_event_name"] for e in entries])

    delete_uses = stream.tool_uses_named(name=delete_name)
    if case["hook_action"] is None:
        expect_equal(what="tools the hook ran for with matcher %r (hooks.md:365: it matches no tool)" % case["matcher"],
                     expected=[], actual=sorted({e["input"]["tool_name"] for e in entries}))
    else:
        for use in delete_uses:
            hits = [e for e in entries if e["input"]["tool_use_id"] == use.id]
            expect_equal(what="hook actions logged for the delete_all tool_use %s" % use.id,
                         expected=[case["hook_action"]], actual=[e["action"] for e in hits])
        list_ids = {use.id for use in stream.tool_uses_named(name=list_name)}
        expect_equal(what="tool_use ids the hook logged `pass` for vs the list_items tool_use ids",
                     expected=sorted(list_ids),
                     actual=sorted({e["input"]["tool_use_id"] for e in entries if e["action"] == ACTION_PASS}))

    if case["delete_reaches_server"]:
        view["delete_passthrough"] = d_passthrough(stream=stream, records=records, server=GUARD, tool=DELETE)
        sandbox.record.observe(key="d_view", value=view)
    else:
        expect_true(what="delete_all tools/call that reached the server",
                    expected="none: the hook stopped it",
                    actual="delete_all reached the server %d time(s) although the hook stopped it" % len(delete_calls)
                    if delete_calls else "none", holds=not delete_calls)
        assert_denied_results(stream=stream, name=delete_name)
        if case["hook_action"] in (ACTION_DENY, ACTION_ASK):
            for row in view["delete_all"]:
                expect_true(what="the hook's permissionDecisionReason in the denied tool_result (hooks.md:1934)",
                            expected="contains %s" % deny_reason, actual=row["tool_results"][0]["text"],
                            holds=deny_reason in row["tool_results"][0]["text"])


# ---------------------------------------------------------------- D23/T10
def test_deny_rule_keeps_call_from_server(model_sandbox, cost_ledger, request):
    """T10 base: a deny rule for one tool, the allow rule for the rest."""
    run_deny_rule(sandbox=model_sandbox, ledger=cost_ledger, request=request, reason=token(prefix=CLEANUP_PREFIX))


def run_deny_rule(*, sandbox, ledger, request, reason):
    """The T10 base body (the test above; tests/test_harness_offline.py replays it)."""
    list_name = mcp_tool_name(server=GUARD, tool=LIST)
    delete_name = mcp_tool_name(server=GUARD, tool=DELETE)
    step(text="server guard; --allowedTools %s, %s %s; prompt: %s, then %s" % (
        allowed_tools_for(servers=[GUARD]), DISALLOWED_TOOLS_FLAG, delete_name, list_name, delete_name))
    triggered = run_flow(
        sandbox=sandbox, ledger=ledger, request=request, names=[GUARD],
        allowed_tools=allowed_tools_for(servers=[GUARD]),
        prompt=PROMPT_LIST_THEN_DELETE.format(list=list_name, prefix=LIST_PREFIX, delete=delete_name, reason=reason),
        trigger_names=[list_name], require_all_triggers=False,
        extra_args=[DISALLOWED_TOOLS_FLAG, delete_name],
    )
    if triggered.inconclusive is not None:
        step(text="skip as inconclusive: %s" % triggered.inconclusive)
        pytest.skip("%s (after %d attempt(s))" % (triggered.inconclusive, len(triggered.attempts)))
    stream = triggered.run.stream
    records = triggered.records[GUARD]
    delete_calls = calls_named(records=records, tool=DELETE)
    denials = denials_view(stream=stream)
    view = {
        "era_seen": assert_era(records=records, negotiation=NEGOTIATION_LEGACY),
        "delete_all_in_init_tools": in_init_tools(stream=stream, name=delete_name),
        "delete_all": tool_view(stream=stream, name=delete_name),
        "delete_all_in_permission_denials": delete_name in repr(denials["permission_denials"]),
        "delete_all_tools_call_count": len(delete_calls),
        "denials": denials,
        "result": result_summary(stream=stream),
    }
    sandbox.record.observe(key="d_view", value=view)
    assert_tool_search_tool(stream=stream, expected=False)
    assert_tools_advertised(stream=stream, names=[list_name])
    view["list_passthrough"] = d_passthrough(stream=stream, records=records, server=GUARD, tool=LIST)
    sandbox.record.observe(key="d_view", value=view)
    got(what="delete_all in system/init tools, delete_all tool_uses, in permission_denials", value=(
        view["delete_all_in_init_tools"], len(view["delete_all"]), view["delete_all_in_permission_denials"]))
    # cli-reference.md:87: a bare tool name in --disallowedTools "removes the
    # matching tools from Claude's context".
    expect_equal(what="%s in system/init tools under %s %s (cli-reference.md:87: removed from Claude's context)"
                 % (delete_name, DISALLOWED_TOOLS_FLAG, delete_name), expected=False,
                 actual=view["delete_all_in_init_tools"])
    expect_equal(what="delete_all tools/call that reached the server despite the deny rule", expected=0,
                 actual=len(delete_calls))
    assert_denied_results(stream=stream, name=delete_name)


def test_tool_without_allow_rule_is_denied(model_sandbox, cost_ledger, request):
    """T10 control for variant A: with no rule that allows it, an MCP tool is
    denied in `-p` (headless.md:323, 333). Variant A rests on this."""
    run_no_rule(sandbox=model_sandbox, ledger=cost_ledger, request=request, service=token(prefix=SERVICE_PREFIX))


def run_no_rule(*, sandbox, ledger, request, service):
    """The T10 control body (the test above; tests/test_harness_offline.py replays it)."""
    list_name = mcp_tool_name(server=GUARD, tool=LIST)
    rotate_name = mcp_tool_name(server=OPS, tool=ROTATE)
    allow_rule = list_name
    step(text="servers guard and guard__ops; --allowedTools %r only; prompt: %s, then %s" % (
        allow_rule, list_name, rotate_name))
    triggered = run_flow(
        sandbox=sandbox, ledger=ledger, request=request, names=[GUARD, OPS], allowed_tools=allow_rule,
        prompt=PROMPT_LIST_THEN_ROTATE.format(list=list_name, prefix=LIST_PREFIX, rotate=rotate_name,
                                              service=service),
        trigger_names=[list_name, rotate_name], require_all_triggers=True, extra_args=[],
    )
    if triggered.inconclusive is not None:
        step(text="skip as inconclusive: %s" % triggered.inconclusive)
        pytest.skip("%s (after %d attempt(s))" % (triggered.inconclusive, len(triggered.attempts)))
    stream = triggered.run.stream
    ops_calls = tools_call_records(records=triggered.records[OPS])
    denials = denials_view(stream=stream)
    rotate_ids = [use.id for use in stream.tool_uses_named(name=rotate_name)]
    denied_events = permission_denied_events(stream=stream)
    view = {
        "allowed_tools": allow_rule,
        "era_seen": {name: assert_era(records=triggered.records[name], negotiation=NEGOTIATION_LEGACY)
                     for name in (GUARD, OPS)},
        "rotate_logs_in_init_tools": in_init_tools(stream=stream, name=rotate_name),
        "rotate_logs": tool_view(stream=stream, name=rotate_name),
        "guard__ops_tools_call_count": len(ops_calls),
        "permission_denied_events": denied_events,
        "denials": denials,
        "result": result_summary(stream=stream),
    }
    sandbox.record.observe(key="d_view", value=view)
    assert_tool_search_tool(stream=stream, expected=False)
    assert_tools_advertised(stream=stream, names=[list_name, rotate_name])
    skip_unless_list_first(stream=stream, records=triggered.records[GUARD], later_name=rotate_name)
    view["list_passthrough"] = d_passthrough(stream=stream, records=triggered.records[GUARD], server=GUARD, tool=LIST)
    sandbox.record.observe(key="d_view", value=view)
    expect_equal(what="tools/call that reached %s with no allow rule for it (only %r)" % (OPS, allow_rule),
                 expected=0, actual=len(ops_calls))
    assert_denied_results(stream=stream, name=rotate_name)
    # headless.md:333: "denials appear as `permission_denied` system messages,
    # and the final result message lists them in `permission_denials`".
    listed = [(d["tool_name"], d["tool_use_id"]) for d in denials["permission_denials"]]
    expect_equal(what="result.permission_denials (tool_name, tool_use_id)",
                 expected=[(rotate_name, use_id) for use_id in rotate_ids], actual=listed)
    events = [(e["tool_name"], e["tool_use_id"]) for e in denied_events]
    expect_equal(what="`permission_denied` system events (tool_name, tool_use_id) (headless.md:333)",
                 expected=[(rotate_name, use_id) for use_id in rotate_ids], actual=events)


@pytest.mark.xfail(strict=True, raises=DocumentedBehaviorMismatch,
                   reason="known defect of 2.1.296, " + ALLOW_SCOPE_DEFECT)
def test_server_allow_rule_does_not_reach_double_underscore_server(model_sandbox, cost_ledger, request):
    """T10 variant A: `--allowedTools "mcp__guard"` must not allow guard__ops."""
    run_allow_scope(sandbox=model_sandbox, ledger=cost_ledger, request=request, service=token(prefix=SERVICE_PREFIX))


def run_allow_scope(*, sandbox, ledger, request, service):
    """The T10 variant A body (the test above; tests/test_harness_offline.py replays it)."""
    list_name = mcp_tool_name(server=GUARD, tool=LIST)
    rotate_name = mcp_tool_name(server=OPS, tool=ROTATE)
    allow_rule = "mcp__%s" % GUARD
    step(text="servers guard and guard__ops; --allowedTools %r only; prompt: %s, then %s" % (
        allow_rule, list_name, rotate_name))
    triggered = run_flow(
        sandbox=sandbox, ledger=ledger, request=request, names=[GUARD, OPS], allowed_tools=allow_rule,
        prompt=PROMPT_LIST_THEN_ROTATE.format(list=list_name, prefix=LIST_PREFIX, rotate=rotate_name,
                                              service=service),
        trigger_names=[list_name, rotate_name], require_all_triggers=True, extra_args=[],
    )
    if triggered.inconclusive is not None:
        step(text="skip as inconclusive: %s" % triggered.inconclusive)
        pytest.skip("%s (after %d attempt(s))" % (triggered.inconclusive, len(triggered.attempts)))
    stream = triggered.run.stream
    ops_calls = tools_call_records(records=triggered.records[OPS])
    view = {
        "allowed_tools": allow_rule,
        "era_seen": {name: assert_era(records=triggered.records[name], negotiation=NEGOTIATION_LEGACY)
                     for name in (GUARD, OPS)},
        "rotate_logs": tool_view(stream=stream, name=rotate_name),
        "guard__ops_tools_call_count": len(ops_calls),
        "denials": denials_view(stream=stream),
        "result": result_summary(stream=stream),
    }
    sandbox.record.observe(key="d_view", value=view)
    assert_tool_search_tool(stream=stream, expected=False)
    assert_tools_advertised(stream=stream, names=[list_name, rotate_name])
    # The `mcp__guard` rule is in effect for guard itself (permissions.md:550).
    view["list_passthrough"] = d_passthrough(stream=stream, records=triggered.records[GUARD], server=GUARD, tool=LIST)
    if ops_calls:
        # Wire consistency of the calls that got through (D), before the defect check.
        view["rotate_passthrough"] = d_passthrough(stream=stream, records=triggered.records[OPS], server=OPS,
                                                   tool=ROTATE)
    else:
        assert_denied_results(stream=stream, name=rotate_name)
    sandbox.record.observe(key="d_view", value=view)
    got(what="tools/call that reached %s" % OPS, value=len(ops_calls))
    expect_documented(what="tools/call that reached %s under --allowedTools %r" % (OPS, allow_rule),
                      doc="0 (%s)" % ALLOW_SCOPE_DEFECT, actual=len(ops_calls), holds=not ops_calls)


@pytest.mark.xfail(strict=True, raises=DocumentedBehaviorMismatch,
                   reason="known defect of 2.1.296, " + DENY_SCOPE_DEFECT)
def test_server_deny_rule_stops_double_underscore_server(model_sandbox, cost_ledger, request):
    """T10 variant B: a server-level deny `mcp__guard__ops` beats the allow `mcp__guard__ops__*`."""
    service = token(prefix=SERVICE_PREFIX)
    rotate_name = mcp_tool_name(server=OPS, tool=ROTATE)
    allow_rule = "mcp__%s__*" % OPS
    deny_rule = "mcp__%s" % OPS
    step(text="servers guard and guard__ops; --allowedTools %r, %s %r; prompt: %s" % (
        allow_rule, DISALLOWED_TOOLS_FLAG, deny_rule, rotate_name))
    triggered = run_flow(
        sandbox=model_sandbox, ledger=cost_ledger, request=request, names=[GUARD, OPS], allowed_tools=allow_rule,
        prompt=PROMPT_ROTATE.format(rotate=rotate_name, service=service),
        trigger_names=[rotate_name], require_all_triggers=False, extra_args=[DISALLOWED_TOOLS_FLAG, deny_rule],
    )
    stream = triggered.run.stream
    # Gate first: a server that is not connected also leaves rotate_logs out
    # of system/init, which must not read as "the deny applied".
    gate = gate_problem(stream=stream, servers=[GUARD, OPS])
    got(what="gate (both servers connected)", value="ok" if gate is None else gate)
    if gate is not None:
        pytest.skip("%s (after %d attempt(s))" % (gate, len(triggered.attempts)))
    ops_calls = tools_call_records(records=triggered.records[OPS])
    offered = in_init_tools(stream=stream, name=rotate_name)
    view = {
        "allowed_tools": allow_rule,
        "disallowed_tools": deny_rule,
        "rotate_logs_in_init_tools": offered,
        "rotate_logs": tool_view(stream=stream, name=rotate_name),
        "guard__ops_tools_call_count": len(ops_calls),
        "flow_inconclusive": triggered.inconclusive,
        "denials": denials_view(stream=stream),
        "result": result_summary(stream=stream),
    }
    model_sandbox.record.observe(key="d_view", value=view)
    got(what="rotate_logs in system/init tools, rotate_logs tool_uses, tools/call on guard__ops", value=(
        offered, len(stream.tool_uses_named(name=rotate_name)), len(ops_calls)))
    if offered and not stream.tool_uses_named(name=rotate_name):
        step(text="skip as inconclusive: %s offered in system/init and never called" % rotate_name)
        pytest.skip("%s (after %d attempt(s))" % (triggered.inconclusive, len(triggered.attempts)))
    # Conclusive: either a rotate_logs tool_use exists, or the deny removed the tool from system/init.
    assert_tool_search_tool(stream=stream, expected=False)
    view["era_seen"] = {name: assert_era(records=triggered.records[name], negotiation=NEGOTIATION_LEGACY)
                        for name in (GUARD, OPS)}
    if ops_calls:
        view["rotate_passthrough"] = d_passthrough(stream=stream, records=triggered.records[OPS], server=OPS,
                                                   tool=ROTATE)
    else:
        assert_denied_results(stream=stream, name=rotate_name)
    model_sandbox.record.observe(key="d_view", value=view)
    expect_documented(what="tools/call that reached %s under --allowedTools %r --disallowedTools %r" % (
        OPS, allow_rule, deny_rule), doc="0 (%s)" % DENY_SCOPE_DEFECT, actual=len(ops_calls), holds=not ops_calls)
