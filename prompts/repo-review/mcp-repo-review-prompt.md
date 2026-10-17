# Prompt: hiring-panel review of the MCP client test suite repo

## How to use

Start a new, plain Claude Code session in `/Users/islootski/Documents/02-Personal/mcp-client-testing/` (no special settings, plugins or memory needed). Paste everything below the line. It is self-contained: every path, rule and step is here.

The review is read-only toward the repo and the plan: it writes review files only. Cost: one paid suite run, about $0.08–0.10.

---

You are a hiring panel reviewing a take-home assignment repo. Follow sections 0–5 exactly. Do not ask questions before you start; where something is unclear, decide, and say what you decided in the review.

## 0. Inputs (all local)

- `REPO` = `/Users/islootski/Documents/02-Personal/mcp-client-testing/mcp-client-suite/` — the git repo under review.
- `MAIL` = `/Users/islootski/Documents/02-Personal/mcp-client-testing/bay-home-assignment.md` — the task mail. It is the bar. Cite it as `mail:<line>`.
- `PLAN_SRC` = `/Users/islootski/Documents/02-Personal/mcp-client-testing/MCP-Client-Testing/` (docs 00, 11–24) — the plan the repo was built from.
- `REF` = `/Users/islootski/Documents/02-Personal/mcp-client-testing/reference/` — downloaded public docs: Claude Code docs incl. `claude-code-docs/changelog.md`, MCP spec 2025-11-25 and 2026-07-28. Cite as `<file>:<line>`.
- `REVIEWS` = `/Users/islootski/Documents/02-Personal/mcp-client-testing/reviews/` — earlier plan reviews (context only).
- `OUT` = `REVIEWS/<today YYYY-MM-DD>-repo-review.md`. Never overwrite: if it exists, add `-2`, `-3`.
- `SCRATCH` = a new empty dir from `mktemp -d`. All clones and temp files go there; delete it at the end.

Environment:
- Docker Desktop's CLI may not be on PATH: run `export PATH="$HOME/.docker/bin:$PATH"` before any docker or `./run.sh` call.
- API key file: `~/.config/bay-mcp/key`. Use it only as `ANTHROPIC_API_KEY="$(cat ~/.config/bay-mcp/key)" ./run.sh …`. Never print it, echo it, or put it in a file or a command line in any other way.
- Do not edit any file in `REPO`, `PLAN_SRC`, `REF`. Do not commit, push, or touch git remotes.

## 1. Context

Bay is a young company that builds security for AI agents on employee computers: it decides Allow, Ask or Deny for agent actions at the agent's hooks, keeps allow and deny lists of MCP servers, and manages agent settings such as Claude Code's. The candidate applies to be Bay's **first automation engineer, who will later build and lead the automation team**. Bay's CTO will run the suite, read the repo, and hold a 30-minute call with the candidate.

The task (read `MAIL` for the exact words): a black-box automated test suite for the MCP client of Claude Code 2.1.296, Claude Code running in Docker; one command; the reviewer's machine has only Docker, git and `ANTHROPIC_API_KEY`; a plan covering 5 questions, at least 2 answered in depth; `PLAN.md`, `PROMPTS.md`, `README.md`; "about 2–3 hours of work"; AI use allowed.

Judge as a **real hiring panel**: say plainly where the work is weak, including no-hire risks. Praise only what evidence supports.

## 2. The panel

Each expert gives the top 3 strengths and the top 3 risks, each with evidence, and a score 1–5.

1. **Bay CTO / hiring manager.** Would I hire this person as the first automation hire and the future team lead? Judgment, priorities, honesty, fit to Bay's product (hooks, permission rules, MCP policy).
2. **Senior test-automation architect.** Oracles (the fake server's wire log vs the model's text), the D/S split (deterministic client facts vs model behavior as a pass rate) and N=5 repeats, the gate (inconclusive never passes), strict xfails for known defects, the harness, whether each test can fail (offline replay tests), depth vs breadth.
3. **MCP protocol expert.** Are the tests right about the MCP spec and Claude Code's docs? Are the "findings" in README real defects, fair readings of the cited doc lines, or misreadings? Open every cited line in `REF` and check it.
4. **Claude Code insider.** Would the team that tests Claude Code want these tests? Right use of `claude -p`, `--output-format stream-json`, `--mcp-config --strict-mcp-config`, settings, hooks, env pins? Anything that would embarrass the candidate in front of that audience?
5. **AI-agent security engineer.** Secret handling (the key handed in by `docker cp`, redaction, artifact scans, stated residual risks), sandbox and non-root, the permission and hook tests — Bay's core product. Are the security claims true and tested?
6. **CI / DevOps engineer.** One command from a fresh clone, reproducibility (pinned image digest and versions), cost control, exit codes, artifacts, the README CI section: concrete or hand-waving?
7. **Engineering manager.** Could a new hire read, run and extend this in a day? Size and structure (`harness/`, `fakes/`, `tests/`), naming, logs and assert messages, docs. Maintainable by a team?
8. **Time-box judge.** The mail says 2–3 hours. Measure what was built (lines of code and docs, number of prompt files, review rounds in `REVIEWS`). Strength (thoroughness) or red flag (cannot scope; AI volume)? How should the candidate explain it in the call?
9. **Busy doc reader.** Read only README.md, PLAN.md and PROMPTS.md, 5 minutes in total, like a CTO between meetings. What lands, what is lost, what is too long? Where would you stop reading?
10. **Skeptic.** What looks AI-generated, padded or over-claimed? Which claims collapse under one follow-up question? What will the reviewers poke at?

## 3. How to work

Run as parallel as possible. If your session can start subagents (the Agent / Task tool), start every agent of a phase in ONE message so they run at the same time; give each this whole prompt plus its one-line role; each writes only its own file under `SCRATCH/`.

- **Phase 1 — two runners, in parallel (start them first, then go on to phase 2 at once):**
  - **R1 paid run:** one full `./run.sh` with the key in `REPO` (the only paid run). Writes `SCRATCH/run-paid.md`: the `artifacts/<run-id>`, counts, exit code, run time, exact sum of `total_cost_usd`.
  - **R2 fresh clone:** `git clone REPO SCRATCH/clone`, then follow README exactly with **no** key (`env -u ANTHROPIC_API_KEY ./run.sh`), plus the no-key gate cases README names; $0. Must not touch `REPO/artifacts/latest`. Writes `SCRATCH/run-clone.md`. Deletes the clone.
- **Phase 2 — ten experts, in parallel, started right after phase 1 (do not wait for it):** one agent per expert in section 2, each writing `SCRATCH/expert-<NN>.md` (its section 4.2 part, its fix candidates with done checks and guardrails, its call questions, its facts). Each uses the newest complete `REPO/artifacts/<run-id>/` for run evidence; experts 2, 4, 5 and 6 then wait for `SCRATCH/run-paid.md` / `run-clone.md` (poll the file, at most 15 minutes) and update their part with the fresh results. Experts read only; no runs.
- **Phase 3 — chair (you):** when all parts exist, write `OUT` per section 4: resolve disagreements (say so), de-duplicate fixes into one ranked list, set the verdict. Spot-check the 3 most decision-relevant claims yourself (`file:line`) before ranking them.

If you cannot start subagents, do the same work yourself in that order.

For everyone:
1. Read `MAIL` in full first. Then README.md, PLAN.md, PROMPTS.md. Then `run.sh`, `Dockerfile`, `pytest.ini`, `harness/`, `fakes/`, `tests/`, `docs/flake-policy.md`, `observations.md`. Skim `prompts/`.
2. Each run writes `artifacts/<run-id>/` with `report.html` (per-test logs), `suite.log`, `junit.xml`, `cost.json`, `secret-scan.json`. Open one `report.html` and read two tests' logs end to end.
3. Evidence: every strength and risk cites `file:line`, `mail:<line>`, a `REF` line, or a run output. Never invent evidence. If you could not check something, say so.
4. Measure, do not guess: `wc -l`, test counts from `junit.xml`, run time, cost.

5. **Re-review**: if `REVIEWS` already holds a `*-repo-review*.md` for this repo, read the newest one and `git log` since its date. Score every expert old → new, mark each of its fixes fixed / partly fixed / still open / made worse, and look hard for problems the fixes introduced (removed guards, grown docs, new over-claims).
6. **Size is a score input**: a fix that grows the docs or the code without removing more is a cost. Report words of README+PLAN+PROMPTS and Python lines, old → new.

## 4. Output (`OUT`)

The review exists to drive the next fix round, so every risk must be actionable or explicitly marked as not fixable.

1. **Verdict**: strong hire / hire / lean no / no hire, one paragraph with the reason. Then a table: expert | score 1–5 (old → new on a re-review) | one-line reason.
2. **Per expert**: strengths (3) and risks (3), each with evidence; then **"To reach 5"**: the concrete changes (file:line, effort S/M/L) that would make this expert give 5, or "cannot reach 5 because …".
3. **Fixable vs not fixable**: every remaining risk in one table: risk | FIXABLE in the repo (effort) or NOT FIXABLE (only an honest call answer handles it, e.g. time already spent, AI-written code) | which expert it limits. Say which category caps the verdict.
4. **Path to strong hire**: the smallest set of changes (max 5) that would make "strong hire" likely, each with file:line and effort, and the expected score change per expert. If no repo change can get there, say so plainly and why.
5. **Top 10 fixes**, ranked by effect on the hiring decision: what, where (`file:line`), effort (S/M/L), expected score change, a **done check** (the exact test, command or grep that proves it landed), and the **guardrail** (what must not get worse: e.g. "README word count must not grow", "keep the regression assert"). Mark the ones that should land before sending.
6. **The 30-minute call**: the 10 most likely questions, each with a short, honest answer the candidate can give, and what not to say.
7. **What to cut**: anything that hurts more than it helps (length, noise, over-claims), with the word or line count it saves.
8. **Facts measured**: sizes, counts, run times, cost, runs made (`artifacts/<run-id>`).

Plain, short sentences. No marketing words.

## 5. Finish

Delete `SCRATCH`. Print: the `OUT` path, the verdict line, the score table, the path to strong hire, the top 3 fixes, and the exact money spent.
