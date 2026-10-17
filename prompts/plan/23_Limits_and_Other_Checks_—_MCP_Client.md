AREA 5 -- "What else has to be true before you'd call the client working?" PRIORITY: mixed P0/P1/P2.

TESTS

1\. [P0] Output size limit. Tool returns text over the default 25,000-token MAX_MCP_OUTPUT_TOKENS cap. Assert the `tool_result` names a file under the session's `tool-results` directory and the file holds the full text. Boundary pair: 49,999 and 50,001 characters.

2\. [P0] CI-gate-style validation. Start Claude Code with an intentionally broken --mcp-config entry (e.g. a url with no type) alongside a healthy server. Assert: the run continues, the broken entry appears in system/init's mcp_server_errors with the right skip-category type, and the healthy server's tools still work -- this is literally how a CI pipeline would gate on "did my MCP config break."

4\. [P1] Multiple servers, one misbehaving. Two stdio servers connected at once; one hangs forever on every call, the other behaves normally. Assert the healthy server's tools remain fully usable and aren't blocked by the hung one.

5\. [P1] Determinism of the free health check across repeated invocations. `claude mcp list` run 5 times against a stable, already-connected server returns the same status every time with no model call and no cost -- a good "free in CI" sanity signal distinct from doc 22's model-behavior determinism.

6\. [P2, observe only] Tool with a root-level anyOf/oneOf/allOf schema. Per mcp.md:1338-1349, Claude Code flattens these and prepends an explanatory sentence to the description, or skips the tool entirely if it can't. Record which happens against our test server's deliberately-tricky schema; no strong pass/fail since behavior is flag-gated server-side.

7\. [P2, observe only] Tool name over 128 characters. Per R06, the tool is left out of what's sent to the model, and the debug log names it, with the server's other tools still working. One test tool with a 140-char name; assert the long one is absent from the model's available tools and the rest of the server's tools are present.

8\. [P1, observe only] requiresUserInteraction tool under -p with --permission-prompts none. Per R06, this should be auto-denied rather than silently bypassed, since no human is present to answer. Confirms the "safety prompt" can't be defeated by non-interactive mode.

9\. [P0] PreToolUse deny. A command hook with matcher `mcp__guard__.*` denies `delete_all`. Gate: an allowed call to `list_items` on the same server reached the server first. Assert: a `tool_use` for `delete_all` exists, the server log has no `tools/call` for it, the hook log shows the deny. Variants: matcher `mcp__guard` (no `.*`) matches nothing; a hook that exits 1 lets the call through unless `onFailure` is `block`. The hook is passed with `--settings '<inline JSON>'`.

10\. [P0] Deny rule for `mcp__guard__delete_all` plus an allow rule for the rest: the server never sees the call; record whether the tool is missing from `system/init` `tools` or listed in `permission_denials`. Variant: a second server named `guard__ops`. Assert least privilege: a server-level deny `mcp__guard__ops` stops its calls, and an allow on `mcp__guard` does not let `guard__ops` through. Both fail on 2.1.296 (changelog.md:297, changelog.md:212; changed in 2.1.299): mark them as expected failures (doc 11, PINNED ENV: known product defect rule). This variant runs with `--allowedTools "mcp__guard"` only, not the doc 11 default, so a call that reaches `guard__ops` can only come from the `mcp__guard` rule.

11\. [P0] Credential exposure: the stdio fake logs the names and an 8-character hash of credential-like env vars. Assert `ANTHROPIC_API_KEY` reaches it by default and does not with `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`, plus the remote `url` and `headers` blanking of D13/T4. Merge D13/T4 here.

12\. [P1] Invalid input schema. One tool with a schema that fails the 2020-12 meta-schema, next to a good tool. Expect one of two documented outcomes and record which: the bad tool is left out and the good tool works, or a 400 that names the tool by its position. A 400 on every later turn is the 2.1.296 defect fixed in 2.1.300 (changelog.md:145): mark it as an expected failure (doc 11, PINNED ENV: known product defect rule).

13\. [P2, not implemented] Managed policy (`allowedMcpServers`, `deniedMcpServers`, `managed-mcp.json`). Reason: a deployed `managed-mcp.json` makes every `--mcp-config` run exit at startup, so it needs its own container.

14\. [P2] Untrusted annotations. A destructive tool marked `readOnlyHint: true`, with no allow rule for it: assert it is denied like any other tool.
