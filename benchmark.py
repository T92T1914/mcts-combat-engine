"""Measure the search against baseline policies across every scenario.

Each policy plays the same seeded games, so the comparison is paired. The
point of the exercise: a searching player should clear the "always hit
hardest" greedy baseline by a wide margin, because it learns to blade before
it hits, shield and heal to survive, focus-fire a gauntlet, and race a boss
before the enrage timer.

    python benchmark.py            # quick: 60 games/policy, 120 ms search
    python benchmark.py 200 300    # thorough: 200 games, 300 ms search
"""
from __future__ import annotations

import sys

from game.baselines import greedy_decider, mcts_decider, random_decider
from game.content import SCENARIOS
from game.runner import play_match


def main() -> None:
    games = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    budget_ms = int(sys.argv[2]) if len(sys.argv) > 2 else 120

    policies = {
        "random": random_decider,
        "greedy": greedy_decider,
        f"mcts({budget_ms}ms)": mcts_decider(budget_ms=budget_ms, horizon=5),
    }

    print(f"{games} games per policy, seeds paired across policies\n")
    header = f"{'scenario':12}" + "".join(f"{p:>18}" for p in policies)
    print(header)
    print("-" * len(header))
    for sname, scenario in SCENARIOS.items():
        row = f"{sname:12}"
        for decider in policies.values():
            r = play_match(scenario, decider, games=games)
            rounds = r["avg_rounds_to_win"]
            cell = f"{r['win_rate']:.0%}" + (f" / {rounds:.1f}r" if rounds else "")
            row += f"{cell:>18}"
        print(row)
    print("\nwin% = clean player wins; Nr = average rounds to win when it won")


if __name__ == "__main__":
    main()
