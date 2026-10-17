# Exit codes

For a maintainer or a CI job. The README lists the common ones; this is the
full table. `./run.sh` exits with the suite's exit code.

| Code | Meaning | Where |
|---|---|---|
| 0 | All tests passed (skips and expected failures included) | pytest |
| 1 | A test failed, or a strict xfail passed (XPASS), or the pytest session timeout (1500 s) was hit; also: a file held the API key or a test credential, or an artifact copy failed (exit 1 whatever pytest returned, except 124/137), or no complete artifacts came out of the container | pytest, `harness/entrypoint.py`, `run.sh` |
| 2 | `./artifacts` is a symlink (`run.sh`); the key hand-off failed or the container was not started by `run.sh` (entrypoint); pytest was interrupted | `run.sh`, entrypoint, pytest |
| 3, 4 | pytest internal error, usage error (e.g. a bad option, or `SUITE_REQUIRE_KEY` set to anything but `1` or empty) | pytest, `tests/conftest.py` |
| 5 | No test selected (e.g. a `-k` that matches nothing) | pytest |
| 10 | `claude --version` is not 2.1.296, or cannot run; no test runs | `tests/conftest.py` |
| 11 | The suite budget would be passed; the run stops before the next model run | `harness/cost_ledger.py` |
| 12 | The model id was not accepted | `harness/model_flow.py` |
| 13 | The key is set and at least one model item was skipped as inconclusive (pytest itself returned 0; the list is printed under "model tier verdict" and is in `outcomes.json`). Two consequences: a `-k` that leaves an S rate item or `test_stdio_crash_mid_call_same_every_run` without its runs exits 13; and one repeat item that stays inconclusive after its retry (the model made no call) makes the run exit 13 even when its S rate item passes (e.g. 4/5) | `tests/conftest.py` |
| 14 | No key, and model items were asked for; no test runs. Three triggers: `SUITE_REQUIRE_KEY=1` (whatever is selected, so `SUITE_REQUIRE_KEY=1 ./run.sh -m free` exits 14 too); a `-m` expression that selects at least one model item (e.g. `./run.sh -m model`); or every selected item is a model item (at least one), e.g. `./run.sh -k test_round_trip_echo_canary`. Without any of them, plain `./run.sh`, `./run.sh -m free` and a mixed `-k` selection exit 0 with no key, model items skipped | `tests/conftest.py` |
| 15 | The Anthropic API rejected the key or the account (HTTP 401 or 403, e.g. a bad key or a billing error); the run stops at the first model run, no retry. The message starts `API key rejected:` | `harness/model_flow.py`, `harness/model_checks.py` (`key_rejected`) |
| 124, 137 | The whole-run cap (1800 s, coreutils `timeout`) stopped pytest; 137 if it had to be killed after the 30 s grace | entrypoint |
| other | `docker build` or `docker create` failed; `run.sh` exits with Docker's code | `run.sh` (`set -e`) |

Checked with no key on 2026-10-17: `./run.sh -m model` and `./run.sh -k
test_round_trip_echo_canary` exit 14; `SUITE_REQUIRE_KEY=1 ./run.sh -m
free` exits 14; `SUITE_REQUIRE_KEY=yes ./run.sh` exits 4; `./run.sh -k
no_such_test_zz` exits 5; plain `./run.sh` exits 0. With a made-up key,
`./run.sh -k test_round_trip_echo_canary` exits 15 after one `claude -p`
run ($0; run `20261017T141626Z-9815`).
