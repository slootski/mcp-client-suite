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
"""

import logging

from harness.check import cut_pair, shown

logger = logging.getLogger(__name__)

CALLER_OF_EXPECT_DOCUMENTED = 2  # stacklevel: the line names the test, not this module


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
