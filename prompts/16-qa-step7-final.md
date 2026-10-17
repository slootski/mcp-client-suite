You are the final QA agent for a take-home assignment: an automated black-box test suite for the MCP client inside Claude Code 2.1.296. You play the reviewer from the hiring team: you got the repo, you have only Docker and git and an `ANTHROPIC_API_KEY`, and you read the docs first. Check everything hard; do not trust any report.

## Where things are

- The repo (not yet a git repo): `/Users/islootski/Documents/02-Personal/mcp-client-testing/mcp-client-suite/`.
- The task mail: `/Users/islootski/Documents/02-Personal/mcp-client-testing/bay-home-assignment.md`. Read it first: it is the bar.
- The spec for the docs step: `mcp-client-suite/prompts/15-dev-step7-docs.md`.
- The plan (read-only): `/Users/islootski/Documents/02-Personal/mcp-client-testing/MCP-Client-Testing/` docs `11`–`24`.
- Docker: `export PATH="$HOME/.docker/bin:$PATH"` first.
- API key: `~/.config/bay-mcp/key`. Use it only by exporting it from the file, never printing it.

## Money

Your budget: **$0.80**: exactly one full run with the key as the reviewer would run it, plus one retry only if the first fails for an outside reason (network). Report the exact sum of `total_cost_usd`.

## What to check

A. **The reviewer's run, exactly**: copy the folder to a scratch dir without `artifacts/` (as a fresh clone would be). There: `export ANTHROPIC_API_KEY="$(cat ~/.config/bay-mcp/key)"`, then type exactly the command README.md tells you. Does it build and pass with no other step? Time it. Do the counts, time and cost match README? Then unset the key and run again: free tier only, exit 0? Delete the scratch dir and any image you built for it.

B. **README.md**: is every claim true of the code? Check each exit code, each path, each "already in the code" claim in the CI section, each product finding against `observations.md` and the test that shows it. Is the requirement table complete (every requirement sentence of the mail) and does each row point to something real? Is it readable in 5 minutes? Anything a reviewer would stop on?

C. **PLAN.md**: does it have every test idea from docs 11–23 (count them in the docs, count them in PLAN.md)? Is every `implemented:` test name real (`pytest --collect-only` in the container, or grep)? Are the 5 questions covered, with at least 2 in depth? Is the D/S tag right for a sample of 10 lines?

D. **PROMPTS.md**: are all prompts listed, in order, and do the files exist and match (copies verbatim: `diff` against the originals)? No transcripts. Grep everything in the repo for secrets (`sk-ant`, `Bearer `, tokens) and personal email addresses; list hits.

E. **Repo hygiene**: `.gitignore` has `artifacts/`; nothing in the repo is a large generated file; `.dockerignore` keeps `artifacts/` and `prompts/` out of the build context; no stray scratch files, `__pycache__`, `.DS_Store`.

F. **Code**: AST scan of every `.py` for default parameter values; list hits. Any test that can never fail (skim each test file for asserts that are always true or skips that hide failures)?

G. **The 30-minute call**: list the 5 questions the reviewers are most likely to ask, and say whether the docs already answer each.

## Rules

Do not edit the real folder. Never print the key. Delete scratch copies and images.

## Report back (under 400 words)

Verdict PASS / FAIL; table finding | severity | file:line | fix; A results (counts, time, cost, exit codes); the G list; **exact money you spent**.
