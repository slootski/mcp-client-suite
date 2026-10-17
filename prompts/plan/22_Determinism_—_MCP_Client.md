AREA 4 -- Determinism. PRIORITY: P0 (the brief asks this question directly; it's one of the 5 required areas and currently the least developed in the plan).

FRAMING

The CTO's question 4 is really two questions: which results are the same every run, and how does the suite treat each kind differently. Answer both explicitly rather than just running things twice.

WHAT'S DETERMINISTIC (wire/protocol facts) -- MUST pass every single run, zero tolerance for flake

- D, once the trigger happened: the client sent the model's `tool_use.input` unchanged, under the `mcp__<server>__<tool>` name, and put the server's result in `tool_result`. S, pass rate with threshold 4/5: whether the model called a tool, which one, and with which values. If the S trigger did not happen, the D check reports 'inconclusive' and is retried once, and the retry is logged.

- Ordering facts: cancelled notification after a timeout (doc 19), initialize before notifications/initialized (doc 12).

- Timeout boundaries within a tolerance window (doc 19) -- the BEHAVIOR is deterministic even though wall-clock jitter of a few hundred ms isn't.

- Status strings from claude mcp list / get (doc 12).

WHAT'S NON-DETERMINISTIC (model behavior) -- must be measured with a flake policy, not asserted as pass/fail on one run

- Exact wording of the model's final text answer.

- Whether the model retries after a tool execution error (doc 16 test 1) or gives up and reports the error instead -- both are reasonable model choices.

- Whether the model uses ToolSearch before the real tool call (depends on tool search being on, see doc 11).

- Latency-sensitive races, e.g. whether a slow-but-not-timed-out tool call finishes before some other model-driven branch point.

TESTS

1\. [P0] Repeat-run harness. Run the doc 15 "right tool, right args" tests and the doc 12 handshake tests N=5 times each. Assert wire-level facts pass 5/5. Record model-behavior facts (e.g. "did it phrase the ticket ID correctly") as a pass rate, not a hard assertion; fail the suite only if the pass rate drops under a stated threshold (e.g. 4/5).

2\. [P0] Explicit flake policy written down. A short table: fact -\> expected variance -\> how the suite treats it (hard assert / soft rate / log-only). This table IS the deliverable for "how does the suite treat each kind" -- it belongs in PLAN.md and README.md directly, not just in test code.

3\. [P1] Temperature / sampling is out of our control (black-box, no source access) -- document that we cannot set it, and that this is exactly why wire-level facts (doc 12, 15, 18, 19) were chosen as the "in depth" areas.

4\. [P1] Same test, two different tool orderings in tools/list. Assert that which tool gets called for an unambiguous request doesn't depend on list order (catches an accidental first-match-wins bug were one to exist).

5\. [P2, not implemented] Scripted fake model behind `ANTHROPIC_BASE_URL`. Free and fixed, but tool search turns off, Claude waits with `WaitForMcpServers`, and failed servers are not reported to Claude. Keep the real-model tier.
