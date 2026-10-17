"""D12/T4 + D13/T3: the `claude mcp list` / `claude mcp get` status matrix.

Free: no model call, no API key. Each case gets a fresh CLAUDE_CONFIG_DIR,
adds one server with `claude mcp add`, then runs `claude mcp list` and
`claude mcp get <name>`.

Two oracles per case:
  1. the status string, verbatim from the docs (mcp.md:257,
     mcp-quickstart.md:61-66), in both commands;
  2. the fake's own wire log: what the client actually sent. A status string
     alone could be printed without any connection attempt.

Cases:
  1.  stdio, healthy                              -> ✔ Connected
  2.  stdio, exits at start                       -> ✘ Failed to connect (+ detail)
  3.  HTTP, right static Authorization            -> ✔ Connected
  3r. HTTP, `claude mcp get` redacts that header  (xfail: 2.1.296 prints it)
  4.  HTTP, wrong static Authorization (401)      -> ✘ Failed to connect + 401 detail  (D13/T3a)
  5.  HTTP, no header, 401 + OAuth metadata       -> ! Needs authentication             (D13/T3b)
  5b. HTTP, no header, bare 401, no metadata      -> status recorded, not asserted     (record-only)
      An out-of-spec server: it breaks the MUST to publish Protected
      Resource Metadata (2025-11-25 basic__authorization.md:65). The client
      follows the spec's MUST fallback and reports what it got; mcp.md:762
      ("Needs authentication") assumes an OAuth server, so the status is
      compared with it record-only (run.json `documented_bare_401_status`),
      while the wire asserts (probe first, 401 on the MCP path) stay hard.

MCP_PROTOCOL_NEGOTIATION is unset (the user default). In every case where
the fake receives a message, the first one must be `server/discover`
(doc 11, doc 12 test 3), so a leaked `legacy` pin or a lost probe fails here.

Test credentials are generated per test and registered with the sandbox, so
they are redacted from artifacts. Assertions about them compute a boolean
first, so a failing assert never prints a value.
"""

import pytest

from fakes.http_fake import UNAUTHORIZED_DESCRIPTION
from fakes.wirelog import fingerprint
from harness.constants import (
    FAKE_MCP_PATH,
    FAKE_PRESENCE_ONLY_NONE,
    FIRST_MESSAGE_NEGOTIATION_UNSET,
    FREE_TEST_CANARY,
    FREE_TEST_TOOLSET,
    INIT_REPLY_IMMEDIATE_MS,
    STATUS_CONNECTED,
    STATUS_FAILED_TO_CONNECT,
    STATUS_NEEDS_AUTH,
)
from harness.check import expect_equal, expect_in, expect_not_in, expect_true, got
from harness.known_defects import DocumentedBehaviorMismatch, expect_documented, record_documented
from harness.mcp_setup import COMMANDS, add_http_server, add_stdio_fake, run_list_and_get, start_http
from harness.wire import (
    http_mcp_posts,
    http_requests,
    http_rpc_method,
    http_summary,
    message_method,
    stdio_lifetimes,
)

pytestmark = pytest.mark.free

PROBE_METHODS = ("server/discover", "ping")  # allowed before initialize
WELL_KNOWN_PREFIX = "/.well-known/"
PROTECTED_RESOURCE_PATH = "/.well-known/oauth-protected-resource" + FAKE_MCP_PATH
AUTHORIZATION_SERVER_PATH = "/.well-known/oauth-authorization-server"
REGISTER_PATH = "/register"
BARE_401_DISCOVERY_PATHS = (
    ("GET", PROTECTED_RESOURCE_PATH),
    ("GET", AUTHORIZATION_SERVER_PATH),
    ("POST", REGISTER_PATH),
)

BARE_401_DOC = ("mcp.md:762: a 401/403 from a server you have not signed in to marks it as needing "
                "authentication (written for an OAuth server; this one breaks the spec MUST to publish "
                "Protected Resource Metadata, 2025-11-25 basic__authorization.md:65)")
REASON_GET_REDACTION = (
    "2.1.296 `claude mcp get` prints the configured Authorization header in plain text. "
    "changelog.md:5864 (2.1.161): 'Fixed `claude mcp` list/get/add printing secrets to the terminal: "
    "... credential headers and URL secrets are redacted'."
)


# --------------------------------------------------------------------------
# helpers


def stdio_lives_by_command(*, sandbox, result):
    lives = {command: stdio_lifetimes(records=result["by_command"][command]) for command in COMMANDS}
    sandbox.record.observe(key="stdio_lifetimes", value=lives)
    sandbox.record.observe(
        key="stdio_messages_per_process",
        value={command: [life["methods"] for life in lives[command]] for command in COMMANDS},
    )
    return lives


def http_requests_by_command(*, sandbox, result):
    by_command = {command: http_requests(records=result["by_command"][command]) for command in COMMANDS}
    sandbox.record.observe(
        key="http_requests", value={command: http_summary(requests=by_command[command]) for command in COMMANDS}
    )
    sandbox.record.observe(
        key="http_rpc_methods_on_mcp_path",
        value={
            command: [
                http_rpc_method(request=r) for r in http_mcp_posts(requests=by_command[command], mcp_path=FAKE_MCP_PATH)
            ]
            for command in COMMANDS
        },
    )
    return by_command


def assert_first_message_is_probe(*, methods, where):
    expect_true(what="%s: messages the fake received" % where, expected="at least 1", actual=methods,
                holds=bool(methods))
    expect_equal(what="%s: first client message (MCP_PROTOCOL_NEGOTIATION unset)" % where,
                 expected=FIRST_MESSAGE_NEGOTIATION_UNSET, actual=methods[0])


def assert_http_first_message_is_probe(*, by_command):
    for command in COMMANDS:
        posts = http_mcp_posts(requests=by_command[command], mcp_path=FAKE_MCP_PATH)
        assert_first_message_is_probe(methods=[http_rpc_method(request=r) for r in posts], where=command)


def assert_handshake_order(*, methods):
    """Within one connection: nothing but a probe before initialize, then
    notifications/initialized, then tools/list (a Connected status implies a
    tools fetch: mcp-quickstart.md:62 has a separate 'tools fetch failed')."""
    expect_in(what="methods the fake received", item="initialize", container=methods)
    first_init = methods.index("initialize")
    before = methods[:first_init]
    expect_equal(what="requests before initialize other than %s" % (PROBE_METHODS,), expected=[],
                 actual=[m for m in before if m not in PROBE_METHODS])
    expect_in(what="methods after initialize", item="notifications/initialized", container=methods[first_init:])
    expect_in(what="methods after initialize", item="tools/list", container=methods[first_init:])
    expect_true(what="order of notifications/initialized and tools/list", expected="notifications/initialized first",
                actual=methods, holds=methods.index("notifications/initialized") < methods.index("tools/list"))


def redacted_detail(*, sandbox, detail):
    """A status detail as it may be shown in a log or a check message."""
    return None if detail is None else sandbox.registry.redact_text(text=detail)


def assert_status(*, sandbox, result, name, status, detail_absent):
    """The `claude mcp list` status (and, when detail_absent, no detail) and
    the `claude mcp get` Status field of server `name`."""
    expect_equal(what="`claude mcp list` status of %s" % name, expected=status, actual=result["status"])
    if detail_absent:
        expect_equal(what="`claude mcp list` failure detail of %s" % name, expected=None,
                     actual=redacted_detail(sandbox=sandbox, detail=result["detail"]))
    expect_equal(what="`claude mcp get %s` Status" % name, expected=status, actual=result["get_fields"]["Status"])


def assert_no_issue_line(*, result, name):
    # Field names only: the field values of `claude mcp get` may hold the
    # configured header in clear (finding 5).
    expect_not_in(what="`claude mcp get %s` field names" % name, item="Issue", container=sorted(result["get_fields"]))


def initialize_versions(*, records):
    return [
        record["msg"]["params"]["protocolVersion"]
        for record in records
        if record["event"] == "recv" and message_method(message=record["msg"]) == "initialize"
    ]


def paths_requested(*, requests, method, path):
    return [r for r in requests if r["method"] == method and r["path"] == path]


# --------------------------------------------------------------------------
# 1. stdio, healthy


def test_stdio_healthy_is_connected(free_sandbox):
    name = "fake_stdio_ok"
    wire_log = add_stdio_fake(
        sandbox=free_sandbox, name=name, mode="normal", init_reply_delay_ms=INIT_REPLY_IMMEDIATE_MS,
        canary=FREE_TEST_CANARY, toolset=FREE_TEST_TOOLSET, presence_only_env=FAKE_PRESENCE_ONLY_NONE, extra_env={}
    )
    result = run_list_and_get(sandbox=free_sandbox, name=name, wire_log=wire_log)
    lives = stdio_lives_by_command(sandbox=free_sandbox, result=result)
    free_sandbox.record.observe(
        key="initialize_protocol_versions", value=initialize_versions(records=result["all_records"])
    )

    assert_status(sandbox=free_sandbox, result=result, name=name, status=STATUS_CONNECTED, detail_absent=True)
    assert_no_issue_line(result=result, name=name)

    # Wire oracle: `list` and `get` each really connected to the fake.
    for command in COMMANDS:
        expect_true(what="%s: stdio fake processes started" % command, expected="at least 1",
                    actual=len(lives[command]), holds=bool(lives[command]))
        for life in lives[command]:
            got(what="%s pid %s: methods received" % (command, life["pid"]), value=life["methods"])
            expect_equal(what="%s pid %s: `started` record" % (command, life["pid"]), expected=True,
                         actual=life["started"])
            assert_first_message_is_probe(methods=life["methods"], where="%s pid %s" % (command, life["pid"]))
            assert_handshake_order(methods=life["methods"])


# --------------------------------------------------------------------------
# 2. stdio, exits at start


def test_stdio_exit_at_start_is_failed_to_connect(free_sandbox):
    name = "fake_stdio_dead"
    wire_log = add_stdio_fake(
        sandbox=free_sandbox, name=name, mode="exit_at_start", init_reply_delay_ms=INIT_REPLY_IMMEDIATE_MS,
        canary=FREE_TEST_CANARY, toolset=FREE_TEST_TOOLSET, presence_only_env=FAKE_PRESENCE_ONLY_NONE, extra_env={}
    )
    result = run_list_and_get(sandbox=free_sandbox, name=name, wire_log=wire_log)
    lives = stdio_lives_by_command(sandbox=free_sandbox, result=result)
    spawns_per_command = {c: len(lives[c]) for c in COMMANDS}
    free_sandbox.record.observe(key="spawns_per_command", value=spawns_per_command)
    got(what="spawns per command (recorded, not asserted)", value=spawns_per_command)

    assert_status(sandbox=free_sandbox, result=result, name=name, status=STATUS_FAILED_TO_CONNECT,
                  detail_absent=False)
    # mcp.md:287: on Failed to connect, list appends a detail, get has Issue:.
    expect_true(what="failure detail on the `claude mcp list` line of %s" % name, expected="a non-empty detail",
                actual=redacted_detail(sandbox=free_sandbox, detail=result["detail"]), holds=bool(result["detail"]))
    fields = result["get_fields"]
    expect_true(what="`claude mcp get %s` Issue line" % name, expected="present and non-empty",
                actual=free_sandbox.registry.redact_text(text=fields["Issue"]) if "Issue" in fields else "(absent)",
                holds="Issue" in fields and bool(fields["Issue"]))

    # Wire oracle: the client did spawn the fake, which died before reading,
    # so it received nothing (no first message to check).
    for command in COMMANDS:
        expect_true(what="%s: stdio fake processes started" % command, expected="at least 1",
                    actual=len(lives[command]), holds=bool(lives[command]))
        for life in lives[command]:
            expect_equal(what="%s pid %s: started, methods received, logged exit" % (command, life["pid"]),
                         expected={"started": True, "methods": [], "exit": True},
                         actual={"started": life["started"], "methods": life["methods"], "exit": "exit" in life["end"]})


# --------------------------------------------------------------------------
# 3. HTTP, right static header


def test_http_right_header_is_connected(free_sandbox):
    name = "fake_http_ok"
    token = free_sandbox.new_bearer()
    with start_http(sandbox=free_sandbox, name=name, auth_mode="require", expected_authorization=token) as fake:
        add_http_server(sandbox=free_sandbox, name=name, url=fake.url, authorization=token)
        result = run_list_and_get(sandbox=free_sandbox, name=name, wire_log=fake.log_path)
    by_command = http_requests_by_command(sandbox=free_sandbox, result=result)

    assert_status(sandbox=free_sandbox, result=result, name=name, status=STATUS_CONNECTED, detail_absent=True)
    assert_no_issue_line(result=result, name=name)

    assert_http_first_message_is_probe(by_command=by_command)
    expected = fingerprint(value=token)
    for command in COMMANDS:
        requests = by_command[command]
        got(what="%s: HTTP requests the fake logged" % command, value=http_summary(requests=requests))
        mcp_requests = [r for r in requests if r["path"] == FAKE_MCP_PATH]
        rpc_ok = [http_rpc_method(request=r) for r in mcp_requests if r["status"] == 200]
        expect_in(what="%s: JSON-RPC methods answered 200" % command, item="initialize", container=rpc_ok)
        expect_in(what="%s: JSON-RPC methods answered 200" % command, item="tools/list", container=rpc_ok)
        # Every MCP request carried exactly the configured header (by hash).
        for request in mcp_requests:
            expect_equal(what="%s: the fake's auth verdict for %s %s" % (command, request["method"], request["path"]),
                         expected="match", actual=request["auth"])
            expect_equal(what="%s: Authorization fingerprint sent vs the configured value" % command,
                         expected=expected, actual=request["headers"]["authorization"])
        expect_equal(what="%s: OAuth discovery requests (%s*) with a working header" % (command, WELL_KNOWN_PREFIX),
                     expected=[], actual=[r["path"] for r in requests if r["path"].startswith(WELL_KNOWN_PREFIX)])


# 3r. HTTP: `claude mcp get` must not print the configured header


@pytest.mark.xfail(strict=True, raises=DocumentedBehaviorMismatch, reason=REASON_GET_REDACTION)
def test_http_configured_header_is_redacted_in_cli_output(free_sandbox):
    name = "fake_http_redact"
    token = free_sandbox.new_bearer()
    with start_http(sandbox=free_sandbox, name=name, auth_mode="require", expected_authorization=token) as fake:
        added = add_http_server(sandbox=free_sandbox, name=name, url=fake.url, authorization=token)
        result = run_list_and_get(sandbox=free_sandbox, name=name, wire_log=fake.log_path)

    # Booleans first: a check never shows the value itself.
    shown = {
        "claude mcp add": token in added.combined,
        "claude mcp list": token in result["listed"].combined,
        "claude mcp get": token in result["got"].combined,
    }
    free_sandbox.record.observe(key="header_value_printed_by", value=shown)
    got(what="configured Authorization value printed in clear, per command", value=shown)
    # add and list redact on 2.1.296: plain checks, a regression fails the run.
    expect_equal(what="configured Authorization value printed by `claude mcp add`", expected=False,
                 actual=shown["claude mcp add"])
    expect_equal(what="configured Authorization value printed by `claude mcp list`", expected=False,
                 actual=shown["claude mcp list"])
    expect_documented(
        what="configured Authorization value printed by `claude mcp get`",
        doc="not printed: credential headers are redacted (changelog.md:5864, 2.1.161)",
        actual="printed in clear" if shown["claude mcp get"] else "not printed",
        holds=not shown["claude mcp get"],
    )


# 4. HTTP, wrong static header -> 401 -> Failed to connect + 401 detail (D13/T3a)


def test_http_wrong_header_is_failed_with_401_detail(free_sandbox):
    name = "fake_http_badkey"
    accepted = free_sandbox.new_bearer()
    configured = free_sandbox.new_bearer()
    with start_http(sandbox=free_sandbox, name=name, auth_mode="require", expected_authorization=accepted) as fake:
        add_http_server(sandbox=free_sandbox, name=name, url=fake.url, authorization=configured)
        result = run_list_and_get(sandbox=free_sandbox, name=name, wire_log=fake.log_path)
    by_command = http_requests_by_command(sandbox=free_sandbox, result=result)
    redact = free_sandbox.registry.redact_text

    # Status: a FAILURE, not "needs authentication" (mcp.md:766), with the
    # HTTP status and the server's error text (mcp.md:287).
    expect_equal(what="`claude mcp list` status of %s" % name, expected=STATUS_FAILED_TO_CONNECT,
                 actual=result["status"])
    detail = result["detail"]
    issue = result["get_fields"]["Issue"]
    expect_true(what="`claude mcp list` failure detail of %s" % name,
                expected="contains '401' and %r" % UNAUTHORIZED_DESCRIPTION,
                actual=redacted_detail(sandbox=free_sandbox, detail=detail),
                holds=bool(detail) and "401" in detail and UNAUTHORIZED_DESCRIPTION in detail)
    expect_equal(what="`claude mcp get %s` Status" % name, expected=STATUS_FAILED_TO_CONNECT,
                 actual=result["get_fields"]["Status"])
    expect_true(what="`claude mcp get %s` Issue line" % name,
                expected="contains '401' and %r" % UNAUTHORIZED_DESCRIPTION, actual=redact(text=issue),
                holds="401" in issue and UNAUTHORIZED_DESCRIPTION in issue)
    # The detail must not echo the credential (mcp.md:287: redacted).
    detail_leaks = configured in detail
    issue_leaks = configured in issue
    expect_equal(what="configured Authorization value in the list failure detail", expected=False, actual=detail_leaks)
    expect_equal(what="configured Authorization value in the get Issue line", expected=False, actual=issue_leaks)

    # Wire oracle: the configured (wrong) header reached the fake and was
    # answered 401; no OAuth discovery for a server with a configured header.
    assert_http_first_message_is_probe(by_command=by_command)
    sent = fingerprint(value=configured)
    for command in COMMANDS:
        requests = by_command[command]
        got(what="%s: HTTP requests the fake logged" % command, value=http_summary(requests=requests))
        mcp_requests = [r for r in requests if r["path"] == FAKE_MCP_PATH]
        expect_true(what="%s: requests that reached %s" % (command, FAKE_MCP_PATH), expected="at least 1",
                    actual=len(mcp_requests), holds=bool(mcp_requests))
        for request in mcp_requests:
            expect_equal(what="%s: the fake's auth verdict and HTTP status" % command, expected=("mismatch", 401),
                         actual=(request["auth"], request["status"]))
            expect_equal(what="%s: Authorization fingerprint sent vs the configured value" % command,
                         expected=sent, actual=request["headers"]["authorization"])
        expect_equal(what="%s: OAuth discovery requests (%s*) with a configured header" % (command, WELL_KNOWN_PREFIX),
                     expected=[], actual=[r["path"] for r in requests if r["path"].startswith(WELL_KNOWN_PREFIX)])


# 5. HTTP, no header, spec-compliant protected server -> Needs authentication (D13/T3b)


def test_http_no_header_needs_authentication(free_sandbox):
    """The fake answers 401 and publishes RFC 9728 / RFC 8414 discovery
    documents (MCP 2025-11-25 authorization: servers MUST implement
    Protected Resource Metadata). It has no authorize/token/register
    endpoints, so no sign-in can complete."""
    name = "fake_http_nokey"
    with start_http(
        sandbox=free_sandbox, name=name, auth_mode="require", expected_authorization=free_sandbox.new_bearer()
    ) as fake:
        add_http_server(sandbox=free_sandbox, name=name, url=fake.url, authorization=None)
        result = run_list_and_get(sandbox=free_sandbox, name=name, wire_log=fake.log_path)
    by_command = http_requests_by_command(sandbox=free_sandbox, result=result)
    register = {c: bool(paths_requested(requests=by_command[c], method="POST", path=REGISTER_PATH)) for c in COMMANDS}
    free_sandbox.record.observe(key="register_requested", value=register)
    got(what="POST %s requested, per command (recorded, not asserted)" % REGISTER_PATH, value=register)

    assert_status(sandbox=free_sandbox, result=result, name=name, status=STATUS_NEEDS_AUTH, detail_absent=True)
    assert_no_issue_line(result=result, name=name)

    # Wire oracle: the request went out with no Authorization header, got
    # 401, and the client then looked up the protected-resource metadata
    # (spec: clients MUST use it for authorization-server discovery).
    assert_http_first_message_is_probe(by_command=by_command)
    for command in COMMANDS:
        requests = by_command[command]
        got(what="%s: HTTP requests the fake logged" % command, value=http_summary(requests=requests))
        mcp_requests = [r for r in requests if r["path"] == FAKE_MCP_PATH]
        expect_true(what="%s: requests that reached %s" % (command, FAKE_MCP_PATH), expected="at least 1",
                    actual=len(mcp_requests), holds=bool(mcp_requests))
        expect_equal(what="%s: the fake's auth verdict and HTTP status of each %s request" % (command, FAKE_MCP_PATH),
                     expected=[("missing", 401)] * len(mcp_requests),
                     actual=[(r["auth"], r["status"]) for r in mcp_requests])
        expect_equal(what="%s: requests that carried an Authorization header" % command, expected=[],
                     actual=["%s %s" % (r["method"], r["path"]) for r in requests if "authorization" in r["headers"]])
        found = paths_requested(requests=requests, method="GET", path=PROTECTED_RESOURCE_PATH)
        expect_true(what="%s: GET %s requests" % (command, PROTECTED_RESOURCE_PATH), expected="at least 1",
                    actual=len(found), holds=bool(found))


# 5b. HTTP, no header, bare 401 with no OAuth metadata (out-of-spec server, record-only)


def test_http_bare_401_out_of_spec_server_status_recorded(free_sandbox):
    """The server breaks the spec MUST to publish Protected Resource
    Metadata (2025-11-25 basic__authorization.md:65), so this is not a
    client defect: the client follows the spec's MUST fallback (it tries
    the discovery paths) and reports the failure it got (2.1.296: "✘
    Failed to connect — Dynamic Client Registration rejected (HTTP 404)").
    The wire checks are plain asserts (the probe, and the 401 on the MCP
    path). The status is compared with mcp.md:762 record-only
    (record_documented, run.json `documented_bare_401_status`), and the
    OAuth discovery paths requested are recorded, not asserted."""
    name = "fake_http_bare401"
    with start_http(
        sandbox=free_sandbox, name=name, auth_mode="require_bare", expected_authorization=free_sandbox.new_bearer()
    ) as fake:
        add_http_server(sandbox=free_sandbox, name=name, url=fake.url, authorization=None)
        result = run_list_and_get(sandbox=free_sandbox, name=name, wire_log=fake.log_path)
    by_command = http_requests_by_command(sandbox=free_sandbox, result=result)

    assert_http_first_message_is_probe(by_command=by_command)
    for command in COMMANDS:
        requests = by_command[command]
        got(what="%s: HTTP requests the fake logged" % command, value=http_summary(requests=requests))
        mcp_requests = [r for r in requests if r["path"] == FAKE_MCP_PATH]
        verdicts = [(r["auth"], r["status"]) for r in mcp_requests]
        expect_true(what="%s: the fake's auth verdict and HTTP status of each %s request" % (command, FAKE_MCP_PATH),
                    expected="at least 1 request, each ('missing', 401)", actual=verdicts,
                    holds=bool(mcp_requests) and all(v == ("missing", 401) for v in verdicts))
    discovery = {
        command: {
            "%s %s" % (method, path): [
                r["status"] for r in paths_requested(requests=by_command[command], method=method, path=path)
            ]
            for method, path in BARE_401_DISCOVERY_PATHS
        }
        for command in COMMANDS
    }
    free_sandbox.record.observe(key="oauth_discovery_paths_requested", value=discovery)
    got(what="OAuth discovery paths requested, with their statuses (recorded, not asserted)", value=discovery)

    detail = redacted_detail(sandbox=free_sandbox, detail=result["detail"])
    matches = record_documented(
        what="status of %s (bare 401, no header configured) in `claude mcp list` and `get`" % name,
        doc="%s in both (%s)" % (STATUS_NEEDS_AUTH, BARE_401_DOC),
        actual="list %r (detail %r), get %r" % (result["status"], detail, result["get_fields"]["Status"]),
        holds=result["status"] == STATUS_NEEDS_AUTH and result["get_fields"]["Status"] == STATUS_NEEDS_AUTH,
    )
    free_sandbox.record.observe(key="documented_bare_401_status", value={
        "doc": "%s in both (%s)" % (STATUS_NEEDS_AUTH, BARE_401_DOC), "list_status": result["status"],
        "list_detail": detail, "get_status": result["get_fields"]["Status"], "matches": matches})
