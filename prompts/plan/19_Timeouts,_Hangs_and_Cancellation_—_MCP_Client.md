AREA 3 -- Errors / Area 4 touches determinism of timing. PRIORITY: P0, candidate for "in depth".

Needs explicit, short timeout values per test -- never rely on the ~28h MCP_TOOL_TIMEOUT default (would hang the suite).

TESTS

1\. [P0] Idle timeout fires with no response and no progress. Server receives tools/call and simply never answers, never sends a progress notification. Set `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT=3000` and `MCP_TOOL_TIMEOUT=60000`, with no per-server `timeout`. Assert, on the server clock, an abort at 3 s or later and before 5 s.

2\. [P0] Progress notifications reset the idle timer but not the wall-clock cap. Gate: the `tools/call` carries `params._meta.progressToken`, else inconclusive. Idle 3000, `MCP_TOOL_TIMEOUT=8000`, progress every 1 s. Assert no abort at 3 s and an abort at 8 s or later. This is the single clearest "determinism of timing" demonstration in the whole suite.

3\. [P0] Cancellation on timeout: assert the server's own log shows a notifications/cancelled was sent referencing the original request id once Claude Code gives up, per the 2025-11-25 cancellation spec, and that the client sends no further messages for that request afterward. In the legacy era this is a SHOULD: report a miss as a warning. In the default era on stdio it is a MUST.

4\. [P1] Auto-background threshold. A tool call that runs longer than CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS (short explicit value) in `-p` with `CLAUDE_AUTO_BACKGROUND_TASKS=1`; observe only, since no stream event is documented. Note from R06: not applied in -p unless CLAUDE_AUTO_BACKGROUND_TASKS=1 -- document the -p-specific gate as part of the assertion, don't just test the interactive path and assume -p matches.

5\. [P1] User-initiated cancellation (SIGINT style with SIGINT to `claude -p`, which ends the turn (headless.md:94), or SIGTERM at the process level). Assert the in-flight tool call is abandoned, the server observes notifications/cancelled (or process teardown, for SIGTERM), and the run's exit code matches what's documented (143 for SIGTERM).

6\. [P2, observe only] HTTP/SSE/connector per-request timer (largest of 60s, tool timeout, MCP_TIMEOUT) vs stdio/WebSocket having no such timer, per R01. Worth one HTTP-side comparison test if time allows; otherwise documented only.
