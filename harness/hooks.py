"""Hooks for model runs: inline `--settings` JSON.

hook_settings_args: each named event gets one command hook with no matcher
(hooks.md: no matcher = every tool) that runs fakes/hook_logger.py with
the log path. The log has one line per hook run: {"epoch", "input": <hook
input>}.

guard_hook_settings_args (D23/T9): one PreToolUse command hook with a
given matcher that runs fakes/guard_hook.py, which logs every input with
the action it took ("pass", "deny", "exit1") and denies or fails one
target tool.
"""

import json
import os
import shlex

from harness.check import expect_equal
from harness.wire import read_records

FAKES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fakes")
HOOK_LOGGER_SCRIPT = os.path.join(FAKES_DIR, "hook_logger.py")
GUARD_HOOK_SCRIPT = os.path.join(FAKES_DIR, "guard_hook.py")
SETTINGS_FLAG = "--settings"
PRE_TOOL_USE = "PreToolUse"


def hook_settings_args(*, python, log_path, events):
    """["--settings", <inline JSON>] registering the logger for each event."""
    command = "%s %s %s" % (shlex.quote(python), shlex.quote(HOOK_LOGGER_SCRIPT), shlex.quote(log_path))
    settings = {"hooks": {event: [{"hooks": [{"type": "command", "command": command}]}] for event in events}}
    return [SETTINGS_FLAG, json.dumps(settings, sort_keys=True, separators=(",", ":"))]


def guard_hook_settings_args(*, python, log_path, matcher, mode, target_tool, reason, handler_fields):
    """["--settings", <inline JSON>] with one PreToolUse command hook
    (fakes/guard_hook.py; D23/T9). matcher: the hook matcher, as written;
    mode: "deny" or "fail" for target_tool (the full mcp__<server>__<tool>
    name); reason: the permissionDecisionReason of a deny; handler_fields:
    more fields of the handler, e.g. {"onFailure": "block"}, {} for none."""
    command = " ".join(shlex.quote(part) for part in (python, GUARD_HOOK_SCRIPT, log_path, mode, target_tool, reason))
    handler = {"type": "command", "command": command}
    handler.update(handler_fields)
    settings = {"hooks": {PRE_TOOL_USE: [{"matcher": matcher, "hooks": [handler]}]}}
    return [SETTINGS_FLAG, json.dumps(settings, sort_keys=True, separators=(",", ":"))]


def read_hook_log(*, path):
    """Every hook line; an absent file means no hook ran (not an error)."""
    if not os.path.exists(path):
        return []
    return read_records(path=path)


def check_hook_log(*, entries):
    """Every line of a hook log (read_hook_log) has a hook_event_name. A line
    whose stdin was not JSON with one fails here (the logger keeps it as
    evidence). Call once per log, before hook_events."""
    bad = [entry for entry in entries if "hook_event_name" not in entry["input"]]
    expect_equal(what="hook log lines without hook_event_name", expected=[], actual=bad)


def hook_events(*, entries, event_name):
    """The lines of one hook event, from entries that passed check_hook_log."""
    return [entry for entry in entries if entry["input"]["hook_event_name"] == event_name]
