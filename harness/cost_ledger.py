"""Suite cost ledger: the sum of `total_cost_usd` over every `claude -p` run.

One ledger per pytest session (tests/conftest.py). Each model run is charged
once, after it ends (harness/model_run.py run_print picks the source):
  * with the `total_cost_usd` of its final `result` event, or
  * with the per-run cap (`--max-budget-usd`) when the real spend is
    unknown: no `result` event (a crash), a `result` event without
    `total_cost_usd`, or an exception during the run (a timeout). The
    ledger assumes the worst the run was allowed to spend.

Two stops, both pytest.exit with BUDGET_EXIT_CODE and cost.json written first:
  * before a run: the total plus one more full per-run cap would pass the
    suite budget (do not start a run that could pass it);
  * after a run: the total passed the suite budget.
"""

import json
import logging

import pytest

logger = logging.getLogger(__name__)

SOURCE_RESULT = "result.total_cost_usd"
SOURCE_NO_RESULT = "no result event: charged the per-run cap"
SOURCE_RESULT_WITHOUT_COST = "result event without total_cost_usd: charged the per-run cap"
SOURCE_EXCEPTION = "exception during the run (timeout, interrupt, parse error): charged the per-run cap"
CAP_SOURCES = (SOURCE_NO_RESULT, SOURCE_RESULT_WITHOUT_COST, SOURCE_EXCEPTION)


class CostLedger:
    def __init__(self, *, suite_budget_usd, per_run_cap_usd, exit_code, cost_file):
        self._budget = suite_budget_usd
        self._cap = per_run_cap_usd
        self._exit_code = exit_code
        self._cost_file = cost_file
        self._runs = []

    def total(self):
        return round(sum(run["charged_usd"] for run in self._runs), 6)

    def per_test(self):
        """{test_id: {"runs": n, "charged_usd": sum}} in first-run order."""
        out = {}
        for run in self._runs:
            if run["test_id"] not in out:
                out[run["test_id"]] = {"runs": 0, "charged_usd": 0.0}
            out[run["test_id"]]["runs"] += 1
            out[run["test_id"]]["charged_usd"] = round(out[run["test_id"]]["charged_usd"] + run["charged_usd"], 6)
        return out

    def check_before_run(self, *, test_id):
        if self.total() + self._cap > self._budget:
            self._stop(
                message="cost ledger: not starting a model run for %s: total $%.4f + per-run cap $%.4f would pass "
                "SUITE_BUDGET_USD $%.4f" % (test_id, self.total(), self._cap, self._budget)
            )

    def charge(self, *, test_id, label, total_cost_usd, source):
        """source: SOURCE_RESULT with the result event's total_cost_usd, or
        one of CAP_SOURCES with total_cost_usd None (the cap is charged).
        Returns the amount charged."""
        if source == SOURCE_RESULT:
            assert total_cost_usd is not None, "SOURCE_RESULT needs a total_cost_usd"
            charged = float(total_cost_usd)
        else:
            assert source in CAP_SOURCES and total_cost_usd is None, (source, total_cost_usd)
            charged = self._cap
        self._runs.append(
            {"test_id": test_id, "label": label, "total_cost_usd": total_cost_usd, "charged_usd": charged,
             "source": source}
        )
        self.write()
        logger.debug("charged $%.6f for %s (%s); suite total $%.6f of $%.2f", charged, label, source,
                     self.total(), self._budget)
        if self.total() > self._budget:
            self._stop(
                message="cost ledger: total $%.4f passed SUITE_BUDGET_USD $%.4f after %s (%s); stopping the run"
                % (self.total(), self._budget, test_id, label)
            )
        return charged

    def write(self):
        report = {
            "suite_budget_usd": self._budget,
            "per_run_cap_usd": self._cap,
            "model_runs": len(self._runs),
            "total_usd": self.total(),
            "per_test": self.per_test(),
            "runs": self._runs,
        }
        with open(self._cost_file, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")

    def _stop(self, *, message):
        self.write()
        pytest.exit(message, returncode=self._exit_code)
