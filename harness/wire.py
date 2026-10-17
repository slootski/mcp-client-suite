"""Read the fakes' JSONL wire logs and answer questions about them."""

import json
import os

from harness.check import expect_true


def read_records(*, path):
    """All records of a wire log. The log must exist: a fake that never
    started (or never logged) is a test failure, not an empty log."""
    expect_true(what="fake wire log %s" % os.path.basename(path), expected="the file exists",
                actual="exists" if os.path.exists(path) else "missing: %s" % path, holds=os.path.exists(path))
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def records_between(*, records, start_epoch, end_epoch):
    """Records written inside a wall-clock window (the fakes and the harness
    run in the same container, so they share one clock)."""
    return [record for record in records if start_epoch <= record["epoch"] <= end_epoch]


def records_by_pid(*, records):
    """Group records by fake process id, in first-seen order."""
    groups = {}
    for record in records:
        if record["pid"] not in groups:
            groups[record["pid"]] = []
        groups[record["pid"]].append(record)
    return groups


def message_method(*, message):
    """The JSON-RPC method of a request/notification, or None for a response."""
    if isinstance(message, dict) and "method" in message:
        return message["method"]
    return None


def stdio_lifetimes(*, records):
    """One summary per fake process: start, methods received, how it ended."""
    lifetimes = []
    for pid, group in records_by_pid(records=records).items():
        received = [record["msg"] for record in group if record["event"] == "recv"]
        lifetimes.append(
            {
                "pid": pid,
                "started": any(record["event"] == "started" for record in group),
                "methods": [message_method(message=message) for message in received],
                "end": [record["event"] for record in group if record["event"] in ("exit", "signal", "stdin_eof")],
            }
        )
    return lifetimes


def http_requests(*, records):
    """The HTTP requests an HTTP fake logged, in order."""
    return [record for record in records if record["event"] == "http_request"]


def http_rpc_method(*, request):
    """JSON-RPC method of an HTTP request body; None for a request that
    carries no JSON-RPC message (a GET, or an empty body)."""
    body = request["body"]
    if isinstance(body, dict):
        return message_method(message=body)
    return None


def http_mcp_posts(*, requests, mcp_path):
    """POSTs to the MCP endpoint: the JSON-RPC traffic."""
    return [request for request in requests if request["method"] == "POST" and request["path"] == mcp_path]


def http_summary(*, requests):
    """Compact list for run.json: METHOD path [rpc] auth -> status."""
    return [
        {
            "http": request["method"],
            "path": request["path"],
            "rpc": http_rpc_method(request=request),
            "auth": request["auth"],
            "status": request["status"],
        }
        for request in requests
    ]
