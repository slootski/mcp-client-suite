HANDOFF -- read this first when resuming.

WHERE THINGS ARE

- This folder:

- Documentation/ -- R01 (curated facts, 2026-10-14) + R06 (addendum: tool search, headless/-p, spec pagination/progress/stdio-era-probe, 2026-10-14) + R02-R05 (verbatim MCP spec pages: lifecycle, cancellation, transports, versioning).

- Linear test-idea docs, current set: 11 Harness, 12 Connection and Handshake, 13 Auth and Remote Transport, 14 Tool-Call Smoke, 15 Right Tool and Right Arguments, 16 Tool Errors, 17 Junk on stdout, 18 Pagination and list_changed, 19 Timeouts/Hangs/Cancellation, 20 Crash and Reconnect, 21 Structural Garbage, 22 Determinism, 23 Limits and Other Checks, 24 (this doc).

STATE AS OF 2026-10-14 EVENING

- Re-read the full docs (tool search section, headless/-p reference, MCP spec pagination/progress/tools pages, and the 2026-07-28 stdio backward-compatibility section) and rewrote the entire test plan around confirmed facts instead of guesses.

- Key correction carried over from the previous session: 2.1.296 includes the v2.1.292 stdio protocol-negotiation rollout, so the client may probe server/discover before falling back to initialize -- doc 12 tests this directly instead of assuming legacy-only.

- Key new facts folded in: tool search is ON by default (affects doc 14 test 2, doc 11's env pinning); MCP tool description limit is 4096/16384 chars as of 2.1.296 (was 2048); -p's system/init event exposes mcp_servers/mcp_server_errors/plugins/capabilities for CI gating (doc 23 test 2); progress notifications reset the idle timeout but never the ~28h wall-clock cap (doc 19 test 2, the clearest determinism demo in the suite); tools/call has two distinct error channels, protocol error vs isError:true (doc 16).

- Gaps closed vs the old plan: added a partial-line-no-newline stdout case (doc 17 test 2), a chained tool-call test (doc 15 test 4), and a dedicated determinism doc (22) with an explicit flake policy instead of leaving Area 4 implicit.

- Removed: the OAuth browser-flow test (can't run under -p, now just one observe-only line in doc 13).

OPEN ITEMS / NOT YET DECIDED

- Decided: Q2 and Q3 in depth; Q1 by free `claude mcp` tests. Build these 10 and mark the rest 'not implemented' with a reason: D12/T1+T3; D12/T4+D13/T3 (status matrix, with a 401 and no configured header, and D23/T2 as a variant); D13/T4+D23/T11; D14/T1 (T2 as a variant); D15/T1; D15/T2+T3; D16/T1+T2; D19/T1+T3; D20/T1; D23/T9 (T10 as a variant). HTTP fake: one small server, JSON replies only, enough for `initialize`, `tools/list` and a scripted 401.

- Not started: any actual code. No MCP test server, no pytest suite, no Dockerfile, no PLAN.md/PROMPTS.md/README.md yet.

- Residual doc gap: Closed 2026-10-16: env-vars.md:484, 495, 497, 499 and 500 match R01.

NEXT STEPS

1\. Build: MCP test server (stdio, scriptable misbehavior), pytest harness, Dockerfile + one-command entrypoint, PLAN.md: one line per test idea in docs 11 to 23: `id, question, what it checks, oracle, D or S, priority, status`. Status is `implemented: tests/<file>::<name>` or `not implemented: <reason>`. PROMPTS.md: the prompts given to AI tools, verbatim, no transcripts: docs 00 and 11 to 24, R01 and R06, the plan review prompt, and each build prompt; R02 to R05 are copied spec pages, so list them by title and source URL. README.md: the one command, the choices, a table from each requirement in the mail to the file or test that meets it, and what CI would need. CI section: a JUnit report (`--junitxml`), `free` and `model` test markers (free on every change, model nightly or before a release), the key as a CI secret, the budget guard, a quarantine list with an owner and an end date, Docker layer cache, per-test ports and config dirs, and a run on the next Claude Code version so the expected failures flip.
