"""Exercise the public managed policy from an external wheel installation.

Run with the installed interpreter's -I flag from outside the checkout. The
CI job supplies a process-group timeout around this disposable consumer. That
test limit does not change the production retirement contract.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import multiprocessing as mp
import random
import sysconfig
from pathlib import Path

import engine
from engine import (
    Card,
    Combatant,
    Element,
    GameState,
    legal_actions,
    mcts_decider,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def require_closed(choose, state: GameState) -> None:
    for operation in (lambda: choose(state, random.Random(2)), choose.__enter__):
        try:
            operation()
        except RuntimeError as error:
            require("closed" in str(error), "Unexpected post-close refusal")
        else:
            raise RuntimeError("A closed policy admitted work or context entry")
    choose.close()


def main() -> None:
    origin = Path(engine.__file__).resolve()
    installed = Path(sysconfig.get_path("purelib")).resolve()
    require(origin.is_relative_to(installed),
            "Engine was not imported from site-packages")
    require(importlib.util.find_spec("game") is None,
            "Worked example leaked into install")
    require(not mp.active_children(), "Consumer started with unrelated child processes")
    state = GameState(
        Combatant("Player", Element.NEUTRAL, 100, 100),
        [Combatant("Opponent", Element.NEUTRAL, 100, 100)],
        [Card("Hit", accuracy=1.0, damage_min=20, damage_max=20)],
    )
    counts: list[int] = []
    serial = mcts_decider(
        budget_ms=60_000, horizon=1, seed=7, max_sims=8,
        on_search=counts.append,
    )
    with serial as choose:
        require(choose(state, random.Random(2)) in legal_actions(state),
                "Illegal serial action")
    require(counts == [8], "Serial public callback did not report its fixed work")
    require_closed(serial, state)

    counts = []
    parallel = mcts_decider(
        budget_ms=20, horizon=1, parallel=True, workers=2,
        on_search=counts.append,
    )
    with parallel as choose:
        require(choose(state, random.Random(2)) in legal_actions(state),
                "Illegal parallel action")
        first = set(mp.active_children())
        require(len(first) == 2 and all(p.is_alive() for p in first),
                "Two workers not alive")
        require(choose(state, random.Random(2)) in legal_actions(state),
                "Illegal reused action")
        require(set(mp.active_children()) == first, "Policy did not reuse its workers")
        require(all(p.is_alive() for p in first), "A retained worker exited early")
    require(len(counts) == 2 and all(n > 0 for n in counts),
            "Parallel work was not reported")
    require(all(not p.is_alive() and p.exitcode is not None for p in first),
            "Workers not retired")
    require(not mp.active_children(), "Consumer retained a child after context exit")
    require_closed(parallel, state)
    print(json.dumps({
        "status": "passed",
        "package_version": importlib.metadata.version("mcts-combat-engine"),
        "engine_origin": str(origin),
        "serial_simulations": 8,
        "parallel_simulations": counts,
        "workers_reused": 2,
        "worker_exitcodes": sorted(p.exitcode for p in first),
        "post_close_refused": True,
        "active_children_after": 0,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
