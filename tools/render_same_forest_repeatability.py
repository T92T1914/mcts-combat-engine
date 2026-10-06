"""Validate repeated same-work receipts and summarize process-block uncertainty."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.render_parallel_scaling import computational, number, require  # noqa: E402
from tools.render_same_forest import validate_receipt  # noqa: E402
from tools.run_parallel_scaling import digest  # noqa: E402
from tools.run_same_forest import compare_condition, differing_paths  # noqa: E402
from tools.run_same_forest_repeatability import (  # noqa: E402
    CONDITIONS,
    PROTOCOL,
    schedule,
    validate_protocol,
)

DATA = ROOT / "docs/same-forest-repeatability-results.json"
REPORT = ROOT / "docs/same-forest-repeatability-results.md"
T_CRITICAL = 2.571  # NIST table, two-sided95 percent, five degrees of freedom.


def validate(record, protocol):
    """Reject partial groups, bad matching work and flattened repetition claims."""
    validate_protocol(protocol)
    try:
        require(record["schema_version"] == 1, "unsupported result schema")
        require(record["protocol"] == protocol["id"] and
                record["protocol_sha256"] == digest(PROTOCOL), "protocol mismatch")
        require(record["status"] == "complete" and
                record["source_unchanged_at_end"] is True, "incomplete attempt")
        source = record["source"]
        require(source["worktree_clean"] is True and
                re.fullmatch(r"[0-9a-f]{40}", source["revision"]), "invalid source")
        require(source["sha256"]["docs/same-forest-repeatability-protocol.json"] ==
                record["protocol_sha256"], "source protocol mismatch")
        require(all(re.fullmatch(r"[0-9a-f]{64}", value)
                    for value in source["sha256"].values()), "invalid source hashes")
        require(source["retained_first_attempt_sha256"] ==
                "eba0584f93cc9ca6be21980cf0d48124e00aaf2ab602fa4f2aa1647070e3fba3",
                "original observation changed")
        env = record["environment"]
        require(env["python"] and env["platform"] and env["conditions"] and
                env["start_method"] == "spawn" and
                re.fullmatch(r"[0-9a-f]{64}", env["interpreter_sha256"]),
                "missing environment")
        require(record["process_tree_bound"], "missing external resource control")
        require(0 < number(record["collection_wall_s"]) <= 300,
                "collection exceeds declared maximum cost")
        require(len(record["blocks"]) == 6, "six fresh blocks required")
        roots, identities = {}, {}
        for block_index, item in enumerate(record["blocks"]):
            require(type(item["block"]) is int and item["block"] == block_index and
                    item["returncode"] == 0 and item["status"] == "complete",
                    "incomplete or reordered controller")
            require(number(item["controller_wall_s"]) > 0, "invalid controller time")
            block = item["record"]
            encoded = (json.dumps(block, indent=2, allow_nan=False) + "\n").encode()
            require(hashlib.sha256(encoded).hexdigest() == item["record_sha256"],
                    "nested record bytes differ")
            require(block["source"] == source and block["status"] == "complete" and
                    block["source_unchanged_at_end"] is True and
                    block["block"] == block_index and
                    block["protocol"] == record["protocol"] and
                    block["protocol_sha256"] == record["protocol_sha256"],
                    "block source or control differs")
            expected = schedule(block_index)
            require(block["schedule"] == expected, "declared schedule differs")
            keys = [(block_index, c["iteration"], c["scenario"], c["roots"], phase)
                    for c in expected for phase in c["order"]]
            actual = [(c["block"], c["iteration"], c["scenario"], c["roots"],
                       c["phase"]) for c in block["cells"]]
            require(not differing_paths(actual, keys),
                    "missing, duplicated or reordered execution")
            comparisons = []
            for index, cell in enumerate(block["cells"]):
                require(cell["search_seed"] == 42 and cell["environment_seed"] == 300,
                        "changed search inputs")
                validate_receipt(cell)
                complete = number(cell["complete_call_s"])
                require(complete >= cell["elapsed_s"] + cell["preparation_s"],
                        "complete call excludes preparation or search")
                key = cell["scenario"]
                root = cell["root_pickle_sha256"]
                require(re.fullmatch(r"[0-9a-f]{64}", root) and
                        roots.setdefault(key, root) == root, "root identity differs")
                key = (cell["scenario"], cell["roots"])
                identity = computational(cell)
                require(not differing_paths(identities.setdefault(key, identity),
                                            identity), "forest differs between blocks")
                if index % 3 == 2:
                    comparison = compare_condition(block["cells"][index - 2:index + 1])
                    comparison.update(block=block_index, iteration=cell["iteration"])
                    require(comparison["matched"], "forest mismatch")
                    comparisons.append(comparison)
            require(block["comparisons"] == comparisons, "saved comparisons differ")
            require(item["controller_wall_s"] >=
                    sum(c["complete_call_s"] for c in block["cells"]),
                    "controller interval excludes complete calls")
        require(len(set(roots.values())) == 3, "scenario roots are not distinct")
        require(record["collection_wall_s"] >=
                sum(item["controller_wall_s"] for item in record["blocks"]),
                "collection interval excludes controller invocations")
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError(f"malformed repeatability record: {exc}") from exc


def summarize(record):
    """Each mean has six outer units, not12 independent observations."""
    rows = []
    for scenario, roots in CONDITIONS:
        for metric in ("elapsed_s", "complete_call_s"):
            for phase in ("cold", "warm"):
                nested = []
                for item in record["blocks"]:
                    pairs = []
                    for iteration in range(2):
                        cells = {c["phase"]: c for c in item["record"]["cells"]
                                 if (c["scenario"], c["roots"], c["iteration"]) ==
                                 (scenario, roots, iteration)}
                        pairs.append(math.log(cells["sequential"][metric] /
                                              cells[phase][metric]))
                    nested.append(pairs)
                means = [statistics.fmean(values) for values in nested]
                mean = statistics.fmean(means)
                variance = statistics.variance(means)
                within = statistics.fmean(statistics.variance(v) for v in nested)
                half_width = T_CRITICAL * math.sqrt(variance / 6)
                low, high = math.exp(mean - half_width), math.exp(mean + half_width)
                rows.append({"scenario": scenario, "roots": roots, "metric": metric,
                             "phase": phase, "sampling_units": 6,
                             "iterations_per_unit": 2, "degrees_of_freedom": 5,
                             "geometric_mean_ratio": math.exp(mean),
                             "approximate_95_interval": [low, high],
                             "block_log_ratio_means": means,
                             "nested_log_ratios": nested,
                             "sample_variance_of_block_means": variance,
                             "mean_within_block_sample_variance": within,
                             "method_of_moments_between_block_variance":
                             max(0.0, variance - within / 2),
                             "result": "bounded advantage" if low > 1 else
                             "bounded disadvantage" if high < 1 else "inconclusive"})
    return rows


def markdown(record, summary):
    lines = ["# Repeated same-forest execution", "",
             "[Raw attempts](same-forest-repeatability-results.json) | "
             "[Predeclared protocol](same-forest-repeatability-protocol.json) | "
             "[Original one-observation control](same-forest-results.md)", "",
             "All 216 executions completed and matched the same computational "
             "receipts within every condition across six fresh Python controller "
             "processes. Each controller ran two repetitions per condition. "
             "Each execution retained 12,000 simulations and 60,000 transitions. "
             "The search algorithm and seeds did not change.", "",
             "The table estimates a geometric mean of paired sequential/process "
             "wall-time ratios. Above 1 favors processes. Each approximate "
             "95-percent interval uses six process-block means, df 5 and the "
             "predeclared rounded Student-t critical value 2.571. The two inner "
             "repetitions are not counted as independent processes. These are "
             "individual intervals, not simultaneous confidence across all 24 "
             "comparisons.", "",
             "| Scenario | Roots | Timer | Process | Ratio | "
             "Approximate 95% interval | Decision |",
             "| --- | ---: | --- | --- | ---: | --- | --- |"]
    for row in summary:
        low, high = row["approximate_95_interval"]
        lines.append(f"| {row['scenario']} | {row['roots']} | {row['metric']} | "
                     f"{row['phase']} | {row['geometric_mean_ratio']:.3f} | "
                     f"{low:.3f} to {high:.3f} | {row['result']} |")
    lines += ["", "## Timing and sampling limits", "",
              "The original search timer includes engine construction in sequential "
              "and cold calls but excludes warm pool preparation. The new complete "
              "call includes preparation, the search, receipt conversion, the "
              "root-mutation check and owned pool cleanup. Controller invocation "
              "cost is retained separately and is not apportioned among modes. "
              "Overlapping components must not be added.", "",
              "Fresh controllers share one machine and one interpreter installation. "
              "No rebuild or cross-machine level was sampled. The approximate "
              "interval assumes reasonably independent, approximately normal block "
              "means. Shared activity, drift and six blocks limit that assumption. "
              "No search was discarded as warmup, no failed block was retried and "
              "there was no outcome-based early stopping or tuning. The maximum-cost "
              "rule was 300 seconds with a 70-second admission reserve.", "",
              "Three fixed initial states and one seed do not represent all workloads "
              "or general search quality. Repetition cannot establish stronger play, "
              "superlinear scaling or portability. Original unfavorable observations "
              "remain in the earlier report.", "",
              f"Measured revision: `{record['source']['revision']}`. Collection wall "
              f"time: {record['collection_wall_s']:.3f} seconds. "
              f"Started: {record['started_utc']}. Ended: {record['ended_utc']}.", "",
              record["environment"]["conditions"], "",
              "## Method sources and reproduction", "",
              "[Kalibera and Jones, Rigorous Benchmarking in Reasonable Time]"
              "(https://kar.kent.ac.uk/33611/) supplied the distinction between "
              "repetition levels through its fetched abstract, author page and "
              "repository abstract. The corrected full manuscript timed out. This "
              "supplement does not claim to implement its complete cost or Fieller "
              "model.", "",
              "[NIST confidence limits for a mean]"
              "(https://www.itl.nist.gov/div898/handbook/eda/section3/eda352.htm) and "
              "[Student-t critical values]"
              "(https://www.itl.nist.gov/div898/handbook/eda/section3/eda3672.htm) "
              "define the declared ordinary mean interval on the process-block "
              "log ratios and the rounded df 5 value.", "",
              "Validate and regenerate this report without running search:", "",
              "```sh", "python tools/render_same_forest_repeatability.py --check",
              "```", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DATA)
    parser.add_argument("--output", type=Path, default=REPORT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    record = json.loads(args.input.read_text(encoding="utf-8"))
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    validate(record, protocol)
    text = markdown(record, summarize(record))
    if args.check:
        require(args.output.read_text(encoding="utf-8") == text,
                "generated report differs")
    else:
        args.output.write_text(text, encoding="utf-8")
    print("Validated six-block repeatability supplement without executing search")


if __name__ == "__main__":
    main()
