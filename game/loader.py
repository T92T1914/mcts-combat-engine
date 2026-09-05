"""Data-driven content: cards, scenarios, and boss rules defined as JSON.

This mirrors how the engine's parent project worked — a knowledge base of
structured content feeding a generic engine — scaled to a self-contained
repo. The engine never reads these files; it receives plain Card/Combatant
objects, so swapping content means editing JSON, not code.

Validation is deliberately loud: every error names the offending card,
scenario, or field. Content errors caught at load time are cheap; the same
errors surfacing as weird simulation behavior are expensive.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from engine import Card, CardType, Combatant, Element, GameState
from engine.rules import EnrageBelowHalf, PunishTraps

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _positive_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def _modifier_fraction(v) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and 0.0 < float(v) <= 2.0)


# rule type -> (class, {param: (validator, requirement)}). Values are
# validated here, not just names — a string "350" or a negative damage
# would otherwise load fine and only blow up (or silently heal the player)
# thousands of simulations deep. Adding a boss mechanic = one entry here
# plus its BossRule subclass in engine/rules.py.
RULE_REGISTRY = {
    "punish_traps": (PunishTraps, {
        "damage": (_positive_int, "a positive integer"),
    }),
    "enrage_below_half": (EnrageBelowHalf, {
        "blade": (_modifier_fraction, "a number in (0, 2]"),
    }),
}

_CARD_FIELDS = {
    "name": str, "element": str, "type": str, "pip_cost": int,
    "accuracy": (int, float), "damage_min": int, "damage_max": int,
    "heal": int, "dot_tick": int, "dot_rounds": int,
    "modifier": (int, float), "hits_all": bool,
}
_REQUIRED_CARD_FIELDS = {"name", "element", "type"}

_COMBATANT_FIELDS = {"name", "element", "hp", "power_pip_chance", "resist",
                     "boost", "is_boss", "attack", "rules"}


def _fail(context: str, message: str):
    raise ValueError(f"{context}: {message}")


def _parse_element(value: str, context: str) -> Element:
    try:
        return Element(value)
    except ValueError:
        _fail(context, f"unknown element {value!r} "
                       f"(valid: {[e.value for e in Element]})")


def parse_card(raw: dict, context: str) -> Card:
    missing = _REQUIRED_CARD_FIELDS - raw.keys()
    if missing:
        _fail(context, f"missing required fields {sorted(missing)}")
    unknown = raw.keys() - _CARD_FIELDS.keys()
    if unknown:
        _fail(context, f"unknown fields {sorted(unknown)}")
    for field, expected in _CARD_FIELDS.items():
        if field in raw and not isinstance(raw[field], expected):
            _fail(context, f"field {field!r} must be {expected}")

    element = _parse_element(raw["element"], context)
    try:
        card_type = CardType(raw["type"])
    except ValueError:
        _fail(context, f"unknown card type {raw['type']!r} "
                       f"(valid: {[t.value for t in CardType]})")

    card = Card(
        name=raw["name"], element=element, card_type=card_type,
        pip_cost=raw.get("pip_cost", 0), accuracy=raw.get("accuracy", 0.85),
        damage_min=raw.get("damage_min", 0), damage_max=raw.get("damage_max", 0),
        heal=raw.get("heal", 0), dot_tick=raw.get("dot_tick", 0),
        dot_rounds=raw.get("dot_rounds", 0), modifier=raw.get("modifier", 0.0),
        hits_all=raw.get("hits_all", False),
    )

    if not 0 <= card.pip_cost <= 14:
        _fail(context, f"pip_cost {card.pip_cost} outside 0..14")
    if not 0.0 < card.accuracy <= 1.0:
        _fail(context, f"accuracy {card.accuracy} outside (0, 1]")
    if card.damage_min < 0 or card.damage_max < card.damage_min:
        _fail(context, "need 0 <= damage_min <= damage_max")
    if (card.dot_tick > 0) != (card.dot_rounds > 0):
        _fail(context, "dot_tick and dot_rounds must be set together")
    if card.card_type == CardType.DAMAGE and card.damage_max == 0:
        _fail(context, "damage card with zero damage_max")
    if card.card_type in (CardType.BLADE, CardType.TRAP, CardType.SHIELD) \
            and not 0.0 < card.modifier <= 2.0:
        _fail(context, f"{card.card_type.value} needs modifier in (0, 2]")
    if card.card_type == CardType.HEAL and card.heal <= 0:
        _fail(context, "heal card with no heal value")
    return card


def load_cards(path: Path | None = None) -> dict[str, Card]:
    path = path or DATA_DIR / "cards.json"
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    cards: dict[str, Card] = {}
    for entry in raw["cards"]:
        context = f"cards.json card {entry.get('name', '<unnamed>')!r}"
        card = parse_card(entry, context)
        if card.name in cards:
            _fail(context, "duplicate card name")
        cards[card.name] = card
    return cards


def _parse_resist(raw: dict, context: str) -> dict[Element, float]:
    out = {}
    for element_name, value in raw.items():
        element = _parse_element(element_name, context)
        if not isinstance(value, (int, float)) or not -1.0 <= value <= 1.0:
            _fail(context, f"resist/boost for {element_name!r} must be in [-1, 1]")
        out[element] = float(value)
    return out


def _parse_combatant(raw: dict, context: str) -> tuple[Combatant, list]:
    unknown = raw.keys() - _COMBATANT_FIELDS
    if unknown:
        _fail(context, f"unknown fields {sorted(unknown)}")
    for field in ("name", "element", "hp"):
        if field not in raw:
            _fail(context, f"missing required field {field!r}")
    if not isinstance(raw["hp"], int) or raw["hp"] <= 0:
        _fail(context, "hp must be a positive integer")

    rules = []
    for rule_raw in raw.get("rules", []):
        rule_type = rule_raw.get("type")
        if rule_type not in RULE_REGISTRY:
            _fail(context, f"unknown rule type {rule_type!r} "
                           f"(valid: {sorted(RULE_REGISTRY)})")
        cls, allowed = RULE_REGISTRY[rule_type]
        params = {k: v for k, v in rule_raw.items() if k != "type"}
        if params.keys() - allowed.keys():
            _fail(context, f"rule {rule_type!r} got unknown params "
                           f"{sorted(params.keys() - allowed.keys())}")
        for param, value in params.items():
            validator, requirement = allowed[param]
            if not validator(value):
                _fail(context, f"rule {rule_type!r} param {param!r} "
                               f"must be {requirement}, got {value!r}")
        rules.append(cls(**params))

    ppc = raw.get("power_pip_chance", 0.55)
    if not isinstance(ppc, (int, float)) or isinstance(ppc, bool) \
            or not 0.0 <= ppc <= 1.0:
        _fail(context, f"power_pip_chance must be a number in [0, 1], "
                       f"got {ppc!r}")
    if not isinstance(raw.get("is_boss", False), bool):
        _fail(context, f"is_boss must be true or false, "
                       f"got {raw['is_boss']!r}")

    base_attack = None
    if "attack" in raw:
        base_attack = parse_card(raw["attack"], f"{context} attack")
        if base_attack.card_type is not CardType.DAMAGE:
            _fail(context, f"attack must be a damage-type card, "
                           f"got {base_attack.card_type.value!r}")

    combatant = Combatant(
        name=raw["name"],
        element=_parse_element(raw["element"], context),
        hp=raw["hp"], max_hp=raw["hp"],
        power_pip_chance=float(ppc),
        is_boss=raw.get("is_boss", False),
        base_attack=base_attack,
    )
    combatant.resist = _parse_resist(raw.get("resist", {}), context)
    combatant.boost = _parse_resist(raw.get("boost", {}), context)
    return combatant, rules


def load_scenarios(path: Path | None = None,
                   cards: dict[str, Card] | None = None) -> dict:
    """Return {name: factory} where factory(rng) -> (GameState, deck) —
    the same shape the runner, demo, and benchmark already consume."""
    cards = cards if cards is not None else load_cards()
    path = path or DATA_DIR / "scenarios.json"
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    scenarios = {}
    for name, spec in raw["scenarios"].items():
        context = f"scenarios.json scenario {name!r}"
        unknown = spec.keys() - {"description", "player", "deck", "enemies"}
        if unknown:
            _fail(context, f"unknown fields {sorted(unknown)}")
        for field in ("player", "deck", "enemies"):
            if field not in spec:
                _fail(context, f"missing required field {field!r}")
        if not spec["enemies"]:
            _fail(context, "needs at least one enemy")
        if not spec["deck"]:
            _fail(context, "needs at least one card in the deck")

        deck = []
        for card_name in spec["deck"]:
            if card_name not in cards:
                _fail(context, f"deck references unknown card {card_name!r}")
            deck.append(cards[card_name])

        player_proto, player_rules = _parse_combatant(
            spec["player"], f"{context} player")
        if player_rules:
            _fail(context, "rules belong on enemies, not the player")
        enemy_protos = []
        all_rules = []
        for i, enemy_raw in enumerate(spec["enemies"]):
            enemy, rules = _parse_combatant(enemy_raw, f"{context} enemy {i}")
            enemy_protos.append(enemy)
            all_rules.extend(rules)

        def factory(rng: random.Random, _player=player_proto,
                    _enemies=enemy_protos, _deck=deck, _rules=all_rules):
            state = GameState(
                player=_player.clone(),
                enemies=[e.clone() for e in _enemies],
                hand=[rng.choice(_deck) for _ in range(7)],
            )
            state.boss_rules = _rules   # stateless, shared across games
            return state, _deck

        scenarios[name] = factory
    return scenarios
