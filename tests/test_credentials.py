"""D13/T4 + D23/T11 (+ D13/T1 connect part): credentials that reach a server.

Free: no model call. ANTHROPIC_API_KEY is set to a per-test dummy
(DUMMY_SECRET_PREFIX + secrets.token_hex), never the real key, in the env of
the claude subprocesses of these tests only. Every dummy is registered with
the sandbox: redacted from command logs and copied config, and the teardown
scan fails the test if one is found in the artifacts. The fakes log only
sha8 + length; the asserts compare fingerprints, never values.

stdio (env inheritance, env-vars.md:406 and the scrub table at 553-558):
  B1a  default: inherited credentials reach the stdio server
  B1b  CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1: they are stripped, by name, with
       the table's exceptions kept
  B3   `claude mcp add --env KEY=value`: the value reaches the server (mcp.md:138)
remote (mcp.md:677-689, "Credential variables that read as empty"):
  B2   `${ANTHROPIC_API_KEY}` / `${NPM_TOKEN}` in headers.Authorization, and
       `${ANTHROPIC_API_KEY}` in the url, are sent empty; a name of our own
       (`${MY_SERVICE_TOKEN}`) is expanded (the control)
"""

import pytest

from fakes.wirelog import fingerprint
from harness.constants import (
    API_KEY_ENV,
    FAKE_MCP_PATH,
    FREE_TEST_CANARY,
    FREE_TEST_TOOLSET,
    INIT_REPLY_IMMEDIATE_MS,
    STATUS_CONNECTED,
    STATUS_FAILED_TO_CONNECT,
    SUBPROCESS_ENV_SCRUB_ENV,
)
from harness.check import expect_equal, expect_not_in, expect_true, got
from harness.mcp_setup import COMMANDS, add_http_server, add_stdio_fake, run_list_and_get, start_http
from harness.wire import http_requests, http_summary, records_by_pid

pytestmark = pytest.mark.free

AUTH_TOKEN_ENV = "ANTHROPIC_AUTH_TOKEN"
NPM_TOKEN_ENV = "NPM_TOKEN"  # mcp.md:685 (blanked remote); env-vars.md:554 (scrubbed)
GITHUB_TOKEN_ENV = "GITHUB_TOKEN"  # env-vars.md:558: the scrub leaves it in place
OWN_INHERITED_ENV = "MY_INHERITED_TOKEN"  # credential-like name of our own, inherited
OWN_SERVICE_ENV = "MY_SERVICE_TOKEN"  # name of our own, passed with --env / used in ${}
CONFIG_DIR_NAME = "CLAUDE_CONFIG_DIR"  # env-vars.md:557: the scrub removes it
SCRUB_ON = "1"
QUERY_PARAM = "key"
EMPTY = fingerprint(value="")


# --------------------------------------------------------------------------
# helpers


def started_records(*, records):
    """The `started` record of every stdio fake process, in order."""
    return [
        group[0] for group in records_by_pid(records=records).values() if group and group[0]["event"] == "started"
    ]


def stdio_env_by_command(*, sandbox, result):
    """{command: [env fingerprints of each spawn]} and the run.json view."""
    by_command = {}
    for command in COMMANDS:
        starts = started_records(records=result["by_command"][command])
        expect_true(what="%s: stdio fake processes started" % command, expected="at least 1", actual=len(starts),
                    holds=bool(starts))
        by_command[command] = [start["env"] for start in starts]
        # Names and fingerprints (sha8 + length) only: the fake never logs a value.
        got(what="%s: credential-like env names each spawn saw" % command,
            value=[start["credential_env"] for start in starts])
    sandbox.record.observe(
        key="credential_env_seen",
        value={
            command: [
                start["credential_env"] for start in started_records(records=result["by_command"][command])
            ]
            for command in COMMANDS
        },
    )
    return by_command


def set_dummy(*, sandbox, name):
    value = sandbox.new_dummy_secret()
    sandbox.set_env(name=name, value=value, secret=True)
    return value


def add_inheritance_fake(*, sandbox, name, service_value):
    return add_stdio_fake(
        sandbox=sandbox, name=name, mode="normal", init_reply_delay_ms=INIT_REPLY_IMMEDIATE_MS,
        canary=FREE_TEST_CANARY, toolset=FREE_TEST_TOOLSET, extra_env={OWN_SERVICE_ENV: service_value},
    )


def assert_reaches(*, envs, name, value):
    """Compared as fingerprints (sha8 + length); a value is never shown."""
    expected = fingerprint(value=value)
    for command in COMMANDS:
        for env in envs[command]:
            expect_equal(what="%s: fingerprint of %s in the stdio server's env" % (command, name), expected=expected,
                         actual=env[name] if name in env else "(absent)")


def assert_absent(*, envs, name):
    for command in COMMANDS:
        for env in envs[command]:
            expect_not_in(what="%s: env names the stdio server got" % command, item=name, container=sorted(env))


# --------------------------------------------------------------------------
# B1a / B1b: stdio env inheritance, default and scrubbed


def test_stdio_inherits_credentials_by_default(free_sandbox):
    """env-vars.md:545: the scrub is what removes credentials from stdio
    servers; without it they inherit Claude Code's environment."""
    inherited = {
        API_KEY_ENV: set_dummy(sandbox=free_sandbox, name=API_KEY_ENV),
        AUTH_TOKEN_ENV: set_dummy(sandbox=free_sandbox, name=AUTH_TOKEN_ENV),
        NPM_TOKEN_ENV: set_dummy(sandbox=free_sandbox, name=NPM_TOKEN_ENV),
        GITHUB_TOKEN_ENV: set_dummy(sandbox=free_sandbox, name=GITHUB_TOKEN_ENV),
        OWN_INHERITED_ENV: set_dummy(sandbox=free_sandbox, name=OWN_INHERITED_ENV),
    }
    service = free_sandbox.new_dummy_secret()
    name = "fake_stdio_env_default"
    wire_log = add_inheritance_fake(sandbox=free_sandbox, name=name, service_value=service)
    result = run_list_and_get(sandbox=free_sandbox, name=name, wire_log=wire_log)
    envs = stdio_env_by_command(sandbox=free_sandbox, result=result)

    expect_equal(what="`claude mcp list` status of %s" % name, expected=STATUS_CONNECTED, actual=result["status"])
    for env_name in sorted(inherited):
        assert_reaches(envs=envs, name=env_name, value=inherited[env_name])
    assert_reaches(envs=envs, name=OWN_SERVICE_ENV, value=service)
    assert_reaches(envs=envs, name=CONFIG_DIR_NAME, value=free_sandbox.config_dir)


def test_stdio_env_scrub_strips_inherited_credentials(free_sandbox):
    """CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1 (env-vars.md:406, 545-558): removes
    ANTHROPIC_API_KEY (553), names that look like a credential (554: NPM_TOKEN;
    also ANTHROPIC_AUTH_TOKEN and our MY_INHERITED_TOKEN), CLAUDE_CONFIG_DIR
    (557); leaves GITHUB_TOKEN (558).

    A credential-named value passed to this server with `--env`
    (MY_SERVICE_TOKEN) is only recorded, not asserted: env-vars.md:406 does
    not exempt server-configured env from the scrub, and mcp.md:138 only
    says the server runs with KEY=value in its environment, so neither
    outcome is a documented fact (observations.md). run.json key
    `observations.configured_env_under_scrub` holds what 2.1.296 did."""
    free_sandbox.set_env(name=SUBPROCESS_ENV_SCRUB_ENV, value=SCRUB_ON, secret=False)
    stripped = (API_KEY_ENV, AUTH_TOKEN_ENV, NPM_TOKEN_ENV, OWN_INHERITED_ENV)
    for env_name in stripped:
        set_dummy(sandbox=free_sandbox, name=env_name)
    github = set_dummy(sandbox=free_sandbox, name=GITHUB_TOKEN_ENV)
    service = free_sandbox.new_dummy_secret()
    name = "fake_stdio_env_scrub"
    wire_log = add_inheritance_fake(sandbox=free_sandbox, name=name, service_value=service)
    result = run_list_and_get(sandbox=free_sandbox, name=name, wire_log=wire_log)
    envs = stdio_env_by_command(sandbox=free_sandbox, result=result)

    expect_equal(what="`claude mcp list` status of %s" % name, expected=STATUS_CONNECTED, actual=result["status"])
    for env_name in stripped + (CONFIG_DIR_NAME,):
        assert_absent(envs=envs, name=env_name)
    assert_reaches(envs=envs, name=GITHUB_TOKEN_ENV, value=github)
    under_scrub = {
        command: [
            {
                "name": OWN_SERVICE_ENV,
                "present": OWN_SERVICE_ENV in env,
                "matches_configured_value": OWN_SERVICE_ENV in env
                and env[OWN_SERVICE_ENV] == fingerprint(value=service),
            }
            for env in envs[command]
        ]
        for command in COMMANDS
    }
    free_sandbox.record.observe(key="configured_env_under_scrub", value=under_scrub)
    got(what="--env %s under the scrub, per spawn (recorded, not asserted)" % OWN_SERVICE_ENV, value=under_scrub)


# --------------------------------------------------------------------------
# B3: `claude mcp add --env KEY=value` reaches the stdio server (D13/T1, connect part)


def test_stdio_env_flag_value_reaches_server(free_sandbox):
    service = free_sandbox.new_dummy_secret()
    name = "fake_stdio_env_flag"
    wire_log = add_inheritance_fake(sandbox=free_sandbox, name=name, service_value=service)
    result = run_list_and_get(sandbox=free_sandbox, name=name, wire_log=wire_log)
    envs = stdio_env_by_command(sandbox=free_sandbox, result=result)

    expect_equal(what="(`claude mcp list` status, `claude mcp get` Status) of %s" % name,
                 expected=(STATUS_CONNECTED, STATUS_CONNECTED), actual=(result["status"], result["get_fields"]["Status"]))
    assert_reaches(envs=envs, name=OWN_SERVICE_ENV, value=service)


# --------------------------------------------------------------------------
# B2: remote url / headers.Authorization blanking (D13/T4)


def mcp_requests_by_command(*, sandbox, result):
    by_command = {
        command: [r for r in http_requests(records=result["by_command"][command]) if r["path"] == FAKE_MCP_PATH]
        for command in COMMANDS
    }
    sandbox.record.observe(
        key="http_requests",
        value={command: http_summary(requests=by_command[command]) for command in COMMANDS},
    )
    sandbox.record.observe(
        key="authorization_sent",
        value={command: [r["authorization"] for r in by_command[command]] for command in COMMANDS},
    )
    sandbox.record.observe(
        key="query_sent", value={command: [r["query"] for r in by_command[command]] for command in COMMANDS}
    )
    for command in COMMANDS:
        got(what="%s: requests to %s" % (command, FAKE_MCP_PATH), value=http_summary(requests=by_command[command]))
        expect_true(what="%s: requests that reached the fake" % command, expected="at least 1",
                    actual=len(by_command[command]), holds=bool(by_command[command]))
    return by_command


@pytest.mark.parametrize("variable", [API_KEY_ENV, NPM_TOKEN_ENV])
def test_remote_header_credential_variable_is_sent_empty(free_sandbox, variable):
    """mcp.md:679: `Bearer ${VAR}` with a covered name reaches the server as
    `Bearer ` with no credential, and the 401 is reported as a failed
    connection (mcp.md:766). The fake accepts only `Bearer <dummy>`."""
    value = set_dummy(sandbox=free_sandbox, name=variable)
    name = "fake_http_blank_header"
    with start_http(
        sandbox=free_sandbox, name=name, auth_mode="require", expected_authorization="Bearer " + value
    ) as fake:
        add_http_server(sandbox=free_sandbox, name=name, url=fake.url, authorization="Bearer ${%s}" % variable)
        result = run_list_and_get(sandbox=free_sandbox, name=name, wire_log=fake.log_path)
    by_command = mcp_requests_by_command(sandbox=free_sandbox, result=result)

    for command in COMMANDS:
        for request in by_command[command]:
            sent = request["authorization"]
            expect_equal(what="%s: Authorization scheme sent" % command, expected="Bearer",
                         actual=sent["scheme"] if sent is not None else "(no Authorization header)")
            expect_equal(what="%s: fingerprint of the credential sent for ${%s}" % (command, variable), expected=EMPTY,
                         actual=sent["credential"])
            expect_equal(what="%s: the fake's auth verdict and HTTP status" % command, expected=("mismatch", 401),
                         actual=(request["auth"], request["status"]))
    expect_equal(what="`claude mcp list` status of %s" % name, expected=STATUS_FAILED_TO_CONNECT,
                 actual=result["status"])
    expect_equal(what="`claude mcp get %s` Status" % name, expected=STATUS_FAILED_TO_CONNECT,
                 actual=result["get_fields"]["Status"])


def test_remote_header_own_variable_is_expanded(free_sandbox):
    """Control for the blanking test: mcp.md:689, a name outside the covered
    set expands as written."""
    value = set_dummy(sandbox=free_sandbox, name=OWN_SERVICE_ENV)
    name = "fake_http_own_header"
    with start_http(
        sandbox=free_sandbox, name=name, auth_mode="require", expected_authorization="Bearer " + value
    ) as fake:
        add_http_server(sandbox=free_sandbox, name=name, url=fake.url, authorization="Bearer ${%s}" % OWN_SERVICE_ENV)
        result = run_list_and_get(sandbox=free_sandbox, name=name, wire_log=fake.log_path)
    by_command = mcp_requests_by_command(sandbox=free_sandbox, result=result)

    for command in COMMANDS:
        for request in by_command[command]:
            sent = request["authorization"]
            expect_equal(what="%s: Authorization scheme sent" % command, expected="Bearer",
                         actual=sent["scheme"] if sent is not None else "(no Authorization header)")
            expect_equal(what="%s: fingerprint of the credential sent for ${%s}" % (command, OWN_SERVICE_ENV),
                         expected=fingerprint(value=value), actual=sent["credential"])
            expect_equal(what="%s: the fake's auth verdict" % command, expected="match", actual=request["auth"])
    expect_equal(what="`claude mcp list` status of %s" % name, expected=STATUS_CONNECTED, actual=result["status"])
    expect_equal(what="`claude mcp get %s` Status" % name, expected=STATUS_CONNECTED,
                 actual=result["get_fields"]["Status"])


@pytest.mark.parametrize(
    "variable, expect_value",
    [(API_KEY_ENV, False), (OWN_SERVICE_ENV, True)],
    ids=["covered-name-blanked", "own-name-expanded"],
)
def test_remote_url_variable(free_sandbox, variable, expect_value):
    """mcp.md:679: the same rule in the url. The fake does not check auth;
    it logs the query parameter as sha8 + length."""
    value = set_dummy(sandbox=free_sandbox, name=variable)
    name = "fake_http_url_var"
    with start_http(sandbox=free_sandbox, name=name, auth_mode="off", expected_authorization=None) as fake:
        url = "%s?%s=${%s}" % (fake.url, QUERY_PARAM, variable)
        add_http_server(sandbox=free_sandbox, name=name, url=url, authorization=None)
        result = run_list_and_get(sandbox=free_sandbox, name=name, wire_log=fake.log_path)
    by_command = mcp_requests_by_command(sandbox=free_sandbox, result=result)

    expected = fingerprint(value=value) if expect_value else EMPTY
    for command in COMMANDS:
        for request in by_command[command]:
            params = [p for p in request["query"] if p["name"] == QUERY_PARAM]
            expect_equal(what="%s: query parameters named %r (query %r)" % (command, QUERY_PARAM, request["query"]),
                         expected=1, actual=len(params))
            expect_equal(what="%s: fingerprint of ${%s} sent in the url" % (command, variable), expected=expected,
                         actual=params[0]["value"])
    expect_equal(what="`claude mcp list` status of %s" % name, expected=STATUS_CONNECTED, actual=result["status"])
