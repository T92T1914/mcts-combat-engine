"""Open-loop Monte Carlo Tree Search over combat rounds.

Why open-loop: accuracy rolls, pip regeneration, and enemy behavior are all
stochastic, so a single action sequence can lead to many different states.
Rather than storing states in nodes (which would require explicit chance
nodes), the tree stores only ACTION sequences; every simulation replays its
path from the root state with fresh randomness. A node's statistics therefore
average over the outcome distribution — exactly what "win probability" means.

Usage::

    mcts = MCTS(horizon_rounds=4)
    ranked = mcts.search(state, time_budget_ms=450)
    for r in ranked:
        print(r.label, r.win_rate, r.visits)

One simulation is: select down the tree by UCB1 while replaying each chosen
action on a fresh clone of the root; expand one untried action; roll out
with uniform-random play to the horizon; back the shaped reward up the
path. Pure-Python throughput is on the order of 10,000 simulations per
second per core. To go faster: compile ``engine/`` with mypyc/Cython, run
under PyPy, or fan the search across cores with
:class:`engine.parallel.ParallelMCTS`.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from .actions import Action, legal_actions
from .simulator import advance_round
from .state import GameState


class Node:
    """One edge of the tree: the action that led here, plus the statistics
    of every simulation that has passed through it.

    No game state lives here (that is the open-loop choice): each descent
    rebuilds the state by replaying the path's actions from the root under
    fresh randomness. ``untried`` is None until the node is first used as a
    parent, then the legal actions not yet expanded from it.
    """
    # No explicit __slots__: a compiled (mypyc) build makes native classes
    # implicitly slotted, which is why every attribute is annotated and the
    # root's action/parent are typed Optional.
    action: "Action | None"
    parent: "Node | None"
    children: "list[Node]"
    untried: "list[Action] | None"
    visits: int
    value_sum: float

    def __init__(self, action: "Action | None", parent: "Node | None"):
        self.action = action          # edge that led here (None at root)
        self.parent = parent
        self.children = []
        self.untried = None           # lazily filled with legal actions
        self.visits = 0
        self.value_sum = 0.0

    @property
    def mean(self) -> float:
        return self.value_sum / self.visits if self.visits else 0.0

    def ucb1(self, c: float) -> float:
        """Upper confidence bound: mean plus an exploration bonus that
        shrinks as this node's share of the parent's visits grows. Unvisited
        children return +inf so every action is tried once before any is
        tried twice."""
        if self.visits == 0 or self.parent is None:
            return float("inf")
        return self.mean + c * math.sqrt(math.log(self.parent.visits) / self.visits)


@dataclass
class RankedAction:
    """One root action after a search: its label, estimated win rate (the
    mean reward of every simulation that started with it), and how many
    simulations that was."""
    action: Action
    label: str
    win_rate: float
    visits: int


@dataclass
class MCTS:
    """Single-process open-loop MCTS; see the module docstring for why the
    tree holds actions rather than states.

    horizon_rounds
        How far a rollout looks before scoring the position with
        ``GameState.heuristic_value()``. Deeper sees more of a fight, but
        every simulation costs more and the uniform-random rollout policy
        gets noisier with depth. The demo and the parallel engine use 6,
        the benchmark 5.
    exploration
        The UCB1 constant ``c``. Rewards here are in [0, 1], for which the
        textbook value is sqrt(2) ~ 1.41; 1.2 sits slightly on the
        exploitation side of that. It is a hand-chosen value, and this repo
        records no sweep of it.
    max_sims
        Hard cap on simulations, independent of the wall-clock budget. A
        time budget stops at a machine-dependent count, so pinning this
        (together with the seed) is what makes a search reproducible.
    rng
        The single source of randomness, so one seed reproduces a search
        exactly. Parallel workers each carry their own.
    last_sims
        Simulations actually run by the most recent ``search()``.
    """
    horizon_rounds: int = 4
    exploration: float = 1.2
    max_sims: int = 10_000
    rng: random.Random = field(default_factory=random.Random)
    last_sims: int = field(init=False, default=0)

    def search(self, root_state: GameState, time_budget_ms: int = 450,
               priors: "dict[str, tuple[int, float]] | None" = None,
               ) -> list[RankedAction]:
        """Search from ``root_state`` until the budget or ``max_sims`` runs
        out; return every root action ranked by estimated win rate, visits
        breaking ties.

        Ranking by mean rather than by visit count (the usual "robust
        child" rule) means a lightly visited action with a lucky mean can
        outrank a well-explored one; the visit column is reported so a
        reader can see when that is happening.

        ``priors``: ``{card_name: (games, win_rate)}`` from a self-play
        opening book. Book moves enter the root with VIRTUAL visits, so
        learned experience biases early exploration but is washed out (or
        confirmed) by real simulations — a simple way to close a learning
        loop.
        """
        deadline = time.perf_counter() + time_budget_ms / 1000.0
        root = Node(action=None, parent=None)
        root.untried = list(legal_actions(root_state))
        if priors:
            for a in list(root.untried):
                name = (root_state.hand[a.card_idx].name
                        if a.card_idx is not None
                        and a.card_idx < len(root_state.hand) else None)
                pr = priors.get(name) if name else None
                if pr:
                    games, wr = pr
                    v0 = max(1, min(30, 3 * int(games)))
                    child = Node(a, root)
                    child.visits = v0
                    child.value_sum = float(wr) * v0
                    root.children.append(child)
                    root.untried.remove(a)
                    root.visits += v0
        sims = 0

        while sims < self.max_sims and time.perf_counter() < deadline:
            state = root_state.clone()
            node = root
            depth = 0

            # --- selection: descend fully-expanded nodes by UCB1.
            # Stop if THIS realization already ended — deeper actions were
            # created under realizations where the duel was still live.
            while node.untried == [] and node.children and not state.is_terminal():
                node = max(node.children, key=lambda n: n.ucb1(self.exploration))
                act = node.action
                if act is None:           # never true below the root
                    break
                advance_round(state, act, self.rng)
                depth += 1

            # --- expansion: try one untested action
            if node.untried is None:
                node.untried = list(legal_actions(state))
            if node.untried and not state.is_terminal():
                action = node.untried.pop(self.rng.randrange(len(node.untried)))
                child = Node(action, node)
                node.children.append(child)
                advance_round(state, action, self.rng)
                depth += 1
                node = child
                node.untried = None   # filled on first visit as a parent

            # --- rollout: random play to horizon or terminal
            reward = self._rollout(state, depth)

            # --- backpropagation
            up: Node | None = node
            while up is not None:
                up.visits += 1
                up.value_sum += reward
                up = up.parent
            sims += 1

        ranked = [
            RankedAction(
                action=ch.action,
                label=ch.action.describe(root_state),
                win_rate=ch.mean,
                visits=ch.visits,
            )
            for ch in root.children
            if ch.action is not None      # always true below the root
        ]
        ranked.sort(key=lambda r: (r.win_rate, r.visits), reverse=True)
        self.last_sims = sims
        return ranked

    def _rollout(self, state: GameState, depth: int) -> float:
        """Uniform-random play from ``state`` until someone dies or the
        horizon arrives. Terminal states get the shaped reward below; a
        still-live horizon state is scored by the HP-differential heuristic,
        which is what keeps a shallow search from calling every unfinished
        fight a coin flip."""
        while depth < self.horizon_rounds:
            result = state.result()
            if result is not None:
                return self._terminal_reward(result, depth)
            acts = legal_actions(state)
            advance_round(state, acts[self.rng.randrange(len(acts))], self.rng)
            depth += 1
        result = state.result()
        if result is not None:
            return self._terminal_reward(result, depth)
        return state.heuristic_value()

    def _terminal_reward(self, result: float, depth: int) -> float:
        """Reward at a terminal (someone died) rollout state.

        WIN — time preference: a win now beats the same win several rounds
        later (mate-in-2 over mate-in-9). At a small per-round discount the
        gap between "bank pips, kill on round 3" and "chip away until round 6"
        falls under the noise floor of a live search and the engine looks
        indifferent to finishing fights. 4.5%/round (capped at 27%) makes the
        fast kill decisively better, while a win at max depth still dwarfs the
        best loss, so healing toward a win keeps full priority.

        LOSS — survival matters. A flat 0.0 for every loss makes the engine
        blind to staying alive: "heal and survive three more rounds" would
        score identically to "cast a useless card and die now". So a later
        loss is worth slightly more, which makes the engine heal/shield to
        stay alive when the win probability is ~0 — the human play. Capped at
        0.15, far below any real winning or surviving line, so it never stalls
        a fight it can win.
        """
        if result >= 1.0:
            return 1.0 - 0.045 * min(6, depth)
        # loss: 0 (died round 1) .. 0.15 (survived the full horizon then died).
        # depth is clamped because tree paths CAN outgrow the rollout horizon
        # (selection/expansion don't stop at it) — unclamped, a deep slow loss
        # would outscore a clean win, inverting the guarantee above.
        h = max(1, self.horizon_rounds)
        return 0.15 * (min(depth, h) / h)
