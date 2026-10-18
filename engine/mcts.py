"""Open-loop Monte Carlo Tree Search over combat rounds.

Why open-loop: accuracy rolls, pip regeneration, and enemy behavior are all
stochastic, so a single action sequence can lead to many different states.
Rather than storing states in nodes (which would require explicit chance
nodes), the tree stores only ACTION sequences; every simulation replays its
path from the root state with fresh randomness. A node's statistics therefore
average shaped rewards over sampled outcomes, not calibrated win probabilities.

Usage::

    mcts = MCTS(horizon_rounds=4)
    ranked = mcts.search(state, time_budget_ms=450)
    for r in ranked:
        print(r.label, r.win_rate, r.visits)

One simulation is: select down the tree by UCB1 while replaying each chosen
action on a fresh clone of the root; expand one untried action; roll out
with uniform-random play to the horizon; back the shaped reward up the
path. Throughput depends on legal branching and horizon; measure it with
the supplied benchmark. Independent workers are available through
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


def _validate_nonnegative_finite(value: float, name: str) -> None:
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or value < 0):
        raise ValueError(f"{name} must be a finite, nonnegative number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"{name} must be a finite, nonnegative number")


def _validate_priors(priors: dict | None) -> None:
    """Validate the whole book before any tree, random draw or worker job."""
    if priors is None:
        return
    if not isinstance(priors, dict):
        raise ValueError("priors must be a dictionary or None")
    for name, entry in priors.items():
        if not isinstance(name, str):
            raise ValueError("prior card names must be strings")
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            raise ValueError("each prior must contain a count and a mean reward")
        games, reward = entry
        if (not isinstance(games, int) or isinstance(games, bool) or games < 0):
            raise ValueError("prior counts must be nonnegative integers")
        _validate_nonnegative_finite(reward, "prior mean reward")
        if reward > 1:
            raise ValueError("prior mean reward must be between 0 and 1")


class Node:
    """One edge of the tree: the action that led here, plus the statistics
    of every simulation that has passed through it.

    No game state lives here (that is the open-loop choice): each descent
    rebuilds the state by replaying the path's actions from the root under
    fresh randomness. Edge card indices refer to ORIGINAL root hand slots,
    including distinct copies of identical cards. Available children are
    recomputed for each realization rather than frozen on the first visit.
    """
    # No explicit __slots__: a compiled (mypyc) build makes native classes
    # implicitly slotted, which is why every attribute is annotated and the
    # root's action/parent are typed Optional.
    action: "Action | None"
    parent: "Node | None"
    children: "list[Node]"
    visits: int
    value_sum: float

    def __init__(self, action: "Action | None", parent: "Node | None"):
        self.action = action          # edge that led here (None at root)
        self.parent = parent
        self.children = []
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


def _available_actions(
    state: GameState, slots: list[int],
    edge_pool: dict[tuple[int, int | None], Action] | None = None,
) -> dict[Action, Action]:
    """Map stable root-slot edges to current hand-index actions.

    Names and Card equality cannot identify a physical copy: duplicate cards
    are legal, including two references to the same immutable Card instance.
    """
    if edge_pool is None:
        return {
            Action(slots[a.card_idx], a.target_idx) if a.card_idx is not None else a: a
            for a in legal_actions(state)
        }
    available: dict[Action, Action] = {}
    edge: Action | None
    for action in legal_actions(state):
        if action.card_idx is None:
            edge = action
        else:
            key = (slots[action.card_idx], action.target_idx)
            edge = edge_pool.get(key)
            if edge is None:
                edge = Action(*key)
                edge_pool[key] = edge
        available[edge] = action
    return available


def _action_coordinates(action: Action) -> dict[str, int | None]:
    return {"card_idx": action.card_idx, "target_idx": action.target_idx}


class _RootHalving:
    """Budget-aware root allocation for a clockless horizon-one search.

    These phase means serve elimination only. Raw Node sums keep their
    existing sequential backup order and remain the reported action values.
    The counters describe allocation work, not machine instructions.
    """
    actions: list[Action]
    indices: dict[Action, int]
    allowance: int
    active: list[int]
    counts: list[int]
    sums: list[float]
    quota: int
    pending: int | None
    phase: dict | None
    diagnostic: dict
    fallback: bool

    def __init__(self, actions: list[Action], allowance: int):
        self.actions = actions
        self.indices = {action: i for i, action in enumerate(actions)}
        self.allowance = allowance
        self.active = list(range(len(actions)))
        self.counts = [0] * len(actions)
        self.sums = [0.0] * len(actions)
        self.quota = 0
        self.pending = None
        self.phase = None
        minimum = 0
        size = len(actions)
        while size > 1:
            minimum += size
            size = (size + 1) // 2
        self.fallback = allowance < minimum
        self.diagnostic = {
            "policy": "budget_aware_sequential_halving_v1",
            "mode": "uniform_fallback" if self.fallback else "halving",
            "usable_allowance": allowance,
            "selections": 0,
            "reward_updates": 0,
            "elimination_rounds": 0,
            "elimination_key_evaluations": 0,
            "remainder_samples": 0,
            "phases": [],
            "winner": None,
            "complete": False,
        }
        if not self.fallback and len(self.active) > 1:
            self._start_phase()

    def _start_phase(self) -> None:
        rounds = 0
        size = len(self.active)
        while size > 1:
            rounds += 1
            size = (size + 1) // 2
        remaining = self.allowance - self.diagnostic["reward_updates"]
        self.quota = max(1, remaining // (rounds * len(self.active)))
        self.counts = [0] * len(self.actions)
        self.sums = [0.0] * len(self.actions)
        self.phase = {
            "active": [_action_coordinates(self.actions[i]) for i in self.active],
            "quota": self.quota,
            "completed_samples": 0,
            "statistics": [
                {"action": _action_coordinates(self.actions[i]), "visits": 0,
                 "value_sum": 0.0, "mean": None}
                for i in self.active
            ],
            "survivors": [],
        }
        self.diagnostic["phases"].append(self.phase)

    def select(self, available: dict[Action, Action]) -> Action:
        if self.pending is not None:
            raise RuntimeError("root allocation has an unfinished sample")
        if self.diagnostic["selections"] >= self.allowance:
            raise RuntimeError("root allocation exhausted its allowance")
        if self.fallback:
            index = self.diagnostic["selections"] % len(self.actions)
        elif len(self.active) == 1:
            index = self.active[0]
        else:
            assert self.phase is not None
            index = self.active[self.phase["completed_samples"] % len(self.active)]
        action = self.actions[index]
        if action not in available:
            raise RuntimeError("scheduled root action is no longer available")
        self.pending = index
        self.diagnostic["selections"] += 1
        return action

    def _elimination_key(self, index: int) -> tuple[float, int]:
        self.diagnostic["elimination_key_evaluations"] += 1
        return (-self.sums[index] / self.counts[index], index)

    def observe(self, action: Action, reward: float) -> None:
        index = self.pending
        if index is None or self.actions[index] != action:
            raise RuntimeError("root reward does not match its scheduled action")
        self.pending = None
        self.diagnostic["reward_updates"] += 1
        if self.fallback:
            return
        if len(self.active) == 1:
            self.diagnostic["remainder_samples"] += 1
            return
        assert self.phase is not None
        position = self.active.index(index)
        self.counts[index] += 1
        self.sums[index] += reward
        self.phase["completed_samples"] += 1
        statistic = self.phase["statistics"][position]
        statistic["visits"] = self.counts[index]
        statistic["value_sum"] = self.sums[index]
        statistic["mean"] = self.sums[index] / self.counts[index]
        if self.phase["completed_samples"] == self.quota * len(self.active):
            survivors = sorted(self.active, key=self._elimination_key)[
                :(len(self.active) + 1) // 2]
            # Elimination chooses by phase mean. The next sweep still uses
            # physical canonical order, independent of those sampled values.
            self.active = sorted(survivors)
            self.phase["survivors"] = [
                _action_coordinates(self.actions[i]) for i in self.active]
            self.diagnostic["elimination_rounds"] += 1
            self.phase = None
            if len(self.active) > 1:
                self._start_phase()

    def survivor(self) -> Action | None:
        if not self.fallback and len(self.active) == 1:
            return self.actions[self.active[0]]
        return None

    def finish(self, winner: Action | None) -> None:
        if (self.pending is not None or self.phase is not None
                or self.diagnostic["reward_updates"] != self.allowance
                or self.diagnostic["selections"] != self.allowance):
            raise RuntimeError("root allocation did not complete its schedule")
        self.diagnostic["winner"] = (
            _action_coordinates(winner) if winner is not None else None)
        self.diagnostic["complete"] = True


@dataclass
class RankedAction:
    """One root action: label, mean shaped reward, and simulation count.

    ``win_rate`` is retained for API compatibility; it is not a calibrated
    win probability because rewards include terminal shaping and a heuristic.
    """
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
        exploitation side of that. It remains the hand-chosen default.
        The bounded coefficient and selector diagnostic in
        ``docs/episode-stability.md`` measures six early states and retains
        1.2. Stability there does not establish stronger decisions or optimality.
    max_sims
        Hard cap on simulations, independent of the wall-clock budget. A
        time budget stops at a machine-dependent count, so pinning this
        (together with the seed) is what makes a search reproducible.
    rng
        The single source of randomness, so one seed reproduces a search
        exactly. Parallel workers each carry their own.
    last_sims
        Simulations actually run by the most recent ``search()``.
    max_transitions
        Optional allowance for simulated rounds, including tree traversal and
        rollout. A simulation starts only with a full horizon left. It always
        finishes normally, so a final remainder smaller than the horizon is
        unused. This counts simulator calls, not elapsed compute time.
    root_allocation
        ``uct`` retains ordinary search. Experimental ``sequential_halving``
        uses phase-local means to allocate a fixed horizon-one allowance and
        ranks its final survivor first. It requires no priors and no clock.
        Its named budget-aware schedule carries no optimality guarantee.
    last_root_allocation
        Candidate allocation counts and phase-local statistics. Unfinished
        searches leave ``complete=False`` and unsampled phase means as None.
        ``uct`` mode leaves allocation-specific counters at zero and its
        usable allowance as None. Existing work counters still describe UCT.

    Counts must be integers (not booleans): a positive horizon and a
    nonnegative simulation cap. Exploration and time budgets must be finite
    and nonnegative. A zero cap or budget runs no simulations; supplied
    priors can still rank actions using their virtual visits.
    """
    horizon_rounds: int = 4
    exploration: float = 1.2
    max_sims: int = 10_000
    rng: random.Random = field(default_factory=random.Random)
    max_transitions: int | None = None
    root_allocation: str = "uct"
    last_sims: int = field(init=False, default=0)
    last_transitions: int = field(init=False, default=0)
    last_unused_transitions: int | None = field(init=False, default=None)
    last_stop_reasons: tuple[str, ...] = field(init=False, default=())
    last_root_statistics: list[tuple[Action, int, float]] = field(
        init=False, default_factory=list)
    last_root_allocation: dict = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self._validate_configuration()

    def _validate_configuration(self) -> None:
        if (not isinstance(self.horizon_rounds, int)
                or isinstance(self.horizon_rounds, bool) or self.horizon_rounds < 1):
            raise ValueError("horizon_rounds must be a positive integer")
        if (not isinstance(self.max_sims, int)
                or isinstance(self.max_sims, bool) or self.max_sims < 0):
            raise ValueError("max_sims must be a nonnegative integer")
        _validate_nonnegative_finite(self.exploration, "exploration")
        if self.max_transitions is not None and (
                not isinstance(self.max_transitions, int)
                or isinstance(self.max_transitions, bool)
                or self.max_transitions < 0):
            raise ValueError("max_transitions must be a nonnegative integer or None")
        if (not isinstance(self.root_allocation, str)
                or self.root_allocation not in ("uct", "sequential_halving")):
            raise ValueError("root_allocation must be uct or sequential_halving")
        if self.root_allocation == "sequential_halving" and self.horizon_rounds != 1:
            raise ValueError("sequential_halving requires horizon_rounds=1")

    def search(self, root_state: GameState, time_budget_ms: float | None = 450,
               priors: "dict[str, tuple[int, float]] | None" = None,
               ) -> list[RankedAction]:
        """Search from ``root_state`` until the budget or ``max_sims`` runs
        out; return every root action ranked by estimated win rate, visits
        breaking ties.

        Ranking by mean rather than by visit count (the usual "robust
        child" rule) means a lightly visited action with a lucky mean can
        outrank a well-explored one; the visit column is reported so a
        reader can see when that is happening.

        Experimental ``sequential_halving`` instead ranks its completed
        survivor first, followed by other sampled actions by raw mean,
        visits and physical canonical order. Below the minimum elimination
        allowance it samples uniform sweeps and uses that raw ordering for
        every sampled action. It never invents values for unvisited actions.

        ``priors``: ``{card_name: (games, win_rate)}`` from a self-play
        opening book. Book moves enter the root with VIRTUAL visits, so
        learned experience biases early exploration but is washed out (or
        confirmed) by real simulations — a simple way to close a learning
        loop. Counts must be nonnegative integers and means finite numbers
        in [0, 1]. JSON list pairs are also accepted. Zero-count entries add
        no virtual visits. Invalid entries raise ValueError before sampling,
        including entries for cards absent from the current hand.

        ``time_budget_ms=None`` disables the clock limit. The simulation and
        optional transition ceilings still apply. Raw root statistics retain
        value sums directly for parallel aggregation, including virtual priors.
        """
        self.last_sims = 0
        self.last_transitions = 0
        self.last_unused_transitions = None
        self.last_stop_reasons = ()
        self.last_root_statistics = []
        self.last_root_allocation = {
            "policy": (self.root_allocation
                       if isinstance(self.root_allocation, str) else "invalid"),
            "mode": "uct",
            "usable_allowance": None, "selections": 0, "reward_updates": 0,
            "elimination_rounds": 0, "elimination_key_evaluations": 0,
            "remainder_samples": 0, "phases": [], "winner": None,
            "complete": False,
        }
        # Configuration is mutable; check again before advancing the RNG.
        self._validate_configuration()
        if time_budget_ms is not None:
            _validate_nonnegative_finite(time_budget_ms, "time_budget_ms")
        _validate_priors(priors)
        if self.root_allocation == "sequential_halving":
            if time_budget_ms is not None:
                raise ValueError("sequential_halving requires time_budget_ms=None")
            if priors is not None:
                raise ValueError("sequential_halving requires priors=None")
        self.last_unused_transitions = self.max_transitions
        if root_state.is_terminal():
            # No decision remains; priors must not manufacture one or spend
            # the full simulation budget repeatedly scoring a finished state.
            self.last_stop_reasons = ("terminal",)
            if self.root_allocation == "sequential_halving":
                allowance = self.max_sims
                if self.max_transitions is not None:
                    allowance = min(allowance, self.max_transitions)
                self.last_root_allocation.update({
                    "policy": "budget_aware_sequential_halving_v1",
                    "mode": "terminal", "usable_allowance": allowance,
                })
            self.last_root_allocation["complete"] = True
            return []
        deadline = (time.perf_counter() + time_budget_ms / 1000.0
                    if time_budget_ms is not None else None)
        root = Node(action=None, parent=None)
        # Reuse coordinate values within this search, never current legality.
        edge_pool: dict[tuple[int, int | None], Action] = {}
        allocation: _RootHalving | None = None
        if self.root_allocation == "sequential_halving":
            allowance = self.max_sims
            if self.max_transitions is not None:
                allowance = min(allowance, self.max_transitions)
            # Existing legal order is Pass, physical card slot, then target.
            # Equal card values remain distinct arms through their coordinates.
            allocation = _RootHalving(legal_actions(root_state), allowance)
            self.last_root_allocation = allocation.diagnostic
        if priors:
            for a in legal_actions(root_state):
                name = (root_state.hand[a.card_idx].name
                        if a.card_idx is not None
                        and a.card_idx < len(root_state.hand) else None)
                pr = priors.get(name) if name else None
                if pr:
                    games, wr = pr
                    if games == 0:
                        continue
                    v0 = min(30, 3 * games)
                    child = Node(a, root)
                    child.visits = v0
                    child.value_sum = float(wr) * v0
                    root.children.append(child)
                    root.visits += v0
        sims = 0
        time_stopped = False

        while sims < self.max_sims:
            if (self.max_transitions is not None
                    and self.max_transitions - self.last_transitions
                    < self.horizon_rounds):
                break
            if deadline is not None and time.perf_counter() >= deadline:
                time_stopped = True
                break
            state = root_state.clone()
            slots = list(range(len(root_state.hand)))
            node = root
            depth = 0

            # Skip unavailable edges without rewarding them as a pass. Pips
            # and living targets vary; newly legal options must be expanded
            # even at a node visited under a different realization before.
            while depth < self.horizon_rounds and not state.is_terminal():
                available = _available_actions(state, slots, edge_pool)
                if allocation is not None and node is root:
                    edge = allocation.select(available)
                    existing = [ch for ch in node.children if ch.action == edge]
                    expanded = not existing
                    if expanded:
                        child = Node(edge, node)
                        node.children.append(child)
                    else:
                        child = existing[0]
                else:
                    tried = {ch.action for ch in node.children}
                    untried = [a for a in available if a not in tried]
                    expanded = bool(untried)
                    if untried:
                        edge = untried[self.rng.randrange(len(untried))]
                        child = Node(edge, node)
                        node.children.append(child)
                    else:
                        child = max(
                            (ch for ch in node.children if ch.action in available),
                            key=lambda n: n.ucb1(self.exploration))
                assert child.action is not None
                action = available[child.action]
                advance_round(state, action, self.rng)
                self.last_transitions += 1
                if action.card_idx is not None:
                    slots.pop(action.card_idx)
                depth += 1
                node = child
                if expanded:
                    break

            # --- rollout: random play to horizon or terminal
            reward = self._rollout(state, depth)

            # --- backpropagation
            up: Node | None = node
            while up is not None:
                up.visits += 1
                up.value_sum += reward
                up = up.parent
            sims += 1
            # Preserve completed work if a later simulation raises an error.
            self.last_sims = sims
            if allocation is not None:
                assert node.action is not None
                allocation.observe(node.action, reward)

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
        if allocation is None:
            ranked.sort(key=lambda r: (r.win_rate, r.visits), reverse=True)
        else:
            survivor = allocation.survivor()
            ranked.sort(key=lambda r: (
                r.action != survivor, -r.win_rate, -r.visits,
                allocation.indices[r.action]))
        self.last_root_statistics = [
            (ch.action, ch.visits, ch.value_sum) for ch in root.children
            if ch.action is not None]
        self.last_sims = sims
        reasons = []
        if self.max_transitions is not None:
            self.last_unused_transitions = self.max_transitions - self.last_transitions
            if self.last_unused_transitions < self.horizon_rounds:
                reasons.append("transition_allowance")
        if sims >= self.max_sims:
            reasons.append("simulation_cap")
        if time_stopped:
            reasons.append("time_limit")
        self.last_stop_reasons = tuple(reasons)
        if allocation is not None:
            allocation.finish(ranked[0].action if ranked else None)
        else:
            self.last_root_allocation["complete"] = True
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
            self.last_transitions += 1
            depth += 1
        result = state.result()
        if result is not None:
            return self._terminal_reward(result, depth)
        return state.heuristic_value()

    def _terminal_reward(self, result: float, depth: int) -> float:
        """Shaped terminal score at a nonnegative rollout depth.

        A win subtracts 0.045 per depth step, capped after six steps, so
        terminal win scores range from 0.73 to 1.0. A loss rises from zero
        at depth zero to 0.15 at the horizon, with deeper losses capped
        there. At depth one its score is 0.15 / max(1, horizon_rounds).

        These bounds order terminal win and loss samples. Ongoing horizon
        states use the separate HP/setup heuristic in [0, 1], which can
        fall below a loss score or above a win score. Search means average
        sampled shaped scores, not calibrated win probabilities. The
        ordering does not guarantee that an action wins or avoids stalling.
        """
        if result >= 1.0:
            return 1.0 - 0.045 * min(6, depth)
        # Scale nonnegative depth up to the horizon, capped at 0.15.
        # Clamp defensively so a caller-provided deep loss cannot outscore a
        # clean win. Selection and rollout both obey the configured horizon.
        h = max(1, self.horizon_rounds)
        return 0.15 * (min(depth, h) / h)
