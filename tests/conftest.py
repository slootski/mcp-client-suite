"""Shared fixtures: version gate, per-test sandbox, run.json, model-test skip,
the suite cost ledger (cost.json, per-test cost printed at the end), the S
pass rates of repeated tests (harness/repeat.py), and the "all model tests
inconclusive" policy (docs/flake-policy.md)."""

import html
import logging
import os
import re
import secrets
import shutil
import subprocess
import tempfile

import pytest

from harness.check import expect_equal, step, wait_done, wait_failed, wait_start
from harness.claude_cli import CommandLog, run_claude
from fakes.wirelog import fingerprint
from harness import repeat
from harness.constants import (
    ALL_INCONCLUSIVE_EXIT_CODE,
    API_KEY_ENV,
    ARTIFACT_DIR_ENV,
    BASE_IMAGE_ENV,
    BEARER_TEST_PREFIX,
    BUDGET_EXIT_CODE,
    CLAUDE_BIN,
    CLAUDE_CLI_TIMEOUT_S,
    CONFIG_DIR_ENV,
    COST_FILE_ENV,
    DUMMY_SECRET_PREFIX,
    EXPECTED_CLAUDE_VERSION,
    FREE_ENV_PINS,
    FREE_ENV_UNSET,
    IMAGE_ID_ENV,
    MAX_BUDGET_USD_PER_RUN,
    MODEL_ENV_PINS,
    MODEL_ENV_UNSET,
    PASSTHROUGH_ENV,
    RATES_FILE_ENV,
    SUITE_BUDGET_USD,
    TEST_SECRET_HEX_BYTES,
    VERSION_GATE_EXIT_CODE,
    VERSION_GATE_TIMEOUT_S,
)
from harness.cost_ledger import CostLedger
from harness.log_format import install_on_pytest
from harness.redact import SecretRegistry, copy_tree_redacted, scan_dir
from harness.run_record import RunRecord

CLAUDE_VERSION_KEY = pytest.StashKey[str]()
CALL_REPORT_KEY = pytest.StashKey[object]()
LEDGER_KEY = pytest.StashKey[object]()
MODEL_OUTCOMES_KEY = pytest.StashKey[list]()  # [(nodeid, outcome)] of model items that ran
ALL_INCONCLUSIVE_KEY = pytest.StashKey[str]()  # the message, when the policy fired
INCONCLUSIVE_MARK = "inconclusive"
logger = logging.getLogger(__name__)
HTML_PLUGIN_NAME = "html"  # pytest-html
REPORT_TESTS_SUBDIR = "tests"  # report.html sits next to this folder (harness/entrypoint.py)
RUN_RECORD_NAME = "run.json"


def api_key_set():
    return API_KEY_ENV in os.environ and os.environ[API_KEY_ENV] != ""


def build_env(*, passthrough, pins, home, config_dir):
    """A claude subprocess environment built from scratch: only the named
    passthrough variables, the pins, and a private HOME and config dir.
    Nothing else from the runner leaks in (the API key included)."""
    missing = [name for name in passthrough if name not in os.environ]
    expect_equal(what="passthrough variables missing from the runner environment (the Dockerfile sets them)",
                 expected=[], actual=missing)
    env = {name: os.environ[name] for name in passthrough}
    env.update(pins)
    env["HOME"] = home
    env[CONFIG_DIR_ENV] = config_dir
    return env


def pytest_sessionstart(session):
    install_on_pytest(config=session.config)  # the logging plugin exists by now
    """Version gate: stop before any test if the CLI is not the pinned one."""
    scratch = tempfile.mkdtemp(prefix="version-gate-")
    env = build_env(
        passthrough=PASSTHROUGH_ENV,
        pins=FREE_ENV_PINS,
        home=scratch,
        config_dir=os.path.join(scratch, "claude-config"),
    )
    started = wait_start(what="%s --version (version gate, limit %s s)" % (CLAUDE_BIN, VERSION_GATE_TIMEOUT_S))
    try:
        proc = subprocess.run(
            [CLAUDE_BIN, "--version"], env=env, capture_output=True, encoding="utf-8",
            timeout=VERSION_GATE_TIMEOUT_S, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        wait_failed(started=started, response="cannot run: %s" % exc)
        pytest.exit("version gate: cannot run `claude --version`: %s" % exc, returncode=VERSION_GATE_EXIT_CODE)
    line = proc.stdout.strip()
    wait_done(started=started, response="exit %d, stdout %r (expected version %s)" % (
        proc.returncode, line, EXPECTED_CLAUDE_VERSION))
    tokens = line.split()
    if proc.returncode != 0 or not tokens or tokens[0] != EXPECTED_CLAUDE_VERSION:
        pytest.exit(
            "version gate: expected Claude Code %s, `claude --version` printed %r (rc=%s)"
            % (EXPECTED_CLAUDE_VERSION, line, proc.returncode),
            returncode=VERSION_GATE_EXIT_CODE,
        )
    session.config.stash[CLAUDE_VERSION_KEY] = line
    shutil.rmtree(scratch, ignore_errors=True)
    session.config.stash[LEDGER_KEY] = CostLedger(
        suite_budget_usd=SUITE_BUDGET_USD,
        per_run_cap_usd=MAX_BUDGET_USD_PER_RUN,
        exit_code=BUDGET_EXIT_CODE,
        cost_file=os.environ[COST_FILE_ENV],
    )
    repeat.init_session(config=session.config)
    session.config.stash[MODEL_OUTCOMES_KEY] = []


def all_model_tests_inconclusive(*, outcomes):
    """True when at least one model item ran and every one of them was
    skipped as inconclusive (a gate or trigger skip, or an S rate item with
    nothing conclusive to judge)."""
    return bool(outcomes) and all(outcome.startswith("skipped") and INCONCLUSIVE_MARK in outcome
                                  for _nodeid, outcome in outcomes)


def pytest_sessionfinish(session, exitstatus):
    """cost.json and s-rates.json on every run (a free-only run writes total
    0 and no rates). Policy: with
    the key set, a run whose model tests were ALL inconclusive proved
    nothing about the client and exits ALL_INCONCLUSIVE_EXIT_CODE."""
    if LEDGER_KEY in session.config.stash:
        session.config.stash[LEDGER_KEY].write()
    if repeat.S_RATES_KEY in session.config.stash:
        repeat.write_rates_file(config=session.config, path=os.environ[RATES_FILE_ENV])
    if MODEL_OUTCOMES_KEY not in session.config.stash or not api_key_set():
        return
    outcomes = session.config.stash[MODEL_OUTCOMES_KEY]
    if all_model_tests_inconclusive(outcomes=outcomes) and session.exitstatus == 0:
        message = "all model tests inconclusive (%d model item(s), none conclusive); exit %d" % (
            len(outcomes), ALL_INCONCLUSIVE_EXIT_CODE)
        session.config.stash[ALL_INCONCLUSIVE_KEY] = message
        session.exitstatus = ALL_INCONCLUSIVE_EXIT_CODE


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Per-test model cost and the suite total, printed at the end."""
    if LEDGER_KEY not in config.stash:
        return
    ledger = config.stash[LEDGER_KEY]
    terminalreporter.section("model cost (sum of result.total_cost_usd)")
    per_test = ledger.per_test()
    for test_id in per_test:
        terminalreporter.write_line(
            "$%.4f  %d run(s)  %s" % (per_test[test_id]["charged_usd"], per_test[test_id]["runs"], test_id)
        )
    terminalreporter.write_line(
        "total $%.4f over %d test(s); SUITE_BUDGET_USD $%.4f" % (ledger.total(), len(per_test), SUITE_BUDGET_USD)
    )
    if repeat.S_RATES_KEY in config.stash and config.stash[repeat.S_RATES_KEY]:
        terminalreporter.section("S pass rates of repeated tests (docs/flake-policy.md)")
        for line in repeat.summary_lines(config=config):
            terminalreporter.write_line(line)
    if ALL_INCONCLUSIVE_KEY in config.stash:
        terminalreporter.section("model tier verdict")
        terminalreporter.write_line(config.stash[ALL_INCONCLUSIVE_KEY], red=True)


def pytest_report_header(config):
    if CLAUDE_VERSION_KEY in config.stash:
        return "claude --version: %s" % config.stash[CLAUDE_VERSION_KEY]
    return "claude --version: (gate not run)"


def pytest_collection_modifyitems(config, items):
    """`model` tests need the key; without it they are skipped, not failed,
    so the free tests still run on a machine with no key."""
    if api_key_set():
        return
    skip = pytest.mark.skip(reason="%s not set: model test skipped" % API_KEY_ENV)
    for item in items:
        if "model" in item.keywords:
            item.add_marker(skip)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call":
        item.stash[CALL_REPORT_KEY] = report
    if report.when == "teardown":
        # pytest-html renders every phase of a test when the teardown report
        # arrives, and shows no row for a passed teardown: so the evidence
        # goes on the call report (the setup report when the call never ran).
        target = item.stash[CALL_REPORT_KEY] if CALL_REPORT_KEY in item.stash else report
        attach_artifacts_to_html_report(item=item, report=target)
    if "model" in item.keywords and MODEL_OUTCOMES_KEY in item.config.stash and (
            report.when == "call" or (report.when == "setup" and not report.passed)):
        item.config.stash[MODEL_OUTCOMES_KEY].append((item.nodeid, outcome_text(report=report)))


def attach_artifacts_to_html_report(*, item, report):
    """Show the test's evidence in report.html: links to its artifact files
    at the top of the row, and its run.json (pins, era, what was observed)
    as a log section after the test's log lines. run.json is written in
    fixture teardown, so this runs at the teardown report. The files were
    already redacted; the entrypoint scans report.html for the key too."""
    plugin = item.config.pluginmanager.getplugin(HTML_PLUGIN_NAME)
    folder = safe_name(text=item.nodeid)
    path = os.path.join(os.environ[ARTIFACT_DIR_ENV], folder)
    if plugin is None or not os.path.isdir(path):
        return
    names = sorted(
        os.path.relpath(os.path.join(root, name), path)
        for root, _, files in os.walk(path)
        for name in files
    )
    links = "".join(
        '<li><a href="%s/%s/%s">%s</a></li>' % (REPORT_TESTS_SUBDIR, folder, html.escape(name), html.escape(name))
        for name in names
    )
    extras = list(report.extras) if hasattr(report, "extras") else []
    extras.append(plugin.extras.html("<p><b>Artifacts</b> (%d files)</p><ul>%s</ul>" % (len(names), links)))
    record = os.path.join(path, RUN_RECORD_NAME)
    if os.path.isfile(record):
        with open(record, encoding="utf-8") as handle:
            text = handle.read()
        report.sections.append((RUN_RECORD_NAME, text))  # pytest-html shows sections after the captured log
    report.extras = extras


def outcome_text(*, report):
    """passed / failed / xfailed / "skipped: <reason>" for one report."""
    if hasattr(report, "wasxfail") and report.skipped:
        return "xfailed"
    if report.skipped and isinstance(report.longrepr, tuple):
        return "skipped: %s" % report.longrepr[2]  # (path, line, reason); "inconclusive: ..." from the gate
    return report.outcome


def safe_name(*, text):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")


class Sandbox:
    """One test's private world: config dir, HOME, project dir (cwd for every
    claude call, since `claude mcp add` defaults to local scope keyed by the
    project path), artifact dir, env, and run record."""

    def __init__(self, *, root, artifact_dir, env, record, registry, command_log):
        self.root = root
        self.registry = registry
        self.artifact_dir = artifact_dir
        self.env = env
        self.record = record
        self.command_log = command_log
        self.project_dir = os.path.join(root, "project")
        self.config_dir = env[CONFIG_DIR_ENV]
        self.extra_config_dirs = []  # more config dirs a test made; copied at teardown
        os.makedirs(self.project_dir, exist_ok=True)
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(env["HOME"], exist_ok=True)

    def claude(self, *, args):
        return run_claude(
            args=args, env=self.env, cwd=self.project_dir,
            timeout_s=CLAUDE_CLI_TIMEOUT_S, command_log=self.command_log,
        )

    def claude_with_env(self, *, args, env):
        """Run claude with an env other than self.env (e.g. a second config
        dir from new_config_env), same project dir and command log."""
        return run_claude(
            args=args, env=env, cwd=self.project_dir,
            timeout_s=CLAUDE_CLI_TIMEOUT_S, command_log=self.command_log,
        )

    def new_config_env(self, *, label):
        """A copy of self.env with a fresh, empty CLAUDE_CONFIG_DIR (same HOME)."""
        config_dir = os.path.join(self.root, "claude-config-%s" % label)
        os.makedirs(config_dir)
        self.extra_config_dirs.append(config_dir)
        env = dict(self.env)
        env[CONFIG_DIR_ENV] = config_dir
        return env

    def new_bearer(self):
        """A throwaway credential for this test only. It is registered, so it
        is redacted from command logs and copied config, and the teardown
        scan fails the test if it is found anywhere in the artifacts."""
        return self.registry.register(value=BEARER_TEST_PREFIX + secrets.token_hex(TEST_SECRET_HEX_BYTES))

    def new_dummy_secret(self):
        """A throwaway env-var credential (never the real key), registered
        like new_bearer."""
        return self.registry.register(value=DUMMY_SECRET_PREFIX + secrets.token_hex(TEST_SECRET_HEX_BYTES))

    def set_env(self, *, name, value, secret):
        """Set one env var for every later claude call of this test, and
        record it in run.json (a secret as its fingerprint only)."""
        self.env[name] = value
        step(text="set %s=%s for every later claude call of this test" % (
            name, fingerprint(value=value) if secret else value))
        self.record.override_env(name=name, shown=fingerprint(value=value) if secret else value)

    def unset_env(self, *, name):
        """Remove one pinned env var for every later claude call of this
        test (e.g. MCP_PROTOCOL_NEGOTIATION for the unset-era run), and
        record it in run.json as unset on purpose."""
        expect_equal(what="%s in the sandbox env before it is removed" % name, expected=True, actual=name in self.env)
        step(text="unset %s for every later claude call of this test" % name)
        del self.env[name]
        self.record.unset_env(name=name)

    def wire_log_path(self, *, name):
        return os.path.join(self.artifact_dir, "wire-%s.jsonl" % name)


def new_sandbox(*, request, tmp_path, pins, unset):
    """A Sandbox with a fresh CLAUDE_CONFIG_DIR and HOME, the given env pins,
    and a run record. finish_sandbox() is its teardown."""
    artifact_dir = os.path.join(os.environ[ARTIFACT_DIR_ENV], safe_name(text=request.node.nodeid))
    os.makedirs(artifact_dir, exist_ok=True)
    root = str(tmp_path)
    env = build_env(
        passthrough=PASSTHROUGH_ENV,
        pins=pins,
        home=os.path.join(root, "home"),
        config_dir=os.path.join(root, "claude-config"),
    )
    record = RunRecord(
        test_id=request.node.nodeid,
        claude_version=request.config.stash[CLAUDE_VERSION_KEY],
        image_id=os.environ[IMAGE_ID_ENV],
        base_image=os.environ[BASE_IMAGE_ENV],
        env_pins=pins,
        env_unset=unset,
    )
    registry = SecretRegistry()
    logger.info("sandbox: fresh CLAUDE_CONFIG_DIR, pins %s, unset %s, artifacts in %s",
                sorted(pins), list(unset), os.path.basename(artifact_dir))
    return Sandbox(
        root=root, artifact_dir=artifact_dir, env=env, record=record, registry=registry,
        command_log=CommandLog(path=os.path.join(artifact_dir, "commands.jsonl"), registry=registry),
    )


@pytest.fixture
def free_sandbox(request, tmp_path):
    """Sandbox for a `free` test: fresh CLAUDE_CONFIG_DIR, no API key."""
    sandbox = new_sandbox(request=request, tmp_path=tmp_path, pins=FREE_ENV_PINS, unset=FREE_ENV_UNSET)
    yield sandbox
    finish_sandbox(request=request, sandbox=sandbox)


@pytest.fixture
def model_sandbox(request, tmp_path):
    """Sandbox for a `model` test: MODEL_ENV_PINS and the real API key. The
    key is registered as a secret: redacted from command logs, streams and
    copied config, and the teardown scan (which covers the --debug-file, as
    it is written into the artifact dir) fails the test if it is found."""
    sandbox = new_sandbox(request=request, tmp_path=tmp_path, pins=MODEL_ENV_PINS, unset=MODEL_ENV_UNSET)
    key = sandbox.registry.register(value=os.environ[API_KEY_ENV])
    sandbox.set_env(name=API_KEY_ENV, value=key, secret=True)
    yield sandbox
    finish_sandbox(request=request, sandbox=sandbox)


@pytest.fixture
def item_artifact_dir(request):
    """The artifact folder of an item that needs no sandbox (an S rate item)."""
    path = os.path.join(os.environ[ARTIFACT_DIR_ENV], safe_name(text=request.node.nodeid))
    os.makedirs(path, exist_ok=True)
    return path


@pytest.fixture
def cost_ledger(request):
    return request.config.stash[LEDGER_KEY]


def finish_sandbox(*, request, sandbox):
    """Copy the config dirs (redacted), write run.json, scan for secrets."""
    artifact_dir = sandbox.artifact_dir
    registry = sandbox.registry
    record = sandbox.record
    dropped = copy_tree_redacted(
        source=sandbox.config_dir, target=os.path.join(artifact_dir, "claude-config"), registry=registry
    )
    for extra in sandbox.extra_config_dirs:
        dropped += copy_tree_redacted(
            source=extra, target=os.path.join(artifact_dir, os.path.basename(extra)), registry=registry
        )
    record.observe(key="claude_config_files_not_copied_binary", value=dropped)
    if CALL_REPORT_KEY in request.node.stash:
        outcome = outcome_text(report=request.node.stash[CALL_REPORT_KEY])
    else:
        outcome = "not run (setup failed or skipped)"
    record.write(path=os.path.join(artifact_dir, "run.json"), outcome=outcome)
    logger.info("run.json written: outcome %s", outcome)
    leaks = scan_dir(root=artifact_dir, registry=registry)
    for relative in leaks:
        os.remove(os.path.join(artifact_dir, relative))
    expect_equal(what="artifact files that hold a test credential of this test (such files are removed)",
                 expected=[], actual=leaks)
