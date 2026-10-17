AREA 3 -- Errors. PRIORITY: P0, candidate for "in depth".

TESTS

1\. [P0] Tool execution error (isError: true). Tool returns a normal JSON-RPC result with isError:true and a text content block describing e.g. "Invalid date: must be in the future." Assert: tool_result in the stream carries is_error (or equivalent field Claude Code surfaces). The fake puts a fresh token in the error text (the `isError` content). Assert: the `tool_result` is an error and holds the token; a `PostToolUseFailure` hook fires; the run ends with a `result` event; the server stays connected and a next call works. The model's reply is S and only recorded.

2\. [P0] Protocol error (JSON-RPC error object). Call a tool name that doesn't exist on the server (server replies with code -32602, "Unknown tool: ..."). Since Claude Code itself normally wouldn't let the model call an unlisted tool, this is triggered by having the server advertise a tool in tools/list that it then refuses at tools/call time (a legitimate case: dynamic tool removal race). Assert how Claude Code surfaces a raw JSON-RPC error vs. a tool execution error differently in the stream, and whether the run continues or the server gets marked unhealthy. The fake puts a fresh token in the error text (`error.message`). Assert: the `tool_result` is an error and holds the token; the run ends with a `result` event; the server stays connected and a next call works. The model's reply is S and only recorded.

3\. [P0] Malformed tools/call request from the client side isn't ours to control, but we CAN assert the reverse: server returns a response with a missing/invalid structure (e.g. result with neither content nor isError). Assert Claude Code's handling -- does it treat this as an error, hang, or silently accept empty content? Real-world servers do this.

4\. [P1] Connection-level failure mid-call vs tool-level error. Compare: (a) tool call that returns isError:true normally, vs (b) the server process dying mid-call (doc 20, test 1) vs (c) a malformed envelope (doc 21, test 2). This doc's job is the clean isError/protocol-error distinction; (b) and (c) are failure modes ABOVE the tool-result layer and live in their own docs.
