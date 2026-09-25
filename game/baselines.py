"""Baseline deciders to measure the search against.

A "decider" takes a GameState and an RNG and returns an Action. The MCTS
engine is itself a decider (wrapped in :func:`mcts_decider`). These simple
policies are the bar the search has to clear.
"""
from __future__ import annotations

import random
import time
from collections.abc import Callable

from engine import Action, CardType, GameState, advance_round, legal_actions
from engine.mcts import MCTS, _validate_nonnegative_finite
from engine.parallel import ParallelMCTS
from game.runner import Decider


def random_decider(state: GameState, rng: random.Random) -> Action:
    """Pick a uniformly random legal action. The floor."""
    return rng.choice(legal_actions(state))


def greedy_decider(state: GameState, rng: random.Random) -> Action:
    """Always throw the hardest affordable hit at the enemy it does most to.

    A strong-looking naive strategy: it never wastes a turn, but it never
    blades, traps, shields, heals, or sequences either — so it over-commits
    into resists, ignores survival, and splits damage across a gauntlet
    instead of focus-firing. Exactly the play the search should punish.
    """
    best: Action | None = None
    best_score = -1.0
    for a in legal_actions(state):
        if a.card_idx is None:
            continue
        card = state.hand[a.card_idx]
        if card.card_type != CardType.DAMAGE:
            continue
        expected = (card.damage_min + card.damage_max) / 2 * card.accuracy
        targets = state.living_enemies if card.hits_all else (
            [state.enemies[a.target_idx]] if a.target_idx is not None else [])
        for t in targets:
            resist = t.resist.get(card.element, 0.0)
            score = expected * (1.0 - resist)
            # nudge toward finishing a low-HP enemy over chipping a fresh one
            if t.hp <= expected:
                score *= 1.5
            if score > best_score:
                best_score, best = score, a
    # no affordable attack -> build pips
    return best if best is not None else Action(card_idx=None)


def one_round_decider(samples_per_action: int | None = None, *,
                       on_evaluation: Callable[[int], None] | None = None,
                       max_transitions: int | None = None,
                       time_budget_ms: float | None = None,
                       on_work: Callable[[dict], None] | None = None) -> Decider:
    """Enumerate legal actions and sample their one-round successor values.

    Each candidate uses the same starting sample seeds. Its actual draw path
    may differ as the action changes the simulated round. Terminal successors
    use the game result, otherwise the existing state heuristic supplies value.
    This is independent of the search tree, not independent of the simulator or
    its evaluation assumptions. ``on_evaluation`` records successor transitions.
    Omitted or None samples mean eight per action. Alternatively, ``max_transitions``
    admits complete equal-sample sweeps over all legal actions. An optional time
    limit is checked between sweeps. A nonterminal decision without one complete
    sweep raises ValueError rather than choosing an unevaluated action.
    """
    if max_transitions is not None:
        if (isinstance(max_transitions, bool)
                or not isinstance(max_transitions, int) or max_transitions < 0):
            raise ValueError("max_transitions must be a nonnegative integer or None")
        if samples_per_action is not None:
            raise ValueError("choose samples_per_action or max_transitions, not both")
    else:
        samples_per_action = 8 if samples_per_action is None else samples_per_action
        if (isinstance(samples_per_action, bool)
                or not isinstance(samples_per_action, int) or samples_per_action < 1):
            raise ValueError("samples_per_action must be a positive integer")
    if time_budget_ms is not None:
        _validate_nonnegative_finite(time_budget_ms, "time_budget_ms")

    def decide(state: GameState, rng: random.Random) -> Action:
        if state.is_terminal():
            if on_evaluation is not None:
                on_evaluation(0)
            if on_work is not None:
                on_work({"max_transitions": max_transitions, "transitions": 0,
                         "unused_transitions": max_transitions,
                         "actions": 0, "intended_sweeps": 0, "completed_sweeps": 0,
                         "stop_reasons": ["terminal"]})
            return Action(card_idx=None)
        # A stable tie break also makes enumeration order irrelevant.
        actions = sorted(legal_actions(state), key=lambda action: (
            -1 if action.card_idx is None else action.card_idx,
            -1 if action.target_idx is None else action.target_idx))
        sweeps = (max_transitions // len(actions) if max_transitions is not None
                  else samples_per_action)
        assert sweeps is not None
        if sweeps < 1:
            raise ValueError(f"transition allowance {max_transitions} cannot fund "
                             f"one complete sweep of {len(actions)} actions")
        deadline = (time.perf_counter() + time_budget_ms / 1000.0
                    if time_budget_ms is not None else None)
        values = [0.0] * len(actions)
        completed = 0
        time_stopped = False
        for _ in range(sweeps):
            if deadline is not None and time.perf_counter() >= deadline:
                time_stopped = True
                break
            seed = rng.getrandbits(64)
            for index, action in enumerate(actions):
                successor = state.clone()
                advance_round(successor, action, random.Random(seed))
                result = successor.result()
                values[index] += (result if result is not None
                                  else successor.heuristic_value())
            completed += 1
        used = len(actions) * completed
        reasons = []
        if completed == sweeps:
            reasons.append("transition_allowance" if max_transitions is not None
                           else "sample_cap")
        if time_stopped:
            reasons.append("time_limit")
        if on_evaluation is not None:
            on_evaluation(used)
        if on_work is not None:
            on_work({"max_transitions": max_transitions, "transitions": used,
                     "unused_transitions": (max_transitions - used
                                            if max_transitions is not None else None),
                     "actions": len(actions), "intended_sweeps": sweeps,
                     "completed_sweeps": completed, "stop_reasons": reasons})
        if completed == 0:
            raise ValueError("time limit stopped the comparator "
                             "before a complete sweep")
        return actions[max(range(len(actions)), key=lambda index: values[index])]

    return decide


def mcts_decider(budget_ms: int = 300, horizon: int = 5,
                 parallel: bool = False, workers: int | None = None,
                 seed: int | None = None,
                 max_sims: int | None = None, *,
                 on_search: Callable[[int], None] | None = None,
                 max_transitions: int | None = None,
                 on_work: Callable[[dict], None] | None = None) -> Decider:
    """Build an MCTS decider. Single-process by default so it is safe to call
    from anywhere; pass ``parallel=True`` for the root-parallel engine.

    For deterministic single-process tests, pass BOTH ``seed`` and ``max_sims``.
    Parallel mode is timed only and rejects either control, even with one
    worker. A seed alone
    is not enough, because a wall-clock budget stops at a machine-dependent
    simulation count. ``on_search`` receives the actual simulation count
    after each decision, including a search stopped by its time limit.
    ``max_transitions`` and its ``on_work`` telemetry are serial-only. A capped
    nonterminal call that cannot finish a simulation raises instead of falling
    back to pass. Omitting the allowance preserves the existing search policy.
    """
    if parallel and (seed is not None or max_sims is not None
                     or max_transitions is not None or on_work is not None):
        raise ValueError("seed, max_sims, max_transitions and on_work "
                         "require single-process search "
                         "(parallel=False)")
    engine = (ParallelMCTS(horizon_rounds=horizon, workers=workers)
              if parallel else MCTS(horizon_rounds=horizon,
                                    max_transitions=max_transitions))
    if max_transitions is not None and max_transitions < horizon:
        raise ValueError("transition allowance must fund at least one complete horizon")
    if isinstance(engine, MCTS):
        engine.max_sims = max_sims if max_sims is not None else 1_000_000
        if seed is not None:
            engine.rng = random.Random(seed)

    def decide(state: GameState, rng: random.Random) -> Action:
        ranked = engine.search(state, time_budget_ms=budget_ms)
        if on_search is not None:
            on_search(engine.last_sims)
        if on_work is not None:
            assert isinstance(engine, MCTS)
            on_work({"max_transitions": max_transitions,
                     "transitions": engine.last_transitions,
                     "unused_transitions": engine.last_unused_transitions,
                     "simulations": engine.last_sims,
                     "stop_reasons": list(engine.last_stop_reasons)})
        if max_transitions is not None and not ranked and not state.is_terminal():
            raise ValueError("search stopped before a complete simulation")
        return ranked[0].action if ranked else Action(card_idx=None)

    return decide
