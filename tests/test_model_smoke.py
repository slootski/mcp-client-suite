"""D14/T1, D14/T2, D23/T2: tool-call smoke through the model (`claude -p`).

Model tier: needs ANTHROPIC_API_KEY, costs tokens (skipped without a key).
Every run goes through harness/model_run.py (doc 11 flags and pins) and is
charged to the suite cost ledger.

The tool: the stdio fake's `echo_canary` returns FAKE_CANARY, a fresh value
per test (`canary-<16 hex>`). The canary is NOT in the prompt: the model can
only learn it from the tool result, so a final answer that holds it shows a
real round trip. The prompt fixes one argument, request_id = REQUEST_ID.

Oracles per run (doc 11, doc 22 D/S split):
  gate  every server of the test is `connected` in system/init, else the
        attempt is inconclusive
  pins  D: the fake's first message is `initialize` asking 2025-11-25
        (MCP_PROTOCOL_NEGOTIATION=legacy), and system/init tools holds
        ToolSearch exactly when tool search is on (T1, D23/T2: no; T2: yes)
  (b) D the client lists mcp__<server>__echo_canary in system/init tools.
        The tool_use name itself is the model's choice (S, recorded).
  (d) D each tool_use of that name reached the fake as exactly one tools/call
        with the same tool name, and arguments == tool_use.input
  (c) D each such tool_use has one tool_result, not is_error (2.1.296 omits
        the key on success), whose text equals the text the fake itself sent
        for that JSON-RPC id (its `sent` record), and it comes before the
        final `result` event
  (S)   tool_use.input == {"request_id": REQUEST_ID}: recorded in run.json
  (a) S the final `result` text contains the exact canary. Oracle: plain
        substring match of the whole canary token (one unbreakable
        `canary-<hex>` string, so a paraphrase cannot match it by parts).
        Recorded in run.json (`s_checks`), not asserted.
  If the model made no tool_use named mcp__<server>__echo_canary, the D
  checks have no trigger: the run is retried once in a fresh config dir
  (INCONCLUSIVE_RETRIES, every attempt recorded and charged), then the test
  is skipped as inconclusive.
"""

import secrets

import pytest

from harness.constants import (
    CANARY_HEX_BYTES,
    CANARY_PREFIX,
    FAKE_PRESENCE_ONLY_MODEL,
    INCONCLUSIVE_RETRIES,
    INIT_REPLY_IMMEDIATE_MS,
    NEGOTIATION_LEGACY,
    MAX_BUDGET_USD_PER_RUN,
    MAX_TURNS,
    MODEL_CLI_TIMEOUT_S,
    MODEL_ID,
    MODEL_REJECTED_EXIT_CODE,
    MODEL_TEST_TIMEOUT_S,
    TOOL_SEARCH_ENV,
    TOOL_SEARCH_OFF,
    TOOLSET_SMOKE,
)
from harness.check import expect_equal, expect_in, expect_not_in, expect_true, got, record, step
from harness.fakes_ctl import STDIO_FAKE_SCRIPT
from harness.mcp_setup import PYTHON, stdio_fake_env
from harness.model_checks import (
    assert_era,
    assert_tool_search_tool,
    assert_tools_advertised,
    d_passthrough,
    init_summary,
    mcp_tool_name,
    s_input,
)
from harness.model_flow import run_until_triggered
from harness.model_run import allowed_tools_for, stdio_server_entry

pytestmark = [pytest.mark.model, pytest.mark.timeout(MODEL_TEST_TIMEOUT_S)]

TOOL = "echo_canary"
REQUEST_ID = "smoke-req-4711"
EXPECTED_INPUT = {"request_id": REQUEST_ID}
TOOL_SEARCH_TOOL = "ToolSearch"
SUCCESS = "success"
PROMPT_TEMPLATE = (
    "Use the tool echo_canary from the MCP server named {server}. Call it exactly once, with request_id set "
    "to exactly \"{request_id}\". Then reply with only the exact text the tool returned, nothing before or "
    "after it."
)

# D23/T2: a --mcp-config entry with a `url` and no `type` is skipped at
# validation (mcp.md:85) and listed in system/init mcp_server_errors with
# type `url_missing_type` (headless.md, mcp_server_errors table).
BROKEN_NAME = "broken_url"
BROKEN_ENTRY = {"url": "http://127.0.0.1:9/mcp"}  # port 9 (discard): never reached, the entry is skipped
URL_MISSING_TYPE = "url_missing_type"
URL_MISSING_TYPE_TEXT = 'has a "url" but no "type"'  # mcp.md:85, the reported message


# --------------------------------------------------------------------------
# helpers


def new_canary():
    return CANARY_PREFIX + secrets.token_hex(CANARY_HEX_BYTES)


def fake_entry(*, sandbox, name, canary):
    return stdio_server_entry(
        fake_script=STDIO_FAKE_SCRIPT,
        python=PYTHON,
        fake_env=stdio_fake_env(
            name=name, mode="normal", log_path=sandbox.wire_log_path(name=name),
            init_reply_delay_ms=INIT_REPLY_IMMEDIATE_MS, canary=canary, toolset=TOOLSET_SMOKE,
            presence_only_env=FAKE_PRESENCE_ONLY_MODEL,
        ),
    )


def prompt_for(*, server):
    return PROMPT_TEMPLATE.format(server=server, request_id=REQUEST_ID)


def run_smoke(*, sandbox, ledger, request, servers, server):
    """run_until_triggered for the echo_canary prompt; skip when inconclusive.
    Returns (run, wire records of `server`)."""
    triggered = run_until_triggered(
        sandbox=sandbox, ledger=ledger, test_id=request.node.nodeid, prompt=prompt_for(server=server),
        model=MODEL_ID, max_turns=MAX_TURNS, max_budget_usd=MAX_BUDGET_USD_PER_RUN, timeout_s=MODEL_CLI_TIMEOUT_S,
        servers=servers, allowed_tools=allowed_tools_for(servers=[server]), gate_servers=[server], wire_servers=[server],
        trigger_names=[mcp_tool_name(server=server, tool=TOOL)], require_all_triggers=False,
        retries=INCONCLUSIVE_RETRIES, rejected_exit_code=MODEL_REJECTED_EXIT_CODE, extra_args=[],
        attempt_checks=[],
    )
    if triggered.inconclusive is not None:
        step(text="skip as inconclusive: %s" % triggered.inconclusive)
        pytest.skip("%s (after %d attempt(s))" % (triggered.inconclusive, len(triggered.attempts)))
    return triggered.run, triggered.records[server]


def check_round_trip(*, sandbox, run, records, server, canary, tool_search_on):
    """Pins, (b), (c), (d) hard; (a) and S recorded. Returns the run.json view."""
    stream = run.stream
    exact = mcp_tool_name(server=server, tool=TOOL)

    # Pins: the era and the tool search setting took effect (client facts).
    assert_era(records=records, negotiation=NEGOTIATION_LEGACY)
    assert_tool_search_tool(stream=stream, expected=tool_search_on)

    # (b) the client offers the tool under its exact mcp__<server>__<tool>
    # name. With tool search on, system/init still names deferred MCP tools.
    assert_tools_advertised(stream=stream, names=[exact])
    uses = stream.tool_uses_named(name=exact)

    # (d) + (c): one tools/call per tool_use, same arguments, and the
    # tool_result text is the fake's own reply for that JSON-RPC id.
    d_view = d_passthrough(stream=stream, records=records, server=server, tool=TOOL)

    # (c) order: every tool_result before the final result event, the last line.
    expect_true(what="final result event in the stream", expected="present", actual="present"
                if stream.result is not None else "absent", holds=stream.result is not None)
    result_index = stream.events.index(stream.result)
    expect_equal(what="stream line of the result event", expected=len(stream.events) - 1, actual=result_index)
    for row in d_view["results"]:
        expect_true(what="stream line of the tool_result of %s" % row["tool_use_id"],
                    expected="before the result event (line %d)" % result_index,
                    actual="line %d" % row["tool_result_index"], holds=row["tool_result_index"] < result_index)
    last_text = max(stream.assistant_text_indexes) if stream.assistant_text_indexes else None

    # S: recorded, never asserted here.
    final_text = stream.result["result"] if "result" in stream.result else None
    s_checks = {
        "tool_use_input_as_prompted": s_input(stream=stream, server=server, tool=TOOL, expected_input=EXPECTED_INPUT),
        "tool_use_names_for_the_tool": sorted({use.name for use in stream.tool_uses if TOOL in use.name}),
        "tool_result_equals_canary": [row["tool_result_text"] == canary for row in d_view["results"]],
        "final_text_contains_canary": isinstance(final_text, str) and canary in final_text,
        "final_text_equals_canary": isinstance(final_text, str) and final_text.strip() == canary,
        "assistant_text_after_tool_result": last_text is not None
        and last_text > max(row["tool_result_index"] for row in d_view["results"]),
        "tool_uses_of_the_tool": len(uses),
        "result_subtype": stream.result["subtype"] if "subtype" in stream.result else None,
        "result_subtype_is_success": "subtype" in stream.result and stream.result["subtype"] == SUCCESS,
    }
    view = {"d": d_view, "final_text": final_text, "canary": canary}
    sandbox.record.observe(key="round_trip", value=view)
    sandbox.record.observe(key="s_checks", value=s_checks)
    got(what="final answer", value=final_text)
    for key in sorted(s_checks):
        record(what=key, value=s_checks[key])
    return view


def tool_search_uses(*, stream):
    """ToolSearch calls and what they returned (recorded in D14/T2)."""
    out = []
    for use in stream.tool_uses_named(name=TOOL_SEARCH_TOOL):
        results = stream.result_for(tool_use_id=use.id)
        out.append({
            "index": use.index, "input": use.input,
            "result_is_error": [r.is_error for r in results],
            "result_content": [r.content for r in results],
        })
    return out


# --------------------------------------------------------------------------
# D14/T1: minimal round trip, tool search off (doc 11 wire pin)


def test_round_trip_echo_canary(model_sandbox, cost_ledger, request):
    model_sandbox.set_env(name=TOOL_SEARCH_ENV, value=TOOL_SEARCH_OFF, secret=False)
    server = "smoke"
    canary = new_canary()
    step(text="stdio server %s (toolset smoke) whose echo_canary returns a fresh canary %s" % (server, canary))
    servers = {server: fake_entry(sandbox=model_sandbox, name=server, canary=canary)}
    run, records = run_smoke(sandbox=model_sandbox, ledger=cost_ledger, request=request, servers=servers, server=server)
    check_round_trip(sandbox=model_sandbox, run=run, records=records, server=server, canary=canary,
                     tool_search_on=False)
    model_sandbox.record.observe(key="tool_search_uses", value=tool_search_uses(stream=run.stream))


# --------------------------------------------------------------------------
# D14/T2: same, tool search at its default (on)


def test_round_trip_with_tool_search_default(model_sandbox, cost_ledger, request):
    """ENABLE_TOOL_SEARCH unset (mcp.md:1512: on by default). The tool must
    still be called; a ToolSearch call before it is allowed and recorded."""
    server = "smoke"
    canary = new_canary()
    step(text="stdio server %s (toolset smoke, %s left unset) whose echo_canary returns %s" % (
        server, TOOL_SEARCH_ENV, canary))
    servers = {server: fake_entry(sandbox=model_sandbox, name=server, canary=canary)}
    run, records = run_smoke(sandbox=model_sandbox, ledger=cost_ledger, request=request, servers=servers, server=server)
    check_round_trip(sandbox=model_sandbox, run=run, records=records, server=server, canary=canary,
                     tool_search_on=True)
    searches = tool_search_uses(stream=run.stream)
    model_sandbox.record.observe(key="tool_search_uses", value=searches)
    before = bool(searches) and min(s["index"] for s in searches) < min(
        u.index for u in run.stream.tool_uses_named(name=mcp_tool_name(server=server, tool=TOOL)))
    model_sandbox.record.observe(key="tool_search_before_tool", value=before)
    record(what="ToolSearch calls", value=len(searches))
    record(what="a ToolSearch call before %s" % TOOL, value=before)


# --------------------------------------------------------------------------
# D23/T2: a broken --mcp-config entry next to a healthy server


def test_broken_config_entry_is_reported_and_healthy_server_works(model_sandbox, cost_ledger, request):
    model_sandbox.set_env(name=TOOL_SEARCH_ENV, value=TOOL_SEARCH_OFF, secret=False)
    server = "healthy"
    canary = new_canary()
    step(text="--mcp-config with a healthy stdio server %s and a broken entry %s = %s (url, no type)" % (
        server, BROKEN_NAME, BROKEN_ENTRY))
    servers = {server: fake_entry(sandbox=model_sandbox, name=server, canary=canary), BROKEN_NAME: BROKEN_ENTRY}
    run, records = run_smoke(sandbox=model_sandbox, ledger=cost_ledger, request=request, servers=servers, server=server)
    init = run.stream.init
    expect_in(what="system/init keys (%s)" % init_summary(stream=run.stream), item="mcp_server_errors",
              container=sorted(init))
    errors = [entry for entry in init["mcp_server_errors"] if entry["name"] == BROKEN_NAME]
    model_sandbox.record.observe(key="mcp_server_errors", value=init["mcp_server_errors"])
    got(what="system/init mcp_server_errors", value=init["mcp_server_errors"])
    expect_equal(what="mcp_server_errors entries for %s" % BROKEN_NAME, expected=1, actual=len(errors))
    expect_equal(what="type of the mcp_server_errors entry for %s" % BROKEN_NAME, expected=URL_MISSING_TYPE,
                 actual=errors[0]["type"])
    expect_in(what="message of the mcp_server_errors entry for %s" % BROKEN_NAME, item=URL_MISSING_TYPE_TEXT,
              container=errors[0]["message"])
    expect_not_in(what="server names in system/init mcp_servers", item=BROKEN_NAME,
                  container=[entry["name"] for entry in init["mcp_servers"]])

    # The run continued: the healthy server's tool works end to end. The
    # result subtype ("success") is recorded in s_checks, not asserted: how
    # the model ends its turn is model behavior.
    check_round_trip(sandbox=model_sandbox, run=run, records=records, server=server, canary=canary,
                     tool_search_on=False)
