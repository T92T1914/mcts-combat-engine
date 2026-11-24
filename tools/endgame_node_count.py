"""Count the distinct decision states in the exact tree under a saved state.

This is the node counting pass of the exact endgame values study. It runs
before any solver exists and it reads no win chance. It plays the engine's own
``advance_round`` under every chance outcome and counts the distinct states
that can follow, round by round, until a win, a loss or the round limit. A
state fits under a cap when its whole tree holds no more distinct states than
the cap. The count is a size, never a probability.

The chance model is the one the search simulates. The hand is fixed and the
game layer never refills it inside the tree. Every draw the simulator makes is
branched. A comparison of a uniform draw against a threshold gives two
outcomes, an integer draw gives one outcome per integer, and a weighted choice
gives one outcome per option with weight above zero.
"""
# The standalone entry needs its own root before local imports.
# ruff: noqa: E402
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import GameState, advance_round, legal_actions
from engine.actions import Action
from game.episode_decision import _reconstruct
from game.episode_record import canonical, record_episode

TOP = 1.0 - 2.0**-53      # the largest value a binary53 uniform draw takes


class _Draw(float):
    """A uniform draw whose comparisons are decided by the current path."""

    _rng: PathRng

    def __new__(cls, rng: PathRng) -> _Draw:
        draw = super().__new__(cls, 0.5)
        draw._rng = rng
        return draw

    def _pick(self, true_possible: bool, false_possible: bool) -> bool:
        if true_possible and false_possible:
            return self._rng.branch(2) == 0
        return true_possible

    def __gt__(self, t: float) -> bool:
        return self._pick(t < TOP, t >= 0.0)

    def __ge__(self, t: float) -> bool:
        return self._pick(t <= TOP, t > 0.0)

    def __lt__(self, t: float) -> bool:
        return self._pick(t > 0.0, t <= TOP)

    def __le__(self, t: float) -> bool:
        return self._pick(t >= 0.0, t < TOP)


class PathRng(random.Random):
    """A random source that follows a script of branch choices.

    Any draw the simulator makes that is not branched here raises, so a new
    kind of draw in the engine cannot be counted by accident.
    """

    def __init__(self, script: list[int]) -> None:
        super().__init__(0)
        self.script = script
        self.widths: list[int] = []

    def branch(self, width: int) -> int:
        position = len(self.widths)
        if position < len(self.script):
            choice = self.script[position]
        else:
            choice = 0
            self.script.append(0)
        self.widths.append(width)
        return choice

    def random(self) -> float:
        return _Draw(self)

    def randint(self, a: int, b: int) -> int:
        return a + self.branch(b - a + 1) if b > a else a

    def choices(self, population, weights=None, *, cum_weights=None, k=1):
        if k != 1 or weights is None or cum_weights is not None:
            raise NotImplementedError("only one weighted choice is branched")
        live = [i for i, w in enumerate(weights) if w > 0]
        pick = live[self.branch(len(live)) if len(live) > 1 else 0]
        return [population[pick]]

    def getrandbits(self, k: int) -> int:
        raise NotImplementedError("an unbranched draw reached the simulator")


def outcomes(run: Callable[[PathRng], Any]) -> Iterator[Any]:
    """Yield the result of ``run`` under every path of chance outcomes."""
    script: list[int] = []
    while True:
        rng = PathRng(script)
        yield run(rng)
        i = len(rng.widths) - 1
        while i >= 0 and script[i] == rng.widths[i] - 1:
            i -= 1
        if i < 0:
            return
        del script[i + 1:]
        script[i] += 1


def _fighter_key(c) -> tuple:
    return (c.hp, c.pips, c.power_pips,
            tuple((x.value, x.element.value) for x in c.blades),
            tuple((x.value, x.element.value) for x in c.traps),
            tuple((x.value, x.element.value) for x in c.shields),
            tuple((d.tick, d.rounds_left, d.element.value) for d in c.dots))


def state_key(state: GameState) -> tuple:
    """A key equal for states that play identically from here on.

    A fallen enemy keeps no effects that matter, and the hand is a multiset
    because the value of a state does not depend on the order of its cards.
    """
    result = state.result()
    if result is not None:
        return ("terminal", result)
    return (state.round_num, _fighter_key(state.player),
            tuple(_fighter_key(e) if e.alive else ("down",)
                  for e in state.enemies),
            tuple(sorted(c.name for c in state.hand)))


class Over(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def count_tree(root: GameState, rounds_left: int, branch_cap: int,
               node_cap: int = 200_000) -> dict:
    """Count the work in the exact tree under ``root`` for ``rounds_left`` rounds.

    ``nodes`` is the number of distinct states. ``branches`` is the number of
    chance outcomes expanded, which is the work a solver with a transposition
    table does. Counting stops as soon as the branches pass ``branch_cap`` or
    the nodes pass ``node_cap``. The status says which, and a stopped count is
    a lower bound.
    """
    seen: set[tuple] = {state_key(root)}
    frontier = [root]
    replays = 0
    depth = 0
    found: dict[tuple, GameState] = {}
    status = "fits"
    try:
        while frontier and depth < rounds_left:
            found = {}
            last_round = depth + 1 == rounds_left
            for state in frontier:
                for action in legal_actions(state):
                    def run(rng: PathRng, s: GameState = state,
                            a: Action = action) -> GameState:
                        return advance_round(s.clone(), a, rng)
                    for after in outcomes(run):
                        replays += 1
                        if replays > branch_cap:
                            raise Over("branches")
                        if after.result() is not None:
                            key: tuple = state_key(after)
                        elif last_round:
                            key = ("limit",)
                        else:
                            key = state_key(after)
                        if key in seen or key in found:
                            continue
                        found[key] = after
                        if len(seen) + len(found) > node_cap:
                            raise Over("nodes")
            seen.update(found)
            frontier = [s for k, s in found.items()
                        if k[0] not in ("terminal", "limit")]
            depth += 1
    except Over as over:
        status = "over_" + over.reason
        seen.update(found)
    return {"status": status, "nodes": len(seen), "branches": replays,
            "depth": depth}


def episode_states(scenario: str, seed: int, episode: dict) -> Iterator[dict]:
    """Yield each decision state of a recorded episode."""
    rounds = episode["max_rounds"]
    record = record_episode(
        scenario, environment_seed=seed, search_seed=seed, rounds=rounds,
        sims=episode["sims"], horizon=episode["horizon"])
    for step in record["steps"]:
        state = _reconstruct(step["state"], "state")
        yield {"scenario": scenario, "environment_seed": seed,
               "step": step["index"], "round_num": state.round_num,
               "rounds_left": rounds - state.round_num + 1,
               "sha256": hashlib.sha256(canonical(step["state"])).hexdigest(),
               "state": state}


def run(protocol: dict, branch_cap: int, scenarios=None, seeds=None) -> dict:
    rows = []
    for scenario in scenarios or protocol["scenarios"]:
        for seed in seeds or protocol["environment_seeds"]:
            for item in episode_states(scenario, seed, protocol["episode"]):
                begun = time.perf_counter()
                state = item.pop("state")
                result = count_tree(state, item["rounds_left"], branch_cap)
                item.update(result)
                item["seconds"] = round(time.perf_counter() - begun, 3)
                rows.append(item)
    return {"branch_cap": branch_cap, "states": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("protocol", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--branch-cap", type=int, required=True)
    parser.add_argument("--scenario", action="append")
    args = parser.parse_args(argv)
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    result = run(protocol, args.branch_cap, args.scenario)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
