# Review

Both tiers were run on the submission.

## What worked well

- **Use of agents.** The Dev/QA loop, where a QA agent tried to break each test the Dev agent wrote, matches how we work: agents do the work, and other agents verify it.
- **Self-tests and robustness.** The offline replays prove each check can fail, and the fake server's own log is the source of truth. When a test fails, it points at the product rather than the framework, so the effort goes into the software under test.
- **CI readiness.** One command, only Docker, separate free and model tiers, and clear exit codes. Moving it into CI would take little effort.

## Where it fell short

- **Coverage.** Coverage tells us how well we test the product, and key areas are missing. No test calls a tool over HTTP, OAuth stops at discovery, and nothing checks how tool and argument descriptions reach the model.
- **Duplication and extensibility.** Our framework needs to grow very large, so repetition and hard-coded parts multiply fast. Today the same setup helper and the same 18-argument runner call repeat across test files. The fake servers are fixed modes in one file, so every new feature means changes in many places.
