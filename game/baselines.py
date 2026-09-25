"""Baseline deciders to measure the search against.

A "decider" takes a GameState and an RNG and returns an Action. The MCTS
engine is itself a decider (wrapped in :func:`mcts_decider`). These simple
policies are the bar the search has to clear.
"""
from __future__ import annotations

import random
from collections.abc import Callable

from engine import Action, CardType, GameState, advance_round, legal_actions
from engine.mcts import MCTS
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


def one_round_decider(samples_per_action: int = 8, *,
                       on_evaluation: Callable[[int], None] | None = None) -> Decider:
    """Enumerate legal actions and sample their one-round successor values.

    Each candidate uses the same starting sample seeds. Its actual draw path
    may differ as the action changes the simulated round. Terminal successors
    use the game result, otherwise the existing state heuristic supplies value.
    This is independent of the search tree, not independent of the simulator or
    its evaluation assumptions. ``on_evaluation`` records successor transitions.
    """
    if (isinstance(samples_per_action, bool)
            or not isinstance(samples_per_action, int) or samples_per_action < 1):
        raise ValueError("samples_per_action must be a positive integer")

    def decide(state: GameState, rng: random.Random) -> Action:
        if state.is_terminal():
            if on_evaluation is not None:
                on_evaluation(0)
            return Action(card_idx=None)
        seeds = [rng.getrandbits(64) for _ in range(samples_per_action)]
        # A stable tie break also makes enumeration order irrelevant.
        actions = sorted(legal_actions(state), key=lambda action: (
            -1 if action.card_idx is None else action.card_idx,
            -1 if action.target_idx is None else action.target_idx))
        best = actions[0]
        best_value = -1.0
        for action in actions:
            value = 0.0
            for seed in seeds:
                successor = state.clone()
                advance_round(successor, action, random.Random(seed))
                result = successor.result()
                value += result if result is not None else successor.heuristic_value()
            if value > best_value:
                best, best_value = action, value
        if on_evaluation is not None:
            on_evaluation(len(actions) * samples_per_action)
        return best

    return decide


def mcts_decider(budget_ms: int = 300, horizon: int = 5,
                 parallel: bool = False, workers: int | None = None,
                 seed: int | None = None,
                 max_sims: int | None = None, *,
                 on_search: Callable[[int], None] | None = None) -> Decider:
    """Build an MCTS decider. Single-process by default so it is safe to call
    from anywhere; pass ``parallel=True`` for the root-parallel engine.

    For deterministic single-process tests, pass BOTH ``seed`` and ``max_sims``.
    Parallel mode is timed only and rejects either control, even with one
    worker. A seed alone
    is not enough, because a wall-clock budget stops at a machine-dependent
    simulation count. ``on_search`` receives the actual simulation count
    after each decision, including a search stopped by its time limit.
    """
    if parallel and (seed is not None or max_sims is not None):
        raise ValueError("seed and max_sims require single-process search "
                         "(parallel=False)")
    engine = (ParallelMCTS(horizon_rounds=horizon, workers=workers)
              if parallel else MCTS(horizon_rounds=horizon))
    if isinstance(engine, MCTS):
        engine.max_sims = max_sims if max_sims is not None else 1_000_000
        if seed is not None:
            engine.rng = random.Random(seed)

    def decide(state: GameState, rng: random.Random) -> Action:
        ranked = engine.search(state, time_budget_ms=budget_ms)
        if on_search is not None:
            on_search(engine.last_sims)
        return ranked[0].action if ranked else Action(card_idx=None)

    return decide
