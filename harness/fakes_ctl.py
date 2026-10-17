"""Paths of the fake MCP servers, and a runner for the HTTP fake."""

import json
import logging
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass

from fakes.http_fake import CHECKING_MODES, EXPECTED_AUTH_ENV
from harness.check import step, wait_done, wait_failed, wait_start

logger = logging.getLogger(__name__)

FAKES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fakes")
HTTP_FAKE_SCRIPT = os.path.join(FAKES_DIR, "http_fake.py")
STDIO_FAKE_SCRIPT = os.path.join(FAKES_DIR, "stdio_fake.py")
READY_POLL_S = 0.05


@dataclass(frozen=True)
class RunningHttpFake:
    url: str
    port: int
    log_path: str


def _wait_ready(*, name, proc, ready_file, timeout_s):
    """Poll for the fake's ready file every READY_POLL_S; logs the start and
    the end of the wait with what came back (the port, or why not)."""
    started = wait_start(what="http fake %s (pid %d) to write its ready file, poll every %.2f s, up to %s s" % (
        name, proc.pid, READY_POLL_S, timeout_s))
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if os.path.exists(ready_file):
            with open(ready_file, encoding="utf-8") as handle:
                ready = json.load(handle)
            wait_done(started=started, response="ready file says %s" % json.dumps(ready, sort_keys=True))
            return ready
        if proc.poll() is not None:
            wait_failed(started=started, response="the fake exited early with code %s" % proc.returncode)
            raise RuntimeError("http fake %s ready: Expected: a ready file. Actual: the process exited with code %s."
                               % (name, proc.returncode))
        time.sleep(READY_POLL_S)
    wait_failed(started=started, response="no ready file after %s s" % timeout_s)
    raise RuntimeError("http fake %s ready: Expected: a ready file within %s s. Actual: none." % (name, timeout_s))


def _stop(*, name, proc, stop_timeout_s):
    """SIGTERM, wait up to stop_timeout_s, then SIGKILL; logs each wait."""
    if proc.poll() is not None:
        logger.info("http fake %s (pid %d) already exited with code %s", name, proc.pid, proc.returncode)
        return
    step(text="stop http fake %s: SIGTERM to pid %d" % (name, proc.pid))
    proc.terminate()  # SIGTERM on POSIX
    started = wait_start(what="http fake %s (pid %d) to exit after SIGTERM, up to %s s" % (name, proc.pid,
                                                                                          stop_timeout_s))
    try:
        code = proc.wait(timeout=stop_timeout_s)
        wait_done(started=started, response="exit code %s" % code)
    except subprocess.TimeoutExpired:
        wait_failed(started=started, response="still running after %s s; sending SIGKILL" % stop_timeout_s)
        proc.kill()
        started = wait_start(what="http fake %s (pid %d) to exit after SIGKILL, up to %s s" % (name, proc.pid,
                                                                                               stop_timeout_s))
        code = proc.wait(timeout=stop_timeout_s)
        wait_done(started=started, response="exit code %s" % code)


@contextmanager
def running_http_fake(*, name, host, path, auth_mode, expected_authorization, log_path, work_dir,
                      base_env, startup_timeout_s, stop_timeout_s):
    """Run http_fake.py for the duration of the `with` block.

    expected_authorization is the exact Authorization value the fake accepts
    in a checking auth_mode; it travels by env var, never on the command
    line. Pass None for auth_mode "off".
    """
    ready_file = os.path.join(work_dir, "%s.ready.json" % name)
    stderr_path = os.path.join(work_dir, "%s.stderr.txt" % name)
    env = dict(base_env)
    if auth_mode in CHECKING_MODES:
        env[EXPECTED_AUTH_ENV] = expected_authorization
    argv = [
        sys.executable, HTTP_FAKE_SCRIPT,
        "--host", host, "--port", "0", "--path", path,
        "--log", log_path, "--ready-file", ready_file,
        "--name", name, "--auth-mode", auth_mode,
    ]
    step(text="start http fake %s on %s, path %s, auth mode %s" % (name, host, path, auth_mode))
    with open(stderr_path, "w", encoding="utf-8") as stderr_file:
        proc = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=stderr_file)
        try:
            ready = _wait_ready(name=name, proc=proc, ready_file=ready_file, timeout_s=startup_timeout_s)
            port = ready["port"]
            logger.info("http fake %s up: pid %d, http://%s:%d%s, auth mode %s", name, proc.pid, host, port, path, auth_mode)
            yield RunningHttpFake(url="http://%s:%d%s" % (host, port, path), port=port, log_path=log_path)
        finally:
            _stop(name=name, proc=proc, stop_timeout_s=stop_timeout_s)
