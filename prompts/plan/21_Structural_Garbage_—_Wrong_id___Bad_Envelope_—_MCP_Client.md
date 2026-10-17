AREA 3 -- Errors. PRIORITY: P1.

TESTS

1\. [P1] Orphan response id. Server sends a JSON-RPC response whose id doesn't match any outstanding request, immediately followed by the real, correctly-id'd response to the actual pending request. Assert Claude Code ignores/discards the orphan and correctly matches the real response -- doesn't get confused into attaching the wrong result to the wrong tool_use block.

2\. [P1] Malformed JSON-RPC envelope. One line that's valid JSON but missing jsonrpc/id/method-or-result fields entirely. Assert the client either drops it cleanly or surfaces a clear protocol error, without crashing the connection or silently hanging on the request that was actually pending.

3\. [P1] Duplicate response id. Server replies twice with the same id (once with a real result, once with an error) for a single request. Assert which one wins, or whether the client treats the second as garbage/ignores it -- not specified by the spec, so this is pure observed-behavior documentation.

4\. [P2, observe only] Response arrives for a request the client already gave up on (post-timeout). Late response after doc 19's idle/wall-clock timeout has already fired. Assert it doesn't resurrect the already-failed tool_result or corrupt a later, unrelated request's matching.
