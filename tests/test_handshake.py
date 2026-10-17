"""D12/T1 + T3: the stdio handshake on the wire, driven by `claude mcp list` / `get`.

Free: no model call, no API key. Every oracle is the stdio fake's own wire
log (fakes/stdio_fake.py): `recv` records are logged as soon as a line is
read, `sent` records just before the reply is written to stdout.

Cases:
  T1  legacy handshake, MCP_PROTOCOL_NEGOTIATION=legacy   (doc 12 test 1)
  T1  same asserts, negotiation unset: server/discover first, then the same
      initialize asserts                                   (doc 11: P0 wire tests run twice)
  T3  discover answered with a generic error (-32603): initialize follows;
      the fallback delay is measured                       (doc 12 test 3)
  T3s discover never answered: initialize follows after the client's own
      timeout, which is measured; the next connect skips the probe
      (the 7-day era memory), and a fresh CLAUDE_CONFIG_DIR probes again

Ordering oracle (2025-11-25 lifecycle, basic__lifecycle.md:159: the client
SHOULD NOT send requests other than pings before the server has responded to
`initialize`): the fake holds its `initialize` reply INIT_REPLY_HELD_MS while
it keeps reading stdin, so a request sent too early is logged before the
reply's `sent` record.

Era memory and isolation (T3s): 2.1.296 writes the verdict to
$CLAUDE_CONFIG_DIR/state/mcp-discover-verdicts.json, nothing outside
CLAUDE_CONFIG_DIR and HOME (checked once with `find / -newer`), and only after
a silent probe (a fast error writes nothing). Every test has its own
CLAUDE_CONFIG_DIR and HOME, so the silent case needs no container of its own
and no ordering. The silent test proves both halves: the second command in
the same config dir skips the probe, and a fresh config dir probes again.

Repeats (doc 22 test 1): every test here runs REPEATS times, one pytest
item per repeat (`repeat` parameter), each with a fresh sandbox
(CLAUDE_CONFIG_DIR, HOME, wire log, artifact folder). All asserts are D:
they must hold in REPEATS of REPEATS; there is no S fact and no rate.

Isolation rests on the per-test CLAUDE_CONFIG_DIR alone. The
`server/discover`-first assert in the other unset tests is NOT a cross-test
leak guard and can never fire as one: the verdict key hashes the server's
command + env (`stdio:<32 hex>`), and every test passes its own FAKE_LOG
path in that env, so no two tests share a key even in one config dir.
"""

import json
import os

import pytest

from harness.constants import (
    FAKE_PRESENCE_ONLY_NONE,
    FIRST_MESSAGE_NEGOTIATION_UNSET,
    FREE_TEST_CANARY,
    FREE_TEST_TOOLSET,
    INIT_REPLY_HELD_MS,
    INIT_REPLY_IMMEDIATE_MS,
    LEGACY_PROTOCOL_VERSION,
    NEGOTIATION_ENV,
    NEGOTIATION_LEGACY,
    REPEATS,
    STATUS_CONNECTED,
)
from harness.check import expect_equal, expect_in, expect_not_in, expect_true, got, step
from harness.mcp_setup import COMMANDS, add_stdio_fake, run_list_and_get, stdio_add_args
from harness.mcp_status import list_status
from harness.wire import message_method, read_records, records_between, records_by_pid

pytestmark = pytest.mark.free

DISCOVER = FIRST_MESSAGE_NEGOTIATION_UNSET
INITIALIZE = "initialize"
INITIALIZED = "notifications/initialized"
PING = "ping"

# The revision the client asks for in the probe's _meta (env-vars.md:495:
# the v2 runtime probes for MCP protocol revision 2026-07-28).
META_VERSION_KEY = "io.modelcontextprotocol/protocolVersion"
MODERN_PROTOCOL_VERSION = "2026-07-28"

GENERIC_ERROR_CODE = -32603  # fakes/stdio_fake.py discover_internal_error

# Timing bounds, from 3 suite runs (observations.md). The fallback after a
# discover error was 2-4 ms; the bound leaves a wide margin for a slow host
# and still separates "falls back at once" from "waits for its timeout".
FALLBACK_AFTER_ERROR_MAX_S = 1.0
# The fallback after a silent discover was 3.00-3.02 s on arm64. Tolerance
# +-1.0 s (2.0-4.0 s): one QA run on amd64 with `--cpus 0.25` measured
# 2.49 s, because both timestamps come from the fake, which is slowed by the
# same load. The window still separates the cases that matter: an immediate
# fallback (~3 ms after an error), the 12 s cancel seen in `claude mcp list`
# (observations.md), and the 15 s MCP_TIMEOUT.
SILENT_FALLBACK_EXPECTED_S = 3.0
SILENT_FALLBACK_TOLERANCE_S = 1.0
# The held initialize reply must really have been held (timer slack).
HOLD_SLACK_S = 0.05

VERDICTS_RELATIVE_PATH = os.path.join("state", "mcp-discover-verdicts.json")


# --------------------------------------------------------------------------
# helpers


def processes(*, records):
    """Wire records of one command, split per fake process (pid), in order."""
    return list(records_by_pid(records=records).values())


def received(*, records):
    return [r for r in records if r["event"] == "recv"]


def received_methods(*, records):
    return [message_method(message=r["msg"]) for r in received(records=records)]


def first_received(*, records, method):
    hits = [r for r in received(records=records) if message_method(message=r["msg"]) == method]
    expect_in(what="methods the fake received", item=method, container=received_methods(records=records))
    return hits[0]


def reply_to(*, records, request_id):
    """The fake's `sent` record answering request_id."""
    hits = [
        r for r in records
        if r["event"] == "sent" and isinstance(r["msg"], dict) and "id" in r["msg"] and r["msg"]["id"] == request_id
    ]
    expect_equal(what="replies the fake sent to id %r" % (request_id,), expected=1, actual=len(hits))
    return hits[0]


def handshake_summary(*, records):
    """run.json view of one process: methods with ms offsets from the first record."""
    start = records[0]["epoch"]
    rows = []
    for record in records:
        if record["event"] == "recv":
            rows.append("+%.1fms recv %s" % ((record["epoch"] - start) * 1000, message_method(message=record["msg"])))
        elif record["event"] == "sent":
            rows.append("+%.1fms sent reply id=%s" % ((record["epoch"] - start) * 1000, record["msg"]["id"]))
        elif record["event"] in ("no_reply", "reply_held"):
            rows.append("+%.1fms %s" % ((record["epoch"] - start) * 1000, record["event"]))
    return rows


def assert_initialize_exchange(*, records, where):
    """The initialize asserts of doc 12 test 1 for one connection. Returns
    (initialize recv record, initialize reply sent record)."""
    init = first_received(records=records, method=INITIALIZE)
    message = init["msg"]
    got(what="%s: initialize request" % where, value=message)
    expect_equal(what="%s: initialize jsonrpc" % where, expected="2.0", actual=message["jsonrpc"])
    expect_true(what="%s: initialize id" % where, expected="present, not null",
                actual=message["id"] if "id" in message else "(absent)", holds="id" in message and message["id"] is not None)
    params = message["params"]
    expect_equal(what="%s: protocolVersion asked in initialize" % where, expected=LEGACY_PROTOCOL_VERSION,
                 actual=params["protocolVersion"])
    expect_true(what="%s: initialize capabilities" % where, expected="an object", actual=params["capabilities"],
                holds=isinstance(params["capabilities"], dict))
    expect_in(what="%s: initialize params" % where, item="clientInfo", container=sorted(params))
    client_info = params["clientInfo"]
    expect_true(what="%s: clientInfo.name" % where, expected="a non-empty string", actual=client_info["name"],
                holds=isinstance(client_info["name"], str) and bool(client_info["name"]))
    expect_true(what="%s: clientInfo.version" % where, expected="a non-empty string", actual=client_info["version"],
                holds=isinstance(client_info["version"], str) and bool(client_info["version"]))

    # The fake's reply echoes the version, and the client accepted it (the
    # caller asserts Connected).
    reply = reply_to(records=records, request_id=message["id"])
    result = reply["msg"]["result"]
    expect_equal(what="%s: (asked, replied) protocolVersion" % where,
                 expected=(LEGACY_PROTOCOL_VERSION, LEGACY_PROTOCOL_VERSION),
                 actual=(params["protocolVersion"], result["protocolVersion"]))
    expect_true(what="%s: initialize reply keys" % where, expected="capabilities and serverInfo", actual=sorted(result),
                holds="capabilities" in result and "serverInfo" in result)

    # The reply really was held, so the ordering check below has a window.
    held_s = reply["epoch"] - init["epoch"]
    expect_true(what="%s: time the fake held the initialize reply" % where,
                expected=">= %.3f s" % (INIT_REPLY_HELD_MS / 1000.0 - HOLD_SLACK_S), actual="%.3f s" % held_s,
                holds=held_s >= INIT_REPLY_HELD_MS / 1000.0 - HOLD_SLACK_S)

    # notifications/initialized follows, has no id, and comes after the reply.
    initialized = first_received(records=records, method=INITIALIZED)
    expect_not_in(what="%s: notifications/initialized keys" % where, item="id", container=sorted(initialized["msg"]))
    expect_true(what="%s: notifications/initialized vs the initialize reply" % where, expected="after the reply",
                actual="%+.4f s after the reply" % (initialized["epoch"] - reply["epoch"]),
                holds=initialized["epoch"] >= reply["epoch"])

    # Lifecycle: no request other than ping before the initialize reply was
    # written. A request has an id AND a method; the client's responses (an
    # id, no method, e.g. a pong to a ping from the server) are not requests. Requests before initialize itself are checked by the caller
    # (legacy: none; unset: only the probe).
    early = [
        message_method(message=r["msg"])
        for r in received(records=records)
        if r["epoch"] > init["epoch"] and r["epoch"] < reply["epoch"]
        and "id" in r["msg"] and "method" in r["msg"] and message_method(message=r["msg"]) != PING
    ]
    expect_equal(what="%s: requests other than ping before the initialize reply was written" % where, expected=[],
                 actual=early)
    return init, reply


def record_repeat(*, sandbox, repeat):
    sandbox.record.observe(key="repeat", value={"index": repeat, "of": REPEATS})


def assert_connected(*, result):
    expect_equal(what="`claude mcp list` (status, detail)", expected=(STATUS_CONNECTED, None),
                 actual=(result["status"], result["detail"]))
    expect_equal(what="`claude mcp get` Status", expected=STATUS_CONNECTED, actual=result["get_fields"]["Status"])


# --------------------------------------------------------------------------
# T1: the legacy handshake, with negotiation pinned to legacy and unset


@pytest.mark.parametrize("repeat", range(REPEATS))
@pytest.mark.parametrize("negotiation", ["legacy", "unset"])
def test_handshake_on_the_wire(free_sandbox, negotiation, repeat):
    record_repeat(sandbox=free_sandbox, repeat=repeat)
    name = "fake_stdio_hs"
    if negotiation == "legacy":
        free_sandbox.set_env(name=NEGOTIATION_ENV, value=NEGOTIATION_LEGACY, secret=False)
    wire_log = add_stdio_fake(
        sandbox=free_sandbox, name=name, mode="normal", init_reply_delay_ms=INIT_REPLY_HELD_MS,
        canary=FREE_TEST_CANARY, toolset=FREE_TEST_TOOLSET, presence_only_env=FAKE_PRESENCE_ONLY_NONE, extra_env={}
    )
    result = run_list_and_get(sandbox=free_sandbox, name=name, wire_log=wire_log)
    assert_connected(result=result)

    seen = {}
    for command in COMMANDS:
        lives = processes(records=result["by_command"][command])
        expect_true(what="%s: fake processes started" % command, expected="at least 1", actual=len(lives),
                    holds=bool(lives))
        seen[command] = []
        for index, records in enumerate(lives):
            where = "%s process %d" % (command, index)
            methods = received_methods(records=records)
            init, reply = assert_initialize_exchange(records=records, where=where)
            before_init = [r for r in received(records=records) if r["epoch"] < init["epoch"]]
            entry = {
                "first_message": methods[0],
                "initialize_protocol_version": init["msg"]["params"]["protocolVersion"],
                "reply_protocol_version": reply["msg"]["result"]["protocolVersion"],
                "client_info": {k: init["msg"]["params"]["clientInfo"][k] for k in ("name", "version")},
                "wire": handshake_summary(records=records),
            }
            got(what="%s: methods received" % where, value=methods)
            if negotiation == "legacy":
                expect_equal(what="%s: first message (negotiation=legacy)" % where, expected=INITIALIZE,
                             actual=methods[0])
                expect_not_in(what="%s: methods received (negotiation=legacy)" % where, item=DISCOVER,
                              container=methods)
            else:
                expect_equal(what="%s: first message (negotiation unset)" % where, expected=DISCOVER,
                             actual=methods[0])
                probe = before_init[0]["msg"]
                meta = probe["params"]["_meta"]
                entry["discover_meta_protocol_version"] = meta[META_VERSION_KEY]
                expect_equal(what="%s: protocol version in the probe's _meta" % where, expected=MODERN_PROTOCOL_VERSION,
                             actual=meta[META_VERSION_KEY])
                expect_equal(what="%s: messages before initialize" % where, expected=[DISCOVER],
                             actual=[message_method(message=r["msg"]) for r in before_init])
                expect_equal(what="%s: error code of the fake's reply to the probe" % where, expected=-32601,
                             actual=reply_to(records=records, request_id=probe["id"])["msg"]["error"]["code"])
            seen[command].append(entry)
    free_sandbox.record.observe(key="era_seen", value=seen)


# --------------------------------------------------------------------------
# T3: discover answered with a generic JSON-RPC error


@pytest.mark.parametrize("repeat", range(REPEATS))
def test_discover_generic_error_falls_back_to_initialize(free_sandbox, repeat):
    """2026-07-28 basic__transports__stdio.md:142-148: any error other than a
    recognized modern one means legacy; fall back to initialize, and the
    fallback MUST NOT be keyed to one error code."""
    record_repeat(sandbox=free_sandbox, repeat=repeat)
    name = "fake_stdio_discover_err"
    wire_log = add_stdio_fake(
        sandbox=free_sandbox, name=name, mode="discover_internal_error",
        init_reply_delay_ms=INIT_REPLY_IMMEDIATE_MS,
        canary=FREE_TEST_CANARY, toolset=FREE_TEST_TOOLSET, presence_only_env=FAKE_PRESENCE_ONLY_NONE,
        extra_env={},
    )
    result = run_list_and_get(sandbox=free_sandbox, name=name, wire_log=wire_log)
    assert_connected(result=result)

    delays = {}
    for command in COMMANDS:
        lives = processes(records=result["by_command"][command])
        expect_true(what="%s: fake processes started" % command, expected="at least 1", actual=len(lives),
                    holds=bool(lives))
        delays[command] = []
        for index, records in enumerate(lives):
            where = "%s process %d" % (command, index)
            methods = received_methods(records=records)
            got(what="%s: methods received" % where, value=methods)
            expect_equal(what="%s: first message" % where, expected=DISCOVER, actual=methods[0])
            probe = first_received(records=records, method=DISCOVER)
            error = reply_to(records=records, request_id=probe["msg"]["id"])
            expect_equal(what="%s: error code of the fake's reply to the probe" % where, expected=GENERIC_ERROR_CODE,
                         actual=error["msg"]["error"]["code"])
            init = first_received(records=records, method=INITIALIZE)
            expect_equal(what="%s: position of initialize in the methods received" % where, expected=1,
                         actual=methods.index(INITIALIZE))
            delays[command].append(round(init["epoch"] - error["epoch"], 4))
    free_sandbox.record.observe(key="fallback_delay_after_error_s", value=delays)
    for command in COMMANDS:
        for delay in delays[command]:
            expect_true(what="%s: delay from the probe error to initialize" % command,
                        expected="in [0, %.1f] s" % FALLBACK_AFTER_ERROR_MAX_S, actual="%.4f s" % delay,
                        holds=0 <= delay <= FALLBACK_AFTER_ERROR_MAX_S)


# --------------------------------------------------------------------------
# T3s: discover never answered (silent), then the era memory


@pytest.mark.parametrize("repeat", range(REPEATS))
def test_discover_silent_falls_back_and_is_remembered_per_config_dir(free_sandbox, repeat):
    record_repeat(sandbox=free_sandbox, repeat=repeat)
    name = "fake_stdio_discover_silent"
    wire_log = add_stdio_fake(
        sandbox=free_sandbox, name=name, mode="discover_silent",
        init_reply_delay_ms=INIT_REPLY_IMMEDIATE_MS,
        canary=FREE_TEST_CANARY, toolset=FREE_TEST_TOOLSET, presence_only_env=FAKE_PRESENCE_ONLY_NONE,
        extra_env={},
    )
    result = run_list_and_get(sandbox=free_sandbox, name=name, wire_log=wire_log)
    assert_connected(result=result)

    # 1. `claude mcp list`: probe, silence, then initialize after the
    #    client's own timeout (measured on the fake's clock).
    list_lives = processes(records=result["by_command"]["claude mcp list"])
    expect_equal(what="fake processes `claude mcp list` started", expected=1, actual=len(list_lives))
    records = list_lives[0]
    methods = received_methods(records=records)
    got(what="claude mcp list: methods received", value=methods)
    expect_equal(what="claude mcp list: first two messages", expected=[DISCOVER, INITIALIZE], actual=methods[:2])
    probe = first_received(records=records, method=DISCOVER)
    expect_equal(what="claude mcp list: replies the fake sent to the probe (it stays silent)", expected=[],
                 actual=[r["msg"] for r in records if r["event"] == "sent" and r["msg"]["id"] == probe["msg"]["id"]])
    init = first_received(records=records, method=INITIALIZE)
    silent_delay = round(init["epoch"] - probe["epoch"], 4)
    free_sandbox.record.observe(key="silent_fallback_delay_s", value=silent_delay)
    free_sandbox.record.observe(
        key="probe_cancelled",
        value=[r["msg"]["params"] for r in received(records=records)
               if message_method(message=r["msg"]) == "notifications/cancelled"],
    )
    expect_true(what="delay from the silent probe to initialize",
                expected="%.1f +- %.1f s" % (SILENT_FALLBACK_EXPECTED_S, SILENT_FALLBACK_TOLERANCE_S),
                actual="%.3f s" % silent_delay,
                holds=abs(silent_delay - SILENT_FALLBACK_EXPECTED_S) <= SILENT_FALLBACK_TOLERANCE_S)

    # 2. The memory: changelog.md:743 (2.1.292) 'after one slow connect they
    #    are remembered for 7 days and connected the older way without the
    #    wait'. `claude mcp get`, same config dir, goes straight to initialize.
    get_lives = processes(records=result["by_command"]["claude mcp get"])
    expect_true(what="fake processes `claude mcp get` started", expected="at least 1", actual=len(get_lives),
                holds=bool(get_lives))
    for records in get_lives:
        got(what="claude mcp get: methods received", value=received_methods(records=records))
        expect_equal(what="claude mcp get: first message (the server is remembered)", expected=INITIALIZE,
                     actual=received_methods(records=records)[0])
        expect_not_in(what="claude mcp get: methods received", item=DISCOVER,
                      container=received_methods(records=records))

    # Where it lives: under CLAUDE_CONFIG_DIR (copied to the artifacts).
    verdicts_path = os.path.join(free_sandbox.config_dir, VERDICTS_RELATIVE_PATH)
    expect_true(what="era verdict file $CLAUDE_CONFIG_DIR/%s" % VERDICTS_RELATIVE_PATH, expected="exists",
                actual="exists" if os.path.exists(verdicts_path) else "missing", holds=os.path.exists(verdicts_path))
    with open(verdicts_path, encoding="utf-8") as handle:
        verdicts = json.load(handle)
    free_sandbox.record.observe(key="era_verdicts_file", value=verdicts)
    got(what="era verdict file", value=verdicts)

    # 3. Isolation: a fresh CLAUDE_CONFIG_DIR with the same HOME and the same
    #    server config probes again, so a fresh config dir per test is enough.
    fresh_env = free_sandbox.new_config_env(label="fresh")
    step(text="add the same stdio server %s in a fresh CLAUDE_CONFIG_DIR (same HOME), then `claude mcp list` there"
         % name)
    added = free_sandbox.claude_with_env(
        args=stdio_add_args(
            name=name, mode="discover_silent", log_path=wire_log,
            init_reply_delay_ms=INIT_REPLY_IMMEDIATE_MS, canary=FREE_TEST_CANARY, toolset=FREE_TEST_TOOLSET,
            presence_only_env=FAKE_PRESENCE_ONLY_NONE, extra_env={},
        ),
        env=fresh_env,
    )
    expect_true(what="exit code of `claude mcp add %s` in the fresh config dir" % name, expected="0",
                actual="%d, output: %s" % (added.returncode, free_sandbox.registry.redact_text(text=added.combined)),
                holds=added.returncode == 0)
    listed = free_sandbox.claude_with_env(args=["mcp", "list"], env=fresh_env)
    status, _detail = list_status(output=listed.combined, server_name=name, registry=free_sandbox.registry)
    expect_equal(what="`claude mcp list` status of %s in the fresh config dir" % name, expected=STATUS_CONNECTED,
                 actual=status)
    fresh = records_between(records=read_records(path=wire_log), start_epoch=listed.start_epoch, end_epoch=listed.end_epoch)
    fresh_lives = processes(records=fresh)
    expect_true(what="fake processes the fresh-config `claude mcp list` started", expected="at least 1",
                actual=len(fresh_lives), holds=bool(fresh_lives))
    fresh_first = [received_methods(records=records)[0] for records in fresh_lives]
    free_sandbox.record.observe(key="fresh_config_dir_first_messages", value=fresh_first)
    expect_equal(what="first message of each process in the fresh config dir", expected=[DISCOVER] * len(fresh_lives),
                 actual=fresh_first)
