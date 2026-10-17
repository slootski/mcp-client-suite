You are the Dev agent for a take-home assignment: an automated black-box test suite for the MCP client inside Claude Code 2.1.296. This is step 1 of a loop. A QA agent will check your work after you finish. Build only what this prompt asks.

## Where things are

- Code folder (create files here): `/Users/islootski/Documents/02-Personal/mcp-client-testing/mcp-client-suite/`. It is NOT a git repo; do not run `git init`.
- The plan (read-only, do not edit): `/Users/islootski/Documents/02-Personal/mcp-client-testing/MCP-Client-Testing/`
- The task mail: `/Users/islootski/Documents/02-Personal/mcp-client-testing/bay-home-assignment.md`
- Downloaded public docs (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/reference/` (Claude Code docs in `claude-code-docs/`, incl. `mcp.md` and the changelog; MCP spec in `mcp-spec-2025-11-25/` and `mcp-spec-2026-07-28/`).
- Fact sheets (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/notes/`

## Read first, in full, before writing anything

1. The task mail.
2. Plan docs `00`, `24`, `11`, `12`, `13`, and test 2 of `23` in `MCP-Client-Testing/`.
3. `Documentation/R01...` and `Documentation/R06...`.
4. The status-string and `claude mcp list` / `claude mcp get` parts of `reference/claude-code-docs/` (search for "Needs authentication", "Failed to connect", "Connected").

## Scope of this step

A. The shared setup from doc 11 (only what this step needs, built so later tests can reuse it):
- `Dockerfile`: base image pinned by a multi-arch index digest (so it resolves on both arm64 and amd64), Python 3 + pytest + pytest-timeout, Node, `npm install -g @anthropic-ai/claude-code@2.1.296`, `DISABLE_AUTOUPDATER=1`, runs as a non-root user.
- `run.sh`: the one command. `docker build`, then `docker run --rm -e ANTHROPIC_API_KEY` (the key may be unset: the free tests must still run). Exit code = pytest exit code. Artifacts go to a host folder (`./artifacts/`) mounted into the container.
- pytest config: markers `free` (no model call) and `model` (needs the key); `--junitxml`; a per-test timeout (e.g. 120 s) and a whole-run cap.
- A version gate: the session stops at start if `claude --version` is not `2.1.296`.
- A fresh `CLAUDE_CONFIG_DIR` per test.
- A stdio fake MCP server in Python that we fully control: implements `initialize`, `notifications/initialized`, `tools/list`, `tools/call`, and answers `server/discover` with JSON-RPC error -32601. It logs every message it receives to a JSONL file with wall-clock timestamps, separate from stdout. Its behavior is chosen by env var or control file (this step needs: `normal`, `exit_at_start`). For env values and headers it logs only a hash and the length, never the value.
- A small HTTP fake MCP server (JSON replies only, no SSE): `initialize`, `tools/list`, and a scripted auth check on the `Authorization` header (right key -> normal; wrong or missing key -> HTTP 401). It logs every request the same way.
- A per-test `run.json` with: `claude --version`, the env pins used, and the test id.
- An artifact scan: before artifacts are kept, check that no file contains the value of `ANTHROPIC_API_KEY` (when set).

B. One test item: D12/T4 + D13/T3, the `claude mcp list` / `claude mcp get` status matrix. Marker `free`. Servers are added with `claude mcp add` inside the fresh config dir. Cases:
1. healthy stdio fake -> `Connected`
2. stdio fake that exits at start -> `Failed to connect`
3. HTTP fake, correct static `Authorization` header -> `Connected`
4. HTTP fake, wrong static header (gets 401) -> `Failed to connect` with the 401 detail (doc 13 test 3a)
5. HTTP fake, no header configured (gets 401) -> `Needs authentication` (doc 13 test 3b)

Use the exact status strings from the docs. For every case, also assert from the fake's own log what the client actually sent (for example: `initialize` reached the fake in cases 1 and 3; the 401 cases logged the request). A status string alone is a weak oracle. Record the first message the client sent to each stdio fake (`server/discover` or `initialize`).

Leave out: the D23/T2 variant, every other test, PLAN.md, README.md, PROMPTS.md. They come in later steps.

## Rules

- No default parameter values, anywhere in the code. Every function and method takes all its parameters from the caller, passed as keyword arguments. No `x=None`, no `x or 5`, no `.get(key, fallback)`. A value used in many places becomes a named constant, passed in explicitly at each call site. This includes pytest fixtures, helpers and the fakes' CLIs.
- Black-box only: public docs, no Claude Code source.
- Never print, log or save a secret value.
- Docker CLI path: run `export PATH="$HOME/.docker/bin:$PATH"` before docker commands. Docker Desktop is running; the host is arm64.
- Run the suite for real with `./run.sh` and make it pass. Then build once with `--platform linux/amd64` to prove the image resolves there too (running it under emulation is optional).
- If a doc fact turns out wrong on 2.1.296 (for example a status string differs), do not bend the test to pass: report it, quote what you saw, and make the test assert what the docs say, marked as an expected failure with the reason.

## Report back (keep it short, under 400 words)

- Files created (paths).
- The exact commands you ran and their results (pass/fail counts, wall time).
- The exact status strings and the first client message you observed per case, quoted.
- Answers to these open questions, from what you observed: does `claude mcp list` actually connect to the servers (did `initialize` reach the fakes)? Does it need an API key or login?
- Anything that differs from the plan, and anything you could not do.
