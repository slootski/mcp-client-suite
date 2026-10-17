# Claude Code MCP: facts checked against the docs

Source: [https://code.claude.com/docs/en/mcp](https://code.claude.com/docs/en/mcp) (also read the zh-CN copy, [https://code.claude.com/docs/zh-CN/mcp](https://code.claude.com/docs/zh-CN/mcp)). Read on 2026-10-14. Target version for the assignment: Claude Code 2.1.296 (release notes: [https://github.com/anthropics/claude-code/releases/tag/v2.1.296](https://github.com/anthropics/claude-code/releases/tag/v2.1.296)).

This is NOT a full copy. The site cannot be downloaded from the shell, and the page-reading tool shortens long pages. These are the facts that matter for the test plan, written down as read. The last ~16,800 characters of the English page were not read (tool search details and later sections). Verify those before relying on them.

Version rule: the docs describe the newest release. Every feature below carries a "v2.1.X or later" tag of 2.1.285 or lower where a tag exists, so it applies to 2.1.296.

## Transports and config

- http (recommended). In JSON, type "streamable-http" is an alias of "http".

- sse is deprecated. From v2.1.265, --transport http tries HTTP first and falls back to SSE.

- stdio: claude mcp add [options] NAME -- COMMAND [args...]. The -- is required to separate Claude's flags from the server's.

- ws (WebSocket): JSON only, type "ws". Listed by claude mcp list since 2.1.285 (changelog.md:1504). Use claude mcp get NAME or /mcp.

- A JSON entry with url but no type is read as stdio and fails.

- stdio servers get CLAUDE_PROJECT_DIR in their environment.

- Scopes: local (default), project (.mcp.json), user. Precedence: local, project, user, plugin, claude.ai connectors.

- In claude -p and the Agent SDK, project-scope servers from .mcp.json load WITHOUT an approval prompt.

- --strict-mcp-config plus --mcp-config: only the servers passed on the command line are used.

- Reserved server names: workspace, claude-in-chrome, computer-use, Claude Preview, Claude Browser.

## Status checks without the model (free)

- claude mcp list health-checks servers: "Connected", "Needs authentication", "Failed to connect". Failure details are added from v2.1.219.

- claude mcp get NAME shows the status and an Issue: line.

- /mcp inside a session shows status and tool counts.

- With --output-format stream-json, the system/init event has a mcp_server_errors field for skipped --mcp-config entries (v2.1.219+).

## Client runtimes and protocol negotiation

- Two runtimes: v1 (MCP TypeScript SDK 1.x) and v2 (SDK 2.0, adds MCP revision 2026-07-28).

- Env MCP_SDK_GENERATION = v1 or v2 forces one. Default: v2 in sessions that fetch feature flags (v2.1.232+); v2 by default on v2.1.274+ in the other listed cases.

- Env MCP_PROTOCOL_NEGOTIATION = auto or legacy. v2 asks HTTP servers whether they support the newer revision. For stdio servers the asking is rolled out from v2.1.292. auto is a different value: it probes every server type. "legacy" keeps every server on the earlier handshake.

- Consequence: pin these two variables in the test harness.

## Dynamic tool updates (list_changed)

- Interactive session: on notification, the client re-fetches the changed list.

- -p and Agent SDK: on notification, the client refreshes the tool list only.

- If the refresh fails, the previous tools are kept (since v2.1.214).

- v2 runtime: list_changed from newer-revision servers arrives on a held-open stream. If the stream closes within 10 s, it is reopened at most 3 times. If it lasted longer than 10 s, after 5 reopens in an hour the client waits about 6 hours.

## Reconnect and retry

- stdio servers are local processes: NO automatic reconnect.

- Remote servers dropped mid-session: reconnect with exponential backoff, up to 5 attempts, starting at 1 s and doubling. Same in claude -p. After 5 failures the server is marked failed (or "needs authentication").

- First connection of an HTTP/SSE server: transient errors (5xx, connection refused, timeout) are retried up to 3 times. Not retried: WebSocket first connection, auth errors, not-found.

- Discovery requests (tools/list, prompts/list, resources/list): retried up to 3 times on transient network or server errors. Not retried: auth errors, 4xx, request timeouts.

- /mcp reconnect all retries failed servers (v2.1.284+).

- Does the model hear about a failed server? With tool search (default ON): yes, it is told which server failed and why. Without tool search: no.

- Resumed session: a call to a tool whose server is still connecting is held up to 10 s, then fails with "No such tool available".

## Timeouts (very important for hang tests)

- MCP_TIMEOUT (env, ms): server startup timeout. Example: MCP_TIMEOUT=10000.

- Tool call wall-clock limit: per-server timeout field (ms) in the server's .mcp.json entry; or env MCP_TOOL_TIMEOUT. Default is about 28 HOURS. Progress notifications do NOT extend this limit. Values under 1000 are ignored.

- HTTP, SSE and connector servers also have a per-request timer until the first response byte: the largest of 60 s, the tool timeout and MCP_TIMEOUT. stdio and WebSocket have no per-request timer.

- Idle timeout (v2.1.203+): a tool call with no response AND no progress notification inside the idle window is aborted with an error. Defaults: 5 min for HTTP/SSE/WS/connectors, 30 min for stdio. Env CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT (ms) changes it, 0 disables it. The floor is the per-server timeout when it is at least 1000.

- Auto-background (v2.1.212+): a main-conversation MCP call running over 2 minutes moves to a background task. Env CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS changes the threshold, 0 turns it off. Not applied in non-interactive -p unless CLAUDE_AUTO_BACKGROUND_TASKS=1. Not applied to subagent calls.

## Output limits

- Warning above 10,000 tokens. Default cap 25,000 tokens (env MAX_MCP_OUTPUT_TOKENS).

- Successful text results over 50,000 characters are saved to a file, unless the server raised the tool's own limit.

## Authentication

- OAuth 2.0 for HTTP servers: /mcp or claude mcp login NAME / claude mcp logout NAME.

- 401 or 403 from a server you are not logged into: marked "needs authentication".

- If the server config has a static headers.Authorization or a headersHelper, a 401/403 at connect is reported as a connection FAILURE, not as "needs authentication".

- Logged-in OAuth server returns 401: refresh the token, reconnect, retry the request once; only then mark it.

- headersHelper: a command that prints a JSON object of headers; 10 s limit; re-run on each connect/reconnect.

- Non-interactive mode cannot run the OAuth flow. With tool search on, Claude is told the server's tools are unavailable until authorized (v2.1.196+).

- Credential env vars in remote url/headers (ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, AWS_BEARER_TOKEN_BEDROCK, HTTPS_PROXY, NPM_TOKEN...) are read as EMPTY on purpose. Use your own variable name.

- For stdio servers, secrets go in --env KEY=value. OAuth flags have no effect on stdio.

## Tool naming

- A server tool is called: mcp, two underscores, SERVER name, two underscores, TOOL name. Example: server "calc", tool "add" becomes mcp__calc__add.

- Plugin servers use: mcp__plugin_PLUGIN_SERVER__TOOL.

- Server names allow letters, digits, hyphen, underscore.

## Roots (v2.1.203+)

- Claude Code answers roots/list with the start directory plus --add-dir directories, and sends notifications/roots/list_changed when the set changes.

## Release 2.1.296 (from release notes, condensed)

- Default limit for MCP tool descriptions and server instructions raised from 2,048 to 4,096 characters.

- Windows: fix for stdio MCP server shutdown.

- Hooks: fixes around PreToolUse denials and updatedMCPToolOutput in managed settings.

- The release page showed "3 days ago", no calendar date.

## Not yet verified

- Tool search details (default ON; ENABLE_TOOL_SEARCH; alwaysLoad). Section not fully read.

- Which exact protocol revision Claude Code 2.1.296 speaks to a plain stdio test server on a fresh container. Check by running it against a logging server.
