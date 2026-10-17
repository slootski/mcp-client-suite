ADDENDUM TO R01 -- facts read after R01 was written.

Source: code.claude.com/docs/en/mcp (rest of the page), code.claude.com/docs/en/headless, code.claude.com/docs/en/env-vars (partial), modelcontextprotocol.io spec pages for tools/pagination/progress (2025-11-25) and stdio transport (2026-07-28). Read 2026-10-14.

== TOOL SEARCH (was "not yet verified" in R01 -- now confirmed) ==

- Tool search is ON BY DEFAULT. Only tool names and server instructions load at session start; full tool definitions load on demand via a ToolSearch call.

- No fixed per-server tool cap; limited by context budget.

- Disabled automatically when ANTHROPIC_BASE_URL points to a non-first-party host. ENABLE_TOOL_SEARCH=true overrides that fallback explicitly.

- CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS forces it off; ENABLE_TOOL_SEARCH cannot override that.

- Not supported on Azure-hosted Microsoft Foundry deployments (server-side rejection); ENABLE_TOOL_SEARCH can't override this either.

- Description length limits: tool loaded upfront or server instructions = 4096 chars (NEW as of 2.1.296; was 2048 before). Tool loaded via tool search = 16384 chars (before v2.1.295 the 2048 limit applied even to searched tools). CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH (v2.1.280+) overrides both numbers with one value.

- Per-tool "anthropic/alwaysLoad": true in _meta forces that tool to load upfront. ":false" keeps a tool deferred even if the whole server is configured alwaysLoad:true (requires v2.1.285+).

- CONSEQUENCE FOR OUR HARNESS: since tool search is on by default, a "right tool, right args" test that calls our MCP tool through the model may first trigger a ToolSearch call before the real tools/call. Pin ENABLE_TOOL_SEARCH=false for wire-level determinism tests where we want tools/call directly without an extra round trip; keep one test with tool search ON (default) to confirm search finds our tool at all.

== HEADLESS / -p MODE FACTS (code.claude.com/docs/en/headless) ==

- Exit code 0 on success, non-zero on failure. Invalid flag -\> stderr before run starts. Failure inside the run (e.g. missing auth) -\> failure printed as the result on stdout.

- --bare skips autodiscovery of hooks/skills/commands/plugins/MCP servers/auto memory/CLAUDE.md. MCP servers only connect if passed explicitly, e.g. --mcp-config.

- --output-format: text (default) \| json (result, session_id, total_cost_usd, per-model cost breakdown) \| stream-json (newline-delimited events, last line is a "result" message).

- system/init event (first event) carries:

- mcp_servers: array of {name, status}

- mcp_server_errors: array of {name, type, message} for --mcp-config entries skipped at validation (type: unknown_type, url_missing_type, invalid_config, reserved_name). Key omitted when there are no errors -- good for a CI gate.

- plugins / plugin_errors: same pattern for plugins.

- capabilities: array of protocol-behavior strings for feature-detection.

- With --mcp-config under -p, Claude Code waits for still-pending servers up to MCP_TIMEOUT (default 30s) before the first turn.

- --permission-prompts none: denies anything needing human approval instead of waiting; with stream-json shows as permission_denied system messages, summarized in the final result's permission_denials.

- --allowedTools "mcp__server__tool" pattern auto-approves specific MCP tools without a permission prompt -- useful for a deterministic -p test run.

- SIGTERM -\> exit code 143, in-progress turn left unfinished, no result recorded, running Bash subprocess tree killed, only SessionEnd hook runs.

- api_retry system event fields: type, subtype="api_retry", attempt, max_retries, retry_delay_ms, error_status, error (category enum), uuid, session_id.

== ENV VARS CONFIRMED (from the partial env-vars read) ==

- CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT: ms; default 300000 (5 min) network, 1800000 (30 min) stdio; 0 disables; \<1000 raised to 1000; capped at MCP_TOOL_TIMEOUT. Requires v2.1.187+; stdio was exempt before v2.1.203. (Matches R01.)

- CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS: ms; default 120000 (2 min); 0 disables. Requires v2.1.212+. (Matches R01.)

- CLAUDE_CODE_MCP_STARTUP_WAIT_MS: first-turn wait for connecting servers in non-interactive mode, v2.1.274+.

- CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH: default 4096 / 16384 split as above, v2.1.280+.

- CLAUDE_CODE_MCP_ALLOWLIST_ENV: set to 1 to spawn stdio servers with a baseline environment.

- MCP_TIMEOUT, MCP_TOOL_TIMEOUT, MCP_SDK_GENERATION, MCP_PROTOCOL_NEGOTIATION, MAX_MCP_OUTPUT_TOKENS, DISABLE_TELEMETRY: page sections not reached in this fetch pass; rely on R01's numbers -- flagged as a small residual gap.

== MCP SPEC 2025-11-25: tools/list, tools/call, pagination, progress -- confirmed verbatim ==

- tools/list supports pagination via an opaque "cursor" string in params; response may carry "nextCursor". Clients MUST treat cursors as opaque. Missing nextCursor = end of results. Invalid cursor SHOULD return JSON-RPC error -32602 (Invalid params). Page size is server-chosen.

- tools/call request: {name, arguments}. Response: {content: [...], isError, structuredContent?}. Content item types: text, image, audio, resource_link, resource (embedded). outputSchema on a tool means the server MUST return structuredContent conforming to it; for back-compat it SHOULD also serialize the same JSON into a text content block.

- Error handling has two channels:

1\. Protocol errors: JSON-RPC error object, e.g. unknown tool -\> code -32602, message "Unknown tool: ...". Malformed request also protocol-level.

2\. Tool execution errors: normal JSON-RPC result with isError: true and a human-readable content block -- meant for model self-correction. Protocol errors are "less likely" to be fixable by the model per spec wording.

- Tool name rules (SHOULD, not MUST): 1-128 chars, case-sensitive, charset [A-Za-z0-9_.-], no spaces/commas, unique within a server.

- Progress: requester sets params._meta.progressToken (string\|int, unique per active request). Receiver MAY send notifications/progress {progressToken, progress, total?, message?}. progress value MUST increase monotonically even with unknown total. Notifications MUST stop once the request completes. R01 already established progress does NOT extend the 28h wall-clock cap, only the idle timer.

== MCP SPEC 2026-07-28: stdio backward-compatibility / era probe -- confirmed verbatim ==

- A dual-era client SHOULD probe with "server/discover" before any other request, declaring its preferred modern version in _meta.

- Three outcomes:

1\. Server replies with a DiscoverResult -\> modern; pick a mutually supported version from supportedVersions.

2\. Server replies with a recognized modern error (e.g. UnsupportedProtocolVersionError) -\> modern but version mismatch; use one of its advertised supported versions; do NOT fall back to initialize.

3\. Any other error, or no response within a reasonable timeout -\> treat as legacy; fall back to the initialize handshake.

- The fallback must not be keyed to one error code: legacy servers reply to unrecognized pre-initialize methods with implementation-defined errors, commonly -32601 or -32602, or nothing at all.

- A client that only supports modern versions is still RECOMMENDED to probe, because some legacy servers process tools/call etc. under legacy semantics by accident if not validated -- probing turns that into a clean, deterministic failure instead.

== NET EFFECT ON THE TEST PLAN ==

- Our stdio test server MUST implement server/discover (even just returning a correctly-shaped UnsupportedProtocolVersionError, or a real DiscoverResult) to observe Claude Code choosing the modern path; if it doesn't answer at all, Claude Code should fall back to initialize after its own timeout -- this fallback delay is worth measuring once.

- The "wrong tool schema", "tool name over 128 chars", and "invalid JSON schema" edge cases documented on the mcp.md page are real, separately-handled exclusions (tool just missing from the list, not a hard failure) -- good P2 observe-only cases. Invalid input schemas are not yet in the plan; see D23/T12.
