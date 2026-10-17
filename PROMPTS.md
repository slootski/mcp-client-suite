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
   prompt ran on the repo. After each review, a repo-fix prompt was given
   to a new session, which ran Dev and QA agents in parallel units (rows
   38 and 39).
6. **Final check before sending.** One more session (Session 4 below)
   ran the suite the way the task mail asks, added the host check to
   `run.sh` (exit 16) with its test, wrote
   [docs/working-process.md](docs/working-process.md), and ran the full
   suite from a fresh clone.

## Who wrote what

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
  - The final session (10-17 20:26 to 21:40): `master` as the project
    branch, the host check in `run.sh`, the working-process doc, and the
    last run before sending.
- **Written by agents:** the code, the build prompts 01 to 19, the Dev
  and QA briefs of the fix rounds (not kept in the repo), and every
  version of the docs (README.md, PLAN.md, this file, `docs/`,
  observations.md).

## The prompts, in order

| # | File | To whom | Purpose |
|---|---|---|---|
| 1-15 | `prompts/plan/00_START_HERE_—_read_this_first.md` and docs 11 to 24 | planning agent | 00: reading order. 11: the harness (pinned version, env, flags, fake server, gate, known-defect rule, cost cap). 12 to 23: one test area each, every idea on one line (question 1: 12, 13; question 2: 14, 15, 18; question 3: 16, 17, 19 to 21; question 4: 22; question 5: 23). 24: the handoff, with the 10 items to build |
| 16-17 | `prompts/plan/Documentation/R01_...md`, `R06_...md` | planning agent (reference) | Fact sheets: Claude Code MCP facts for 2.1.296; an addendum on tool search, `-p`, pagination, progress |
| 18 | `prompts/plan-review/mcp-plan-review-prompt.md` | reviewer | Plan review, run 5 times |
| 19-37 | `prompts/01-...md` to `prompts/19-...md` | Dev (odd numbers) and QA (even numbers) | The build in 8 steps, each a Dev prompt and a QA check; the file names say the step. 1: harness, Dockerfile, `run.sh`, fakes, status matrix (01-04, with one fix and re-check). 2: handshake, credentials. 3: model-run harness, cost ledger, smoke. 4: right tool, arguments, repeats, flake policy. 5: tool errors, crash. 6: idle timeout, permissions. 7: the docs, then a final check as the reviewer from a fresh clone. 8: a log line for every action, wait and result, every assert as Expected/Actual (17-19, with one fix) |
| 38 | `prompts/repo-review/mcp-repo-review-prompt.md` | reviewer | Hiring-panel review of the repo: a panel of experts scores it and ranks the fixes. Run after the build and after each fix round |
| 39 | `prompts/repo-review/mcp-repo-fix-prompt.md` | orchestrating agent | Apply the fixes of the newest repo review. Given to a new Claude Code session after each review; each run used Dev and QA agents in parallel units |

R02 to R05, also given to the planning agent, are copies of public MCP
spec pages (2025-11-25 lifecycle, cancellation and transports; 2026-07-28
versioning), so they are not copied here.

## Launcher text

Prompts 01 to 04 were passed to the agents inline. From step 2 on, each
agent got one line: ``You are the Dev [QA] agent for step N. Your full task
is in this file; read it in full first and follow it exactly: <path>.``,
plus the files it must not edit. Between steps, the orchestrating session
pasted each QA finding into the next Dev prompt ("Fix first") and each Dev
report's claims into the next QA prompt; the prompt files are as sent.

## What was checked before copying

Every copied file (docs 00, 11 to 24, R01, R06, the three review and fix
prompts) and every build prompt was searched for `sk-ant`, `Bearer `
followed by a value, the word "token" and e-mail addresses. No secret was
found; the hits are "token" in its normal sense and the `sk-ant` pattern
named in the prompts' own rules. One e-mail address, in the repo-fix
prompt, was replaced with `[e-mail address removed]`; the `noreply`
address of the commit trailer was kept.

## The candidate's messages

The chat messages in which the candidate made a decision, taken from the
session transcripts. Each is paraphrased: spelling fixed, meaning kept.
Times are local (UTC+3). The plan docs were written and revised outside
these sessions; those chats are not listed.

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
(active 00:05-00:58, 11:43-13:21, 13:45-14:13), 73 messages. This session
wrote build prompts 01 to 19 and ran the Dev and QA agents.

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

### Session 4: final check before sending

Claude Code session `8aadc9ce`, 2026-10-17 20:25 to 2026-10-17 21:53, 27
messages. This session ran the suite as the task mail asks, made the
last changes, and ran the final check. It used no prompt file; the
messages below were the prompts.

- 20:26 (paraphrased): "Find the mail from Boris that says how the
  project should run, and start the project the way he asks."
- 20:54 (paraphrased): "Create a doc that describes the working process:
  going over the project with Claude to understand how it works,
  splitting it into topics, implementing topic by topic, validating what
  the report shows, running the review prompt with experts, and finally
  committing and pushing. Ask me questions." This became
  [docs/working-process.md](docs/working-process.md).
- 21:01 (paraphrased): "`master` is the branch of the project; delete
  `main`."
- 21:10 (paraphrased): "Go over the packages and programs the run needs,
  and make sure the script tells the user what to install, or that the
  project cannot run." This became the host check in `run.sh` (exit 16)
  and `tests/test_run_sh_host_check.py`.
- 21:36 (paraphrased): "What can you do about what can still go wrong on
  a plain Mac?" This became the amd64 run under emulation and the "On a
  new machine" notes in the README.
- 21:40 (paraphrased): "Run the last test before sending." This was the
  full run from a fresh clone, run `20261017T184642Z-2379`.

The four sessions hold 118 messages. 15 are above: the 4 lines that ran
the plan-review prompt and the 11 decisions. The other 103 were short
steering, status and how-it-works questions (what is running, how much
was spent, open the report, set up git, how a run works), plus two
messages that held the API key and one paste of another tool's output,
dropped; they are not listed.
