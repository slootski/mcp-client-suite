"""Add fake servers with `claude mcp add`, and run `claude mcp list` / `get`.

Shared by the free test files. Every argument is required.
"""

from harness.check import expect_true, got, step
from harness.constants import FAKE_HOST, FAKE_MCP_PATH, FAKE_STARTUP_TIMEOUT_S, FAKE_STOP_TIMEOUT_S
from harness.fakes_ctl import STDIO_FAKE_SCRIPT, running_http_fake
from harness.mcp_status import get_fields, list_line, list_status
from harness.wire import read_records, records_between

PYTHON = "python3"
PRESENCE_ONLY_SEPARATOR = ","  # fakes/stdio_fake.py PRESENCE_ONLY_SEPARATOR
COMMANDS = ("claude mcp list", "claude mcp get")


def stdio_fake_env(*, name, mode, log_path, init_reply_delay_ms, canary, toolset, presence_only_env):
    """The FAKE_* variables the stdio fake requires (fakes/stdio_fake.py).
    presence_only_env: env names the fake logs as {"set": true}, never as a
    fingerprint (constants FAKE_PRESENCE_ONLY_MODEL / FAKE_PRESENCE_ONLY_NONE)."""
    return {
        "FAKE_MODE": mode,
        "FAKE_LOG": log_path,
        "FAKE_NAME": name,
        "FAKE_INIT_REPLY_DELAY_MS": str(init_reply_delay_ms),
        "FAKE_CANARY": canary,
        "FAKE_TOOLSET": toolset,
        "FAKE_PRESENCE_ONLY_ENV": PRESENCE_ONLY_SEPARATOR.join(presence_only_env),
    }


def stdio_add_args(*, name, mode, log_path, init_reply_delay_ms, canary, toolset, presence_only_env, extra_env):
    """Arguments of `claude mcp add <name> --env ... -- python3 stdio_fake.py`.
    extra_env: more NAME -> value pairs passed with --env (may be empty)."""
    fake_env = stdio_fake_env(
        name=name, mode=mode, log_path=log_path, init_reply_delay_ms=init_reply_delay_ms, canary=canary,
        toolset=toolset, presence_only_env=presence_only_env,
    )
    env_pairs = list(fake_env.items()) + sorted(extra_env.items())
    args = ["mcp", "add", name]
    for key, value in env_pairs:
        args += ["--env", "%s=%s" % (key, value)]
    return args + ["--", PYTHON, STDIO_FAKE_SCRIPT]


def add_stdio_fake(*, sandbox, name, mode, init_reply_delay_ms, canary, toolset, presence_only_env, extra_env):
    """Add the stdio fake (see stdio_add_args). Returns its wire log path."""
    log_path = sandbox.wire_log_path(name=name)
    step(text="add stdio server %s: FAKE_MODE=%s, toolset %s, initialize reply delay %s ms, extra --env %s" % (
        name, mode, toolset, init_reply_delay_ms, sorted(extra_env)))
    added = sandbox.claude(
        args=stdio_add_args(
            name=name, mode=mode, log_path=log_path, init_reply_delay_ms=init_reply_delay_ms, canary=canary,
            toolset=toolset, presence_only_env=presence_only_env, extra_env=extra_env,
        )
    )
    expect_true(what="exit code of `claude mcp add %s`" % name, expected="0",
                actual="%d, output: %s" % (added.returncode, sandbox.registry.redact_text(text=added.combined)),
                holds=added.returncode == 0)
    return log_path


def add_http_server(*, sandbox, name, url, authorization):
    """authorization None means: configure no Authorization header at all.
    Returns the `claude mcp add` result."""
    args = ["mcp", "add", "--transport", "http", name, url]
    if authorization is not None:
        args += ["--header", "Authorization: %s" % authorization]
        step(text="add http server %s at %s with header Authorization: %s" % (
            name, url, sandbox.registry.redact_text(text=authorization)))
    else:
        step(text="add http server %s at %s with no Authorization header" % (name, url))
    added = sandbox.claude(args=args)
    expect_true(what="exit code of `claude mcp add --transport http %s`" % name, expected="0",
                actual="%d" % added.returncode, holds=added.returncode == 0)
    return added


def start_http(*, sandbox, name, auth_mode, expected_authorization):
    return running_http_fake(
        name=name,
        host=FAKE_HOST,
        path=FAKE_MCP_PATH,
        auth_mode=auth_mode,
        expected_authorization=expected_authorization,
        log_path=sandbox.wire_log_path(name=name),
        work_dir=sandbox.root,
        base_env=sandbox.env,
        startup_timeout_s=FAKE_STARTUP_TIMEOUT_S,
        stop_timeout_s=FAKE_STOP_TIMEOUT_S,
    )


def wire_events_line(*, records):
    """A short view of wire records for the log: event and JSON-RPC method
    or HTTP request line, per record (values of env and headers are never in
    a wire record; the fakes log only hash + length)."""
    parts = []
    for record in records:
        if record["event"] in ("recv", "sent") and isinstance(record["msg"], dict):
            msg = record["msg"]
            parts.append("%s %s" % (record["event"], msg["method"] if "method" in msg else "reply id=%s" % (
                msg["id"] if "id" in msg else None)))
        elif record["event"] == "http_request":
            parts.append("http %s %s -> %s" % (record["method"], record["path"], record["status"]))
        else:
            parts.append(record["event"])
    return ", ".join(parts)


def run_list_and_get(*, sandbox, name, wire_log):
    """Run `claude mcp list` then `claude mcp get <name>`. Return the parsed
    statuses, the raw results, and the wire records of each command."""
    step(text="run `claude mcp list`, then `claude mcp get %s`" % name)
    listed = sandbox.claude(args=["mcp", "list"])
    got_result = sandbox.claude(args=["mcp", "get", name])
    records = read_records(path=wire_log)

    status, detail = list_status(output=listed.combined, server_name=name, registry=sandbox.registry)
    fields = get_fields(output=got_result.combined, server_name=name, registry=sandbox.registry)
    redact = sandbox.registry.redact_text
    got(what="`claude mcp list` status of %s" % name, value=status)
    got(what="`claude mcp list` detail of %s" % name, value=None if detail is None else redact(text=detail))
    got(what="`claude mcp get %s` fields (redacted)" % name,
        value={key: redact(text=fields[key]) for key in fields})
    by_command = {
        "claude mcp list": records_between(records=records, start_epoch=listed.start_epoch,
                                           end_epoch=listed.end_epoch),
        "claude mcp get": records_between(records=records, start_epoch=got_result.start_epoch,
                                          end_epoch=got_result.end_epoch),
    }
    for command in COMMANDS:
        got(what="wire log of %s during `%s`" % (name, command),
            value="%d records: %s" % (len(by_command[command]), wire_events_line(records=by_command[command])))
    sandbox.record.observe(
        key="status",
        value={
            "list_line": sandbox.registry.redact_text(
                text=list_line(output=listed.combined, server_name=name, registry=sandbox.registry)),
            "list_status": status,
            "list_detail": None if detail is None else sandbox.registry.redact_text(text=detail),
            "list_returncode": listed.returncode,
            "list_duration_s": listed.duration_s,
            "get_fields": {key: sandbox.registry.redact_text(text=fields[key]) for key in fields},
            "get_returncode": got_result.returncode,
        },
    )
    return {
        "status": status,
        "detail": detail,
        "get_fields": fields,
        "listed": listed,
        "got": got_result,
        "by_command": by_command,
        "all_records": records,
    }
