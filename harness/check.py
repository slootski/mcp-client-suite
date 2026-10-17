"""Log what a test does and what it gets back, and check with Expected/Actual.

Every test and every harness check uses these, so a test's log in
report.html reads as a story: what it did, what came back, what it checked.

  step(text=...)            INFO  "step: <action>"
  got(what=..., value=...)  INFO  "got <what>: <value>"            (a status, a field, a count read back)
  record(what=..., value=...) INFO "S recorded: <what>: <value>"   (a model fact kept, never asserted)
  wait_start(what=...)      INFO  "start waiting for: <what>"; returns the start time
  wait_done(started=..., response=...)   INFO  "waiting done (0.43 s): <response>"
  wait_failed(started=..., response=...) ERROR "waiting done (10.00 s): <response>"
  expect_equal / expect_true / expect_in / expect_not_in
      one line "check <what>: Expected: <e>, Actual: <a> -> OK" (INFO) or
      "-> FAIL" (ERROR), then on a miss
      AssertionError("<what>: Expected: <e>. Actual: <a>.")

Log lines are cut at LOG_VALUE_MAX_CHARS. When both sides of a check are
long, the cut keeps the first place where they differ in view, so the log
line never hides the difference. The AssertionError carries the full values.

Secrets: these helpers do not redact. Callers pass redacted text, a
fingerprint, or a boolean (computed first), never a credential value.
The `stacklevel` arguments make each line name the caller's file, line and
function, not this module's.
"""

import logging
import time

logger = logging.getLogger(__name__)

LOG_VALUE_MAX_CHARS = 300  # a longer value is cut in the log line only, never in the AssertionError
DIFF_CONTEXT_CHARS = 60  # kept before the first difference when both sides of a check are cut
CALLER_OF_HELPER = 2  # stacklevel: the function that called step/got/record/wait_*
CALLER_OF_CHECK = 3  # stacklevel: the function that called expect_* (through _report)
LINE_BREAK_SHOWN = " | "  # a line break inside a value, so each log record stays one line
RESULT_OK = "OK"
RESULT_FAIL = "FAIL"


def shown(*, value):
    """The text form of a value: a str as is, anything else as repr."""
    return value if isinstance(value, str) else repr(value)


def one_line(*, text):
    """text with its line breaks shown as LINE_BREAK_SHOWN (log lines only)."""
    return LINE_BREAK_SHOWN.join(text.splitlines()) if "\n" in text or "\r" in text else text


def cut(*, text):
    """text on one line, cut to LOG_VALUE_MAX_CHARS, with the number of
    chars left out."""
    text = one_line(text=text)
    if len(text) <= LOG_VALUE_MAX_CHARS:
        return text
    return "%s [... %d more chars]" % (text[:LOG_VALUE_MAX_CHARS], len(text) - LOG_VALUE_MAX_CHARS)


def _window(*, text, start):
    piece = text[start:start + LOG_VALUE_MAX_CHARS]
    head = "[%d chars ...] " % start if start else ""
    rest = len(text) - start - len(piece)
    tail = " [... %d more chars]" % rest if rest > 0 else ""
    return head + piece + tail


def cut_pair(*, expected, actual):
    """Both texts cut for one log line. When either is too long, both are
    cut at the same offset, a little before their first difference."""
    expected = one_line(text=expected)
    actual = one_line(text=actual)
    if len(expected) <= LOG_VALUE_MAX_CHARS and len(actual) <= LOG_VALUE_MAX_CHARS:
        return expected, actual
    first = 0
    limit = min(len(expected), len(actual))
    while first < limit and expected[first] == actual[first]:
        first += 1
    start = max(0, first - DIFF_CONTEXT_CHARS)
    return _window(text=expected, start=start), _window(text=actual, start=start)


def step(*, text):
    """A test action: add a server, start a fake, run a command, mutate a recording."""
    logger.info("step: %s", text, stacklevel=CALLER_OF_HELPER)


def got(*, what, value):
    """A value the test read back: a status line, a field, a count, a timing."""
    logger.info("got %s: %s", what, cut(text=shown(value=value)), stacklevel=CALLER_OF_HELPER)


def record(*, what, value):
    """An S fact that is recorded, not asserted."""
    logger.info("S recorded: %s: %s", what, cut(text=shown(value=value)), stacklevel=CALLER_OF_HELPER)


def wait_start(*, what):
    """Log the start of a wait; returns the monotonic start time for wait_done."""
    logger.info("start waiting for: %s", what, stacklevel=CALLER_OF_HELPER)
    return time.monotonic()


def wait_done(*, started, response):
    logger.info("waiting done (%.2f s): %s", time.monotonic() - started, cut(text=response),
                stacklevel=CALLER_OF_HELPER)


def wait_failed(*, started, response):
    logger.error("waiting done (%.2f s): %s", time.monotonic() - started, cut(text=response),
                 stacklevel=CALLER_OF_HELPER)


def _report(*, what, expected_text, actual_text, holds):
    """One log line for a check, then the AssertionError on a miss."""
    expected_log, actual_log = cut_pair(expected=expected_text, actual=actual_text)
    if holds:
        logger.info("check %s: Expected: %s, Actual: %s -> %s", what, expected_log, actual_log, RESULT_OK,
                    stacklevel=CALLER_OF_CHECK)
        return
    logger.error("check %s: Expected: %s, Actual: %s -> %s", what, expected_log, actual_log, RESULT_FAIL,
                 stacklevel=CALLER_OF_CHECK)
    raise AssertionError("%s: Expected: %s. Actual: %s." % (what, expected_text, actual_text))


def expect_equal(*, what, expected, actual):
    """actual == expected (values shown with repr, so 3 and '3' differ)."""
    _report(what=what, expected_text=repr(expected), actual_text=repr(actual), holds=actual == expected)


def expect_true(*, what, expected, actual, holds):
    """holds is the check, computed by the caller; expected and actual
    describe it (a str is shown as is, anything else as repr)."""
    _report(what=what, expected_text=shown(value=expected), actual_text=shown(value=actual), holds=bool(holds))


def expect_in(*, what, item, container):
    """item in container."""
    _report(what=what, expected_text="contains %r" % (item,), actual_text=repr(container), holds=item in container)


def expect_not_in(*, what, item, container):
    """item not in container."""
    _report(what=what, expected_text="does not contain %r" % (item,), actual_text=repr(container),
            holds=item not in container)
