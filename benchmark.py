"""Measure the search against baseline policies across every scenario.

Each policy plays the same seeded games, so the comparison is paired. The
point of the exercise: a searching player should clear the "always hit
hardest" greedy baseline by a wide margin, because it learns to blade before
it hits, shield and heal to survive, focus-fire a gauntlet, and race a boss
before the enrage timer.

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
import os
import platform
import time

from game.baselines import greedy_decider, mcts_decider, random_decider
from game.content import SCENARIOS
from game.runner import Decider, play_match
from game.stats import two_proportion_z, wilson_interval

# {scenario: {policy: play_match() result}}
Results = dict[str, dict[str, dict]]


def _policies(budget_ms: int) -> dict[str, Decider]:
    return {
        "random": random_decider,
        "greedy": greedy_decider,
        f"mcts ({budget_ms} ms)": mcts_decider(budget_ms=budget_ms, horizon=5),
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
                    machine: str = "", elapsed_s: float = 0.0) -> str:
    """The README results table, with provenance, from one benchmark run."""
    policies = list(next(iter(results.values())))
    search = policies[-1]
    lines = [
        f"{games} games per policy per scenario, game seeds paired across "
        f"policies; {budget_ms} ms of search per decision, single process.",
        f"Python {platform.python_version()} on {platform.platform()}, "
        f"{os.cpu_count()} logical CPUs"
        + (f"; {machine}" if machine else "") + ".",
        f"Run on {dt.date.today().isoformat()}"
        + (f" in {elapsed_s / 60:.1f} min" if elapsed_s else "") + ".",
        "",
        "| scenario | " + " | ".join(policies) + " | search vs best baseline |",
        "|---|" + "---|" * (len(policies) + 1),
    ]
    for sname, row in results.items():
        top = max(row[p]["wins"] for p in policies)
        cells = []
        for p in policies:
            cell = _cell(row[p], dash="–", dot="·")
            cells.append(f"**{cell}**" if row[p]["wins"] == top else cell)
        best, z = _versus_best_baseline(row, search)
        cells.append(f"z = {z:.2f} vs {best}")
        lines.append(f"| {sname} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "*win % = clean wins (95% Wilson interval) · Nr = average rounds "
        "to win, when it won · bold = best in row*",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Search vs baselines on every scenario, seeds paired.")
    ap.add_argument("games", nargs="?", type=int, default=60,
                    help="games per policy per scenario (default 60)")
    ap.add_argument("budget_ms", nargs="?", type=int, default=120,
                    help="search budget per decision in ms (default 120)")
    ap.add_argument("--markdown", metavar="PATH",
                    help="also write the table as markdown with provenance")
    ap.add_argument("--machine", default="",
                    help='free-text machine description for the markdown, '
                         'e.g. "Ryzen 7 7800X3D"')
    args = ap.parse_args()

    policies = _policies(args.budget_ms)
    search = list(policies)[-1]
    results: Results = {}

    print(f"{args.games} games per policy, seeds paired across policies\n")
    header = f"{'scenario':12}" + "".join(f"{p:>24}" for p in policies)
    print(header)
    print("-" * len(header))
    t0 = time.perf_counter()
    for sname, scenario in SCENARIOS.items():
        row = {pname: play_match(scenario, decider, games=args.games)
               for pname, decider in policies.items()}
        results[sname] = row
        best, z = _versus_best_baseline(row, search)
        print(f"{sname:12}" + "".join(f"{_cell(row[p]):>24}" for p in policies)
              + f"   z = {z:.2f} vs {best}")
    elapsed = time.perf_counter() - t0
    print("\nwin% = clean wins (95% Wilson interval); Nr = average rounds to "
          f"win when it won; {elapsed / 60:.1f} min")

    if args.markdown:
        text = render_markdown(results, args.games, args.budget_ms,
                               machine=args.machine, elapsed_s=elapsed)
        with open(args.markdown, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"markdown table written to {args.markdown}")


if __name__ == "__main__":
    main()
