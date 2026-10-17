"""Scriptable stdio MCP server (legacy era, initialize handshake).

The client starts it as a subprocess. Configuration comes only from the
environment, which `claude mcp add --env NAME=value` sets:

  FAKE_MODE                 behavior to play, one of MODES below
  FAKE_LOG                  path of the JSONL wire log
  FAKE_NAME                 label written into every log record and into serverInfo
  FAKE_INIT_REPLY_DELAY_MS  hold the `initialize` reply this long (integer ms,
                            0 = reply at once). While it is held, the fake
                            keeps reading and logging stdin, so any request
                            the client sends before the reply is written
                            shows up in the log before the `sent` record.
  FAKE_CANARY               a fresh token per model test (not a secret): the
                            text the `echo_canary` tool returns, and the token
                            the tool_error / protocol_error toolsets put in
                            their error text
  FAKE_TOOLSET              which tools tools/list offers, one of TOOLSETS below
  FAKE_PRESENCE_ONLY_ENV    comma-separated env var names (empty string = none)
                            that the `started` record logs as {"set": true}
                            instead of {sha8, len}: names whose value must not
                            leave even a fingerprint. Model tests pass
                            ANTHROPIC_API_KEY (the live key); free tests pass
                            none, so their dummy credentials keep a
                            fingerprint the test can compare.

All seven are required: the fake exits with an error if one is missing.

Toolsets (tools/list):
  smoke             `echo` (returns arguments.text) and `echo_canary` (needs
                    arguments.request_id, a string; returns FAKE_CANARY as its
                    only text content).
  calc              `add(a, b)`: integers, returns the sum as text.
  calc_side_effect  the same `add(a, b)`, same name, schema, description and
                    reply; it also logs a `side_effect` record (SIDE_EFFECT_MARKER)
                    for each call. Doc 15 test 1: two near-duplicate tools that
                    return the same sum but differ inside.
  ticket            `create_ticket` (title, priority enum, tags array, due date,
                    optional notes, nested meta object). Returns one text block:
                    JSON {"id": "TCK-<8 hex>", "echo": <arguments as received>}.
                    The id is fresh per call (secrets.token_hex) and exists
                    only in this reply and the fake's log.
  tool_error        `validate_booking(date)`: always a normal result with
                    isError: true and one text block holding FAKE_CANARY
                    (a tool execution error, doc 16 test 1); and `echo`.
  protocol_error    `lookup_order(order_id)`: listed in tools/list, but
                    tools/call is answered with a JSON-RPC error, code
                    -32602, message holding FAKE_CANARY (doc 16 test 2: a
                    tool the server lists and then refuses); and `echo`.
  guard             `list_items(prefix)` (returns a JSON list of fixed item
                    names) and `delete_all(reason)` (returns how many items
                    it deleted; test data only). Doc 23 tests 9 and 10: the
                    tool a hook or a deny rule must stop.
  ops               `rotate_logs(service)` (returns "rotated <service>").
                    Doc 23 test 10: the tool of the second server,
                    `guard__ops`.

Each `tools/call` is logged as `recv` like every other message, so the test
reads the exact arguments the client sent. A call to a tool of the calc,
ticket, guard and ops toolsets also logs `tool_executed` (server name,
tool, JSON-RPC id, arguments): the fake's own record that this server ran
the tool.

stdout carries only JSON-RPC replies, one per line. Diagnostics go to stderr.
Every message received on stdin is logged with a wall-clock timestamp as soon
as it is read. Every reply is logged as `sent` immediately before it is
written to stdout (so `sent.epoch` <= the moment the client can see it).

The `started` record lists every env var as name -> {sha8, len} (never the
value), and separately `credential_env`: the same fingerprints for the vars
whose name looks like a credential (CREDENTIAL_NAME_MARKERS). In both, a
name listed in FAKE_PRESENCE_ONLY_ENV is logged as {"set": true} instead
(it was in the env; nothing about its value is written).

Modes:
  normal                   answer server/discover with -32601 (method not
                           found), then serve initialize,
                           notifications/initialized, ping, tools/list and
                           tools/call.
  discover_internal_error  like normal, but answer server/discover with the
                           generic JSON-RPC error -32603 (internal error).
  discover_silent          like normal, but never answer server/discover.
  exit_at_start            log a "started" record, then exit 1 before reading stdin.
  exit_on_first_tools_call like normal, except the first tools/call that one
                           client process sends: log it (`recv`), log an
                           `exit` record, then exit EXIT_ON_TOOLS_CALL_CODE
                           without replying (doc 20 test 1, a crash with a
                           call in flight). "One client process" = the
                           parent pid: a process the same client starts
                           again (a restart) finds that `exit` record in
                           its own log (same FAKE_LOG, same ppid) and
                           serves normally, so a call after a restart can
                           succeed. A new client process (a retry attempt
                           of the harness) gets the crash again.
  hang_on_tools_call       like normal, except that no tools/call is ever
                           answered: the fake logs it (`recv`), logs a
                           `no_reply` record (method, JSON-RPC id, the
                           progressToken the call carried or null), sends
                           nothing for it (no reply, no progress) and keeps
                           reading stdin, so a later notifications/cancelled
                           is logged as `recv` (doc 19 tests 1 and 3).

Every process logs one `started` record with its pid and ppid, so the
number of `started` records in a window is the number of spawns.
"""

import json
import os
import secrets
import signal
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wirelog import WireLog, fingerprint, fingerprint_mapping, presence  # noqa: E402

MODES = ("normal", "discover_internal_error", "discover_silent", "exit_at_start", "exit_on_first_tools_call",
         "hang_on_tools_call")
EXIT_ON_FIRST_CALL_REASON = "exit_on_first_tools_call"
REQUIRED_ENV = ("FAKE_MODE", "FAKE_LOG", "FAKE_NAME", "FAKE_INIT_REPLY_DELAY_MS", "FAKE_CANARY", "FAKE_TOOLSET",
                "FAKE_PRESENCE_ONLY_ENV")
PRESENCE_ONLY_SEPARATOR = ","
TOOLSETS = ("smoke", "calc", "calc_side_effect", "ticket", "tool_error", "protocol_error", "guard", "ops")
SIDE_EFFECT_MARKER = "calc2-side-effect: add also wrote this record"
TICKET_ID_PREFIX = "TCK-"
TICKET_ID_HEX_BYTES = 4  # 8 hex characters
DISCOVER_METHOD = "server/discover"

# Substrings of an env var name that mark it as credential-like.
CREDENTIAL_NAME_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH", "CREDENTIAL")

# Legacy (initialize-era) revisions this fake can speak. If the client asks
# for one of them, the fake echoes it; otherwise it answers with the newest.
LEGACY_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
NEWEST_LEGACY_VERSION = LEGACY_VERSIONS[0]

METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
FAKE_VERSION = "0.1.0"
EXIT_AT_START_CODE = 1
EXIT_ON_TOOLS_CALL_CODE = 3
# Error texts of the error toolsets; %s is FAKE_CANARY (the fresh token).
TOOL_ERROR_TEXT = "Invalid date: must be in the future. Error token: %s"
PROTOCOL_ERROR_TEXT = "Unknown tool: lookup_order (error token: %s)"

ECHO_TOOL = {
    "name": "echo",
    "description": "Return the given text unchanged.",
    "inputSchema": {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "Text to echo back."}},
        "required": ["text"],
        "additionalProperties": False,
    },
}

ECHO_CANARY_TOOL = {
    "name": "echo_canary",
    "description": "Return this server's canary string. Pass the request_id you were given.",
    "inputSchema": {
        "type": "object",
        "properties": {"request_id": {"type": "string", "description": "Request id given by the user."}},
        "required": ["request_id"],
        "additionalProperties": False,
    },
}

ADD_TOOL = {
    "name": "add",
    "description": "Add two integers a and b and return the sum.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "a": {"type": "integer", "description": "First addend."},
            "b": {"type": "integer", "description": "Second addend."},
        },
        "required": ["a", "b"],
        "additionalProperties": False,
    },
}

CREATE_TICKET_TOOL = {
    "name": "create_ticket",
    "description": "Create a ticket and return it with its new server-generated id.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Ticket title."},
            "priority": {"type": "string", "enum": ["low", "medium", "high"], "description": "Priority."},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags, in order."},
            "due": {"type": "string", "format": "date", "description": "Due date, YYYY-MM-DD."},
            "notes": {"type": "string", "description": "Optional free-text notes."},
            "meta": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Where the ticket came from."},
                    "count": {"type": "integer", "description": "A count."},
                },
                "required": ["source", "count"],
                "additionalProperties": False,
            },
        },
        "required": ["title", "priority", "tags", "due", "meta"],
        "additionalProperties": False,
    },
}

VALIDATE_BOOKING_TOOL = {
    "name": "validate_booking",
    "description": "Validate a booking date (YYYY-MM-DD).",
    "inputSchema": {
        "type": "object",
        "properties": {"date": {"type": "string", "description": "Booking date, YYYY-MM-DD."}},
        "required": ["date"],
        "additionalProperties": False,
    },
}

LOOKUP_ORDER_TOOL = {
    "name": "lookup_order",
    "description": "Look up an order by its id.",
    "inputSchema": {
        "type": "object",
        "properties": {"order_id": {"type": "string", "description": "Order id."}},
        "required": ["order_id"],
        "additionalProperties": False,
    },
}

LIST_ITEMS_TOOL = {
    "name": "list_items",
    "description": "List the items of this test server's scratch list whose name starts with prefix.",
    "inputSchema": {
        "type": "object",
        "properties": {"prefix": {"type": "string", "description": "Name prefix; an empty string lists all."}},
        "required": ["prefix"],
        "additionalProperties": False,
    },
}

DELETE_ALL_TOOL = {
    "name": "delete_all",
    "description": "Clear this test server's scratch list (fake test data only) and return how many items it held.",
    "inputSchema": {
        "type": "object",
        "properties": {"reason": {"type": "string", "description": "Why the list is cleared."}},
        "required": ["reason"],
        "additionalProperties": False,
    },
}

ROTATE_LOGS_TOOL = {
    "name": "rotate_logs",
    "description": "Rotate the log files of a service on this test server (fake; nothing real happens).",
    "inputSchema": {
        "type": "object",
        "properties": {"service": {"type": "string", "description": "Service name."}},
        "required": ["service"],
        "additionalProperties": False,
    },
}

# The guard toolset's scratch list (fixed; list_items filters it).
GUARD_ITEMS = ("alpha", "beta", "gamma")

TOOLS_BY_SET = {
    "smoke": [ECHO_TOOL, ECHO_CANARY_TOOL],
    "calc": [ADD_TOOL],
    "calc_side_effect": [ADD_TOOL],
    "ticket": [CREATE_TICKET_TOOL],
    "tool_error": [VALIDATE_BOOKING_TOOL, ECHO_TOOL],
    "protocol_error": [LOOKUP_ORDER_TOOL, ECHO_TOOL],
    "guard": [LIST_ITEMS_TOOL, DELETE_ALL_TOOL],
    "ops": [ROTATE_LOGS_TOOL],
}

# Tools of the guard and ops toolsets: each call logs `tool_executed` and
# answers one text block. name -> (required string argument, reply builder).
EXECUTED_TOOLS = {
    "list_items": ("prefix", lambda value: json.dumps([item for item in GUARD_ITEMS if item.startswith(value)])),
    "delete_all": ("reason", lambda value: "deleted %d items" % len(GUARD_ITEMS)),
    "rotate_logs": ("service", lambda value: "rotated %s" % value),
}


def read_config():
    missing = [name for name in REQUIRED_ENV if name not in os.environ]
    if missing:
        sys.stderr.write("stdio_fake: missing required env: %s\n" % ", ".join(missing))
        sys.exit(2)
    mode = os.environ["FAKE_MODE"]
    if mode not in MODES:
        sys.stderr.write("stdio_fake: unknown FAKE_MODE %r, expected one of %s\n" % (mode, MODES))
        sys.exit(2)
    toolset = os.environ["FAKE_TOOLSET"]
    if toolset not in TOOLSETS:
        sys.stderr.write("stdio_fake: unknown FAKE_TOOLSET %r, expected one of %s\n" % (toolset, TOOLSETS))
        sys.exit(2)
    delay_text = os.environ["FAKE_INIT_REPLY_DELAY_MS"]
    if not delay_text.isdigit():
        sys.stderr.write("stdio_fake: FAKE_INIT_REPLY_DELAY_MS must be a non-negative integer, got %r\n" % delay_text)
        sys.exit(2)
    presence_text = os.environ["FAKE_PRESENCE_ONLY_ENV"]
    presence_only = tuple(presence_text.split(PRESENCE_ONLY_SEPARATOR)) if presence_text else ()
    if any(not name for name in presence_only):
        sys.stderr.write("stdio_fake: FAKE_PRESENCE_ONLY_ENV must be comma-separated names with no empty item, "
                         "got %r\n" % presence_text)
        sys.exit(2)
    return {
        "mode": mode,
        "presence_only": presence_only,
        "log": os.environ["FAKE_LOG"],
        "name": os.environ["FAKE_NAME"],
        "init_reply_delay_s": int(delay_text) / 1000.0,
        "canary": os.environ["FAKE_CANARY"],
        "toolset": toolset,
    }


def env_view(*, mapping, presence_only):
    """name -> {sha8, len} for every var, except {"set": true} for the
    names in presence_only (no fingerprint of their value is written)."""
    view = fingerprint_mapping(mapping={name: mapping[name] for name in mapping if name not in presence_only})
    for name in mapping:
        if name in presence_only:
            view[name] = presence()
    return {name: view[name] for name in sorted(view)}


def credential_like(*, name):
    upper = name.upper()
    return any(marker in upper for marker in CREDENTIAL_NAME_MARKERS)


class Replier:
    """Writes replies to stdout one at a time, logging each just before."""

    def __init__(self, *, log):
        self._log = log
        self._lock = threading.Lock()

    def send(self, *, message):
        line = json.dumps(message, separators=(",", ":"))
        with self._lock:
            self._log.write(event="sent", fields={"msg": message})
            sys.stdout.write(line + "\n")
            sys.stdout.flush()


def result_reply(*, request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_reply(*, request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def invalid_params(*, request_id, detail):
    return error_reply(request_id=request_id, code=INVALID_PARAMS, message="Invalid params: %s" % detail)


def discover_reply(*, mode, request_id):
    """The reply to server/discover for this mode; None means stay silent."""
    if mode == "discover_silent":
        return None
    if mode == "discover_internal_error":
        return error_reply(request_id=request_id, code=INTERNAL_ERROR, message="Internal error")
    # normal: a legacy server does not know the method.
    return error_reply(request_id=request_id, code=METHOD_NOT_FOUND, message="Method not found: %s" % DISCOVER_METHOD)


def is_integer(*, value):
    return isinstance(value, int) and not isinstance(value, bool)


def call_add(*, log, name, toolset, request_id, arguments):
    """add(a, b). Logs tool_executed (and side_effect for calc_side_effect)."""
    log.write(event="tool_executed", fields={"server": name, "tool": "add", "rpc_id": request_id,
                                             "arguments": arguments})
    if toolset == "calc_side_effect":
        log.write(event="side_effect", fields={"server": name, "rpc_id": request_id, "marker": SIDE_EFFECT_MARKER})
    if not all(key in arguments and is_integer(value=arguments[key]) for key in ("a", "b")):
        return result_reply(
            request_id=request_id,
            result={"content": [{"type": "text", "text": "add needs integer a and b"}], "isError": True},
        )
    total = arguments["a"] + arguments["b"]
    return result_reply(request_id=request_id, result={"content": [{"type": "text", "text": str(total)}], "isError": False})


def call_create_ticket(*, log, name, request_id, arguments):
    """create_ticket: a fresh id, and the arguments echoed exactly as received."""
    ticket_id = TICKET_ID_PREFIX + secrets.token_hex(TICKET_ID_HEX_BYTES)
    log.write(event="tool_executed", fields={"server": name, "tool": "create_ticket", "rpc_id": request_id,
                                             "arguments": arguments, "ticket_id": ticket_id})
    text = json.dumps({"id": ticket_id, "echo": arguments}, ensure_ascii=False, separators=(",", ":"))
    return result_reply(request_id=request_id, result={"content": [{"type": "text", "text": text}], "isError": False})


def handle_tools_call(*, log, name, canary, toolset, request_id, params):
    offered = [tool["name"] for tool in TOOLS_BY_SET[toolset]]
    if params["name"] not in offered:
        return error_reply(request_id=request_id, code=INVALID_PARAMS, message="Unknown tool: %s" % params["name"])
    arguments = params["arguments"] if "arguments" in params else {}
    if params["name"] == ADD_TOOL["name"]:
        return call_add(log=log, name=name, toolset=toolset, request_id=request_id, arguments=arguments)
    if params["name"] == CREATE_TICKET_TOOL["name"]:
        return call_create_ticket(log=log, name=name, request_id=request_id, arguments=arguments)
    if params["name"] == VALIDATE_BOOKING_TOOL["name"]:
        # A tool execution error: a normal result with isError: true.
        return result_reply(
            request_id=request_id,
            result={"content": [{"type": "text", "text": TOOL_ERROR_TEXT % canary}], "isError": True},
        )
    if params["name"] == LOOKUP_ORDER_TOOL["name"]:
        # A protocol error: the JSON-RPC error object, no result.
        return error_reply(request_id=request_id, code=INVALID_PARAMS, message=PROTOCOL_ERROR_TEXT % canary)
    if params["name"] in EXECUTED_TOOLS:
        key, build = EXECUTED_TOOLS[params["name"]]
        log.write(event="tool_executed", fields={"server": name, "tool": params["name"], "rpc_id": request_id,
                                                 "arguments": arguments})
        if key not in arguments or not isinstance(arguments[key], str):
            return invalid_params(request_id=request_id, detail="%s needs arguments.%s (string)" % (params["name"], key))
        return result_reply(request_id=request_id,
                            result={"content": [{"type": "text", "text": build(arguments[key])}], "isError": False})
    if params["name"] == ECHO_CANARY_TOOL["name"]:
        if "request_id" not in arguments or not isinstance(arguments["request_id"], str):
            return invalid_params(request_id=request_id, detail="echo_canary needs arguments.request_id (string)")
        return result_reply(request_id=request_id, result={"content": [{"type": "text", "text": canary}], "isError": False})
    if "text" not in arguments:
        return invalid_params(request_id=request_id, detail="echo needs arguments.text")
    return result_reply(
        request_id=request_id, result={"content": [{"type": "text", "text": arguments["text"]}], "isError": False}
    )


def handle_request(*, log, name, canary, toolset, message):
    method = message["method"]
    request_id = message["id"]

    if method == "initialize":
        if "params" not in message or "protocolVersion" not in message["params"]:
            return invalid_params(request_id=request_id, detail="initialize needs params.protocolVersion")
        asked = message["params"]["protocolVersion"]
        version = asked if asked in LEGACY_VERSIONS else NEWEST_LEGACY_VERSION
        return result_reply(
            request_id=request_id,
            result={
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": name, "version": FAKE_VERSION},
            },
        )
    if method == "ping":
        return result_reply(request_id=request_id, result={})
    if method == "tools/list":
        return result_reply(request_id=request_id, result={"tools": TOOLS_BY_SET[toolset]})
    if method == "tools/call":
        if "params" not in message or "name" not in message["params"]:
            return invalid_params(request_id=request_id, detail="tools/call needs params.name")
        return handle_tools_call(
            log=log, name=name, canary=canary, toolset=toolset, request_id=request_id, params=message["params"]
        )
    return error_reply(request_id=request_id, code=METHOD_NOT_FOUND, message="Method not found: %s" % method)


def client_already_crashed(*, log_path):
    """True when this fake's log already holds an exit_on_first_tools_call
    `exit` record written by a process with the same parent (the same
    client) as this one."""
    ppid = os.getppid()
    with open(log_path, encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if record["event"] == "exit" and record["reason"] == EXIT_ON_FIRST_CALL_REASON \
                    and record["ppid"] == ppid:
                return True
    return False


def serve(*, log, config):
    replier = Replier(log=log)
    held = []  # timers holding an initialize reply
    for raw in sys.stdin:
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            message = json.loads(stripped)
        except ValueError:
            log.write(event="recv_unparsed", fields={"line": fingerprint(value=stripped)})
            continue
        log.write(event="recv", fields={"msg": message})
        if config["mode"] == "exit_on_first_tools_call" and isinstance(message, dict) and "method" in message \
                and message["method"] == "tools/call" and not client_already_crashed(log_path=config["log"]):
            log.write(event="exit", fields={"code": EXIT_ON_TOOLS_CALL_CODE, "reason": EXIT_ON_FIRST_CALL_REASON,
                                            "rpc_id": message["id"], "ppid": os.getppid()})
            sys.stderr.write("stdio_fake: exit_on_first_tools_call, exiting without a reply\n")
            sys.exit(EXIT_ON_TOOLS_CALL_CODE)
        if config["mode"] == "hang_on_tools_call" and isinstance(message, dict) and "method" in message \
                and message["method"] == "tools/call" and "id" in message:
            params = message["params"] if "params" in message and isinstance(message["params"], dict) else {}
            meta = params["_meta"] if "_meta" in params and isinstance(params["_meta"], dict) else {}
            log.write(event="no_reply", fields={"method": "tools/call", "id": message["id"],
                                                "progress_token": meta["progressToken"] if "progressToken" in meta
                                                else None})
            continue
        if not isinstance(message, dict) or "method" not in message:
            continue  # a response or junk: nothing to answer
        if "id" not in message:
            continue  # a notification, e.g. notifications/initialized
        if message["method"] == DISCOVER_METHOD:
            reply = discover_reply(mode=config["mode"], request_id=message["id"])
            if reply is None:
                log.write(event="no_reply", fields={"method": DISCOVER_METHOD, "id": message["id"]})
            else:
                replier.send(message=reply)
            continue
        reply = handle_request(
            log=log, name=config["name"], canary=config["canary"], toolset=config["toolset"], message=message
        )
        if message["method"] == "initialize" and config["init_reply_delay_s"] > 0:
            log.write(event="reply_held", fields={"method": "initialize", "delay_s": config["init_reply_delay_s"]})
            timer = threading.Timer(config["init_reply_delay_s"], replier.send, kwargs={"message": reply})
            timer.daemon = True  # a SIGTERM during the hold must not wait for it
            timer.start()
            held.append(timer)
            continue
        replier.send(message=reply)
    log.write(event="stdin_eof", fields={})
    for timer in held:
        timer.cancel()


def main():
    config = read_config()
    log = WireLog(path=config["log"], source=config["name"])

    def on_signal(signum, frame):
        log.write(event="signal", fields={"signal": signal.Signals(signum).name})
        sys.exit(128 + signum)

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    environment = dict(os.environ)
    log.write(
        event="started",
        fields={
            "mode": config["mode"],
            "toolset": config["toolset"],
            "init_reply_delay_s": config["init_reply_delay_s"],
            "ppid": os.getppid(),
            "argv": sys.argv,
            "cwd": os.getcwd(),
            "env": env_view(mapping=environment, presence_only=config["presence_only"]),
            "credential_env": env_view(
                mapping={name: environment[name] for name in environment if credential_like(name=name)},
                presence_only=config["presence_only"],
            ),
        },
    )
    if config["mode"] == "exit_at_start":
        log.write(event="exit", fields={"code": EXIT_AT_START_CODE, "reason": "exit_at_start"})
        sys.stderr.write("stdio_fake: exit_at_start, exiting before reading stdin\n")
        sys.exit(EXIT_AT_START_CODE)
    serve(log=log, config=config)
    log.write(event="exit", fields={"code": 0, "reason": "stdin closed"})


if __name__ == "__main__":
    main()
