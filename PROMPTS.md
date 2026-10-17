# PROMPTS

The prompts given to AI tools, as files, in the order they were used. No
transcripts.

## How AI was used

1. **Research.** The public Claude Code docs and the MCP spec were read
   into two fact sheets (R01, R06); four MCP spec pages were saved as
   copies (R02 to R05).
2. **Plan as prompt files** for an AI build agent ("planning agent" below):
   docs 00 and 11 to 24, verbatim in `prompts/plan/`. PLAN.md is built
   from them.
3. **Plan review, 5 rounds.** Each round ran the review prompt
   (`prompts/plan-review/mcp-plan-review-prompt.md`) in a new session. It
   plays a panel of experts and writes a ranked list of fixes, which went
   back into the docs before the next round.
4. **Build loop.** An orchestrating Claude Code session ran the build in
   steps. For each step it wrote a Dev prompt and ran a Dev agent, then
   wrote a QA prompt and ran a QA agent that checked the Dev's work and
   reported findings by severity. Each QA's findings went into the next Dev
   prompt ("Fix first").
5. **Repo review and fix rounds.** After the build, a hiring-panel review
   prompt ran on the repo, twice. After each review, a repo-fix prompt was
   given to a new session, which ran Dev and QA agents in parallel units
   (rows 38 and 39).

## Who wrote what

- **Build prompts 01 to 19 were written by the orchestrating agent**, not
  by the candidate. The candidate wrote none of the code and none of their
  text.
- **Decisions that were the candidate's** (the chat messages behind them
  are in [The candidate's messages](#the-candidates-messages)):
  - The plan: its structure (one doc per topic, docs 11 to 23, every idea
    tagged P0/P1/P2, doc 24 as the handoff) and the plan-review prompt.
  - The Dev/QA loop (10-17 00:07).
  - The scope cut: doc 24 cut the build to 10 items, with question 2 and
    question 3 in depth. Written in the plan docs, not in a chat message.
  - The spend cap (10-17 00:58). The suite's own cap, `SUITE_BUDGET_USD`
    $5.00, sits inside it.
  - The no-defaults rule: no default parameter values, every argument
    passed by keyword, values as named constants. It comes from the
    candidate's global Claude Code instructions, which every session
    loaded, not from a chat message.
  - The logging rule (10-17 12:01 and 12:16). Build prompts 17 to 19
    turned it into code (`harness/check.py`).
  - The hiring-panel review of the repo (10-17 13:13).
- **Written by agents:** the code, the build prompts, and the first
  drafts of README.md, PLAN.md and this file (build step 7).

## The prompts, in order

| # | File | To whom | Purpose |
|---|---|---|---|
| 1 | `prompts/plan/00_START_HERE_—_read_this_first.md` | planning agent | Reading order for the plan folder |
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
| 36 | `prompts/18-qa-step8-test-logs-and-asserts.md` | QA | Check step 8: the logs, the Expected/Actual messages, no secret in the logs |
| 37 | `prompts/19-dev-step8b-log-fixes.md` | Dev | Fix the step 8 QA findings |
| 38 | `mcp-repo-review-prompt.md` (kept outside the repo) | reviewer | Hiring-panel review of the repo: a panel of experts scores it and ranks the fixes. Run twice, on 2026-10-17 |
| 39 | `mcp-repo-fix-prompt.md` (kept outside the repo) | orchestrating agent | Apply the fixes of the newest repo review. Given to a new Claude Code session after each review (twice: after review 1 and after review 2); each run used Dev and QA agents in parallel units |

R02 to R05 were given to the planning agent too, but they are copies of public
spec pages, so they are listed here and not copied:

| File (in the plan folder) | Source |
|---|---|
| `Documentation/R02_MCP_Spec_2025-11-25_—_Lifecycle.md` | https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle |
| `Documentation/R03_MCP_Spec_2025-11-25_—_Cancellation.md` | https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/cancellation |
| `Documentation/R04_MCP_Spec_2025-11-25_—_Transports_(stdio,_Streamable_HTTP).md` | https://modelcontextprotocol.io/specification/2025-11-25/basic/transports |
| `Documentation/R05_MCP_Spec_2026-07-28_—_Versioning_and_Compatibility.md` | https://modelcontextprotocol.io/specification/latest/basic/lifecycle |

## Launcher text

Prompts 01 to 04 were passed to the agents inline. From step 2 on, each
Dev and QA agent was started with one line that points to its prompt
file (N = the step, `<path>` = the file):

- Dev: ``You are the Dev agent for step N. Your full task is in this file; read it in full first and follow it exactly: <path>. Do not edit that file or any other file under `mcp-client-suite/prompts/`.``
  Step 7 added: ``(you may add the new folders `prompts/plan/` and `prompts/plan-review/` as the task says)``.
- QA: ``You are the QA agent for step N. Your full task is in this file; read it in full first and follow it exactly: <path>. Do not edit that file or any other file under `mcp-client-suite/`.``

Between steps, the orchestrating session pasted each QA finding into the
next Dev prompt ("Fix first") and each Dev report's claims into the next
QA prompt ("Dev's claims"); the prompt files are as sent.

## What was checked before copying

Every copied file (docs 00, 11 to 24, R01, R06, the review prompt) and
every build prompt was searched for `sk-ant`, `Bearer ` followed by a
value, the word "token" and e-mail addresses. No secret and no e-mail
address was found; the hits are "token" in its normal sense and the
`sk-ant` pattern named in prompt 15's own instructions.

## The candidate's messages

The chat messages in which the candidate made a decision, taken from the
session transcripts. Each is paraphrased: spelling fixed, meaning kept. Times are local (UTC+3). The plan docs were written and
revised outside these sessions; those chats are not listed.

### Session 1: plan review, round 1

Claude Code session `890dc2e7`, 2026-10-16 17:51 to 2026-10-16 17:51, 1
message: the line that runs the plan-review prompt on the plan folder.

### Session 2: plan reviews, rounds 2 to 5, and the docx-to-md conversion

Claude Code session `e231d4fc`, 2026-10-16 17:55 to 2026-10-16 21:46, 17
messages: the same review line at 17:55, 19:56 and 21:29, and short
requests for fix prompts, file paths and the conversion of the plan docs
from docx to md.

### Session 3: the build

Claude Code session `b8db9188`, 2026-10-17 00:05 to 2026-10-17 14:13
(active 00:05-00:58, 11:43-13:21, 13:45-14:13), 73 messages. This session wrote build prompts 01 to 19 and ran the Dev and
QA agents.

- 00:07 (paraphrased): "I am thinking of two agents, QA and Dev. They
  work through the plan docs in a loop: when one doc is done, go to the
  next one. Recommend what I should do. Don't assume; check."
- 00:58 (paraphrased): "Spend $20 if you need, but try not to be a
  spender; use the money wisely."
- 12:01 (paraphrased): "The log format should look like this:
  `11:58:01.34 2026-10-17 [DEBUG   ] runner.py:42 connect() - Connecting to server`"
- 12:16 (paraphrased): "The rule for logs: each test action has a log
  line. Each returned status has a log line. When you wait, log 'start
  waiting for <command>', and when the wait is done, 'waiting done, the
  response is ...'. The test tells what it did and what it got back for
  its request. Each assert explains itself: Expected: ... Actual: ..."
- 13:13 (paraphrased): "Look at the project; it is my home assignment for
  an interview. Collect the experts a reviewer needs and review it. The
  interview is for a senior automation engineer, the first hire and the
  future manager of the team. Improve the prompt; ask questions." This
  became the repo-review prompt (row 38).

The other 82 messages of the three sessions (91 in all) were short
steering and status lines (what is running, how much was spent, open the
report, set up git), plus one message that held the API key and one
paste of another tool's output, dropped; they are not listed.
