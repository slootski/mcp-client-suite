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
6. **The candidate's own messages** to these sessions are listed
   verbatim in [The candidate's own prompts](#the-candidates-own-prompts)
   below. Most are short steering lines; they are all the candidate typed
   into these sessions.

## Who wrote what

- **Build prompts 01 to 19 were written by the orchestrating agent**, not
  by the candidate. The candidate wrote none of their text. The
  candidate's part in the build is the messages listed below.
- **Decisions that were the candidate's:**
  - The plan: its structure (one doc per topic, docs 11 to 23, every idea
    tagged P0/P1/P2, doc 24 as the handoff) and the plan-review prompt
    that was run 5 times on it.
  - The Dev/QA loop: two agents, Dev then QA, step by step (session 3,
    10-17 00:07).
  - The scope cuts: doc 24 cut the build to 10 items, with question 2 and
    question 3 in depth.
  - The spend cap: "spend 20$ if you need, but try not to be a spender"
    (session 3, 10-17 00:58). The suite's own cap, `SUITE_BUDGET_USD`
    $5.00, sits inside it.
  - The no-defaults rule: no default parameter values, every argument
    passed by keyword, values as named constants. It comes from the
    candidate's global Claude Code instructions, which every session
    loaded, not from a chat message.
  - The logging rule: every action, returned status and wait is logged,
    and every assert reads `Expected: ... Actual: ...` (session 3, 10-17
    12:01 and 12:16). Build prompts 17 to 19 turned it into code.
- **Written by agents:** the code, the build prompts, and the first
  drafts of README.md, PLAN.md and this file (build step 7).

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
| 37 | `prompts/19-dev-step8b-log-fixes.md` | Dev | Fix the step 8 QA findings: less log noise, the last asserts in Expected/Actual form, missing step lines |
| 38 | `mcp-repo-fix-prompt.md` (kept outside the repo) | orchestrating agent | Apply the fixes of the hiring-panel repo review: run-level gate, secret handling, findings wording, the candidate's own prompts, the time spent. Given by the candidate to a new Claude Code session, which ran a Dev and a QA agent per wave |

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

## The candidate's own prompts

Every chat message the candidate typed into the Claude Code sessions of
this work, verbatim, typos kept, in order. Taken from the session
transcripts: user messages with plain text only. Left out: tool results,
system and command blocks, agent hand-backs, and the summaries Claude
Code writes when a session is compacted (none of these were typed by the
candidate). Changes: one message held the API key and is dropped; one
work e-mail address is removed; one pasted `run.json` is replaced by a
note. A few messages are about another project that ran in parallel
(`itbr`); they are kept, since they are part of the same sessions. The
plan docs 00 and 11 to 24 were written and revised outside these Claude
Code sessions (session 2 shows the review fixes being copied out "to
claude"); those chats are not listed. The docs as used are in
`prompts/plan/`. This repo-fix session (row 38) is not listed here.

### Session 1: Plan review, round 1

Claude Code session `890dc2e7`, 2026-10-16 17:51 to 2026-10-16 17:51 (local time, UTC+3), 1 message(s).

- 10-16 17:51: `Read prompts/mcp-plan-review-prompt.md. Follow everything below its first --- line. Inputs: PLAN = ~/Documents/02-Personal/mcp-client-testing/MCP-Client-Testing/ ; REPO = empty ; OUT = the default.`

### Session 2: Plan reviews, rounds 2 to 5, and the docx-to-md conversion of the plan

Claude Code session `e231d4fc`, 2026-10-16 17:55 to 2026-10-16 21:46 (local time, UTC+3), 17 message(s).

- 10-16 17:55: `Read prompts/mcp-plan-review-prompt.md. Follow everything below its first --- line. Inputs: PLAN = ~/Documents/02-Personal/mcp-client-testing/MCP-Client-Testing/ ; REPO = empty ; OUT = the default.`
- 10-16 18:34: `how to run the fix revew?`
- 10-16 18:35: `copy to clip ill past to claude`
- 10-16 18:36: `print the revwe in short points to screen`
- 10-16 19:04: `copy step 2 to clip`
- 10-16 19:56: `Read prompts/mcp-plan-review-prompt.md. Follow everything below its first --- line. Inputs: PLAN = ~/Documents/02-Personal/mcp-client-testing/MCP-Client-Testing/ ; REPO = empty ; OUT = the default.`
- 10-16 20:11: `copy to clip promt for claude to fix the revew demends`
- 10-16 21:01: `did you run the verefication`
- 10-16 21:29: `Read prompts/mcp-plan-review-prompt.md. Follow everything below its first --- line. Inputs: PLAN = ~/Documents/02-Personal/mcp-client-testing/MCP-Client-Testing/ ; REPO = empty ; OUT = the default.`
- 10-16 21:34: `how critical thery are`
- 10-16 21:35: `give me the the link to the documents`
- 10-16 21:35: `paht`
- 10-16 21:36: `what is the test plan to implement`
- 10-16 21:38: `full paht to #1`
- 10-16 21:39: `would it easer to cluade to read docx or md file?`
- 10-16 21:39: `convert the docx files to md and rplace the spaces to _`
- 10-16 21:46: `where are the new md file`

### Session 3: The build: the orchestrating session that wrote build prompts 01-19 and ran the Dev and QA agents

Claude Code session `b8db9188`, 2026-10-17 00:05 to 2026-10-17 14:13 (local time, UTC+3), 73 message(s).

- 10-17 00:05:

  ```text
   i have a task for hoem assiment
  ```
- 10-17 00:07:

  ```text
  i thing of 2 agents - qa and dev
  and tye will run in documentation in loop - ones dock is finish 
  going to next one
  
  This is the home assimet:
  /Users/islootski/Documents/02-Personal/mcp-client-testing/MCP-Client-Testing/
  
  please recomed what should id do.
  dont assume check
  ```
- 10-17 00:10: `list what you need me to install`
- 10-17 00:14: `check if you missing somthing to install?`
- 10-17 00:26: `check now`
- 10-17 00:27: `check now, i allow you to compoit what is missing`
- 10-17 00:28: `skip the login to github for now`
- 10-17 00:30: `go`
- 10-17 00:31: `use the api key for itbr from my_itbr`
- 10-17 00:34:

  ```text
  what key you need?
  where can i find it?
  ```
- 10-17 00:35: `can you get do it for me from ?`
- 10-17 00:37: `look on the screen now, what should i do?`
- 10-17 00:42: `look at my screen`
- 10-17 00:42: `what now?`
- 10-17 00:46: `look right now, what you see with the auto reload`
- 10-17 00:47: `no`
- 10-17 00:47: `now`
- 10-17 00:51: *[dropped: this message held the API key]*
- 10-17 00:51: `what to do now`
- 10-17 00:54: `look at the key`
- 10-17 00:54: `now the key is in`
- 10-17 00:54: `now the key is in ~/.config/bay-mcp/key`
- 10-17 00:56: `is there anything you need? can i go sleep?`
- 10-17 00:56: `go on without me`
- 10-17 00:58:

  ```text
  spend 20$ if you need, but try not to be a spender - use the money wizly
  good night
  ```
- 10-17 09:16: `go on - dont stop for qastions`
- 10-17 11:43: `how much did we spend so far`
- 10-17 11:44: `how much time left?`
- 10-17 11:45: `how much time left?`
- 10-17 11:46: `what are you doing in one line>?`
- 10-17 11:46: `what are you working on?`
- 10-17 11:47: `i need to creat repor for my assing did you created it?`
- 10-17 11:47: `did you generated the code?`
- 10-17 11:48: `are you using pytest?`
- 10-17 11:48: `run all test show me pytest html report`
- 10-17 11:52: `when done ipen it`
- 10-17 11:55: `i open passed test what i see is No log output captured.`
- 10-17 11:56: `does the has logger - he pytest project ?`
- 10-17 12:01: `log format should look like that: 11:58:01.34 2026-10-17 [DEBUG   ] runner.py:42 connect() - Connecting to server`
- 10-17 12:16:

  ```text
  the rool for logs is the followng:
  each test  action should have log 
  each status return staus should have log
  when you wait  - log like start waitiong for ...command..   when the waiting is done -> waiting doen the responce is...
  the genaral idia is that the test tell what did he did and what did it recive for his requast
  the assertion should be self explanagle like Expected:... Acutioal
  ```
- 10-17 12:35: `is anygihg running?`
- 10-17 12:35: `how much left?`
- 10-17 12:35: `can you parallize the work?`
- 10-17 12:39: `go on`
- 10-17 12:42: `give status`
- 10-17 12:47: `what is done`
- 10-17 12:49: `what is running¿`
- 10-17 12:50: `you are working on home assingmet or itbr?`
- 10-17 12:50: *[a pasted `run.json` from one test's artifacts with the question "what does this big json mand:"; the JSON is omitted]*
- 10-17 12:52: `1`
- 10-17 12:53: `give me a path to python project`
- 10-17 12:53: `full`
- 10-17 12:57: `can you open ?`
- 10-17 12:58: `run git init and add gitigrnore with all relevat parts`
- 10-17 12:59: `create fist commit with "Good luch!!!" mesate`
- 10-17 13:01: `i need you to push it to gihub mail iliasltski@gmail.com`
- 10-17 13:04:

  ```text
  i told you once:
  this is my work mac so mainly must work with [work e-mail address removed]
  in the back ground it should have the option to work with my gmail as well and you set it to work
  check convrsations
  ```
- 10-17 13:05: `check with it`
- 10-17 13:06: `done`
- 10-17 13:07: `ok`
- 10-17 13:13:

  ```text
  i need you to look at the project, it is my homeassinmet for intervew.
  i need you to go over project collect experteeds you need to do a  revewer 
  it is intervew for automation senior engenneer, fist man an futur manage of the team
  
  imporve the pormt 
  ask qastions
  ```
- 10-17 13:16: `make it so it will run from vanila claude`
- 10-17 13:18: `is it ready?`
- 10-17 13:21: `how much left?`
- 10-17 13:45: `does the score followied with revew?`
- 10-17 13:47: `what is the best way to run the revew fix?`
- 10-17 14:10: `give me cmd to clip to run ther revew fixes`
- 10-17 14:10: `will vanila claude know how to do that?`
- 10-17 14:11: `-`
- 10-17 14:11:

  ```text
  ⏺ The P2 screen QA is still in its long browser test run, so I'm waiting on four screen QA agents (P2, P3, P5, P6a). All develop
  quote>
  ```
- 10-17 14:12: `no session strted - give me full cmd`
- 10-17 14:12: `give me to clip full cmd that starts with cd ...`
- 10-17 14:13: `how much time it sould run?`
