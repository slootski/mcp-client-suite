AREA 2 -- Tool calls, smoke level. PRIORITY: P0.

TESTS

1\. [P0] Minimal round trip. One tool `echo_canary` that returns a random canary string generated fresh per test run (not a fixed "4" -- avoids a hardcoded test accidentally passing against a cached/wrong answer). Prompt the model to call it and report the string back. Assert: (a) the final text result contains the exact canary, (b) the tool_use block in the stream names the right tool, (c) a tool_result block follows with the right content before the final assistant message.

2\. [P0] Tool search reachability (default ON). Same tool, default env (ENABLE_TOOL_SEARCH unset). Assert the tool is still successfully called -- confirms our harness's "pin ENABLE_TOOL_SEARCH=false elsewhere" choice isn't hiding a default-path bug.

3\. [P1] Tool-name mapping. Server name "calc", tool name "add" -\> assert the tool_use block's name is exactly mcp__calc__add, per the documented mcp__SERVER__TOOL convention.
