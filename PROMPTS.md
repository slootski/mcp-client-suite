# PROMPTS

The prompts given to AI tools, as files, in the order they were used. No
transcripts.

## How AI was used

1. **Research.** The public Claude Code docs and the MCP spec were read
   into two fact sheets: R01 (Claude Code MCP facts, checked 2026-10-14 for
   2.1.296) and R06 (tool search, headless `-p`, spec pagination and
   progress). Four MCP spec pages were saved as copies (R02 to R05). The
   fact sheets are in this repo; the research itself is not a prompt file
   here.
2. **Plan as prompt files.** The plan was written as prompt files for an AI
   build agent (called "planning agent" in the table below): doc 00 (reading order), docs 11 to 23 (one topic each,
   every test idea tagged P0/P1/P2) and doc 24 (handoff: state, decisions,
   the 10 items to build). They are kept verbatim in `prompts/plan/`.
   PLAN.md is built from them.
3. **Plan review, 5 rounds.** Each round ran the review prompt
   (`prompts/plan-review/mcp-plan-review-prompt.md`) in a new session, with
   the plan folder as input. It plays a panel of experts and writes a
   ranked list of fixes. The fixes went back into docs 11 to 24 before the
   next round. After round 5, doc 24 trimmed the build to 10 items.
4. **Build loop.** An orchestrating Claude Code session ran the build in
   steps. For each step it wrote a Dev prompt, ran a Dev agent on it, then
   wrote a QA prompt and ran a QA agent that checked the Dev's work against
   that prompt and reported findings by severity. Each QA's findings went
   into the next Dev prompt ("Fix first"). A failed QA (step 1) got its own
   fix and re-check prompts (03, 04). Both agents ran the suite in Docker
   with a budget per step.
5. **The suite's own model calls** use `claude-haiku-5-5`
   (`harness/constants.py`, `MODEL_ID`), with `--max-turns 4` and
   `--max-budget-usd 0.25` per run.
6. **The human's own messages** to the orchestrating session were short
   steering lines in chat (the order of work, scope cuts, the spend cap,
   "go on"), not task specs. They are not listed here: every task an agent
   worked from is one of the files below, as sent.

## The prompts, in order

| # | File | To whom | Purpose |
|---|---|---|---|
| 1 | `prompts/plan/00_START_HERE_—_read_this_first.md` | planning agent | Reading order for the plan folder; do not start before reading all of it |
| 2 | `prompts/plan/11_Harness_and_Pinned_Config_—_MCP_Client.md` | planning agent | Harness: pinned version, env, flags, fake server, gate, known-defect rule, cost cap |
| 3 | `prompts/plan/12_Connection_and_Handshake_—_MCP_Client.md` | planning agent | Question 1: handshake, era probe, status strings (9 ideas) |
| 4 | `prompts/plan/13_Auth_and_Remote_Transport_—_MCP_Client.md` | planning agent | Question 1: auth, headers, credential variables, remote transport (11 ideas + 1 merged) |
| 5 | `prompts/plan/14_Tool-Call_Smoke_—_MCP_Client.md` | planning agent | Question 2: round trip, tool search, tool names |
| 6 | `prompts/plan/15_Right_Tool_and_Right_Arguments_—_MCP_Client.md` | planning agent | Question 2: right tool, argument and result fidelity |
| 7 | `prompts/plan/16_Tool_Errors_—_isError_vs_Protocol_Error_—_MCP_Client.md` | planning agent | Question 3: `isError` vs JSON-RPC error |
| 8 | `prompts/plan/17_Junk_on_stdout_—_MCP_Client.md` | planning agent | Question 3: stdout and stderr hygiene |
| 9 | `prompts/plan/18_Pagination_and_list_changed_—_MCP_Client.md` | planning agent | Question 2: pagination, `list_changed` |
| 10 | `prompts/plan/19_Timeouts,_Hangs_and_Cancellation_—_MCP_Client.md` | planning agent | Question 3: idle timeout, progress, cancellation |
| 11 | `prompts/plan/20_Crash_and_Reconnect_—_MCP_Client.md` | planning agent | Question 3: crash, restart, reconnect, shutdown |
| 12 | `prompts/plan/21_Structural_Garbage_—_Wrong_id___Bad_Envelope_—_MCP_Client.md` | planning agent | Question 3: wrong ids, bad envelopes |
| 13 | `prompts/plan/22_Determinism_—_MCP_Client.md` | planning agent | Question 4: D vs S, repeats, flake policy |
| 14 | `prompts/plan/23_Limits_and_Other_Checks_—_MCP_Client.md` | planning agent | Question 5: limits, config errors, hooks, permission rules, credentials |
| 15 | `prompts/plan/24_Handoff_—_Bay_MCP_Assignment.md` | planning agent | State, the 10 items to build, next steps |
| 16 | `prompts/plan/Documentation/R01_Claude_Code_—_MCP_Facts_(checked_2026-10-14,_for_2.1.296).md` | planning agent (reference) | Fact sheet: Claude Code MCP facts for 2.1.296 |
| 17 | `prompts/plan/Documentation/R06_Claude_Code_MCP_Facts_—_Tool_Search,_Headless,_Spec_Pagination_Progress_(addendum).md` | planning agent (reference) | Fact sheet addendum: tool search, `-p`, pagination, progress |
| 18 | `prompts/plan-review/mcp-plan-review-prompt.md` | reviewer | Plan review, run 5 times (rounds 1 to 5) |
| 19 | `prompts/01-dev-setup-and-status-matrix.md` | Dev | Step 1: harness, Dockerfile, `run.sh`, fakes, status matrix (D12/T4, D13/T3) |
| 20 | `prompts/02-qa-setup-and-status-matrix.md` | QA | Check step 1 |
| 21 | `prompts/03-dev-fix-step1-after-qa.md` | Dev | Fix the step 1 QA findings (bare 401 case, no bind mount, ...) |
| 22 | `prompts/04-qa-recheck-step1.md` | QA | Re-check the step 1 fixes |
| 23 | `prompts/05-dev-step2-handshake-and-credentials.md` | Dev | Step 2: handshake (D12/T1, T3), credentials (D13/T4, D23/T11) |
| 24 | `prompts/06-qa-step2-handshake-and-credentials.md` | QA | Check step 2 |
| 25 | `prompts/07-dev-step3-model-harness-and-smoke.md` | Dev | Step 3: model-run harness, cost ledger, D14/T1, T2, D23/T2 |
| 26 | `prompts/08-qa-step3-model-harness-and-smoke.md` | QA | Check step 3 |
| 27 | `prompts/09-dev-step4-right-tool-args-determinism.md` | Dev | Step 4: D15/T1-T3, repeat harness, flake policy |
| 28 | `prompts/10-qa-step4-right-tool-args-determinism.md` | QA | Check step 4 |
| 29 | `prompts/11-dev-step5-tool-errors-and-crash.md` | Dev | Step 5: D16/T1, T2, D20/T1, plus the step 4 fix |
| 30 | `prompts/12-qa-step5-tool-errors-and-crash.md` | QA | Check step 5 |
| 31 | `prompts/13-dev-step6-timeouts-and-permissions.md` | Dev | Step 6: D19/T1+T3, D23/T9, T10, plus the step 5 fix |
| 32 | `prompts/14-qa-step6-timeouts-and-permissions.md` | QA | Check step 6 |
| 33 | `prompts/15-dev-step7-docs.md` | Dev | Step 7: step 6 fixes, PLAN.md, README.md, PROMPTS.md, repo hygiene |
| 34 | `prompts/16-qa-step7-final.md` | QA | Final check as the reviewer: fresh-clone run, docs vs code |
| 35 | `prompts/17-dev-step8-test-logs-and-asserts.md` | Dev | Step 8: every test logs its actions, waits and results; every assert in Expected/Actual form (`harness/check.py`) |
| 36 | `prompts/18-qa-step8-test-logs-and-asserts.md` | QA | Check of step 8: the logs, the Expected/Actual messages, same outcomes, no secret in the logs |

R02 to R05 were given to the planning agent too, but they are copies of public
spec pages, so they are listed here and not copied:

| File (in the plan folder) | Title | Source |
|---|---|---|
| `Documentation/R02_MCP_Spec_2025-11-25_—_Lifecycle.md` | MCP Specification 2025-11-25: Lifecycle | https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle |
| `Documentation/R03_MCP_Spec_2025-11-25_—_Cancellation.md` | MCP Specification 2025-11-25: Cancellation | https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/cancellation |
| `Documentation/R04_MCP_Spec_2025-11-25_—_Transports_(stdio,_Streamable_HTTP).md` | MCP Specification 2025-11-25: Transports | https://modelcontextprotocol.io/specification/2025-11-25/basic/transports |
| `Documentation/R05_MCP_Spec_2026-07-28_—_Versioning_and_Compatibility.md` | MCP Specification (latest, revision 2026-07-28): Versioning and Compatibility | https://modelcontextprotocol.io/specification/latest/basic/lifecycle |

## Launcher text

Prompts 01 to 04 were passed to the agents inline. From step 2 on, each
Dev and QA agent was started with one line that points to its prompt
file (N = the step, `<path>` = the file):

- Dev: ``You are the Dev agent for step N. Your full task is in this file; read it in full first and follow it exactly: <path>. Do not edit that file or any other file under `mcp-client-suite/prompts/`.``
  Step 7 added: ``(you may add the new folders `prompts/plan/` and `prompts/plan-review/` as the task says)``.
- QA: ``You are the QA agent for step N. Your full task is in this file; read it in full first and follow it exactly: <path>. Do not edit that file or any other file under `mcp-client-suite/`.``

Between steps, the orchestrating session pasted each QA finding into the
next Dev prompt as a "Fix first" section, and each Dev report's claims
into the next QA prompt as "Dev's claims". Those edits are in the prompt
files as sent.

## What was checked before copying

Every copied file (docs 00, 11 to 24, R01, R06, the review prompt) and
every build prompt was searched for `sk-ant`, `Bearer ` followed by a
value, the word "token" and e-mail addresses. No secret and no e-mail
address was found. The hits are the word "token" in its normal sense
(model tokens, OAuth token refresh) and the `sk-ant` pattern named in
prompt 15's own instructions. Absolute home paths (`/Users/islootski/...`)
stay as they were.
