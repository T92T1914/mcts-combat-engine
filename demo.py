"""Show the engine making one decision, with its ranked options.

    python demo.py                      # default: the boss fight, 800 ms
    python demo.py gauntlet             # or: duel | gauntlet | boss
    python demo.py boss --sims 10000    # pinned: the same table on any machine

A wall-clock budget stops at a machine-dependent simulation count, so two
timed runs never agree exactly. ``--sims`` replaces the budget with a fixed
count; together with the search seed (``--seed``, default 7, the same seed
that deals the hand) that makes the printed table reproducible bit for bit,
which is how the README's example was produced.
"""
from __future__ import annotations

import argparse
import random
import time

from engine.mcts import MCTS
from game.content import SCENARIOS


def main() -> None:
    ap = argparse.ArgumentParser(description="One search decision, ranked.")
    ap.add_argument("scenario", nargs="?", default="boss",
                    choices=sorted(SCENARIOS), help="default: boss")
    ap.add_argument("--budget-ms", type=int, default=800,
                    help="wall-clock search budget (default 800)")
    ap.add_argument("--sims", type=int, default=None,
                    help="run exactly this many simulations instead of a "
                         "time budget; makes the table reproducible")
    ap.add_argument("--seed", type=int, default=7,
                    help="seed for the search RNG (default 7)")
    ap.add_argument("--horizon", type=int, default=6,
                    help="rollout horizon in rounds (default 6)")
    args = ap.parse_args()

    rng = random.Random(7)                  # deals the hand; fixed on purpose
    state, _ = SCENARIOS[args.scenario](rng)

    player = state.player
    print(f"Scenario: {args.scenario}")
    print(f"You: {player.name}  HP {player.hp}/{player.max_hp}  "
          f"pips {player.pips}+{player.power_pips}p")
    for e in state.enemies:
        tag = " [boss]" if e.is_boss else ""
        print(f"  vs {e.name}{tag}  HP {e.hp}/{e.max_hp}")
    print(f"Hand: {', '.join(c.name for c in state.hand)}")
    for r in state.boss_rules:
        print(f"  rule: {r.description}")

    mcts = MCTS(horizon_rounds=args.horizon, rng=random.Random(args.seed))
    if args.sims is not None:
        mcts.max_sims = args.sims
        budget_ms = 10 * 60 * 1000          # the count, not the clock, stops it
    else:
        mcts.max_sims = 1_000_000
        budget_ms = args.budget_ms
    t0 = time.perf_counter()
    ranked = mcts.search(state, time_budget_ms=budget_ms)
    dt = time.perf_counter() - t0

    print(f"\n{mcts.last_sims:,} simulations in {dt*1000:.0f} ms "
          f"({mcts.last_sims / dt:,.0f}/s)\n")
    print(f"{'move':32}{'reward':>8}{'visits':>10}")
    for r in ranked[:8]:
        print(f"{r.label:32}{r.win_rate:>8.3f}{r.visits:>10,}")
    print(f"\nRecommended: {ranked[0].label}")


if __name__ == "__main__":
    main()
