"""Sample content for the toy duel game: a card deck and a few scenarios.

None of this is part of the engine — it is example data the engine reasons
over. Swap in your own cards and encounters without touching ``engine/``.
"""
from __future__ import annotations

import random

from engine import Card, CardType, Combatant, Element, GameState
from engine.rules import EnrageBelowHalf, PunishTraps

E = Element.EMBER


# ------------------------------------------------------------------- the deck
# A small Ember-element deck: a wand hit, two staple hits, a damage-over-time,
# an area hit, plus the support cards (blade, trap, shield, heal) that reward
# sequencing. A naive "hit hardest" player never touches the support cards;
# a searching player learns when they pay off.

def make_deck() -> list[Card]:
    return [
        Card("Spark", E, CardType.DAMAGE, pip_cost=0, accuracy=1.0,
             damage_min=65, damage_max=95),
        Card("Flame Dart", E, CardType.DAMAGE, pip_cost=2, accuracy=0.9,
             damage_min=205, damage_max=275),
        Card("Fire Blast", E, CardType.DAMAGE, pip_cost=4, accuracy=0.85,
             damage_min=440, damage_max=520),
        Card("Cinder", E, CardType.DAMAGE, pip_cost=3, accuracy=0.85,
             damage_min=120, damage_max=160, dot_tick=130, dot_rounds=3),
        Card("Firestorm", E, CardType.DAMAGE, pip_cost=5, accuracy=0.8,
             damage_min=340, damage_max=420, hits_all=True),
        Card("Ember Blade", E, CardType.BLADE, pip_cost=1, accuracy=1.0,
             modifier=0.35),
        Card("Weakness Mark", E, CardType.TRAP, pip_cost=0, accuracy=1.0,
             modifier=0.30),
        Card("Stone Ward", Element.NEUTRAL, CardType.SHIELD, pip_cost=1,
             accuracy=1.0, modifier=0.70),
        Card("Mend", E, CardType.HEAL, pip_cost=2, accuracy=1.0, heal=520),
    ]


def _hand(deck: list[Card], rng: random.Random, n: int = 7) -> list[Card]:
    return [rng.choice(deck) for _ in range(n)]


# ------------------------------------------------------------------ scenarios
# Each returns (GameState, deck). The runner draws from the deck to refill the
# player's hand between rounds.

def duel_1v1(rng: random.Random) -> tuple[GameState, list[Card]]:
    deck = make_deck()
    player = Combatant("Player", E, hp=2400, max_hp=2400, power_pip_chance=0.6)
    enemy = Combatant("Frost Warden", Element.FROST, hp=2100, max_hp=2100,
                      resist={Element.EMBER: 0.15})
    return GameState(player=player, enemies=[enemy], hand=_hand(deck, rng)), deck


def gauntlet_1v3(rng: random.Random) -> tuple[GameState, list[Card]]:
    deck = make_deck()
    player = Combatant("Player", E, hp=2600, max_hp=2600, power_pip_chance=0.6)
    weak = Card("(minion strike)", Element.FROST, CardType.DAMAGE,
                pip_cost=3, accuracy=0.85, damage_min=140, damage_max=210)
    enemies = [
        Combatant("Warden", Element.FROST, hp=900, max_hp=900, base_attack=weak),
        Combatant("Acolyte", Element.FROST, hp=750, max_hp=750, base_attack=weak),
        Combatant("Adept", Element.FROST, hp=1100, max_hp=1100, base_attack=weak),
    ]
    return GameState(player=player, enemies=enemies, hand=_hand(deck, rng)), deck


def boss_fight(rng: random.Random) -> tuple[GameState, list[Card]]:
    deck = make_deck()
    player = Combatant("Player", E, hp=3000, max_hp=3000, power_pip_chance=0.65)
    hit = Card("(boss strike)", Element.FROST, CardType.DAMAGE,
               pip_cost=4, accuracy=0.9, damage_min=340, damage_max=470)
    boss = Combatant("Frost Tyrant", Element.FROST, hp=3200, max_hp=3200,
                     is_boss=True, base_attack=hit, resist={Element.EMBER: 0.15})
    state = GameState(player=player, enemies=[boss], hand=_hand(deck, rng))
    # elite mechanics: punishes traps, enrages below half HP
    state.boss_rules = [PunishTraps(damage=350), EnrageBelowHalf(blade=0.25)]
    return state, deck


SCENARIOS = {
    "duel": duel_1v1,
    "gauntlet": gauntlet_1v3,
    "boss": boss_fight,
}
