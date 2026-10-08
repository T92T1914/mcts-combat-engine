"""Make repeated fixed-work decisions with the installed engine.

Install a wheel, then run this file outside its source checkout. On Windows
the main guard lets the owned worker processes import the entry point safely.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict

from engine import Card, Combatant, Element, GameState, mcts_decider


def main() -> None:
    state = GameState(
        Combatant("Player", Element.NEUTRAL, 100, 100),
        [Combatant("Opponent", Element.NEUTRAL, 100, 100)],
        [Card("Hit", accuracy=1.0, damage_min=20, damage_max=30)],
    )
    with mcts_decider(
        parallel=True, workers=2, horizon=2, mode="fixed", budget_ms=None,
        seed=7, max_sims=12, max_transitions=24,
    ) as choose:
        for call, seed in enumerate((None, None, 23, None), start=1):
            action = (choose(state, random.Random(99)) if seed is None
                      else choose.decide(state, seed=seed))
            assert choose.last_report is not None
            print(json.dumps({"decision": call, "action": asdict(action),
                              "work": asdict(choose.last_report)}, sort_keys=True))
    try:
        choose.decide(state)
    except RuntimeError as error:
        print(json.dumps({"after_close": str(error)}, sort_keys=True))


if __name__ == "__main__":
    main()
