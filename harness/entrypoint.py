"""Container entrypoint: run pytest into a staging folder, scan, then keep.

  python3 -m harness.entrypoint --staging-dir DIR --artifact-dir DIR -- [pytest args]

0. The API key, when run.sh got one, arrives as a file, not as container
   env (QA step 3: `docker inspect` showed `ANTHROPIC_API_KEY=<value>`, and
   a `kill -9` of run.sh skips its cleanup trap and leaves that container).
   run.sh `docker cp`s a 0600 file owned by the container user to
   SUITE_API_KEY_FILE before `docker start`. This script reads it, deletes
   it, and puts the value in the env of the pytest process only (not in
   its own os.environ). If SUITE_API_KEY_FILE is set but the file cannot
   be read, or ANTHROPIC_API_KEY is already in the container env, it stops
   with exit 2: a silent "no key" would skip every model test and pass.
1. pytest runs under coreutils `timeout` (hard whole-run cap) and writes
   every artifact (per-test folders, junit.xml, cost.json from the suite
   cost ledger, path in SUITE_COST_FILE, s-rates.json with the S pass
   rates of repeated tests, path in SUITE_S_RATES_FILE, and outcomes.json
   with every item's outcome, xfails apart from each kind of skip, path in
   SUITE_OUTCOMES_FILE) to the staging folder, inside the container and not
   mounted. Like every staged file, they go through the scan below.
2. Every staged file is scanned for the prefixes of the test credentials
   the suite generates (SECRET_SCAN_MARKERS: `Bearer test-`, `test-dummy-`),
   and, when ANTHROPIC_API_KEY is set, for its value. A file that contains
   one is NOT kept; only its path is printed. Each test also scans its own
   folder for the exact credentials it generated (tests/conftest.py,
   harness/redact.py), but that per-test scan does not run when the hard
   cap kills pytest (exit 124); the prefix scan here still does.
3. secret-scan.json is written to the artifact folder first, then the clean
   files are copied there. The artifact folder is inside the container (no
   bind mount): run.sh copies it out with `docker cp` after the container
   exits, into a fresh ./artifacts/<run-id>/ on the host.

Exit code: pytest's exit code (124 if the hard cap killed it, 137 if it had
to be killed). A leaked key or a failed copy fails the run with exit 1,
whatever pytest returned (0, 13, 14, ...), except 124 / 137: a hard-cap
stop is kept, so the reader sees the run was cut short (secret-scan.json
still lists the leak).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

from harness.artifact_scan import find_leaks
from harness.constants import (
    API_KEY_ENV,
    API_KEY_FILE_ENV,
    ARTIFACT_DIR_ENV,
    BASE_IMAGE_ENV,
    COST_FILE_ENV,
    IMAGE_ID_ENV,
    OUTCOMES_FILE_ENV,
    RATES_FILE_ENV,
    SECRET_SCAN_MARKERS,
    WHOLE_RUN_KILL_GRACE_S,
    WHOLE_RUN_TIMEOUT_S,
)

FAILURE_EXIT_CODE = 1
HARD_CAP_EXIT_CODES = (124, 137)  # coreutils `timeout`: TERM'd at the cap, or KILLed after the grace
SETUP_ERROR_EXIT_CODE = 2
REPORT_NAME = "secret-scan.json"
COST_FILE_NAME = "cost.json"  # written by tests/conftest.py (cost ledger), kept like any staged file
RATES_FILE_NAME = "s-rates.json"  # written by harness/repeat.py (S pass rates of repeated tests)
OUTCOMES_FILE_NAME = "outcomes.json"  # written by tests/conftest.py (outcome counts, xfails apart from skips)


class KeyHandoffError(Exception):
    pass


def take_api_key(*, environ):
    """The API key from the run.sh hand-off file (then deleted), or None
    when run.sh got no key. Raises KeyHandoffError on any inconsistency."""
    if API_KEY_ENV in environ:
        raise KeyHandoffError("%s is set in the container env; start the suite with ./run.sh, which hands the key "
                              "over as a file so `docker inspect` never shows it" % API_KEY_ENV)
    if API_KEY_FILE_ENV not in environ:
        return None
    path = environ[API_KEY_FILE_ENV]
    try:
        with open(path, encoding="utf-8") as handle:
            key = handle.read()
    except OSError as exc:
        raise KeyHandoffError("%s=%s but the key file cannot be read (%s); refusing to run the model tier "
                              "as if no key was given" % (API_KEY_FILE_ENV, path, exc.strerror))
    try:
        os.remove(path)
    except OSError as exc:
        raise KeyHandoffError("cannot delete the key file %s after reading it (%s)" % (path, exc.strerror))
    if not key:
        raise KeyHandoffError("the key file %s is empty" % path)
    return key


def parse_args(*, argv):
    parser = argparse.ArgumentParser(description="run the MCP client suite")
    parser.add_argument("--staging-dir", required=True)
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    extra = args.pytest_args[1:] if args.pytest_args[:1] == ["--"] else args.pytest_args
    return args.staging_dir, args.artifact_dir, extra


def write_report(*, artifact_dir, report):
    with open(os.path.join(artifact_dir, REPORT_NAME), "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")


def copy_clean(*, staging, artifact_dir, leaks):
    """Copy every staged file not in leaks. Return (kept, errors)."""
    kept = 0
    errors = []
    for directory, _subdirs, files in os.walk(staging):
        for filename in files:
            source = os.path.join(directory, filename)
            relative = os.path.relpath(source, staging)
            if relative in leaks:
                continue
            target = os.path.join(artifact_dir, relative)
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copyfile(source, target)
                kept += 1
            except OSError as exc:
                errors.append("%s: %s" % (relative, exc.strerror))
    return kept, errors


def main():
    staging, artifact_dir, pytest_args = parse_args(argv=sys.argv[1:])
    for name in (IMAGE_ID_ENV, BASE_IMAGE_ENV):
        if name not in os.environ:
            sys.stderr.write("entrypoint: %s is not set; start the suite with ./run.sh\n" % name)
            return SETUP_ERROR_EXIT_CODE
    os.makedirs(artifact_dir, exist_ok=True)
    tests_dir = os.path.join(staging, "tests")
    os.makedirs(tests_dir, exist_ok=True)

    try:
        api_key = take_api_key(environ=os.environ)
    except KeyHandoffError as exc:
        sys.stderr.write("entrypoint: %s\n" % exc)
        return SETUP_ERROR_EXIT_CODE
    env = {name: os.environ[name] for name in os.environ if name != API_KEY_FILE_ENV}
    if api_key is not None:
        env[API_KEY_ENV] = api_key  # the pytest process only
    env[ARTIFACT_DIR_ENV] = tests_dir
    env[COST_FILE_ENV] = os.path.join(staging, COST_FILE_NAME)
    env[RATES_FILE_ENV] = os.path.join(staging, RATES_FILE_NAME)
    env[OUTCOMES_FILE_ENV] = os.path.join(staging, OUTCOMES_FILE_NAME)
    argv = [
        "timeout", "--signal=TERM", "--kill-after=%d" % WHOLE_RUN_KILL_GRACE_S, str(WHOLE_RUN_TIMEOUT_S),
        sys.executable, "-m", "pytest", "--junitxml", os.path.join(staging, "junit.xml"),
        "--html", os.path.join(staging, "report.html"), "--self-contained-html",
        "--log-file", os.path.join(staging, "suite.log"),
    ] + pytest_args
    print("entrypoint: %s" % " ".join(argv), flush=True)
    rc = subprocess.run(argv, env=env).returncode

    key_set = api_key is not None
    key_leaks = find_leaks(root=staging, needles=[api_key]) if key_set else []
    marker_leaks = find_leaks(root=staging, needles=list(SECRET_SCAN_MARKERS))
    leaks = sorted(set(key_leaks) | set(marker_leaks))
    report = {
        "api_key_set": key_set,
        "scanned_for_api_key": key_set,
        "scanned_for_markers": list(SECRET_SCAN_MARKERS),
        "files_with_api_key": key_leaks,
        "files_with_test_credential_marker": marker_leaks,
        "leaking_files_not_kept": leaks,
        "pytest_exit_code": rc,
        "copy": "pending",
    }
    write_report(artifact_dir=artifact_dir, report=report)
    if not key_set:
        print("entrypoint: %s not set, API key scan skipped (test-credential marker scan ran)" % API_KEY_ENV, flush=True)
    if leaks:
        print("entrypoint: SECRET SCAN FAILED, %d file(s) held the API key or a test credential and were not kept:"
              % len(leaks), flush=True)
        for path in leaks:
            print("  " + path, flush=True)

    kept, errors = copy_clean(staging=staging, artifact_dir=artifact_dir, leaks=set(leaks))
    report["copy"] = {"files_kept": kept, "errors": errors}
    write_report(artifact_dir=artifact_dir, report=report)
    print("entrypoint: kept %d artifact file(s), %d copy error(s)" % (kept, len(errors)), flush=True)
    for error in errors:
        print("  copy error: " + error, flush=True)
    if (leaks or errors) and rc not in HARD_CAP_EXIT_CODES:
        return FAILURE_EXIT_CODE
    return rc


if __name__ == "__main__":
    sys.exit(main())
