PRIORITY: P0 (infrastructure, not a test itself)

PURPOSE

Fix the knobs every other test relies on, so results are comparable across runs and across the two protocol eras.

PINNED ENV (unless a test explicitly varies one)

- Claude Code 2.1.296, installed at that exact version in the Dockerfile on a base image pinned by digest, with `DISABLE_AUTOUPDATER=1`. The suite stops at start if `claude --version` is not 2.1.296.

- MCP_PROTOCOL_NEGOTIATION=legacy for the bulk of the suite (deterministic initialize handshake). One dedicated handshake test runs with the variable unset (the user default). `auto` is a different value: it probes every server type.

- MCP_SDK_GENERATION unset (use the real default, v2) except where a test targets v1 behavior explicitly.

- ENABLE_TOOL_SEARCH=false for wire-level / determinism tests that need to see tools/call directly with no ToolSearch round trip in between. One dedicated test leaves tool search at its default (on) and confirms the tool is still reachable.

- MCP_TIMEOUT and MCP_TOOL_TIMEOUT set explicitly per test (never rely on the ~28h default in a hang test).

- Every run passes `--permission-mode default --allowedTools "mcp__<server>__*" --permission-prompts none`, runs as a non-root user, and never uses bypass mode.

- --output-format stream-json --verbose for every run so system/init, tool_use/tool_result and the final result event are all capturable as structured JSON.

- Each test gets a fresh `CLAUDE_CONFIG_DIR`. Servers come from `--mcp-config <file> --strict-mcp-config` (D12/T4 and D13 use `claude mcp add` inside that dir). Each run writes `run.json`: `claude --version`, image digest, model id, era seen (first message and `protocolVersion`), env pins, `total_cost_usd`. P0 wire tests run twice: `MCP_PROTOCOL_NEGOTIATION=legacy`, and unset. The unset run uses the same legacy fake, which answers `server/discover` at once with -32601, so it covers the default path for a legacy server (probe, fallback, legacy), and the fast reply avoids the slow connect behind the 7-day memory. The Q2 and Q3 asserts are the same in both runs.

- A known product defect is an expected failure that names the changelog line and the fixed version, for example `xfail(strict=True, reason='2.1.296 HTTP startup timeout, fixed 2.1.299, mcp-quickstart.md:356')`, so it fails once it starts to pass. Retries never hide a product failure, and every retry is in the report. A new failure that matches no known defect is reported as a candidate product bug, with its wire log.

TEST SERVER

- A small Python (or Node) stdio MCP server we fully control, passed with `--mcp-config` (D12/T4 and D13 use `claude mcp add`). Logs every request/notification it receives to a file with wall-clock timestamps, independent of what it replies on stdout.

- Implements: initialize, notifications/initialized, tools/list (paginated), tools/call, and (for the era test) server/discover.

- Deliberately scriptable: each test can tell it, via an env var or a control file, to behave normally, hang, crash, emit garbage, paginate, send list_changed, etc.

- Every model-driven test asserts from the server log exactly one `tools/call` per `tool_use` id in the stream, with the same name. Arguments are checked twice: server args equal `tool_use.input` (client fact, D), and `tool_use.input` equals the values fixed in the prompt (model fact, S). A 'must not call' check first proves that the server served `tools/list` and that the model tried (a `tool_use` exists). Otherwise the result is 'inconclusive', never 'pass'.

- Before any tool assert, the test reads `system/init` and requires each of its servers to be `connected`; otherwise it reports 'inconclusive' with the status it saw.

WHAT "DONE" LOOKS LIKE

- One command on a machine with only Docker and git: `./run.sh`, which runs `docker build` and then `docker run --rm -e ANTHROPIC_API_KEY`. Pin one model by full id (for example `claude-haiku-5-5`). Each `claude -p` run gets `--max-turns` and `--max-budget-usd` (for example 4 and 0.25). The suite adds up `total_cost_usd`, stops at a set total (for example $5), and prints it. The fakes log a hash and the length of each header and env value, never the value. Before saving artifacts, the harness checks that no file contains the key. Set the suite cap from one measured smoke run: count the model runs (tests times eras times repeats), print the cost per test, and set the cap with a margin, far below $50.

- pytest runs every implemented test; each test's wire log and stream-json transcript are saved as artifacts on failure.

- Each run writes `--debug-file` with `--debug=mcp`; the artifact scan covers it.
