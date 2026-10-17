# Prompt: apply the newest hiring-panel review to the MCP client test suite

## How to use

Start a new, plain Claude Code session in `/Users/islootski/Documents/02-Personal/mcp-client-testing/` (or run `prompts/run-fix.sh`). Paste everything below the line. It is self-contained and can be run again after every review.

---

Apply the newest hiring-panel review to a take-home repo, then prove the scores moved. Follow sections 0–7. Do not ask questions; decide, and list each decision in your final report.

## 0. Inputs

- `REPO` = `/Users/islootski/Documents/02-Personal/mcp-client-testing/mcp-client-suite/` (git, branch `main`, remote `origin` = `git@github.com:slootski/mcp-client-suite.git`, private).
- `REVIEW` = the newest `/Users/islootski/Documents/02-Personal/mcp-client-testing/reviews/*-repo-review*.md` (by name, then mtime). Your task list is, in this order: its **"Path to strong hire"**, then its **Top 10 fixes** marked before sending, then the rest of the **FIXABLE** risks by effect. Ignore NOT FIXABLE risks except where the review asks for a README sentence.
- `REVIEW_PROMPT` = `/Users/islootski/Documents/02-Personal/mcp-client-testing/prompts/mcp-repo-review-prompt.md` — used in section 6 to re-score.
- `MAIL` = `/Users/islootski/Documents/02-Personal/mcp-client-testing/bay-home-assignment.md` — the task; the bar for every doc change.
- `PLAN_SRC` = `/Users/islootski/Documents/02-Personal/mcp-client-testing/MCP-Client-Testing/`, `REF` = `/Users/islootski/Documents/02-Personal/mcp-client-testing/reference/` — read-only; cite as `<file>:<line>`.
- Docker: `export PATH="$HOME/.docker/bin:$PATH"`. Key: `~/.config/bay-mcp/key`, only as `ANTHROPIC_API_KEY="$(cat ~/.config/bay-mcp/key)" ./run.sh …`; never print it.
- Budget: **$0.60** total model spend, re-review included (`total_cost_usd` in each run's `artifacts/<run-id>/cost.json`).

## 1. Baseline (before any change)

Create `SCRATCH` with `mktemp -d`. Record in `SCRATCH/baseline.md` (and note the baseline commit, `git -C REPO rev-parse HEAD`): the REVIEW's score table; words of README.md + PLAN.md + PROMPTS.md (`wc -w`); Python lines (`find harness fakes tests -name '*.py' | xargs wc -l`); the newest full run's per-test outcomes (`artifacts/<run-id>/junit.xml`). Every later step compares against this.

## 2. Guardrails (a fix that breaks one is not done)

1. **Net size**: README + PLAN + PROMPTS words must not grow overall; each doc fix that adds text removes at least as much elsewhere (or moves detail to `docs/`). Python lines may grow only for new tests.
2. **No lost guards**: never delete or weaken an assert to make a finding "record-only" without keeping the hard part (the wire-log fact) as an assert. A behavior change Claude Code makes later must still be noticed.
3. **Every code fix has a can-fail proof**: an offline replay or a mutation in `tests/test_harness_offline.py` that fails without the fix and passes with it (free, $0).
4. **Every claim true**: each doc sentence you touch is checked against the code or a `REF` line.
5. **PROMPTS.md is for a hiring panel**: the candidate's own prompts appear as the few messages that hold decisions (scope, loop design, cuts, spend cap, coding and logging rules), short and in clean wording, marked "paraphrased" where not verbatim. No personal email, no other projects, no small talk, no secrets.
6. Code rules: no default parameter values; keyword arguments; named constants; no hidden fallbacks. Logs and asserts via `harness/check.py` (`step`, `got`, `wait_start`/`wait_done`, `expect_*` with `Expected: … Actual: …`). Strict xfails raise `DocumentedBehaviorMismatch`. Black-box only. Never log or write a secret.
7. Do not edit `REVIEW`, `MAIL`, `PLAN_SRC`, `REF`, `REVIEW_PROMPT`.

## 3. Plan the parallel work (you, before any edit)

Split the task list into **work units** that can run at the same time:
- **One owner per file.** Each unit lists the files it may edit; no file is in two units. All doc files (README.md, PLAN.md, PROMPTS.md, `docs/`, `observations.md`) belong to one **docs unit**, which applies the review's "What to cut" first and then adds only what the task list needs (guardrail 1). Code units split by module (for example: exit codes and gate in `tests/conftest.py` + `harness/model_flow.py` + `harness/model_checks.py`; a new hook test in `tests/test_permissions.py` + `fakes/guard_hook.py`; offline self-tests in `tests/test_harness_offline.py`).
- **Decide shared facts up front** and write them into every unit's brief: new exit codes and their numbers, new test names, new constants, the exact README sentence each code change needs. Then the docs unit can work at the same time as the code units and still match the code.
- At most 5 units. Write the plan to `SCRATCH/plan.md`.

## 4. Build in parallel

If you can start subagents, start all units' Dev agents in ONE message so they run at the same time. Each Dev:
1. Works in its own git worktree: `git -C REPO worktree add SCRATCH/wt-<unit> -b fix/<unit> main`. Never edits the main checkout or another unit's files.
2. Makes its changes, each with its can-fail proof (guardrail 3) and the review's done check.
3. Runs only the free tier in its worktree (`env -u ANTHROPIC_API_KEY ./run.sh` — each worktree has its own `artifacts/`; `run.sh` creates the container from the image ID it built, so parallel runs do not clash). No paid runs in units.
4. Commits on its branch (plain message, `Co-Authored-By: Claude <noreply@anthropic.com>`) and reports: files changed, proof results, free-run counts.

Then start one fresh **QA agent per unit, all in one message**: each checks its unit's branch against this prompt, the REVIEW and the guardrails, tries to break each change, and reports by severity. A medium or worse finding goes back to that unit's Dev (in parallel with other units' fixes).

## 5. Merge and verify (you, in order)

1. Merge each unit branch into `main` (`git merge --no-ff fix/<unit>`); code units first, the docs unit last. Resolve conflicts by the plan's file ownership.
2. On merged `main`: free run with no key, then ONE full run with the key. Every per-test outcome difference vs the baseline must be one a unit made on purpose. `secret-scan.json` clean. Guardrail 1 (`wc -w`) holds.
3. If a check fails, fix it in one more small unit (Dev + QA), then repeat step 2.
4. Remove the worktrees (`git worktree remove`) and delete the `fix/*` branches.

If you cannot start subagents, do the units yourself one after another, in the same order.

## 6. Re-score and loop

1. Before pushing, scan the merged changes (`git diff <baseline-commit>..main`) for `sk-ant-` and for email addresses other than `[e-mail address removed]`. Push to `origin main` (never force).
2. Run `REVIEW_PROMPT` (it runs its own phases in parallel; start it in a subagent if you can; it writes the next `reviews/<date>-repo-review-N.md`).
3. Compare its scores with the baseline. If the verdict did not improve and the new review lists FIXABLE items that fit the remaining budget, run sections 3–6 once more (at most 2 rounds in total). Stop when the verdict is "strong hire", when only NOT FIXABLE risks remain, or when the budget is spent.

## 7. Report

Under 300 words: per round, the fixes done or skipped (with reason); score table baseline → final; words and Python lines baseline → final; runs (counts, exit codes, cost); junit differences; decisions you made; total money; what the candidate must still check by hand.
