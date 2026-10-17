AREA 1 -- Connection and auth (continued). PRIORITY: P0/P1 split by transport.

TESTS

1\. [P0] stdio secrets via --env. Server requires a secret in its own environment to behave; add it with --env KEY=value; assert it connects. Then omit --env and assert the server-side behavior change (e.g. it reports auth failure in its own tool result) is visible through Claude Code's tool_result, since stdio has no OAuth/header concept at all.

2\. [P0] HTTP static header auth: right key. A minimal local HTTP MCP server checks a static Authorization header; configure Claude Code's headers.Authorization correctly; assert "Connected" via claude mcp get.

3a. [P0] HTTP static header auth: wrong key -\> FAILURE, not "needs authentication". This is the specific, non-obvious distinction from R01: a static headers.Authorization or headersHelper that gets 401/403 is reported as a connection FAILURE. A configured header that gets a 401 gives `✘ Failed to connect` with the 401 detail. Assert the exact status string, contrasted against test 3b.

3b. [P0] HTTP auth: missing key (a 401 with no configured header). No configured header gives `! Needs authentication`, the case D12/T4 needs. Assert the exact status string.

4\. [P0] Credential env var read as empty. Point headers.Authorization or the url at $ANTHROPIC_API_KEY (one of the names R01 lists as deliberately blanked) and confirm the value Claude Code actually sends is empty, not the real key -- i.e. prove the deny-list is real and use a differently-named var as the correct pattern (test 2).

5\. [P1] OAuth 401 on a server Claude IS logged into -\> refresh, reconnect, retry once, THEN mark. Not implemented: needs a scripted `claude mcp login` with a terminal and a fake authorization server, which does not fit the time box.

6\. [P2, observe only] Non-interactive mode cannot run the OAuth browser flow; with tool search on, the model is told the server's tools are unavailable until authorized (v2.1.196+). Capture one transcript showing this message; no further assertion.

7\. Merged into doc 20, test 3.

8\. [P1] First-connection transient retry. New HTTP server returns 503 on its first 1-2 connection attempts, then succeeds; assert the "up to 3 attempts" first-connect retry policy, and separately that an auth error or not-found is NOT retried this way.

9\. [P1] HTTP headers, legacy era. The HTTP fake logs `MCP-Protocol-Version` on every POST after `initialize`, and returns an `Mcp-Session-Id`. Assert the header equals the negotiated version, and the session id is echoed on every later POST.

10\. [P1] Project `.mcp.json` under `-p`. Put a marker server in the repo's `.mcp.json`. Run `-p` with and without `--strict-mcp-config`. Assert from the marker log: it started without any approval in the first run, and never started in the second.

11\. [P2, not implemented] `headersHelper`. Reason: in `-p` it runs only after trust is set by hand in the config file; the static-header tests cover the auth path.
