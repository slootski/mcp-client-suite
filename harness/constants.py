"""Named constants shared by the harness and the tests.

Every value that more than one place needs lives here once, and is passed
explicitly at each call site. Nothing here is a parameter default.
"""

# System under test.
EXPECTED_CLAUDE_VERSION = "2.1.296"
CLAUDE_BIN = "claude"
VERSION_GATE_TIMEOUT_S = 30
VERSION_GATE_EXIT_CODE = 10  # pytest.exit code when `claude --version` is wrong

# A `claude ...` subprocess must finish well inside the per-test pytest
# timeout (pytest.ini: timeout = 120), so a hang still returns its output.
CLAUDE_CLI_TIMEOUT_S = 60

# Environment.
API_KEY_ENV = "ANTHROPIC_API_KEY"
ARTIFACT_DIR_ENV = "SUITE_ARTIFACT_DIR"  # set by harness.entrypoint
IMAGE_ID_ENV = "SUITE_IMAGE_ID"  # set by run.sh
BASE_IMAGE_ENV = "SUITE_BASE_IMAGE"  # set in the Dockerfile from the FROM pin
# Copied from the runner's environment into every claude subprocess.
PASSTHROUGH_ENV = ("PATH", "LANG", "LC_ALL")

MCP_TIMEOUT_MS = "15000"  # server startup timeout, set explicitly (doc 11)

# Per-test env overrides (set with Sandbox.set_env, recorded in run.json).
NEGOTIATION_ENV = "MCP_PROTOCOL_NEGOTIATION"
NEGOTIATION_LEGACY = "legacy"
SUBPROCESS_ENV_SCRUB_ENV = "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"
# env-vars.md:334: "Set to `1` to spawn stdio MCP servers with only a safe
# baseline environment plus the server's configured `env`, instead of
# inheriting your shell environment".
MCP_ALLOWLIST_ENV = "CLAUDE_CODE_MCP_ALLOWLIST_ENV"
MCP_ALLOWLIST_ON = "1"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"

# Test credentials. Every generated value starts with one of these prefixes,
# so the entrypoint scan can find a leak even when the per-test scan did not
# run (a hard timeout). The prefixes are not secrets; the hex after them is.
BEARER_TEST_PREFIX = "Bearer test-"
DUMMY_SECRET_PREFIX = "test-dummy-"
SECRET_SCAN_MARKERS = (BEARER_TEST_PREFIX, DUMMY_SECRET_PREFIX)
TEST_SECRET_HEX_BYTES = 16

# stdio fake FAKE_PRESENCE_ONLY_ENV (fakes/stdio_fake.py): env names the
# fake logs as {"set": true} instead of a fingerprint. Model tests: the live
# key, so not even its sha8 reaches an artifact. Free tests: none, so the
# credential tests can compare the dummy ANTHROPIC_API_KEY by fingerprint.
FAKE_PRESENCE_ONLY_MODEL = (API_KEY_ENV,)
FAKE_PRESENCE_ONLY_NONE = ()

# Config-dir files never copied into the artifacts, whatever they hold
# (harness/redact.py copy_tree_redacted): `.credentials.json` is where
# Claude Code keeps OAuth tokens. Listed in run.json as withheld.
WITHHELD_CONFIG_FILE_NAMES = (".credentials.json",)

# Pins for tests that make no model call (marker `free`). The API key is
# left out on purpose: a free test must not depend on it.
FREE_ENV_PINS = {
    "DISABLE_AUTOUPDATER": "1",
    "DISABLE_TELEMETRY": "1",
    "DISABLE_ERROR_REPORTING": "1",
    "MCP_TIMEOUT": MCP_TIMEOUT_MS,
}
# Left unset on purpose in free tests, so the user default applies. Recorded
# in run.json so a reader sees the choice was deliberate.
FREE_ENV_UNSET = ("MCP_PROTOCOL_NEGOTIATION", "MCP_SDK_GENERATION", API_KEY_ENV)

# Fakes.
FAKE_HOST = "127.0.0.1"
# stdio fake FAKE_INIT_REPLY_DELAY_MS: 0 answers initialize at once; the
# handshake tests hold the reply so a request sent too early shows in the log.
INIT_REPLY_IMMEDIATE_MS = 0
INIT_REPLY_HELD_MS = 300
FAKE_MCP_PATH = "/mcp"
FAKE_STARTUP_TIMEOUT_S = 10
FAKE_STOP_TIMEOUT_S = 5

# `claude mcp list` / `claude mcp get` status strings, verbatim from
# mcp.md:257 and mcp-quickstart.md:61-66 (glyph included).
STATUS_CONNECTED = "✔ Connected"
STATUS_FAILED_TO_CONNECT = "✘ Failed to connect"
STATUS_NEEDS_AUTH = "! Needs authentication"
# `claude mcp list` appends a failure detail after this separator (observed
# on 2.1.296: "✘ Failed to connect — <detail>"); `claude mcp get` puts the
# same detail on an "Issue:" line (mcp.md:287).
LIST_DETAIL_SEPARATOR = " — "

# With MCP_PROTOCOL_NEGOTIATION unset, the client probes before the legacy
# handshake (doc 11, doc 12 test 3; R01: rolled out to stdio from v2.1.292).
FIRST_MESSAGE_NEGOTIATION_UNSET = "server/discover"
# Legacy revision the client asks for in `initialize` (observed on 2.1.296,
# step 1) and the one the fakes echo back.
LEGACY_PROTOCOL_VERSION = "2025-11-25"

# Fakes: the stdio fake's echo_canary tool returns FAKE_CANARY (required by
# the fake). Free tests never call the tool, so they pass this fixed value;
# model tests pass a fresh canary per test (CANARY_PREFIX + hex).
FREE_TEST_CANARY = "canary-not-used-by-free-tests"
# stdio fake FAKE_TOOLSET values (fakes/stdio_fake.py TOOLSETS). Free tests
# use the smoke set (echo, echo_canary); they never call a tool.
TOOLSET_SMOKE = "smoke"
TOOLSET_CALC = "calc"
TOOLSET_CALC_SIDE_EFFECT = "calc_side_effect"
TOOLSET_TICKET = "ticket"
TOOLSET_TOOL_ERROR = "tool_error"  # doc 16 test 1: isError: true
TOOLSET_PROTOCOL_ERROR = "protocol_error"  # doc 16 test 2: JSON-RPC error -32602
# stdio fake FAKE_MODE values used by name in more than one place.
FAKE_MODE_NORMAL = "normal"
FAKE_MODE_EXIT_ON_FIRST_TOOLS_CALL = "exit_on_first_tools_call"  # doc 20 test 1
FAKE_MODE_HANG_ON_TOOLS_CALL = "hang_on_tools_call"  # doc 19 tests 1 and 3
TOOLSET_GUARD = "guard"  # doc 23 tests 9, 10: list_items, delete_all
TOOLSET_OPS = "ops"  # doc 23 test 10: rotate_logs, on the server `guard__ops`
FREE_TEST_TOOLSET = TOOLSET_SMOKE
CANARY_PREFIX = "canary-"
CANARY_HEX_BYTES = 8

# ---------------------------------------------------------------- model tier
# Every `claude -p` run (doc 11). Flags checked against 2.1.296 in the suite
# image: `claude --help` lists all of them except --max-turns, which is
# hidden from --help but accepted (an unknown flag is rejected at parse,
# --max-turns is not; cli-reference.md documents it; observations.md).
MODEL_ID = "claude-haiku-5-5"  # changelog.md:642 (2.1.293)
MAX_TURNS = 4
MAX_BUDGET_USD_PER_RUN = 0.25
# Cost ledger: the suite stops (pytest.exit) once the summed total_cost_usd
# passes this. Before each run the ledger also refuses to start one that
# could pass it (total + MAX_BUDGET_USD_PER_RUN > SUITE_BUDGET_USD).
# Set from the measured smoke run (observations.md, "model run cost"):
# ~16 model tests (doc 24) x 2 eras x 5 repeats x 2 (one inconclusive retry)
# = 320 runs x $0.01 (2.7x the worst measured run, $0.0037) = $3.20, plus
# ~50% margin. Far below $50.
SUITE_BUDGET_USD = 5.00
BUDGET_EXIT_CODE = 11  # pytest.exit code when the ledger stops the run
MODEL_REJECTED_EXIT_CODE = 12  # pytest.exit code when MODEL_ID is not accepted
COST_FILE_ENV = "SUITE_COST_FILE"  # set by harness.entrypoint
# One model run: MCP startup wait (MCP_TIMEOUT 15 s) + up to MAX_TURNS model
# turns + API retries. Above CLAUDE_CLI_TIMEOUT_S on purpose.
MODEL_CLI_TIMEOUT_S = 150
# pytest-timeout for a model test: two attempts (one retry) plus setup.
MODEL_TEST_TIMEOUT_S = 360
# Doc 22: a D check whose S trigger did not happen is retried once.
INCONCLUSIVE_RETRIES = 1
# Doc 22 test 1: repeated tests run REPEATS times (one pytest item each, a
# fresh config dir each). D facts must hold in REPEATS of REPEATS; the S
# pass rate fails the suite only below S_RATE_MIN_PASSES of REPEATS.
REPEATS = 5
S_RATE_MIN_PASSES = 4
# Doc 20 test 1 (stdio crash mid-call): run CRASH_RUNS times; every run
# must show the same behavior (D in each run, and one cross-run check).
CRASH_RUNS = 3
# Doc 20 test 1: the crash must reach the stream as an error tool_result
# within this many seconds of the fake's exit (stream timestamp minus the
# fake's own `exit` epoch, one container clock). Why 5 s: a client that
# missed the exit would wait for the tool timeout, MCP_TOOL_TIMEOUT_MS =
# 30 s (stdio has no per-request timer, mcp.md:433, and a 30 min idle
# window, mcp.md:437); measured: see observations.md. 5 s is 6x under 30 s
# and far above the measured value, and well under MODEL_CLI_TIMEOUT_S.
CRASH_FAILURE_BOUND_S = 5.0
# Hook events the D16 / D20 runs log (hooks.md).
HOOK_POST_TOOL_USE = "PostToolUse"
HOOK_POST_TOOL_USE_FAILURE = "PostToolUseFailure"
# Doc 11 era check for a model test: one run with MCP_PROTOCOL_NEGOTIATION
# unset (not repeated; docs/flake-policy.md).
UNSET_ERA_RUNS = 1
RATES_FILE_ENV = "SUITE_S_RATES_FILE"  # set by harness.entrypoint
# outcomes.json: per-item outcomes, xfails apart from skips (tests/conftest.py).
OUTCOMES_FILE_ENV = "SUITE_OUTCOMES_FILE"  # set by harness.entrypoint
# Run-level gate (tests/conftest.py, docs/flake-policy.md). With the key
# set, a run in which ANY model item was skipped as inconclusive exits
# INCONCLUSIVE_EXIT_CODE (when pytest itself returned 0): such an item
# proved nothing. A `-k` that leaves an S rate item or the crash
# same-every-run item without its runs therefore exits 13 too.
INCONCLUSIVE_EXIT_CODE = 13
# With no key, a run that asked for model items on purpose (REQUIRE_KEY_ENV
# = REQUIRE_KEY_ON, a `-m` expression that selects a model item, or a
# selection made only of model items, e.g. `-k <model test>`) stops before
# any test with MODEL_TESTS_NEED_KEY_EXIT_CODE, instead of skipping them
# and exiting 0. With no key, a selection with free items skips the model ones.
MODEL_TESTS_NEED_KEY_EXIT_CODE = 14
# The Anthropic API rejected the key (HTTP 401 or 403): the run stops at the
# first model run that shows it, with no retry (harness/model_flow.py,
# model_checks.key_rejected). Not exit 13: the model is not to blame.
API_KEY_REJECTED_EXIT_CODE = 15
API_KEY_REJECTED_STATUSES = (401, 403)
API_RETRY_AUTH_FAILED = "authentication_failed"  # system/api_retry `error` category (headless.md:249)
REQUIRE_KEY_ENV = "SUITE_REQUIRE_KEY"  # not a secret; run.sh forwards it
REQUIRE_KEY_ON = "1"
REQUIRE_KEY_OFF = ""  # the same as unset
USAGE_ERROR_EXIT_CODE = 4  # pytest's own code for a usage error (pytest.ExitCode.USAGE_ERROR)

# API key hand-off (run.sh -> container): run.sh `docker cp`s a 0600 file
# holding the key to API_KEY_FILE_IN_CONTAINER before `docker start` and
# sets API_KEY_FILE_ENV to that path. The entrypoint reads it, deletes it,
# and passes the value to the pytest process env only. The container
# config (docker inspect) never holds the value.
API_KEY_FILE_ENV = "SUITE_API_KEY_FILE"
API_KEY_FILE_IN_CONTAINER = "/tmp/suite-api-key"

MCP_TOOL_TIMEOUT_MS = "30000"  # doc 11: set explicitly, never the ~28 h default
PRINT_BG_WAIT_CEILING_MS = "5000"  # doc 11: short; no test starts background work
TOOL_TIMEOUT_ENV = "MCP_TOOL_TIMEOUT"  # wall-clock limit per tool call (env-vars.md:500)
IDLE_TIMEOUT_ENV = "CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT"  # idle window per tool call (env-vars.md:337)
DISALLOWED_TOOLS_FLAG = "--disallowedTools"  # deny rules (cli-reference.md:87)
TOOL_SEARCH_ENV = "ENABLE_TOOL_SEARCH"
TOOL_SEARCH_OFF = "false"  # doc 11: wire tests see tools/call with no ToolSearch first

# Pins for `model` tests. ANTHROPIC_API_KEY is added per test from the
# runner's env (tests/conftest.py), registered as a secret.
MODEL_ENV_PINS = {
    "DISABLE_AUTOUPDATER": "1",
    "DISABLE_TELEMETRY": "1",
    "DISABLE_ERROR_REPORTING": "1",
    "MCP_TIMEOUT": MCP_TIMEOUT_MS,
    TOOL_TIMEOUT_ENV: MCP_TOOL_TIMEOUT_MS,
    "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": PRINT_BG_WAIT_CEILING_MS,
    NEGOTIATION_ENV: NEGOTIATION_LEGACY,
}
# ENABLE_TOOL_SEARCH is set per test (TOOL_SEARCH_OFF) except in the one
# test that keeps the default (doc 14 test 2); set_env removes it from here.
MODEL_ENV_UNSET = ("MCP_SDK_GENERATION", TOOL_SEARCH_ENV)

# Hard cap on the whole pytest run, enforced with coreutils `timeout` inside
# the container (pytest.ini's session_timeout = 1500 is the soft inner cap).
WHOLE_RUN_TIMEOUT_S = 1800
WHOLE_RUN_KILL_GRACE_S = 30
