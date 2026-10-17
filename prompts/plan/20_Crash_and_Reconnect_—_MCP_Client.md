AREA 3 -- Errors. PRIORITY: P0, candidate for "in depth".

TESTS

1\. [P0] stdio server crashes mid-call. Server process exits (nonzero) while a tools/call is in flight. Assert: the in-flight request is surfaced to the model as a failure (not a silent hang), and per the spec's stdio "unexpected termination" guidance, assert whether Claude Code actually restarts the process -- R01/R06 found no documented auto-restart for stdio in Claude Code's own docs, which is a direct conflict with the spec's "client SHOULD restart" wording. This test's job is to settle that conflict empirically and record the real answer, since it changes what "working" means for this transport.

2\. [P0] stdio server crashes between calls (idle). Process dies with no call in flight. Assert whether Claude Code notices before the next tool call attempt or only discovers it on the next call attempt. Assert that the next call fails within a set time and the spawn count stays 1.

3\. [P0] HTTP server drops mid-session, then comes back. Contrast with doc 20, test 1 (stdio: no auto-reconnect at all): assert the exponential backoff (5 attempts, 1s doubling) actually succeeds in reconnecting once the server is healthy again, and that a tool call issued during the outage either queues/retries correctly or fails cleanly -- not silently dropped. Merged from doc 13, test 7: if the server stays down, after 5 failures the server is marked failed.

4\. [P1] stdio shutdown hygiene. At the end of a session, assert Claude Code on Linux sends SIGINT, then SIGTERM after 100 ms, then SIGKILL after 400 ms more; the fake logs each signal; report the gap with the spec's SHOULD; run `ps` inside the container before it stops, and start it with `--init` -- and that no orphan server process is left running. Directly testable via `ps`/process list inside the Docker container at teardown.

5\. [P1] Resumed-session race: a tool call issued while its server is still reconnecting. Per R01, this is held up to 10s, then fails with "No such tool available". Assert that exact behavior with a server that reconnects slowly on purpose.

6\. [P1] Stdio server exits during the handshake. Assert: the status is failed, there is no restart (spawn count 1), and the run ends with a `result` event.
