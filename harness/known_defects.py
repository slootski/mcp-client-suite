"""Documented behavior that 2.1.296 does not show.

A test marks such a check with
    @pytest.mark.xfail(strict=True, raises=DocumentedBehaviorMismatch, reason=...)
and raises DocumentedBehaviorMismatch only at the documented-behavior check.
Any other failure in the same test (a wire-log assert, a setup error) is a
plain AssertionError or other error, which `raises=` does not accept, so it
fails the run instead of hiding behind the xfail. With strict=True, the day
the documented behavior appears the test XPASSes and fails the run.

expect_documented logs and raises in the same Expected/Actual form as
harness/check.py, with the doc line as Expected.

record_documented is the record-only form, for a doc line the product is
not held to (a doc gap, or a server that breaks the spec first): it logs
the same Expected/Actual line, "-> MATCHES" (INFO) or "-> DIFFERS"
(WARNING), never raises, and returns whether the doc line held, so the
test can store it in run.json.
"""

import logging

from harness.check import cut_pair, shown

logger = logging.getLogger(__name__)

CALLER_OF_EXPECT_DOCUMENTED = 2  # stacklevel: the line names the test, not this module
RECORD_MATCHES = "MATCHES"
RECORD_DIFFERS = "DIFFERS"


class DocumentedBehaviorMismatch(AssertionError):
    pass


def expect_documented(*, what, doc, actual, holds):
    """Raise DocumentedBehaviorMismatch("<what>: Expected: <doc>. Actual:
    <actual>.") when the documented behavior does not hold. doc: the doc
    line (what the docs say happens); actual: what 2.1.296 did."""
    expected_text = shown(value=doc)
    actual_text = shown(value=actual)
    expected_log, actual_log = cut_pair(expected=expected_text, actual=actual_text)
    if not holds:
        logger.warning("check %s (documented behavior): Expected: %s, Actual: %s -> FAIL (documented behavior not "
                       "shown: DocumentedBehaviorMismatch)", what, expected_log, actual_log,
                       stacklevel=CALLER_OF_EXPECT_DOCUMENTED)
        raise DocumentedBehaviorMismatch("%s: Expected: %s. Actual: %s." % (what, expected_text, actual_text))
    logger.info("check %s (documented behavior): Expected: %s, Actual: %s -> OK", what, expected_log, actual_log,
                stacklevel=CALLER_OF_EXPECT_DOCUMENTED)


def record_documented(*, what, doc, actual, holds):
    """Log "record <what> (documented behavior, record-only): Expected:
    <doc>, Actual: <actual> -> MATCHES" (INFO) or "-> DIFFERS" (WARNING).
    Never raises. Returns holds (a bool) for the caller's run.json."""
    expected_log, actual_log = cut_pair(expected=shown(value=doc), actual=shown(value=actual))
    matches = bool(holds)
    if matches:
        logger.info("record %s (documented behavior, record-only): Expected: %s, Actual: %s -> %s", what,
                    expected_log, actual_log, RECORD_MATCHES, stacklevel=CALLER_OF_EXPECT_DOCUMENTED)
    else:
        logger.warning("record %s (documented behavior, record-only): Expected: %s, Actual: %s -> %s", what,
                       expected_log, actual_log, RECORD_DIFFERS, stacklevel=CALLER_OF_EXPECT_DOCUMENTED)
    return matches
