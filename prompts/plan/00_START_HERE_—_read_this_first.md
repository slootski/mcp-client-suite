START HERE. This folder (MCP-Client-Testing) is the planning workspace for a take-home assignment: build an automated black-box test suite for the MCP client inside Claude Code 2.1.296, public docs only, runs in Docker with one command, deliverables are a git repo + PLAN.md + PROMPTS.md + README.md. No code has been written yet -- only planning and research documents exist here so far.

INSTRUCTION FOR THE AGENT READING THIS: do not start writing code, PLAN.md, or any other deliverable after reading only this file or only one or two of the documents below. Read every document listed under "READ IN THIS ORDER" in full, in order, before writing anything. These are short documents (roughly 1-5 KB of plain text each) and reading all of them costs little; skipping ahead risks missing a test case, a pinned env var, or a decision already made, and redoing work later is more expensive than reading now. All files are local. If a listed file is missing, stop and name it.

READ IN THIS ORDER:

1\. This file.

2\. 24 Handoff — Bay MCP Assignment -- full current state, what's decided, what's still open.

3\. 11 through 23 (in numeric order) -- the actual test plan, one document per topic area, each test tagged P0/P1/P2 by priority. This is the material to turn into PLAN.md and actual test code.

4\. Documentation/ folder -- R01 through R06, the factual reference material (curated Claude Code docs excerpts + verbatim MCP spec pages) that the test plan is built on. Consult these when writing code if you need to confirm a specific behavior or env var.

NEXT STEP: the test trim and the two in-depth areas are decided in doc 24 OPEN ITEMS. Build those 10 tests, the MCP test servers, the pytest suite, the Dockerfile and the three deliverable docs (doc 24 NEXT STEPS).
