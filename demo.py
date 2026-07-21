"""Show the engine making one decision, with its ranked options.

    python demo.py            # default: the boss fight
    python demo.py gauntlet   # or: duel | gauntlet | boss
"""
from __future__ import annotations

import random
import sys
import time

from engine.mcts import MCTS
from game.content import SCENARIOS


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "boss"
    scenario = SCENARIOS.get(name)
    if scenario is None:
        print(f"unknown scenario {name!r}; choose from {list(SCENARIOS)}")
        raise SystemExit(2)

    rng = random.Random(7)
    state, _ = scenario(rng)

    player = state.player
    print(f"Scenario: {name}")
    print(f"You: {player.name}  HP {player.hp}/{player.max_hp}  "
          f"pips {player.pips}+{player.power_pips}p")
    for e in state.enemies:
        tag = " [boss]" if e.is_boss else ""
        print(f"  vs {e.name}{tag}  HP {e.hp}/{e.max_hp}")
    print(f"Hand: {', '.join(c.name for c in state.hand)}")
    for r in state.boss_rules:
        print(f"  rule: {r.description}")

    mcts = MCTS(horizon_rounds=6)
    mcts.max_sims = 1_000_000
    t0 = time.perf_counter()
    ranked = mcts.search(state, time_budget_ms=800)
    dt = time.perf_counter() - t0

    print(f"\n{mcts.last_sims:,} simulations in {dt*1000:.0f} ms "
          f"({mcts.last_sims / dt:,.0f}/s)\n")
    print(f"{'move':32}{'win%':>8}{'visits':>10}")
    for r in ranked[:8]:
        print(f"{r.label:32}{r.win_rate:>7.1%}{r.visits:>10,}")
    print(f"\nRecommended: {ranked[0].label}")


if __name__ == "__main__":
    main()
