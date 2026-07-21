"""Full-game runner: play a scenario to the end with a given decider.

The engine's ``advance_round`` removes a played card from the hand but does
not draw — drawing is a game-layer concern. The runner refills the hand from
the deck each round, then asks the decider for an action.
"""
from __future__ import annotations

import random
from typing import Callable

from engine import GameState, advance_round
from engine.state import Card

Decider = Callable[[GameState, random.Random], "object"]
HAND_SIZE = 7


def _refill(state: GameState, deck: list[Card], rng: random.Random) -> None:
    while len(state.hand) < HAND_SIZE:
        state.hand.append(rng.choice(deck))


def play_game(state: GameState, deck: list[Card], decider: Decider,
              rng: random.Random, max_rounds: int = 30) -> float:
    """Play one game. Returns 1.0 (player win), 0.0 (loss), or a partial
    heuristic score if it hits ``max_rounds`` without a result (a stalemate,
    which counts as neither a clean win nor loss)."""
    for _ in range(max_rounds):
        result = state.result()
        if result is not None:
            return result
        _refill(state, deck, rng)
        action = decider(state, rng)
        advance_round(state, action, rng)
    result = state.result()
    return result if result is not None else state.heuristic_value()


def play_match(scenario, decider: Decider,
               games: int, seed: int = 0) -> dict:
    """Play ``games`` independent games of a scenario with one decider.

    Every decider faces the SAME sequence of seeds, so the comparison is
    paired: differences come from the policy, not the luck of the draw.
    """
    wins = 0.0
    clean_wins = 0
    rounds_to_win = []
    for g in range(games):
        rng = random.Random(seed + g)
        state, deck = scenario(rng)
        score = play_game(state, deck, decider, rng)
        wins += score
        if score >= 1.0:
            clean_wins += 1
            # advance_round increments round_num at the END of every round,
            # so after a kill during round k the counter reads k+1
            rounds_to_win.append(state.round_num - 1)
    avg_score = wins / games
    avg_rounds = (sum(rounds_to_win) / len(rounds_to_win)
                  if rounds_to_win else None)
    return {
        "games": games,
        "win_rate": clean_wins / games,
        "avg_score": avg_score,          # counts partial/stalemate credit
        "avg_rounds_to_win": avg_rounds,
    }
