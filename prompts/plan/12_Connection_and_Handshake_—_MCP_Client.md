AREA 1 -- Connection and auth. PRIORITY: P0, candidate for "in depth".

R01+R06 confirm 2.1.296 includes the v2.1.292 stdio protocol-negotiation rollout, so the client may be dual-era (probe with server/discover, then fall back to initialize).

TESTS

1\. [P0] Legacy handshake, wire-level. MCP_PROTOCOL_NEGOTIATION=legacy. Assert from the server's own log: client sends initialize with jsonrpc/id/method/params.protocolVersion/capabilities/clientInfo; server replies with its protocolVersion + capabilities + serverInfo; client then sends notifications/initialized (a notification: no id). Assert the ORDER: no request other than ping before the `initialize` reply.

2\. [P0] Modern / dual-era probe. Default env (negotiation unset). Server implements server/discover. Assert the client probes server/discover BEFORE initialize, with its preferred version in _meta. The fake returns a DiscoverResult: assert no `initialize`, and log the client's next request (the fake may answer it with an error). The fake returns -32022 with `supported`: assert a retry with a listed version and no `initialize`. The fake returns -32601: assert `initialize` follows. A full session on 2026-07-28 is a 'not implemented' line.

3\. [P0] Fallback to legacy when discover is unimplemented. Server returns a generic JSON-RPC error (or nothing) for server/discover. Assert the client falls back to initialize, and measure the fallback delay (the spec explicitly allows "no response within a reasonable timeout" as one trigger -- that timeout value is what we're measuring, since neither doc names it). Run the silent variant last, in its own container. In every other test with negotiation unset, assert that the first message is `server/discover`, so a leaked memory shows up.

4\. [P0] claude mcp list / claude mcp get status strings, free (no model call, no API spend): "Connected" for a healthy server, "Failed to connect" for one that refuses to start, "Needs authentication" for a 401/403 case (doc 13, test 3b: a 401 with no configured header). Good test to run first and cheaply in CI.

5\. [P1] Startup slower than MCP_TIMEOUT. Server sleeps before answering initialize. Assert the status in `system/init` is `pending` or `failed`, the wall time is at least `MCP_TIMEOUT` minus slack, and the fake logged `initialize`.

6\. [P1] Capability negotiation content. Assert the server capability object advertised (e.g. tools.listChanged) matches what later behavior actually does (e.g. doc 18's list_changed test should only run if listChanged:true was declared here).

7\. [P2, observe only] roots/list. Confirm (or not) that Claude Code answers roots/list with the working directory, by having the server send that request if the negotiated era allows server-initiated requests.

8\. [P2] Scope precedence. Define server `dup` at local and user scope with different commands. Assert `claude mcp get dup` shows the local entry, and only the local fake's log shows a start.

9\. [P2] Version mismatch. The fake answers `initialize` with a version the client does not support. Assert the client disconnects or reports a failed status.

NOTES

- Area 1 is cheap to make airtight (no model tokens needed for 1-4), which is exactly the kind of "real behavior over many shallow tests" evidence the CTO's brief asks for.
