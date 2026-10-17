AREA 2 / AREA 3 boundary -- dynamic tool list behavior. PRIORITY: P1.

TESTS

1\. [P1] tools/list pagination. Server returns 2 tools + nextCursor on the first page, 1 more tool + no nextCursor on the second. Assert Claude Code follows the cursor and ends up with all 3 tools available to the model (e.g. the model can call the one on page 2). Assert the client treats the cursor as opaque -- doesn't need our test to prove this directly, but the test must NOT assume a fixed page size per spec.

3\. [P0] list_changed ordering. Server starts with tool `lock_door`; after the first successful call to it, server sends notifications/tools/list_changed, then only exposes `unlock_door` (lock_door removed). Assert: the list_changed notification arrives BEFORE the model is able to successfully call unlock_door, and the OLD tool (lock_door) is no longer offered after the refresh -- the ordering is the actual thing under test, not just "eventually works."

4\. [P1] list_changed with a failing refresh. Notification fires, but the server's next tools/list call fails (error or timeout). Per R01: previous tools are kept (since v2.1.214). Assert the model can still call the OLD tools after a failed refresh, rather than ending up with none.

5\. [P2, observe only] v2 runtime held-open stream reconnect behavior for list_changed on newer-revision servers (reopen logic, 10s/3-retries/6-hour-wait cascade from R01). Hard to trigger deterministically in 2-3 hours; documented as known behavior, not implemented.
