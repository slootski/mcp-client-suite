"""Repeat harness and S pass rates (doc 22 test 1, docs/flake-policy.md).

A repeated test is parametrized over `repeat` in range(REPEATS). Each repeat
is its own pytest item, so it gets its own sandbox: a fresh
CLAUDE_CONFIG_DIR and HOME, a fresh canary / ids / argument values, its own
artifact folder (wire logs, stream, run.json) and its own ledger line.

  D facts  hard asserts inside every repeat item. N of N: any repeat that
           breaks one fails, with its wire log kept in its artifact folder.
  S facts  each repeat records one sample (record_s_sample) BEFORE its D
           asserts, so a D failure never hides the S result and vice versa.
           A trailing `..._s_rate` item (evaluate_s_rate) counts the repeats
           whose rated S facts all held and fails only below the threshold.
           The rate goes to <rate item artifact dir>/s-rate.json, to the
           suite-level s-rates.json (SUITE_S_RATES_FILE) and is printed in
           the terminal summary.

Inconclusive: a repeat whose S trigger did not happen (no tool_use, or a
server not connected) is retried once in a fresh config dir; if the retry
is inconclusive too, the repeat is skipped as inconclusive and its sample
counts as an S miss ("model did not call the tool"). A retry happens only
for a missing trigger, never after a D failure.

A repeat item that ends before it recorded its sample (an exception before
the S facts) counts as an S miss in the rate, with that reason. When fewer
than REPEATS repeat items ran in the session (a `-k` subset), the rate item
is skipped as inconclusive: it does not judge a partial sample.
"""

import json
import os

import pytest

S_SAMPLES_KEY = pytest.StashKey[dict]()  # {group: {repeat index: sample or None}}
S_RATES_KEY = pytest.StashKey[dict]()  # {group: rate summary}, for the terminal summary

NO_SAMPLE_REASON = "no sample: the repeat ended before its S facts were read"


def init_session(*, config):
    config.stash[S_SAMPLES_KEY] = {}
    config.stash[S_RATES_KEY] = {}


def start_repeat(*, config, group, repeat):
    """Mark repeat `repeat` of `group` as started (sample still missing)."""
    samples = config.stash[S_SAMPLES_KEY]
    if group not in samples:
        samples[group] = {}
    samples[group][repeat] = None


def record_s_sample(*, config, group, repeat, rated, recorded, inconclusive):
    """rated: {fact: bool} counted against the threshold; recorded: {fact:
    bool} reported as a rate, never failing; inconclusive: None, or the
    reason the trigger did not happen (then every rated fact is False)."""
    config.stash[S_SAMPLES_KEY][group][repeat] = {
        "rated": dict(rated), "recorded": dict(recorded), "inconclusive": inconclusive,
    }


def _rate(*, values):
    return {"held": sum(1 for value in values if value), "of": len(values)}


def evaluate_s_rate(*, config, group, repeats, min_passes, rates_file, artifact_dir):
    """Count the S pass rate of `group`, write it, return the summary.
    Skips (inconclusive) when fewer than `repeats` repeats ran or every one
    was inconclusive; the caller asserts summary["passes"] >= min_passes."""
    started = config.stash[S_SAMPLES_KEY][group] if group in config.stash[S_SAMPLES_KEY] else {}
    runs = []
    for repeat in sorted(started):
        sample = started[repeat]
        if sample is None:
            runs.append({"repeat": repeat, "passed": False, "reason": NO_SAMPLE_REASON, "rated": {}, "recorded": {}})
            continue
        passed = sample["inconclusive"] is None and all(sample["rated"].values())
        reason = sample["inconclusive"] if sample["inconclusive"] is not None else (
            None if passed else "failed: %s" % sorted(k for k in sample["rated"] if not sample["rated"][k]))
        runs.append({"repeat": repeat, "passed": passed, "reason": reason, "rated": sample["rated"],
                     "recorded": sample["recorded"]})
    fact_names = sorted({name for run in runs for name in run["rated"]})
    recorded_names = sorted({name for run in runs for name in run["recorded"]})
    summary = {
        "group": group,
        "repeats_expected": repeats,
        "repeats_ran": len(runs),
        "min_passes": min_passes,
        "passes": sum(1 for run in runs if run["passed"]),
        "inconclusive_repeats": sum(1 for run in runs if run["reason"] is not None
                                    and run["reason"].startswith("inconclusive")),
        "per_rated_fact": {name: _rate(values=[run["rated"][name] for run in runs if name in run["rated"]])
                           for name in fact_names},
        "per_recorded_fact": {name: _rate(values=[run["recorded"][name] for run in runs if name in run["recorded"]])
                              for name in recorded_names},
        "runs": runs,
    }
    if len(runs) < repeats:
        summary["verdict"] = "inconclusive: %d of %d repeats ran in this session" % (len(runs), repeats)
    elif summary["inconclusive_repeats"] == len(runs):
        summary["verdict"] = "inconclusive: every repeat was inconclusive"
    else:
        summary["verdict"] = "pass" if summary["passes"] >= min_passes else "fail"
    config.stash[S_RATES_KEY][group] = summary
    os.makedirs(artifact_dir, exist_ok=True)
    with open(os.path.join(artifact_dir, "s-rate.json"), "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    write_rates_file(config=config, path=rates_file)
    if summary["verdict"].startswith("inconclusive"):
        pytest.skip(summary["verdict"])
    return summary


def write_rates_file(*, config, path):
    """Every S rate of the session so far, in one file next to cost.json."""
    rates = config.stash[S_RATES_KEY]
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({group: {key: rates[group][key] for key in rates[group] if key != "runs"} for group in rates},
                  handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")


def summary_lines(*, config):
    """One line per S rate, for the terminal summary."""
    rates = config.stash[S_RATES_KEY]
    lines = []
    for group in rates:
        rate = rates[group]
        facts = ", ".join("%s %d/%d" % (name, value["held"], value["of"])
                          for name, value in sorted(rate["per_rated_fact"].items()))
        recorded = ", ".join("%s %d/%d" % (name, value["held"], value["of"])
                             for name, value in sorted(rate["per_recorded_fact"].items()))
        lines.append("%s: S %d/%d (threshold %d/%d, %s) [%s] recorded-only [%s]" % (
            group, rate["passes"], rate["repeats_ran"], rate["min_passes"], rate["repeats_expected"],
            rate["verdict"], facts, recorded))
    return lines
