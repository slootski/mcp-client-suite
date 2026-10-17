You are the Dev agent for step 7 of a take-home assignment: an automated black-box test suite for the MCP client inside Claude Code 2.1.296. All test steps are built and passed QA. Your job now is a few small fixes from the last QA ("Fix first" below), then the three deliverable documents and the repo hygiene. A QA agent checks your work after you, and the reviewers (a hiring team) will read these files first.

## Where things are

- Suite (this folder becomes the git repo root): `/Users/islootski/Documents/02-Personal/mcp-client-testing/mcp-client-suite/`. Read all of it: `run.sh`, `Dockerfile`, `pytest.ini`, `harness/`, `fakes/`, `tests/`, `docs/flake-policy.md`, `observations.md`, `evidence/`, `prompts/`.
- The task mail (the requirements): `/Users/islootski/Documents/02-Personal/mcp-client-testing/bay-home-assignment.md`.
- The plan (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/MCP-Client-Testing/` — `00`, `11`–`24`, `Documentation/R01`–`R06`. Docs 11–23 hold every test idea, tagged P0/P1/P2; doc 24 says which 10 items were built.
- The plan review prompt (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/prompts/mcp-plan-review-prompt.md`. The last review: `/Users/islootski/Documents/02-Personal/mcp-client-testing/reviews/2026-10-16-plan-review-5.md`.
- Docker: `export PATH="$HOME/.docker/bin:$PATH"` first.
- API key: `~/.config/bay-mcp/key`, only as `ANTHROPIC_API_KEY="$(cat ~/.config/bay-mcp/key)" ./run.sh …`. Never print it or write it anywhere.

## Money

Your budget: **$0.90**: up to $0.10 for the Fix-first targeted runs, then exactly one full run with the key (to get real counts, time and cost for the README) plus one retry if needed. Report the exact sum of `total_cost_usd`.

## Fix first: QA findings from step 6 (do these before the full run)

1. Low — tests/test_idle_timeout.py:240-246: the hard window [2.75 s, 50 s) accepts any abort between 5 s and 50 s, and nothing asserts that the idle check caused it. Assert the `tool_result` text contains the client's idle text (`sent no response or progress`; take the exact wording from a recorded run). Keep 3–5 s as the strict xfail. Do not hard-pin 30 s (a fixed client must XPASS, not fail hard).
2. Low — tests/test_permissions.py:58-65: variant A assumes an MCP tool with no allow rule is denied, but no test checks that. Add a control test: allow only `mcp__guard__list_items`, ask for a `guard__ops` tool; assert no call reaches `guard__ops` and the denial is in `permission_denials`; assert the `permission_denied` system event (QA saw it live; this gives headless.md:333 a real assert). Gate it like the others.
3. Low — tests/test_harness_offline.py: add free replay breaks for the idle bound, T9 and T10, using the step 6 recorded runs (as QA did: an early give-up fails; the server getting `delete_all` fails; a fixed-version shape XPASSes strictly).
4. Nit — the matcher sentence is at hooks.md:365, not :363: fix it in test_permissions.py:33, :304, the flake-policy row and observations.md.
5. Info only — doc 19's MUST case (default era with a 2026-07-28 server) is not run; list it in PLAN.md as not implemented, with the reason.

Run only the targeted tests for 1–3 with the key, plus the free tier. Then do the scope below.

## Scope

Write plain, short, direct English. No marketing words. Every claim in these docs must be true of the code as it is now: check it, do not copy it from a prompt.

### A. PLAN.md
1. A short intro: the plan was written as prompt files for an AI build agent (docs 00, 11–24, kept verbatim under `prompts/plan/`), reviewed 5 times, then trimmed to 10 build items (doc 24).
2. One table per mail question (1 Connection and auth, 2 Tool calls, 3 Errors, 4 Determinism, 5 Other). One line per test idea from docs 11–23, every idea, none dropped: `ID (D<nn>/T<n>) | what it checks | oracle (how the test knows) | D or S | priority | status`. Status is `implemented: tests/<file>::<test>` (check the name exists) or `not implemented: <short reason>`. An idea may appear under the question it answers best; say once how you mapped them.
3. The 10 built items, with the variants and strict xfails each one has.
4. The flake-policy table (from `docs/flake-policy.md`), or a link plus a 5-line summary.

### B. README.md
1. **Run it** first: what the reviewer types, from a fresh clone, with only Docker and git and `ANTHROPIC_API_KEY` exported. Also: no key (free tier only), one test (`./run.sh -k …` if supported), where the results land (`artifacts/<run-id>/`, `artifacts/latest`), exit codes (list every one `run.sh` and the entrypoint can return, with meaning), measured time and cost of a full run (from your run), and that the suite stops itself at `SUITE_BUDGET_USD`.
2. **What it found**: the product facts and defects the suite observed on 2.1.296, each with the test that shows it and the doc or changelog line it differs from (from `observations.md`; strict xfails first). Keep it to the strong ones.
3. **Choices made**, each with its reason: black-box only; fake MCP servers that log every message (the oracle is the server's log, not the model's words); the D vs S split and N = 5 repeats; the gate (inconclusive is never a pass); strict xfail for known defects; the pinned version and image digest; the model and its caps (`--max-turns`, `--max-budget-usd`, the suite budget); the fresh config dir per test; legacy protocol negotiation as the default era and where the unset era is run; the key handed in by `docker cp` instead of `docker run -e` (say why, and the residual risk); `docker cp` for artifacts instead of a bind mount (say why); non-root.
4. **How each requirement is met**: a table, one row per requirement sentence in the mail (one command, Docker + git only, the key in `ANTHROPIC_API_KEY`, plan covers all 5 questions, at least 2 in depth — name which and why, real behavior over count, CI-ready, PLAN/PROMPTS/README), each pointing to a file or test.
5. **CI**: what it would take, concretely: junit XML output, the free/model markers as two jobs (free on every change, model on a schedule or label), the key as a CI secret, the budget guard, a quarantine list for flaky S items, Docker layer cache, running the suite against the next Claude Code version (and what a strict XPASS then means), artifacts upload, runner timeouts. Say which of these already exist in the code.
6. **Limits**: what the suite does not do and why (time box, cost, black-box).
7. Layout: a short tree of the repo with one line per folder.

### C. PROMPTS.md
The mail asks for "the prompts you gave your AI tools. We do not need transcripts."
1. A short "How AI was used" section: research into fact sheets, the plan written as prompt files for a build agent, 5 review rounds with the review prompt, then a build loop with a Dev agent and a QA agent per step, run by an orchestrating Claude Code session that wrote each prompt and folded each QA's findings into the next Dev prompt. Name the model used for the suite runs (`claude-haiku-5-5`, check `harness/constants.py`).
2. Copy the plan prompt files verbatim into `prompts/plan/` (00, 11–24, R01, R06; for R02–R05, which are copies of public spec pages, list title and URL only, do not copy). Copy the review prompt verbatim into `prompts/plan-review/`. The build prompts are already in `prompts/` (01–16); leave them as they are.
3. PROMPTS.md: one table row per prompt, in the order they were used: `# | file | to whom (planning agent / reviewer / Dev / QA) | one-line purpose`. Then the exact one-line launcher text used for the Dev and QA agents from step 2 on (read it from prompt files 05–15 context: "You are the Dev agent for step N. Your full task is in this file; read it in full first and follow it exactly: <path>. Do not edit that file or any other file under `mcp-client-suite/prompts/`.").
4. Before copying, grep every file you copy for secrets (`sk-ant`, tokens) and for personal email addresses; report what you find, do not copy secrets. Absolute home paths may stay.

### D. Repo hygiene
- `.gitignore`: `artifacts/`, caches, `__pycache__/`, `.pytest_cache/`.
- `.dockerignore` still keeps `artifacts/` and `prompts/` out of the image.
- Make sure the repo works from a fresh copy: copy the folder (without `artifacts/`) to a scratch dir, run `./run.sh` with no key there, and confirm exit 0. Delete the scratch copy.
- Do not `git init` (the user will do that).

## Rules

No code changes beyond "Fix first" and the hygiene files, unless a doc claim is false and the fix is one line; list any such change. Never print a secret. No default parameter values in any `.py` you touch.

## Report back (under 350 words)

Files written; full-run results (counts, time, cost); how many plan ideas are in PLAN.md vs implemented; anything in the docs you could not verify; anything found by the secret/email grep; exact money spent.
