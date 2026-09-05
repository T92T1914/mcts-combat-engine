"""Boss rules — the "cheats" that make elite encounters interesting.

A rule is a stateless object attached to ``GameState.boss_rules``. The
simulator fires events at fixed points in a round; each rule inspects the
event and the state, and mutates the state to model its effect. Because
rules are pure functions of (state, event) and hold no mutable data, cloning
a state stays cheap — the rule objects are shared, never copied.

This keeps special encounter mechanics out of the core damage model: the
simulator stays simple, and every simulated line still *pays the price* of a
boss's mechanic, so the search won't walk into a punisher's counterattack.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from .state import CardType, Charm, Element


@dataclass
class RuleEvent:
    kind: str                        # "cast" | "enemy_turn" | "round_end"
    caster: Optional[object] = None  # Combatant
    card: Optional[object] = None    # Card


class BossRule:
    """Subclass and override apply(). Keep rules stateless."""
    description: str = ""

    def apply(self, state, event: RuleEvent, rng: random.Random) -> None:
        raise NotImplementedError


def fire_rules(state, event: RuleEvent, rng: random.Random) -> None:
    for rule in state.boss_rules:
        rule.apply(state, event, rng)


# ----------------------------------------------------------------- examples

class PunishTraps(BossRule):
    """The boss counter-hits whenever the player casts a trap."""

    def __init__(self, damage: int = 300):
        self.damage = damage
        self.description = (
            f"Boss hits back for {damage} whenever the player casts a trap"
        )

    def apply(self, state, event, rng):
        if (event.kind == "cast" and event.caster is state.player
                and event.card is not None
                and event.card.card_type == CardType.TRAP):
            state.player.hp = max(0, state.player.hp - self.damage)


class EnrageBelowHalf(BossRule):
    """Once under 50% HP, the boss blades itself every round."""

    def __init__(self, blade: float = 0.25):
        self.blade = blade
        self.description = (
            f"Under 50% HP the boss gains a +{blade:.0%} blade each round"
        )

    def apply(self, state, event, rng):
        if event.kind != "round_end":
            return
        for enemy in state.enemies:
            if enemy.is_boss and enemy.alive and enemy.hp < enemy.max_hp // 2:
                enemy.blades.append(Charm(self.blade, Element.NEUTRAL))
