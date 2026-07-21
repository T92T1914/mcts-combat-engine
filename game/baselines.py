"""Baseline deciders to measure the search against.

A "decider" takes a GameState and an RNG and returns an Action. The MCTS
engine is itself a decider (wrapped in :func:`mcts_decider`). These simple
policies are the bar the search has to clear.
"""
from __future__ import annotations

import random
from typing import Callable

from engine import Action, CardType, GameState, legal_actions
from engine.mcts import MCTS
from engine.parallel import ParallelMCTS

Decider = Callable[[GameState, random.Random], Action]


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


def mcts_decider(budget_ms: int = 300, horizon: int = 5,
                 parallel: bool = False, workers: int | None = None,
                 seed: int | None = None) -> Decider:
    """Build an MCTS decider. Single-process by default so it is safe to call
    from anywhere; pass ``parallel=True`` for the root-parallel engine.
    ``seed`` makes the single-process search deterministic (used in tests)."""
    engine = (ParallelMCTS(horizon_rounds=horizon, workers=workers)
              if parallel else MCTS(horizon_rounds=horizon))
    if isinstance(engine, MCTS):
        engine.max_sims = 1_000_000  # let the time budget rule
        if seed is not None:
            engine.rng = random.Random(seed)

    def decide(state: GameState, rng: random.Random) -> Action:
        ranked = engine.search(state, time_budget_ms=budget_ms)
        return ranked[0].action if ranked else Action(card_idx=None)

    return decide
