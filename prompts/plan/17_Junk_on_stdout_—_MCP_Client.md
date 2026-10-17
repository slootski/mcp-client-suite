AREA 3 -- Errors (protocol-hygiene edge case). PRIORITY: P1.

Spec: "The server MUST NOT write anything to its stdout that is not a valid MCP message." Tests how Claude Code behaves when a misbehaving server breaks that rule, and confirms stderr is correctly never treated as a protocol channel.

TESTS

1\. [P1] Non-JSON line on stdout between valid messages. Server writes a plain log line ("DEBUG: starting up") to stdout before/after a legitimate JSON-RPC message. The changelog says non-JSON stdout fails fast with `Connection closed`; expect that, not a skipped line, and record any difference.

2\. [P1] Partial line with no trailing newline (new case, was a gap). Server writes a JSON-RPC message without a terminating newline, then nothing else for a while. Spec requires newline-delimited, no embedded newlines. Assert whether the client waits for the newline (per spec) or times out, and that a subsequent well-formed message following a late newline is still parsed correctly.

3\. [P1] Noise on stderr. Server writes arbitrary text (including something that looks like JSON) to stderr continuously. Per spec, the client MAY capture/forward/ignore stderr and SHOULD NOT treat stderr output as indicating error conditions. Assert the connection and tool calls behave completely normally despite heavy stderr noise -- confirms stderr is truly out-of-band.

4\. [P2, observe only] Extremely long single line on stdout (no newline for a very large payload). Record whether there's a practical line-length limit before something breaks; no strong expectation from the spec either way.
