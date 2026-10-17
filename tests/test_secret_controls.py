"""Can-fail self-tests of the secret controls (free: no model call, no real key).

Every planted value is made up (DUMMY_SECRET_PREFIX + random hex) and lives
in tmp_path, never in the run's artifacts: the entrypoint's marker scan would
drop any staged file that holds one, the suite log included. So no log line
here holds a planted value or a path that does; checks log roles, booleans
and placeholders only.

  * harness/artifact_scan.find_leaks: a marker in a file's bytes or in its
    name is found; a clean file is not.
  * harness/redact: redact_text and redact_argv replace every registered
    value (--env, --header, the presence-only key, with no hash of it);
    scan_dir finds a registered value left on disk; copy_tree_redacted
    withholds `.credentials.json` and drops a binary file.
  * harness/entrypoint.take_api_key: the hand-off file is read, then deleted;
    a key in the container env, a missing file or an empty file is refused.
  * harness/entrypoint.main: a pytest run that writes the handed-off key
    into its artifacts exits 1, the file is not kept, and secret-scan.json
    lists it; the same run writing a clean file exits 0 and keeps it.
"""

import json
import os
import secrets
import sys

import pytest

import harness.entrypoint as entrypoint
from harness.artifact_scan import find_leaks
from harness.check import expect_equal, expect_in, expect_true, got, step
from harness.constants import (
    API_KEY_ENV,
    API_KEY_FILE_ENV,
    ARTIFACT_DIR_ENV,
    BASE_IMAGE_ENV,
    DUMMY_SECRET_PREFIX,
    IMAGE_ID_ENV,
    SECRET_SCAN_MARKERS,
    WITHHELD_CONFIG_FILE_NAMES,
)
from harness.entrypoint import KeyHandoffError, take_api_key
from harness.redact import (
    PRESENCE_ONLY_PLACEHOLDER,
    SecretRegistry,
    copy_tree_redacted,
    placeholder,
    redact_argv,
    scan_dir,
)

pytestmark = [pytest.mark.free]

HEX_BYTES = 8
KEY_FILE_NAME = "suite-api-key"
PLANTED_NAME = "planted.txt"
PLANTED_RELATIVE = os.path.join("tests", PLANTED_NAME)  # under the staging folder (main puts ARTIFACT_DIR_ENV there)
NOT_A_SECRET = "self-test of the secret controls"
CLEAN_TEXT = "nothing secret here"
INNER_TEST = '''
import os


def test_writes_one_artifact():
    value = {source}
    with open(os.path.join(os.environ["{artifact_env}"], "{name}"), "w", encoding="utf-8") as handle:
        handle.write(value)
'''
INNER_SOURCES = {"key_written": 'os.environ["%s"]' % API_KEY_ENV, "clean": repr(CLEAN_TEXT)}


def dummy_secret():
    return DUMMY_SECRET_PREFIX + secrets.token_hex(HEX_BYTES)


def plant(*, root, relative, data):
    path = os.path.join(root, relative)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def test_find_leaks_finds_a_planted_marker(tmp_path):
    root = str(tmp_path / "staged")
    roles = {
        os.path.join("tests", "a", "stream.jsonl"): "marker in the bytes",
        os.path.join("tests", "a", DUMMY_SECRET_PREFIX + "name.txt"): "marker in the name",
        os.path.join("tests", "b", "clean.txt"): "clean",
    }
    plant(root=root, relative=os.path.join("tests", "a", "stream.jsonl"),
          data=('{"token": "%s"}\n' % dummy_secret()).encode("utf-8"))
    plant(root=root, relative=os.path.join("tests", "a", DUMMY_SECRET_PREFIX + "name.txt"),
          data=CLEAN_TEXT.encode("utf-8"))
    plant(root=root, relative=os.path.join("tests", "b", "clean.txt"), data=CLEAN_TEXT.encode("utf-8"))
    step(text="find_leaks over 3 planted files (needles: the %d SECRET_SCAN_MARKERS)" % len(SECRET_SCAN_MARKERS))
    leaks = find_leaks(root=root, needles=list(SECRET_SCAN_MARKERS))
    expect_equal(what="files find_leaks reports, by role", expected=["marker in the bytes", "marker in the name"],
                 actual=sorted(roles[path] if path in roles else "unknown file" for path in leaks))


def test_redact_replaces_every_registered_value():
    registry = SecretRegistry()
    token = registry.register(value=dummy_secret(), presence_only=False)
    key = registry.register(value=dummy_secret(), presence_only=True)
    text = registry.redact_text(text="header Bearer %s, key %s" % (token, key))
    expect_equal(what="(token, key) left in the redact_text output", expected=(False, False),
                 actual=(token in text, key in text))
    expect_equal(what="redact_text output", expected="header Bearer %s, key %s" % (
        placeholder(value=token), PRESENCE_ONLY_PLACEHOLDER), actual=text)
    argv = ["claude", "mcp", "add", "--env", "TOKEN=%s" % token, "--header", "Authorization: Bearer %s" % token,
            "-e", "KEY=%s" % key, "prompt with %s inside" % key]
    out = redact_argv(argv=argv, registry=registry)
    expect_equal(what="argv items that still hold a registered value", expected=[],
                 actual=[index for index, item in enumerate(out) if token in item or key in item])
    expect_equal(what="redacted argv values (--env, --header, -e with the key, a plain arg with the key)",
                 expected=["TOKEN=" + placeholder(value=token),
                           "Authorization: " + placeholder(value="Bearer " + token),
                           "KEY=" + placeholder(value=PRESENCE_ONLY_PLACEHOLDER),  # a hash of the placeholder only
                           "prompt with %s inside" % PRESENCE_ONLY_PLACEHOLDER],
                 actual=[out[4], out[6], out[8], out[9]])


def test_scan_dir_finds_a_value_and_copy_withholds_credentials(tmp_path):
    registry = SecretRegistry()
    token = registry.register(value=dummy_secret(), presence_only=False)
    source = str(tmp_path / "config")
    target = str(tmp_path / "copied")
    plant(root=source, relative="settings.json", data=('{"header": "%s"}' % token).encode("utf-8"))
    plant(root=source, relative=WITHHELD_CONFIG_FILE_NAMES[0],
          data=('{"accessToken": "%s"}' % dummy_secret()).encode("utf-8"))  # not registered: redaction cannot help
    plant(root=source, relative="blob.bin", data=b"\xff\xfe\x00")
    expect_equal(what="scan_dir of the source (the registered value is in settings.json)", expected=["settings.json"],
                 actual=scan_dir(root=source, registry=registry))
    report = copy_tree_redacted(source=source, target=target, registry=registry,
                                withheld_names=WITHHELD_CONFIG_FILE_NAMES)
    expect_equal(what="copy_tree_redacted report", expected={"withheld": [WITHHELD_CONFIG_FILE_NAMES[0]],
                                                             "dropped_binary": ["blob.bin"]}, actual=report)
    expect_equal(what="files copied", expected=["settings.json"], actual=sorted(os.listdir(target)))
    expect_equal(what="scan_dir of the copy", expected=[], actual=scan_dir(root=target, registry=registry))
    expect_equal(what="files of the copy with a test-credential marker", expected=[],
                 actual=find_leaks(root=target, needles=list(SECRET_SCAN_MARKERS)))


def key_file(*, tmp_path, text):
    path = str(tmp_path / KEY_FILE_NAME)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def test_take_api_key_reads_then_deletes_the_file(tmp_path):
    key = dummy_secret()
    path = key_file(tmp_path=tmp_path, text=key)
    taken = take_api_key(environ={API_KEY_FILE_ENV: path})
    expect_equal(what="(value returned is the file's, key file still on disk)", expected=(True, False),
                 actual=(taken == key, os.path.exists(path)))
    expect_equal(what="take_api_key with no hand-off file named", expected=None, actual=take_api_key(environ={}))


@pytest.mark.parametrize("case_id", ["key_in_container_env", "file_missing", "file_empty"])
def test_take_api_key_refuses_a_bad_hand_off(tmp_path, case_id):
    path = key_file(tmp_path=tmp_path, text="" if case_id == "file_empty" else dummy_secret())
    if case_id == "file_missing":
        os.remove(path)
    environ = {API_KEY_FILE_ENV: path}
    if case_id == "key_in_container_env":
        environ[API_KEY_ENV] = dummy_secret()
    with pytest.raises(KeyHandoffError) as caught:
        take_api_key(environ=environ)
    got(what="KeyHandoffError", value=str(caught.value))
    expected = {"key_in_container_env": "is set in the container env", "file_missing": "cannot be read",
                "file_empty": "is empty"}
    expect_in(what="the refusal", item=expected[case_id], container=str(caught.value))


@pytest.mark.parametrize("case_id", list(INNER_SOURCES))
def test_entrypoint_drops_a_leaking_file_and_exits_1(tmp_path, monkeypatch, case_id):
    """main() with a made-up key handed off as a file and an inner pytest
    run (coreutils `timeout`, pytest-html: the image has both) that writes
    one artifact: the key itself, or a clean text."""
    monkeypatch.delenv(API_KEY_ENV, raising=False)  # a keyed outer run: the real key must not reach this run
    monkeypatch.setenv(API_KEY_FILE_ENV, key_file(tmp_path=tmp_path, text=dummy_secret()))
    for name in (IMAGE_ID_ENV, BASE_IMAGE_ENV):
        monkeypatch.setenv(name, NOT_A_SECRET)
    inner = plant(root=str(tmp_path / "inner"), relative="test_plant.py", data=INNER_TEST.format(
        source=INNER_SOURCES[case_id], artifact_env=ARTIFACT_DIR_ENV, name=PLANTED_NAME).encode("utf-8"))
    staging, out = str(tmp_path / "staging"), str(tmp_path / "out")
    monkeypatch.setattr(sys, "argv", ["entrypoint", "--staging-dir", staging, "--artifact-dir", out, "--", inner,
                                      "-p", "no:cacheprovider", "-q"])
    step(text="entrypoint.main: inner pytest writes %s (%s)" % (PLANTED_RELATIVE, case_id))
    rc = entrypoint.main()
    with open(os.path.join(out, entrypoint.REPORT_NAME), encoding="utf-8") as handle:
        report = json.load(handle)
    got(what="secret-scan.json (file lists)", value={name: report[name] for name in report if name.startswith(
        ("files_", "leaking_"))})
    leaked = case_id == "key_written"
    expected_leaks = [PLANTED_RELATIVE] if leaked else []
    expect_equal(what="(entrypoint exit code, inner pytest exit code)",
                 expected=(entrypoint.FAILURE_EXIT_CODE if leaked else 0, 0), actual=(rc, report["pytest_exit_code"]))
    expect_equal(what="(files_with_api_key, leaking_files_not_kept)", expected=(expected_leaks, expected_leaks),
                 actual=(report["files_with_api_key"], report["leaking_files_not_kept"]))
    expect_true(what="%s in the kept artifacts" % PLANTED_RELATIVE, expected="absent" if leaked else "present",
                actual=os.path.exists(os.path.join(out, PLANTED_RELATIVE)),
                holds=os.path.exists(os.path.join(out, PLANTED_RELATIVE)) is not leaked)
