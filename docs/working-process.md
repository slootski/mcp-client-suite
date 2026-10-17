# Working process

How the suite was built with Claude Code, step by step. The prompts
themselves are in [PROMPTS.md](../PROMPTS.md) and `prompts/`.

## 1. Understand the project

- Started from the task mail (Bay, 2026-10-11): the five questions, Docker
  and git only, one command, the key in `ANTHROPIC_API_KEY`.
- Had Claude read the public sources (the Claude Code MCP docs, the
  changelog, the MCP spec) and write fact sheets that every later session
  read: R01 (Claude Code MCP facts for 2.1.296) and R06 (tool search, `-p`,
  pagination, progress). R02 to R05 are copies of MCP spec pages.
- Asked Claude to explain each part before building on it: the `claude`
  CLI, the `-p` stream, the MCP config, the connection flow.
- Checked each explanation against the public docs. Only checked facts went
  into the plan.

## 2. Split into topics

- One plan doc per test area: docs 11 to 23 (`prompts/plan/`).
  - 11: the harness (pinned version, env, flags, fake server, gate,
    known-defect rule, cost cap).
  - 12 to 23: one topic each, mapped to the five questions (question 1: 12,
    13; question 2: 14, 15, 18; question 3: 16, 17, 19 to 21; question 4:
    22; question 5: 23).
- Every idea is one line, tagged P0, P1 or P2.
- Doc 24 is the handoff: it cuts the build to 10 items, with questions 2
  and 3 in depth.
- `PLAN.md` is built from these docs.

## 3. Implement topic by topic

- An orchestrating Claude Code session ran the build in 8 steps, one or
  two topics per step.
- Each step had a Dev prompt and a QA prompt (`prompts/01-...md` to
  `prompts/19-...md`):
  - The Dev agent built the step.
  - The QA agent checked the Dev's work and reported findings by severity.
  - The QA findings went into the next Dev prompt as "Fix first".
- Steps: harness and status matrix; handshake and credentials; model-run
  harness and smoke; right tool and arguments; tool errors and crash; idle
  timeout and permissions; docs; logs and Expected/Actual asserts.

## 4. Validate what the report shows

- The QA agent of each build step ran the suite and checked its results.
- I also ran `./run.sh` myself, with the key, and read the outputs in
  `./artifacts/<run-id>/`:
  - `report.html` and `junit.xml`: pass, fail, xfail and skip, with reasons.
  - `cost.json`: spend per test, against the $5 suite cap.
  - `s-rates.json`: pass rates of the repeated model tests (at least 4 of
    5).
  - `secret-scan.json`: no file holds the API key or a test credential.
  - Per-test folders: wire logs, debug log, command transcripts.
- Checked that each pass rests on a real fact (the wire log of the fake
  server), not on the model's words.
- Checked that every known-defect xfail still fails for the documented
  reason.
- Wrote the measured numbers (time, cost, counts) into the docs from the
  real runs.

## 5. Review with an expert panel

The experts are roles that Claude plays in a review prompt. No human
reviewed the plan or the repo.

- **Plan review, 5 rounds** (`prompts/plan-review/mcp-plan-review-prompt.md`):
  - Each round ran in a new session.
  - A panel of 8 experts gave a verdict and a ranked list of fixes.
  - The fixes went back into the plan docs before the next round.
- **Repo review, 4 rounds** (`prompts/repo-review/mcp-repo-review-prompt.md`):
  - A 10-expert hiring panel, read-only, with one paid run of the suite.
  - It gave a verdict, strengths and risks per expert, the top 10 fixes,
    and questions for the call.
  - Verdict: hire after round 1, close to strong hire after round 4.
- **Fix rounds** (`prompts/repo-review/mcp-repo-fix-prompt.md`):
  - Each round ran in a new session, with Dev and QA agents in parallel
    units.
  - Each unit worked on its own `fix/*` branch (`fix/gate`, `fix/hygiene`,
    `fix/guards`, `fix/docs`, `fix/product`, `fix/harness`, `fix/docs2`).
  - The next review checked what was fixed and what was still open.

## 6. Commit and push

- The fix units worked on their own `fix/*` branches, which were merged
  when their QA check passed.
- I committed and pushed the result myself, to `master` on `origin`
  (`github.com:slootski/mcp-client-suite`).
