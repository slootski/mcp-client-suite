"""Run the `claude` CLI as a subprocess and record every call."""

import json
import subprocess
import time
from dataclasses import dataclass

from harness.check import wait_done, wait_failed, wait_start
from harness.constants import CLAUDE_BIN
from harness.redact import redact_argv

LOG_ARG_MAX_CHARS = 120  # a long prompt is cut in the log line; commands.jsonl has it in full
OUTPUT_PREVIEW_CHARS = 200  # first chars of stdout/stderr in the "waiting done" line (redacted first)
# run_claude show_output_preview: a `claude mcp ...` command shows the start of
# its output in the "waiting done" line; a `claude -p` run shows byte counts only.
OUTPUT_PREVIEW_SHOWN = True
OUTPUT_PREVIEW_HIDDEN = False
LINE_JOIN = " | "  # output lines joined on one log line


@dataclass(frozen=True)
class CliResult:
    argv: list
    returncode: int
    stdout: str
    stderr: str
    duration_s: float
    start_epoch: float  # wall clock, to cut the fakes' logs per command
    end_epoch: float

    @property
    def combined(self):
        return self.stdout + self.stderr


class CommandLog:
    """Appends one JSON line per command to <artifact dir>/commands.jsonl.
    --env/--header values are stored as hash + length, and every value in
    the registry is replaced in argv, stdout and stderr before writing."""

    def __init__(self, *, path, registry):
        self._path = path
        self._registry = registry

    def loggable(self, *, argv):
        """Redacted argv as one line for the suite log, long args cut."""
        parts = redact_argv(argv=argv, registry=self._registry)
        return " ".join(part if len(part) <= LOG_ARG_MAX_CHARS else part[:LOG_ARG_MAX_CHARS] + "..." for part in parts)

    def redacted(self, *, text):
        """text with every registered secret replaced (before any cut, so a
        cut never leaves part of a secret)."""
        return self._registry.redact_text(text=text)

    def append(self, *, argv, fields):
        entry = {"argv": redact_argv(argv=argv, registry=self._registry)}
        for key in fields:
            value = fields[key]
            entry[key] = self._registry.redact_text(text=value) if isinstance(value, str) else value
        with open(self._path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _captured_text(*, data):
    """Text of a TimeoutExpired capture: None means nothing was captured."""
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", "replace")
    return data


def output_preview(*, text, command_log):
    """The first OUTPUT_PREVIEW_CHARS of an output, redacted, on one line."""
    flat = LINE_JOIN.join(line for line in command_log.redacted(text=text).splitlines() if line.strip())
    if len(flat) <= OUTPUT_PREVIEW_CHARS:
        return flat
    return flat[:OUTPUT_PREVIEW_CHARS] + "..."


def outputs_summary(*, stdout, stderr, command_log, output_preview_shown):
    """'stdout N bytes: <preview>, stderr M bytes[: <preview>]' for the log,
    or 'stdout N bytes, stderr M bytes' when output_preview_shown is False."""
    if not output_preview_shown:
        return "stdout %d bytes, stderr %d bytes" % (len(stdout), len(stderr))
    out = "stdout %d bytes: %s" % (len(stdout), output_preview(text=stdout, command_log=command_log))
    if stderr:
        return out + ", stderr %d bytes: %s" % (len(stderr), output_preview(text=stderr, command_log=command_log))
    return out + ", stderr 0 bytes"


def run_claude(*, args, env, cwd, timeout_s, command_log, show_output_preview):
    """Run `claude <args>` and return a CliResult. A timeout fails the test
    with whatever output was captured so far. Logs "start waiting for:
    <command>" and "waiting done (<s> s): exit <rc>, <outputs>": byte
    counts, plus the start of each redacted output when show_output_preview is
    OUTPUT_PREVIEW_SHOWN. commands.jsonl has every output in full."""
    argv = [CLAUDE_BIN] + list(args)
    command = command_log.loggable(argv=argv)
    start_epoch = time.time()
    started = wait_start(what="%s (limit %s s)" % (command, timeout_s))
    try:
        proc = subprocess.run(
            argv,
            env=env,
            cwd=cwd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        duration, wall = time.monotonic() - started, time.time() - start_epoch
        partial_out = _captured_text(data=exc.stdout)
        partial_err = _captured_text(data=exc.stderr)
        command_log.append(
            argv=argv,
            fields={"timeout_s": timeout_s, "timed_out": True, "mono_s": round(duration, 3), "wall_s": round(wall, 3),
                    "stdout": partial_out, "stderr": partial_err},
        )
        wait_failed(started=started, response="timed out after %.3f s (wall %.3f s, limit %s s), partial %s" % (
            duration, wall, timeout_s, outputs_summary(stdout=partial_out, stderr=partial_err, command_log=command_log,
                                                       output_preview_shown=show_output_preview)))
        raise AssertionError("%s finished within the limit: Expected: exit within %s s. Actual: still running after "
                             "%.3f s." % (command, timeout_s, duration)) from exc
    duration = time.monotonic() - started
    result = CliResult(
        argv=argv, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr,
        duration_s=round(duration, 3), start_epoch=start_epoch, end_epoch=time.time(),
    )
    wait_done(started=started, response="exit %d, %s" % (
        result.returncode, outputs_summary(stdout=result.stdout, stderr=result.stderr, command_log=command_log,
                                           output_preview_shown=show_output_preview)))
    command_log.append(
        argv=argv,
        fields={"returncode": result.returncode, "duration_s": result.duration_s,
                "stdout": result.stdout, "stderr": result.stderr},
    )
    return result
