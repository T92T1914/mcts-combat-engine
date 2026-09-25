"""Render the bounded comparison from its retained results, without rerunning it."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render(report: dict) -> str:
    labels = ["random", "greedy", "one_round (8 samples/action)", "mcts (300 sims)"]
    lines = [
        "# One-round comparator study",
        "",
        "The one-round policy could use healing and defense that damage-only greedy "
        "ignored. It won every duel condition here, including one that MCTS "
        "did not finish within the 30-round limit. "
        "MCTS won more gauntlet and boss games. Random also beat the one-round "
        "policy in one gauntlet repeat and one boss repeat. The new baseline "
        "makes the comparison more demanding without establishing a universal ranking.",
        "",
        "## Method and reproduction",
        "",
        "The [protocol](comparison-protocol.json) was fixed before these outcomes. "
        "Each repeat used environment seeds 0 through 4 for every policy and scenario. "
        "The search seeds were 7, 42 and 99. Their corresponding policy seed ranges "
        "were 7 through 11, 42 through 46 and 99 through 103. Policy randomness is "
        "separate from the environment. MCTS starts a fresh search stream per "
        "scenario and continues it across that scenario's five games.",
        "",
        "At each decision, the new policy enumerates legal actions and samples "
        "eight one-round successors per action. Every candidate starts from the "
        "same eight sample seeds, although its subsequent draw path can differ. "
        "It uses terminal results or the existing state heuristic. This decision "
        "algorithm does not use the search tree, but it shares the simulator and "
        "heuristic with MCTS. It is not independent ground truth.",
        "",
        "MCTS receives 300 simulations per decision, a five-round horizon and a "
        "60-second safety cap. All runs use one process. The comparator's successor "
        "transitions and MCTS simulations are different work units. One simulation "
        "can advance several rounds, so these are unequal compute budgets and "
        "do not support an efficiency claim.",
        "",
        "```sh",
        "python benchmark.py 5 --sims 300 --seed 7 --policy-seed 7 "
        "--one-round-samples 8 --json seed-7.json",
        "python benchmark.py 5 --sims 300 --seed 42 --policy-seed 42 "
        "--one-round-samples 8 --json seed-42.json",
        "python benchmark.py 5 --sims 300 --seed 99 --policy-seed 99 "
        "--one-round-samples 8 --json seed-99.json",
        "python tools/render_comparison.py --check",
        "```",
        "",
        "The last command checks the committed report against the retained JSON. "
        "It does not run another experiment. The benchmark's legacy console "
        "intervals and z statistics are not used in this report.",
        "",
        "## Every measured condition",
        "",
        "Each entry reports clean wins out of five. These are paired repeated "
        "conditions over only five distinct environment seeds per scenario, not "
        "15 independent trials. Greedy is deterministic and repeats the same "
        "outcomes. No confidence interval or significance claim is made.",
        "",
        "| Scenario | Search / policy seed base | Random | Greedy | One round | MCTS |",
        "|---|---|---|---|---|---|",
    ]
    rows = [(name, run["settings"]["search_seed"], row)
            for run in report["runs"] for name, row in run["results"].items()]
    for name, seed, row in rows:
        cells = " | ".join(f"{row[p]['wins']}/{row[p]['games']}" for p in labels)
        lines.append(f"| {name} | {seed} | {cells} |")
    lines += ["", "Mean shaped score includes partial credit for unfinished games. "
              "It is not a win probability.", "",
              "| Scenario | Seed base | Random | Greedy | One round | MCTS |",
              "|---|---|---|---|---|---|"]
    for name, seed, row in rows:
        cells = " | ".join(f"{row[p]['avg_score']:.4f}" for p in labels)
        lines.append(f"| {name} | {seed} | {cells} |")
    lines += ["", "Average rounds to win, conditional on winning. A dash means "
              "no clean win, not zero rounds.", "",
              "| Scenario | Seed base | Random | Greedy | One round | MCTS |",
              "|---|---|---|---|---|---|"]
    for name, seed, row in rows:
        values = [row[p]["avg_rounds_to_win"] for p in labels]
        cells = " | ".join("-" if value is None else f"{value:.2f}" for value in values)
        lines.append(f"| {name} | {seed} | {cells} |")
    lines += ["", "## Observed work", "",
              "| Scenario | Seed base | One-round decisions | Successor transitions | "
              "MCTS decisions | MCTS simulations | Shortfalls |",
              "|---|---|---|---|---|---|---|"]
    for name, seed, row in rows:
        one = row[labels[2]]["one_round_work"]["decision_transitions"]
        search = row[labels[3]]["search_work"]
        counts = search["decision_simulations"]
        lines.append(f"| {name} | {seed} | {len(one)} | {sum(one)} | {len(counts)} | "
                     f"{sum(counts)} | {search['below_requested_simulations']} |")
    elapsed = report["evaluation"]["benchmark_elapsed_seconds"]
    env = report["runs"][0]["environment"]
    lines += [
        "",
        f"The three sequential runs took {elapsed:.2f} seconds inside the benchmark "
        f"on Python {env['python']}, {env['platform']}. This is an environment "
        "record, not a timed comparison between policies. Every observed MCTS "
        "decision reached its requested 300 simulations.",
        "",
        "## Evidence and limits",
        "",
        "[Retained JSON](comparison-results.json) includes every individual game, "
        "its environment and policy seed, score, terminal result and round count. "
        "It also retains the per-decision work counts, run settings and normalized "
        "decision-source hashes captured before evaluation. Hashes use UTF-8 text "
        "with LF newlines and no BOM, so checkout line endings do not change identity.",
        "",
        "The five environment seeds are a small fixed sample. Search randomness "
        "continues between games and the repeats reuse those environments. Neither "
        "wins nor shaped scores establish calibrated uncertainty or general playing "
        "strength. Different actions can consume different environment draws even "
        "when the initial seeds match. Parallel search and larger budgets were not "
        "evaluated here. No policy parameters were tuned after these results.",
        "",
        "The zero boss wins for the one-round policy and MCTS's unfinished duel "
        "remain in the record. A useful next experiment would test a predeclared "
        "set of new environment seeds with matched transition or elapsed-work "
        "accounting. "
        "The historical reports remain separate and unchanged.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = json.loads((ROOT / "docs/comparison-results.json").read_text("utf-8-sig"))
    destination = ROOT / "docs/comparison-results.md"
    text = render(data)
    if args.check:
        if destination.read_text("utf-8") != text:
            raise SystemExit("comparison report differs from retained results")
        print("Comparison report matches retained results.")
    else:
        destination.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
