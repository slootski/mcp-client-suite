"""One model-driven check: run `claude -p` until the S trigger happened.

run_until_triggered runs the prompt at most 1 + retries times (doc 22), each
retry in a fresh CLAUDE_CONFIG_DIR. An attempt is inconclusive, and only then
retried, when the host clock jumped during it (clock_step_problem), a server
of the test is not `connected` in system/init (the gate), or the model made no
tool_use with a trigger name. Each attempt is charged and recorded in run.json
(`observations.model_runs`), unless its stream shows the API rejected the key,
the account or the model: then the run stops at once, no retry.

D checks run on every attempt before the retry decision, so a retry never
hides them, and are never retried (docs/flake-policy.md): every tools/call
that reached a fake has a tool_use (QA step 4); the run ends with a `result`
event (QA step 5); the test's own attempt_checks, each called as
check(stream=<Stream>, records=<{server: wire records}>), unless the clock
jumped (they may compare the stream's clock with a fake's).
"""

import logging
from dataclasses import dataclass

import pytest

from harness.check import expect_true, got, step
from harness.constants import API_KEY_ENV, API_KEY_REJECTED_EXIT_CODE, CLOCK_STEP_TOLERANCE_S
from harness.model_checks import (
    assert_every_call_has_a_tool_use,
    era_seen,
    gate_problem,
    init_summary,
    key_rejected,
    model_rejected,
    result_summary,
    tools_call_records,
)
from harness.model_run import run_print
from harness.wire import read_records, records_between

logger = logging.getLogger(__name__)
CLOCK_STEP_REASON = "inconclusive: the host clock jumped during the run (wall %.1f s, monotonic %.1f s)"


@dataclass(frozen=True)
class Triggered:
    run: object  # harness.model_run.ModelRun of the attempt that counts
    records: dict  # {server: wire records of that attempt}
    inconclusive: object  # None when triggered, else the reason of the last attempt
    attempts: list  # run.json view of every attempt


def trigger_problem(*, stream, trigger_names, require_all_triggers):
    """None when the S trigger happened, else the inconclusive reason.
    require_all_triggers False: any tool_use named in trigger_names counts;
    True: each name in trigger_names needs its own tool_use."""
    used = {use.name for use in stream.tool_uses}
    if require_all_triggers:
        missing = sorted(name for name in trigger_names if name not in used)
        if missing:
            return "inconclusive: the model made no tool_use named %s" % " and no ".join(missing)
        return None
    if not used & set(trigger_names):
        return "inconclusive: the model made no tool_use named %s" % " or ".join(sorted(trigger_names))
    return None


def clock_step_problem(*, cli, tolerance_s):
    """None, or the inconclusive reason when the run's wall-clock span passed
    its monotonic span by more than tolerance_s (a host pause or clock step)."""
    wall_s = cli.end_epoch - cli.start_epoch
    if wall_s - cli.duration_s <= tolerance_s:
        return None
    return CLOCK_STEP_REASON % (wall_s, cli.duration_s)


def run_until_triggered(*, sandbox, ledger, test_id, prompt, model, max_turns, max_budget_usd, timeout_s,
                        servers, allowed_tools, gate_servers, wire_servers, trigger_names, require_all_triggers,
                        retries, rejected_exit_code, extra_args, attempt_checks):
    """servers: {name: --mcp-config entry}; allowed_tools: the --allowedTools
    value (model_run.allowed_tools_for gives the doc 11 default); wire_servers:
    the fakes whose logs are read; trigger_names: see require_all_triggers;
    extra_args: more `claude -p` arguments, [] for none; attempt_checks: the
    test's D checks per attempt (module docstring), [] for none.
    Returns a Triggered; the caller skips when .inconclusive is set."""
    attempts = []
    total_charged = 0.0
    run = None
    records = {}
    reason = None
    for attempt in range(1 + retries):
        if attempt == 0:
            env, config_label = sandbox.env, "claude-config"
        else:
            config_label = "claude-config-retry%d" % attempt
            env = sandbox.new_config_env(label="retry%d" % attempt)
        step(text="attempt%d (%d of %d): claude -p with servers %s, config dir %s" % (
            attempt, attempt + 1, 1 + retries, sorted(servers), config_label))
        run = run_print(
            sandbox=sandbox, env=env, ledger=ledger, test_id=test_id, label="attempt%d" % attempt,
            prompt=prompt, model=model, max_turns=max_turns, max_budget_usd=max_budget_usd,
            servers=servers, allowed_tools=allowed_tools, timeout_s=timeout_s, extra_args=extra_args,
        )
        total_charged = round(total_charged + run.charged_usd, 6)
        stream = run.stream
        key_problem = key_rejected(stream=stream)
        if key_problem is not None:
            got(what="%s: API key rejected" % run.label, value=key_problem)
            pytest.exit("API key rejected: the API rejected the key or the account (HTTP 401 or 403): %s; no retry "
                        "(check %s)" % (key_problem, API_KEY_ENV), returncode=API_KEY_REJECTED_EXIT_CODE)
        rejected = model_rejected(stream=stream, model=model)
        if rejected is not None:
            pytest.exit("model %s not accepted: %s" % (model, rejected), returncode=rejected_exit_code)
        expect_true(what="%s: system/init or result event in the stream" % run.label,
                    expected="at least one of them",
                    actual="present" if stream.init is not None or stream.result is not None
                    else "neither (rc=%s), stderr tail: %s" % (
                        run.cli.returncode, sandbox.registry.redact_text(text=run.cli.stderr)[-2000:]),
                    holds=stream.init is not None or stream.result is not None)
        records = {
            name: records_between(records=read_records(path=sandbox.wire_log_path(name=name)),
                                  start_epoch=run.cli.start_epoch, end_epoch=run.cli.end_epoch)
            for name in wire_servers
        }
        got(what="%s: mcp_servers in system/init" % run.label,
            value=init_summary(stream=stream)["mcp_servers"] if stream.init is not None else None)
        clock_jump = clock_step_problem(cli=run.cli, tolerance_s=CLOCK_STEP_TOLERANCE_S)
        reason = clock_jump
        if reason is None:
            reason = gate_problem(stream=stream, servers=gate_servers)
            logger.info("%s: gate (servers connected %s): %s", run.label, sorted(gate_servers),
                        "ok" if reason is None else reason)
        if reason is None:
            reason = trigger_problem(stream=stream, trigger_names=trigger_names,
                                     require_all_triggers=require_all_triggers)
            logger.info("%s: trigger %s: %s", run.label, sorted(trigger_names), "ok" if reason is None else reason)
        logger.debug("%s: tools/call per fake %s", run.label,
                     {name: len(tools_call_records(records=records[name])) for name in wire_servers})
        attempts.append({
            "label": run.label,
            "config_dir": config_label,
            "returncode": run.cli.returncode,
            "duration_s": run.cli.duration_s,
            "charged_usd": run.charged_usd,
            "inconclusive": reason,
            "retried": reason is not None and attempt < retries,
            "init": init_summary(stream=stream),
            "result": result_summary(stream=stream),
            "tool_uses": [{"id": u.id, "name": u.name, "input": u.input, "index": u.index} for u in stream.tool_uses],
            "tools_call_count": {name: len(tools_call_records(records=records[name])) for name in wire_servers},
            "unparsed_stdout_lines": len(stream.unparsed_lines),
            "stream_file": run.stream_file.rsplit("/", 1)[1],
            "debug_file": run.debug_file.rsplit("/", 1)[1],
            "era_seen": {name: era_seen(records=records[name]) for name in wire_servers},
        })
        sandbox.record.observe(key="model_runs", value=attempts)
        sandbox.record.set_field(key="model_id", value=model)
        sandbox.record.set_field(key="total_cost_usd", value=total_charged)
        sandbox.record.set_field(key="era_seen", value=attempts[-1]["era_seen"])
        # D, on every attempt and before any retry: a retry must never hide it.
        assert_every_call_has_a_tool_use(stream=stream, records_by_server=records)
        expect_true(what="%s: result event in the stream" % run.label,
                    expected="a result event (the client ends every run with one)",
                    actual="present" if stream.result is not None else (
                        "the stream has no result event (rc=%s, %d events, %d tool_use, %d tool_result): the client "
                        "ended the run without a result" % (run.cli.returncode, len(stream.events),
                                                            len(stream.tool_uses), len(stream.tool_results))),
                    holds=stream.result is not None)
        logger.debug("%s: D held: every tools/call has a tool_use; result event present", run.label)
        for check in attempt_checks if clock_jump is None else []:
            check(stream=stream, records=records)
            logger.debug("%s: attempt check %s held", run.label, check.__name__)
        if reason is None:
            break
        if attempt < retries:
            logger.warning("%s inconclusive (%s): retrying with a fresh config dir", run.label, reason)
        else:
            logger.warning("%s inconclusive (%s): no retry left", run.label, reason)
    return Triggered(run=run, records=records, inconclusive=reason, attempts=attempts)
