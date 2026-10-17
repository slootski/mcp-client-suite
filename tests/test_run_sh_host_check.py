"""run.sh says what the host is missing, and stops before it builds (free).

The suite needs only Docker on the host, with a daemon that runs Linux
containers (README "Run it"). When that is missing, run.sh must stop with
exit 16 and a message that says what to install or start, not with bash's
`command not found` (exit 127). A failed `docker build` keeps Docker's exit
code and adds a hint (network, disk).

Each case runs the real run.sh with bash under a controlled PATH. The
container has no docker, so the base PATH is the "not installed" case; the
other cases put a fake `docker` first on PATH. The fake logs every call, so
the test also proves that a host-check stop never reached `docker build`.
"""

import os
import shutil
import stat
import subprocess

import pytest

from harness.check import expect_equal, expect_in, expect_true, got, step

pytestmark = [pytest.mark.free]

RUN_SH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "run.sh")
BASH = "/bin/bash"
BASE_PATH = "/usr/bin:/bin"  # holds bash and coreutils, no docker
RUN_TIMEOUT_S = 30
HOST_NOT_READY_EXIT_CODE = 16  # run.sh HOST_NOT_READY_EXIT_CODE, docs/exit-codes.md
BUILD_FAILED_EXIT_CODE = 1  # what the fake `docker build` returns; run.sh passes it on
SHIM_LOG_NAME = "docker-calls.log"
BUILD_SUBCOMMAND = "build"

# Body of the fake docker, after the line that logs its arguments.
DAEMON_DOWN = 'echo "Cannot connect to the Docker daemon" >&2\nexit 1\n'
WINDOWS_DAEMON = '[ "$1" = version ] && { echo windows; exit 0; }\nexit 1\n'
BUILD_FAILS = ('[ "$1" = version ] && { echo linux; exit 0; }\n'
               '[ "$1" = build ] && { echo "failed to resolve source metadata" >&2; exit %d; }\n'
               'exit 99\n' % BUILD_FAILED_EXIT_CODE)

CASES = [
    # (case id, fake docker body or None for no docker, exit code, message part, build reached)
    ("not_installed", None, HOST_NOT_READY_EXIT_CODE, "docker not found on PATH", False),
    ("daemon_down", DAEMON_DOWN, HOST_NOT_READY_EXIT_CODE, "daemon is not reachable", False),
    ("windows_containers", WINDOWS_DAEMON, HOST_NOT_READY_EXIT_CODE, "needs Linux containers", False),
    ("build_fails", BUILD_FAILS, BUILD_FAILED_EXIT_CODE, "docker build failed (exit %d)" % BUILD_FAILED_EXIT_CODE,
     True),
]


def write_fake_docker(*, shim_dir, log_path, body):
    """A `docker` script in shim_dir that appends its arguments to log_path, then runs body."""
    os.makedirs(shim_dir)
    path = os.path.join(shim_dir, "docker")
    with open(path, "w") as handle:
        handle.write('#!/bin/sh\necho "$*" >> "%s"\n%s' % (log_path, body))
    os.chmod(path, stat.S_IRWXU)


def logged_calls(*, log_path):
    """The fake docker's calls, one argument string per call ([] when it never ran)."""
    if not os.path.exists(log_path):
        return []
    with open(log_path) as handle:
        return handle.read().splitlines()


@pytest.mark.parametrize("case_id,fake_body,expected_rc,message_part,build_reached",
                         CASES, ids=[case[0] for case in CASES])
def test_run_sh_stops_with_what_to_install(tmp_path, case_id, fake_body, expected_rc, message_part, build_reached):
    expect_true(what="the base PATH holds no docker (else the not-installed case proves nothing)",
                expected="no docker on %s" % BASE_PATH, actual=shutil.which("docker", path=BASE_PATH),
                holds=shutil.which("docker", path=BASE_PATH) is None)
    log_path = str(tmp_path / SHIM_LOG_NAME)
    path = BASE_PATH
    if fake_body is not None:
        shim_dir = str(tmp_path / "bin")
        write_fake_docker(shim_dir=shim_dir, log_path=log_path, body=fake_body)
        path = "%s:%s" % (shim_dir, BASE_PATH)
    step(text="run %s with bash, PATH=%s (case %s)" % (RUN_SH, path, case_id))
    result = subprocess.run([BASH, RUN_SH], env={"PATH": path, "HOME": str(tmp_path)},
                            capture_output=True, text=True, timeout=RUN_TIMEOUT_S, check=False)
    got(what="exit code", value=result.returncode)
    got(what="stderr", value=result.stderr)
    expect_equal(what="run.sh exit code", expected=expected_rc, actual=result.returncode)
    expect_in(what="run.sh tells the user what is wrong", item=message_part, container=result.stderr)
    expect_true(what="no bash 'command not found' left to the user", expected="no 'command not found'",
                actual=result.stderr, holds="command not found" not in result.stderr)
    calls = logged_calls(log_path=log_path)
    got(what="fake docker calls", value=calls)
    build_calls = [call for call in calls if call.split(" ")[0] == BUILD_SUBCOMMAND]
    expect_equal(what="run.sh reached docker build", expected=build_reached, actual=bool(build_calls))
