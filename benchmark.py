"""Measure the search against baseline policies across every scenario.

Policies start from the same environment seeds, with separate policy and
search streams. Search is reseeded for each scenario so reordering scenarios
does not alter a fixed-budget result. Different actions can still lead to
different random outcomes. These simple baselines are a starting comparison,
not evidence of general playing strength.

    python benchmark.py                      # quick: 60 games/policy, 120 ms search
    python benchmark.py 200 300              # thorough: 200 games, 300 ms search
    python benchmark.py --markdown results.md --machine "Ryzen 7 7800X3D"

The search runs in a single process here, so every number describes one
core. Each cell carries a 95% Wilson interval and each row a z-score for
the search against its best baseline (see ``game/stats.py``); the markdown
output records the interpreter and machine so a table is never quoted
without the box it came from.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import time
from collections.abc import Callable
from pathlib import Path

from game.baselines import greedy_decider, mcts_decider, random_decider
from game.content import SCENARIOS
from game.runner import Decider, play_match
from game.stats import two_proportion_z, wilson_interval

# {scenario: {policy: play_match() result}}
Results = dict[str, dict[str, dict]]


def _search_label(budget_ms: int, sims: int | None) -> str:
    return f"mcts ({sims} sims)" if sims is not None else f"mcts ({budget_ms} ms)"


def _policies(budget_ms: int, sims: int | None = None,
              seed: int = 42, *,
              on_search: Callable[[int], None] | None = None) -> dict[str, Decider]:
    label = _search_label(budget_ms, sims)
    return {
        "random": random_decider,
        "greedy": greedy_decider,
        label: mcts_decider(budget_ms=60000 if sims is not None else budget_ms,
                            horizon=5, max_sims=sims,
                            seed=seed if sims is not None else None,
                            on_search=on_search),
    }


def _cell(r: dict, dash: str = "-", dot: str = "/") -> str:
    """'55% (43-67) / 23.4r': win rate, 95% interval, rounds to win."""
    lo, hi = wilson_interval(r["wins"], r["games"])
    text = f"{r['win_rate']:.0%} ({lo * 100:.0f}{dash}{hi * 100:.0f})"
    rounds = r["avg_rounds_to_win"]
    if rounds is not None:
        text += f" {dot} {rounds:.1f}r"
    return text


def _versus_best_baseline(row: dict[str, dict], search: str) -> tuple[str, float]:
    """Name of the strongest baseline in this row and z for search vs it."""
    best = max((p for p in row if p != search), key=lambda p: row[p]["wins"])
    z = two_proportion_z(row[search]["wins"], row[search]["games"],
                         row[best]["wins"], row[best]["games"])
    return best, z


def render_markdown(results: Results, games: int, budget_ms: int,
                    machine: str = "", elapsed_s: float = 0.0,
                    sims: int | None = None, seed: int = 42, *,
                    game_seed: int = 0, policy_seed: int = 0) -> str:
    """The README results table, with provenance, from one benchmark run."""
    policies = list(next(iter(results.values())))
    search = policies[-1]
    lines = [
        f"{games} games per policy per scenario, game seeds paired across "
        "policies; " + (f"{sims} simulations per decision, search seed {seed}, "
                        "horizon 5, 60 second safety cap, single process."
                        if sims is not None else
                        f"{budget_ms} ms of search per decision, single process."),
        f"Python {platform.python_version()} on {platform.platform()}, "
        f"{os.cpu_count()} logical CPUs"
        + (f"; {machine}" if machine else "") + ".",
        f"Run on {dt.date.today().isoformat()}"
        + (f" in {elapsed_s / 60:.1f} min" if elapsed_s else "") + ".",
        f"Environment seeds {game_seed} to {game_seed + games - 1}. "
        f"Policy seeds {policy_seed} to {policy_seed + games - 1}, "
        "using separate policy-v1 streams. Search starts fresh per scenario "
        "and continues across that scenario's games.",
        "",
        "| scenario | " + " | ".join(policies) + " | search vs best baseline |",
        "|---|" + "---|" * (len(policies) + 1),
    ]
    for sname, row in results.items():
        top = max(row[p]["wins"] for p in policies)
        cells = []
        for p in policies:
            cell = _cell(row[p], dash=" to ", dot="·")
            cells.append(f"**{cell}**" if row[p]["wins"] == top else cell)
        best, z = _versus_best_baseline(row, search)
        cells.append(f"z = {z:.2f} vs {best}")
        lines.append(f"| {sname} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "*win % = clean wins (95% Wilson interval) · Nr = average rounds "
        "to win, when it won · bold = best in row*",
    ]
    measured = [(name, row[search]["search_work"]) for name, row in results.items()
                if "search_work" in row[search]]
    if measured:
        lines += ["", "Observed search work:", "",
                  "| scenario | decisions | simulations | per decision min/max | "
                  "fixed-budget shortfalls |",
                  "|---|---|---|---|---|"]
        for name, work in measured:
            counts = work["decision_simulations"]
            span = f"{min(counts)}/{max(counts)}" if counts else "not run"
            shortfalls = work["below_requested_simulations"]
            lines.append(f"| {name} | {len(counts)} | {sum(counts)} | {span} | "
                         f"{shortfalls if shortfalls is not None else 'n/a'} |")
        lines += ["", "A fixed-budget shortfall means the safety time limit "
                  "stopped a nonterminal decision before its requested count. "
                  "Such a run is not a completed fixed-budget comparison."]
    return "\n".join(lines) + "\n"


def render_json(results: Results, games: int, budget_ms: int,
                machine: str = "", elapsed_s: float = 0.0,
                sims: int | None = None, seed: int = 42, *,
                game_seed: int = 0, policy_seed: int = 0) -> str:
    """Export aggregate results and the settings that produced them.

    Timed search uses unseeded search randomness. The game seeds remain paired,
    but recording a seed here would falsely suggest a repeatable search run.
    """
    report = {
        "schema_version": 2,
        "run_date": dt.date.today().isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "logical_cpus": os.cpu_count(),
            "machine": machine,
        },
        "settings": {
            "games_per_policy": games,
            "game_seeds": list(range(game_seed, game_seed + games)),
            "policy_seeds": list(range(policy_seed, policy_seed + games)),
            "policy_seed_format": "policy-v1:{seed} (Python Random string seed)",
            "mode": "fixed_simulations" if sims is not None else "timed",
            "max_simulations": sims,
            "search_seed": seed if sims is not None else None,
            "search_seed_scope": "reset_per_scenario_then_persistent_across_games",
            "time_limit_ms": 60000 if sims is not None else budget_ms,
            "horizon": 5,
            "processes": 1,
        },
        "elapsed_s": elapsed_s,
        "results": results,
    }
    return json.dumps(report, indent=2, allow_nan=False) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Search vs baselines on every scenario, seeds paired.")
    ap.add_argument("games", nargs="?", type=int, default=60,
                    help="games per policy per scenario (default 60)")
    ap.add_argument("budget_ms", nargs="?", type=int, default=120,
                    help="search budget per decision in ms (default 120)")
    ap.add_argument("--markdown", metavar="PATH",
                    help="also write the table as markdown with provenance")
    ap.add_argument("--json", type=Path, metavar="PATH",
                    help="also write aggregate results and settings as JSON")
    ap.add_argument("--sims", type=int,
                    help="fixed simulations per decision (60-second safety cap)")
    ap.add_argument("--seed", type=int, default=42,
                    help="search seed for --sims mode (default 42)")
    ap.add_argument("--game-seed", type=int, default=0,
                    help="first environment seed (default 0)")
    ap.add_argument("--policy-seed", type=int, default=0,
                    help="first policy seed, separate from environment (default 0)")
    ap.add_argument("--machine", default="",
                    help='free-text machine description for the markdown, '
                         'e.g. "Ryzen 7 7800X3D"')
    args = ap.parse_args()
    if (args.games < 1 or args.budget_ms < 1
            or (args.sims is not None and args.sims < 1)):
        ap.error("games, budget_ms and sims must be positive")
    if (args.json and args.markdown
            and args.json.resolve() == Path(args.markdown).resolve()):
        ap.error("JSON and Markdown output paths must be different")

    policy_names = ["random", "greedy", _search_label(args.budget_ms, args.sims)]
    search = policy_names[-1]
    results: Results = {}

    print(f"{args.games} games per policy, seeds paired across policies\n")
    header = f"{'scenario':12}" + "".join(f"{p:>24}" for p in policy_names)
    print(header)
    print("-" * len(header))
    t0 = time.perf_counter()
    for sname, scenario in SCENARIOS.items():
        counts: list[int] = []
        policies = _policies(args.budget_ms, args.sims, args.seed,
                             on_search=counts.append)
        row = {pname: play_match(scenario, decider, games=args.games,
                                seed=args.game_seed, policy_seed=args.policy_seed)
               for pname, decider in policies.items()}
        row[search]["search_work"] = {
            "decision_simulations": counts,
            "below_requested_simulations": (
                sum(count < args.sims for count in counts)
                if args.sims is not None else None),
        }
        results[sname] = row
        best, z = _versus_best_baseline(row, search)
        print(f"{sname:12}" + "".join(f"{_cell(row[p]):>24}" for p in policies)
              + f"   z = {z:.2f} vs {best}")
        shortfalls = row[search]["search_work"]["below_requested_simulations"]
        if shortfalls:
            print(f"  Incomplete fixed budget: {shortfalls} decisions stopped "
                  "at the safety time limit.")
    elapsed = time.perf_counter() - t0
    print("\nwin% = clean wins (95% Wilson interval); Nr = average rounds to "
          f"win when it won; {elapsed / 60:.1f} min")

    if args.markdown:
        text = render_markdown(results, args.games, args.budget_ms,
                               machine=args.machine, elapsed_s=elapsed,
                               sims=args.sims, seed=args.seed,
                               game_seed=args.game_seed, policy_seed=args.policy_seed)
        with open(args.markdown, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"markdown table written to {args.markdown}")
    if args.json:
        args.json.write_text(render_json(
            results, args.games, args.budget_ms, machine=args.machine,
            elapsed_s=elapsed, sims=args.sims, seed=args.seed,
            game_seed=args.game_seed, policy_seed=args.policy_seed), encoding="utf-8")
        print(f"JSON results written to {args.json}")


if __name__ == "__main__":
    main()
