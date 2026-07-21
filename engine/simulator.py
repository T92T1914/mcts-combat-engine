"""Stochastic combat simulator: advances a GameState by one full round.

One call to ``advance_round(state, action, rng)`` mutates the (already
cloned) state through:
  1. the player's chosen action (accuracy roll, damage/heal/charm resolution)
  2. every living enemy's response (policy + boss rules)
  3. end-of-round upkeep (damage-over-time ticks, pip regeneration)

The damage model is deliberately compact but structurally faithful: blades
multiply outgoing damage, traps/shields multiply incoming damage, then
resist/boost apply. Tune per-card numbers in the content, not here.
"""
from __future__ import annotations

import random

from .actions import Action
from .state import Card, CardType, Charm, Combatant, DoT, Element, GameState
from .rules import RuleEvent, fire_rules

DEFAULT_ATTACK = Card(
    name="(basic attack)", card_type=CardType.DAMAGE,
    pip_cost=3, accuracy=0.85, damage_min=250, damage_max=400,
)


# ---------------------------------------------------------------- damage math

def _consume_charms(charms: list, element: Element) -> float:
    """Pop matching charms (universal or same-element) and return the combined
    multiplier. Blades/traps are (1+v) each; shields are (1+v) with v < 0."""
    mult, remaining = 1.0, []
    for ch in charms:
        if ch.element in (Element.NEUTRAL, element):
            mult *= (1.0 + ch.value)
        else:
            remaining.append(ch)
    charms[:] = remaining
    return mult


def resolve_damage(attacker: Combatant, target: Combatant,
                   base: int, element: Element,
                   blade_mult: float | None = None) -> int:
    """``blade_mult`` lets a multi-target cast consume the caster's blades
    once and apply the multiplier to every target; when None (single-target
    path), blades are consumed here."""
    dmg = float(base)
    if blade_mult is None:
        blade_mult = _consume_charms(attacker.blades, element)
    dmg *= blade_mult
    dmg *= _consume_charms(target.traps, element)
    dmg *= _consume_charms(target.shields, element)
    dmg *= (1.0 - max(0.0, target.resist.get(element, 0.0)))
    dmg *= (1.0 + target.boost.get(element, 0.0))
    dealt = max(0, int(dmg))
    target.hp = max(0, target.hp - dealt)
    return dealt


# ------------------------------------------------------------ card resolution

def cast(state: GameState, caster: Combatant, card: Card,
         targets: list, rng: random.Random) -> None:
    """Resolve one card from ``caster`` onto ``targets`` (list of Combatant)."""
    caster.spend_pips(card.pip_cost, card.element)

    if rng.random() > card.accuracy:      # fizzle: the round is lost, and in
        return                            # this model pips are spent anyway

    fire_rules(state, RuleEvent("cast", caster=caster, card=card), rng)

    if card.card_type == CardType.DAMAGE:
        living = [t for t in targets if t.alive]
        # blades are consumed once per CAST, not once per target — an AoE
        # behind a blade multiplies every hit (this is also what the search
        # heuristic assumes when it credits blades against the enemy pool)
        blade_mult = _consume_charms(caster.blades, card.element) if living else 1.0
        for t in living:
            base = rng.randint(card.damage_min, max(card.damage_min, card.damage_max))
            dealt = resolve_damage(caster, t, base, card.element, blade_mult)
            # drain: a DAMAGE card carrying a heal value restores half the
            # damage actually dealt back to the caster
            if card.heal > 0 and dealt > 0:
                caster.hp = min(caster.max_hp, caster.hp + dealt // 2)
            if card.dot_tick > 0:
                t.dots.append(DoT(card.dot_tick, card.dot_rounds, card.element))
    elif card.card_type == CardType.HEAL:
        caster.hp = min(caster.max_hp, caster.hp + card.heal)
    elif card.card_type == CardType.BLADE:
        caster.blades.append(Charm(card.modifier, card.element))
    elif card.card_type == CardType.TRAP:
        for t in targets:
            t.traps.append(Charm(card.modifier, card.element))
    elif card.card_type == CardType.SHIELD:
        caster.shields.append(Charm(-abs(card.modifier), card.element))
    # UTILITY: no-op in this model.


# ------------------------------------------------------------- enemy policy

def enemy_act(state: GameState, enemy: Combatant, rng: random.Random) -> None:
    """Enemy model. Without a policy: attack when affordable. With one
    (``enemy.policy``), sample the action TYPE from that combatant's learned
    tendencies, so lookahead fights an opponent shaped like the real one."""
    fire_rules(state, RuleEvent("enemy_turn", caster=enemy), rng)
    if not enemy.alive or not state.player.alive:
        return
    atk = enemy.base_attack or DEFAULT_ATTACK

    if enemy.policy:
        kinds, weights = zip(*enemy.policy.items())
        kind = rng.choices(kinds, weights=weights)[0]
        if kind == "attack":
            if enemy.effective_pips(atk.element) >= atk.pip_cost:
                cast(state, enemy, atk, [state.player], rng)
            # can't afford the hit -> builds pips (implicit pass)
        elif kind == "shield":
            enemy.shields.append(Charm(-0.7, Element.NEUTRAL))
        elif kind == "blade":
            enemy.blades.append(Charm(0.35, enemy.element))
        elif kind == "heal":
            if enemy.pips + enemy.power_pips >= 2:
                enemy.spend_pips(2, enemy.element)
                enemy.hp = min(enemy.max_hp,
                               enemy.hp + int(enemy.max_hp * 0.18))
        return

    if enemy.effective_pips(atk.element) >= atk.pip_cost and rng.random() < 0.85:
        cast(state, enemy, atk, [state.player], rng)


# ------------------------------------------------------------- round upkeep

def _tick_dots(c: Combatant) -> None:
    for d in c.dots:
        # ticks respect elemental resist/boost like any other damage
        tick = int(d.tick * (1.0 - c.resist.get(d.element, 0.0))
                   * (1.0 + c.boost.get(d.element, 0.0)))
        c.hp = max(0, c.hp - max(0, tick))
        d.rounds_left -= 1
    c.dots = [d for d in c.dots if d.rounds_left > 0]


def _regen_pips(c: Combatant, rng: random.Random) -> None:
    if c.pips + c.power_pips >= 7:        # pip cap (7 slots)
        return
    if rng.random() < c.power_pip_chance:
        c.power_pips += 1
    else:
        c.pips += 1


# ------------------------------------------------------------- full round

def advance_round(state: GameState, action: Action, rng: random.Random) -> GameState:
    """Mutates ``state`` (clone it first!) through one full round."""
    player = state.player

    # 1. player action. Open-loop search replays action sequences under fresh
    # randomness, so an action minted in one realization can be stale in
    # another (e.g. the hand didn't shrink because the player died earlier
    # here). A stale index degrades to a pass rather than crashing.
    idx = action.card_idx
    if idx is not None and player.alive and idx < len(state.hand):
        card = state.hand[idx]
        # re-check affordability: pip regen is stochastic, so an action minted
        # as legal in one realization can be unaffordable in this one — it
        # degrades to a pass instead of casting at a free discount
        if player.effective_pips(card.element) >= card.pip_cost:
            if card.hits_all:
                targets = state.living_enemies
            elif action.target_idx is not None:
                targets = [state.enemies[action.target_idx]]
            else:
                targets = [player]
            cast(state, player, card, targets, rng)
            state.hand = [c for i, c in enumerate(state.hand) if i != idx]

    # 2. enemies respond
    for enemy in state.enemies:
        if enemy.alive:
            enemy_act(state, enemy, rng)

    # 3. upkeep
    _tick_dots(player)
    for enemy in state.enemies:
        _tick_dots(enemy)
    _regen_pips(player, rng)
    for enemy in state.enemies:
        if enemy.alive:
            _regen_pips(enemy, rng)

    state.round_num += 1
    fire_rules(state, RuleEvent("round_end"), rng)
    return state
