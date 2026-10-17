"""One model-driven check: run `claude -p` until the S trigger happened.

run_until_triggered runs the prompt at most 1 + INCONCLUSIVE_RETRIES times
(doc 22): an attempt is inconclusive when a server of the test is not
`connected` in system/init (the gate) or the model made no tool_use with
one of the trigger names (with require_all_triggers: not one tool_use for
EACH trigger name). Only then is it retried, in a fresh CLAUDE_CONFIG_DIR,
and every attempt is charged and recorded in run.json
(`observations.model_runs`, with the reason it was retried). A D failure is
never retried: the D asserts run after this returns.

D checks run here, on every attempt, before the retry decision, in this
order. A retry would replace the attempt's records and hide them, so none
of them may wait for a "triggered" attempt. The attempt is written to
run.json (with its per-fake tools/call count) and its stream file stays in
the artifacts before any of them can fail.
  1. (QA step 4) every tools/call that reached a fake in the attempt
     belongs to a tool_use of that attempt's stream
     (model_checks.assert_every_call_has_a_tool_use). A call without a
     tool_use is a client fact, not an S miss.
  2. (QA step 5) the run ends with a `result` event. A client that exits
     after an error or a crash (system/init and a first tool_result, then
     no next tool_use and no result) is a D failure, not an inconclusive
     attempt: without this assert it was retried and then skipped, and
     the suite exited 0.
  3. the test's own attempt_checks, each called as
     check(stream=<Stream>, records=<{server: wire records}>). A test
     passes the D facts it can judge as soon as some tool_use exists
     (e.g. D20/T1: the crashed call's error tool_result and its time
     bound, whenever the crash tool_use exists); [] for none.
"""

import logging
from dataclasses import dataclass

import pytest

from harness.check import expect_true, got, step
from harness.model_checks import (
    assert_every_call_has_a_tool_use,
    era_seen,
    gate_problem,
    init_summary,
    model_rejected,
    result_summary,
    tools_call_records,
)
from harness.model_run import run_print
from harness.wire import read_records, records_between

logger = logging.getLogger(__name__)


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


def run_until_triggered(*, sandbox, ledger, test_id, prompt, model, max_turns, max_budget_usd, timeout_s,
                        servers, allowed_tools, gate_servers, wire_servers, trigger_names, require_all_triggers,
                        retries, rejected_exit_code, extra_args, attempt_checks):
    """servers: {name: --mcp-config entry}; allowed_tools: the --allowedTools
    value (model_run.allowed_tools_for gives the doc 11 default);
    wire_servers: the fakes whose logs are read; trigger_names: tool_use
    names that count as the trigger (see require_all_triggers);
    extra_args: more `claude -p` arguments (e.g. ["--settings", <json>]),
    [] for none; attempt_checks: D checks run on every attempt before the
    retry decision (module docstring), [] for none.
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
        for check in attempt_checks:
            check(stream=stream, records=records)
            logger.debug("%s: attempt check %s held", run.label, check.__name__)
        if reason is None:
            break
        if attempt < retries:
            logger.warning("%s inconclusive (%s): retrying with a fresh config dir", run.label, reason)
        else:
            logger.warning("%s inconclusive (%s): no retry left", run.label, reason)
    return Triggered(run=run, records=records, inconclusive=reason, attempts=attempts)
