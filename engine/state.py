"""Game state model for a turn-based elemental duel.

Everything here is plain data with a fast manual ``.clone()``. The search
clones the state thousands of times per decision, so we avoid
``copy.deepcopy`` and share anything that is never mutated.

The toy game modeled here: two or more combatants trade turns. Each turn a
combatant spends *pips* (a regenerating resource) to play a card — a hit, a
heal, or a modifier (blade = outgoing-damage buff, trap = incoming-damage
debuff on a target, shield = incoming-damage reduction). Damage-over-time
and elemental resist/boost round out the mechanics. It is deliberately small
but structurally rich enough that lookahead genuinely helps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Element(str, Enum):
    EMBER = "ember"
    FROST = "frost"
    GALE = "gale"
    RUNE = "rune"
    VERDANT = "verdant"
    SHADE = "shade"
    AETHER = "aether"
    NEUTRAL = "neutral"     # universal: matches any element for modifiers


class CardType(str, Enum):
    DAMAGE = "damage"        # a hit, optionally carrying a damage-over-time
    HEAL = "heal"
    BLADE = "blade"          # outgoing-damage multiplier on the caster
    TRAP = "trap"            # incoming-damage multiplier on the target
    SHIELD = "shield"        # incoming-damage reduction on the caster
    UTILITY = "utility"      # no combat effect in this model


@dataclass
class Card:
    name: str
    element: Element = Element.NEUTRAL
    card_type: CardType = CardType.DAMAGE
    pip_cost: int = 0
    accuracy: float = 0.85       # 0..1 chance the card lands (else it fizzles)
    damage_min: int = 0
    damage_max: int = 0
    heal: int = 0
    dot_tick: int = 0            # damage per round after the initial hit
    dot_rounds: int = 0
    modifier: float = 0.0        # blade/trap/shield strength, e.g. 0.35
    hits_all: bool = False       # area of effect

    def clone(self) -> "Card":
        # Cards are immutable in practice; sharing the instance is safe.
        return self


@dataclass
class Charm:
    """A blade (positive) / trap (positive) / shield (negative) modifier."""
    value: float                       # +0.35 blade, +0.25 trap, -0.70 shield
    element: Element = Element.NEUTRAL  # NEUTRAL == universal


@dataclass
class DoT:
    tick: int
    rounds_left: int
    element: Element = Element.NEUTRAL


@dataclass
class Combatant:
    name: str
    element: Element
    hp: int
    max_hp: int
    pips: int = 0
    power_pips: int = 0
    power_pip_chance: float = 0.55
    # concrete container types keep an optional compiled build fast; untyped
    # 'list'/'dict' cost a large slowdown under mypyc.
    resist: dict[Element, float] = field(default_factory=dict)
    boost: dict[Element, float] = field(default_factory=dict)
    blades: list[Charm] = field(default_factory=list)
    traps: list[Charm] = field(default_factory=list)
    shields: list[Charm] = field(default_factory=list)
    dots: list[DoT] = field(default_factory=list)
    is_boss: bool = False
    base_attack: Optional[Card] = None           # overrides the default hit
    policy: Optional[dict[str, float]] = None     # action-type weights:
                                                  # {attack, shield, blade, heal}

    @property
    def alive(self) -> bool:
        return self.hp > 0

    def effective_pips(self, element: Element) -> int:
        """Pips available for a card of ``element`` (power pips count double
        when they match the caster's own element)."""
        mult = 2 if element == self.element else 1
        return self.pips + self.power_pips * mult

    def spend_pips(self, cost: int, element: Element) -> None:
        """Spend power pips first, matching how the resource is consumed."""
        mult = 2 if element == self.element else 1
        while cost > 0 and self.power_pips > 0:
            self.power_pips -= 1
            cost -= mult
        self.pips = max(0, self.pips - max(0, cost))

    def clone(self) -> "Combatant":
        c = Combatant(
            name=self.name, element=self.element, hp=self.hp, max_hp=self.max_hp,
            pips=self.pips, power_pips=self.power_pips,
            power_pip_chance=self.power_pip_chance, is_boss=self.is_boss,
            base_attack=self.base_attack,        # Card is immutable, share
            policy=self.policy,                  # read-only dict, share
        )
        c.resist = self.resist          # read-only, share
        c.boost = self.boost            # read-only, share
        c.blades = list(self.blades)    # Charm instances are never mutated
        c.traps = list(self.traps)
        c.shields = list(self.shields)
        c.dots = [DoT(d.tick, d.rounds_left, d.element) for d in self.dots]
        return c


@dataclass
class GameState:
    player: Combatant
    enemies: list[Combatant]
    hand: list[Card]                    # up to 7
    round_num: int = 1
    boss_rules: list = field(default_factory=list)  # shared, stateless rules

    @property
    def living_enemies(self) -> list[Combatant]:
        return [e for e in self.enemies if e.alive]

    def is_terminal(self) -> bool:
        return (not self.player.alive) or (not self.living_enemies)

    def result(self) -> Optional[float]:
        """1.0 = win, 0.0 = loss, None = ongoing."""
        if not self.player.alive:
            return 0.0
        if not self.living_enemies:
            return 1.0
        return None

    def heuristic_value(self) -> float:
        """Score a non-terminal horizon state in [0, 1] by HP differential.

        Setup counts as progress: a trap on an enemy discounts its effective
        HP by the trap's multiplier, and player blades discount the enemy
        pool. Without this, "trap now, one-shot next round" would evaluate as
        zero achievement at the horizon and never be recommended.
        """
        p = self.player.hp / max(1, self.player.max_hp)
        e_hp = 0.0
        e_max = 0.0
        for x in self.enemies:
            mult = 1.0
            for t in x.traps:
                mult *= (1.0 + t.value)
            # An enemy's importance scales with the damage it deals, not just
            # its HP: killing the hard hitter relieves pressure sooner.
            atk = x.base_attack
            threat = 1.0
            if atk is not None:
                threat = max(0.5, min(2.5, (atk.damage_min + atk.damage_max)
                                      / 400.0))
            e_hp += (x.hp / max(0.5, mult)) * threat
            e_max += x.max_hp * threat
        for b in self.player.blades:
            e_hp *= max(0.65, 1.0 / (1.0 + b.value * 0.5))
        e = e_hp / max(1.0, e_max)
        return max(0.0, min(1.0, 0.5 + 0.5 * (p - e)))

    def clone(self) -> "GameState":
        return GameState(
            player=self.player.clone(),
            enemies=[e.clone() for e in self.enemies],
            hand=list(self.hand),        # Cards are immutable
            round_num=self.round_num,
            boss_rules=self.boss_rules,  # stateless, share
        )
