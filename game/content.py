"""Example game content, loaded from data/ at import time.

The cards, scenarios, and boss rules all live in ``data/cards.json`` and
``data/scenarios.json`` — this module just loads and validates them. Edit
the JSON to change the game; ``game/loader.py`` documents the format and
fails loudly on invalid content.
"""
from __future__ import annotations

from game.loader import load_cards, load_scenarios

CARDS = load_cards()
SCENARIOS = load_scenarios(cards=CARDS)


def make_deck():
    """All defined cards, in definition order."""
    return list(CARDS.values())
