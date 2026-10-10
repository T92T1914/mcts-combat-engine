"""Independent finite one-round arithmetic for a declared existing-domain subset.

This separately authored test oracle has no product arithmetic imports. Each
complete leaf carries an exact rational probability under independent uniform
53-bit random draws and inclusive uniform integer damage. Successor arithmetic
uses Python binary64 operations to preserve the inspected modeled transitions.
This is not an enumeration of the Mersenne Twister seed space or a full-game
optimal policy. A limit or unsupported mechanic supplies no accepted value.
"""

from __future__ import annotations

import math
import time
from copy import deepcopy
from fractions import Fraction

GRID = 2**53
MODEL = "independent_one_round_binary53_binary64_v1"
ELEMENTS = {"ember", "frost", "gale", "rune", "verdant", "shade", "aether", "neutral"}
KINDS = {"damage", "heal", "blade", "trap", "shield", "utility"}
CARD_FIELDS = {
    "name",
    "element",
    "card_type",
    "pip_cost",
    "accuracy",
    "damage_min",
    "damage_max",
    "heal",
    "dot_tick",
    "dot_rounds",
    "modifier",
    "hits_all",
}
FIGHTER_FIELDS = {
    "name",
    "element",
    "hp",
    "max_hp",
    "pips",
    "power_pips",
    "power_pip_chance",
    "resist",
    "boost",
    "blades",
    "traps",
    "shields",
    "dots",
    "is_boss",
    "base_attack",
    "policy",
}
DEFAULT_ATTACK = {
    "name": "(basic attack)",
    "element": "neutral",
    "card_type": "damage",
    "pip_cost": 3,
    "accuracy": 0.85,
    "damage_min": 250,
    "damage_max": 400,
    "heal": 0,
    "dot_tick": 0,
    "dot_rounds": 0,
    "modifier": 0.0,
    "hits_all": False,
}


class UnsupportedReference(ValueError):
    """The entire requested state or action falls outside this reference."""


class ReferenceLimitExceeded(RuntimeError):
    """No complete value is admitted when path or cooperative limits are reached."""


def _object(value, keys, location):
    if not isinstance(value, dict) or set(value) != keys:
        raise UnsupportedReference(f"{location}: missing or unsupported fields")


def _integer(value, low, high, location):
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not low <= value <= high
    ):
        raise UnsupportedReference(f"{location}: expected integer in {low}..{high}")


def _number(value, low, high, location):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not low <= value <= high
        or not math.isfinite(value)
    ):
        raise UnsupportedReference(
            f"{location}: expected finite number in {low}..{high}"
        )


def _card(card, location):
    _object(card, CARD_FIELDS, location)
    if not isinstance(card["name"], str) or not 1 <= len(card["name"]) <= 128:
        raise UnsupportedReference(f"{location}: nonempty card name required")
    if (
        not isinstance(card["element"], str)
        or card["element"] not in ELEMENTS
        or not isinstance(card["card_type"], str)
        or card["card_type"] not in KINDS
    ):
        raise UnsupportedReference(f"{location}: unknown element or card type")
    _integer(card["pip_cost"], 0, 14, location + "/pip_cost")
    _number(card["accuracy"], 0, 1, location + "/accuracy")
    if card["accuracy"] <= 0:
        raise UnsupportedReference(
            f"{location}: positive saved-state accuracy required"
        )
    for field in ("damage_min", "damage_max", "heal", "dot_tick"):
        _integer(card[field], 0, 1_000_000, location + "/" + field)
    _integer(card["dot_rounds"], 0, 30, location + "/dot_rounds")
    _number(card["modifier"], -2, 2, location + "/modifier")
    if card["damage_min"] > card["damage_max"]:
        raise UnsupportedReference(f"{location}: ordered damage range required")
    if card["card_type"] == "damage" and card["damage_max"] <= 0:
        raise UnsupportedReference(f"{location}: positive damage maximum required")
    if card["card_type"] == "heal" and card["heal"] <= 0:
        raise UnsupportedReference(f"{location}: positive healing required")
    if (card["dot_tick"] > 0) != (card["dot_rounds"] > 0):
        raise UnsupportedReference(
            f"{location}: paired positive effect tick and duration required"
        )
    if card["card_type"] in {"blade", "trap", "shield"} and card["modifier"] <= 0:
        raise UnsupportedReference(f"{location}: positive modifier-card value required")
    if not isinstance(card["hits_all"], bool):
        raise UnsupportedReference(f"{location}: Boolean hits_all required")
    width = max(card["damage_min"], card["damage_max"]) - card["damage_min"] + 1
    if width > 151:
        raise UnsupportedReference(f"{location}: damage width exceeds 151")


def _fighter(fighter, location):
    _object(fighter, FIGHTER_FIELDS, location)
    if not isinstance(fighter["name"], str) or not 1 <= len(fighter["name"]) <= 128:
        raise UnsupportedReference(f"{location}: nonempty name required")
    if not isinstance(fighter["element"], str) or fighter["element"] not in ELEMENTS:
        raise UnsupportedReference(f"{location}: unknown element")
    _integer(fighter["hp"], 1, 1_000_000, location + "/hp")
    _integer(fighter["max_hp"], 1, 1_000_000, location + "/max_hp")
    if fighter["hp"] > fighter["max_hp"]:
        raise UnsupportedReference(f"{location}: current HP exceeds maximum")
    for field in ("pips", "power_pips"):
        _integer(fighter[field], 0, 7, location + "/" + field)
    if fighter["pips"] + fighter["power_pips"] > 7:
        raise UnsupportedReference(f"{location}: root pip slots exceed seven")
    _number(fighter["power_pip_chance"], 0, 1, location + "/power_pip_chance")
    for field in ("resist", "boost"):
        mapping = fighter[field]
        if not isinstance(mapping, dict) or set(mapping) - ELEMENTS:
            raise UnsupportedReference(f"{location}/{field}: unsupported mapping")
        for value in mapping.values():
            _number(value, -1, 1, location + "/" + field)
    for field in ("blades", "traps", "shields"):
        charms = fighter[field]
        if not isinstance(charms, list) or len(charms) > 4:
            raise UnsupportedReference(f"{location}/{field}: at most four charms")
        for charm in charms:
            _object(charm, {"value", "element"}, location + "/" + field)
            if (
                not isinstance(charm["element"], str)
                or charm["element"] not in ELEMENTS
            ):
                raise UnsupportedReference(f"{location}/{field}: unknown charm element")
            low, high = (-2, 0) if field == "shields" else (0, 2)
            _number(charm["value"], low, high, location + "/" + field)
    dots = fighter["dots"]
    if not isinstance(dots, list) or len(dots) > 4:
        raise UnsupportedReference(f"{location}/dots: at most four existing effects")
    for dot in dots:
        _object(dot, {"tick", "rounds_left", "element"}, location + "/dots")
        _integer(dot["tick"], 0, 1_000_000, location + "/dots/tick")
        _integer(dot["rounds_left"], 1, 30, location + "/dots/rounds_left")
        if not isinstance(dot["element"], str) or dot["element"] not in ELEMENTS:
            raise UnsupportedReference(f"{location}/dots: unknown element")
    if fighter["is_boss"] is not False or fighter["policy"] is not None:
        raise UnsupportedReference(
            f"{location}: boss/policy mechanics are outside this subset"
        )
    if fighter["base_attack"] is not None:
        _card(fighter["base_attack"], location + "/base_attack")
        attack = fighter["base_attack"]
        if attack["card_type"] != "damage":
            raise UnsupportedReference(f"{location}: damage enemy attack required")


def _available(fighter, card):
    return fighter["pips"] + fighter["power_pips"] * (
        2 if card["element"] == fighter["element"] else 1
    )


def validate_state(state):
    """Admit a complete nonterminal root, never a silently reduced state."""
    _object(state, {"player", "enemies", "hand", "round_num", "boss_rules"}, "state")
    _fighter(state["player"], "player")
    if not isinstance(state["enemies"], list) or not 1 <= len(state["enemies"]) <= 2:
        raise UnsupportedReference(
            "state: one or two initially living enemies required"
        )
    attackers = 0
    for index, enemy in enumerate(state["enemies"]):
        _fighter(enemy, f"enemies/{index}")
        attack = enemy["base_attack"] or DEFAULT_ATTACK
        attackers += _available(enemy, attack) >= attack["pip_cost"]
    if attackers > 1:
        raise UnsupportedReference(
            "state: at most one initially affordable enemy attack"
        )
    if not isinstance(state["hand"], list) or not 0 <= len(state["hand"]) <= 7:
        raise UnsupportedReference("state: hand must contain zero to seven cards")
    for index, card in enumerate(state["hand"]):
        _card(card, f"hand/{index}")
    _integer(state["round_num"], 1, 30, "round_num")
    if state["boss_rules"] != []:
        raise UnsupportedReference("state: boss rules are unsupported")


def materialize_case(document, case_id):
    """Expand shared input data only. This performs no transition or scoring."""
    case = next((item for item in document["cases"] if item["id"] == case_id), None)
    if case is None:
        refusal = next(
            (item for item in document["refusal_cases"] if item["id"] == case_id), None
        )
        if refusal is None:
            raise KeyError(case_id)
        state = materialize_case(document, refusal["base_case"])
        if "edit" in refusal:
            path = refusal["edit"]["pointer"].split("/")[1:]
            container = state
            for field in path[:-1]:
                container = (
                    container[int(field)]
                    if isinstance(container, list)
                    else container[field]
                )
            key = int(path[-1]) if isinstance(container, list) else path[-1]
            container[key] = deepcopy(refusal["edit"]["value"])
        return state
    recipe = case["recipe"]

    def fighter(spec):
        result = deepcopy(document["combatants"][spec["template"]])
        result.update(deepcopy(spec.get("overrides", {})))
        return result

    hand = []
    for spec in recipe["hand"]:
        name = spec if isinstance(spec, str) else spec["card"]
        item = deepcopy(document["cards"][name])
        if isinstance(spec, dict):
            item.update(deepcopy(spec.get("overrides", {})))
        hand.append(item)
    return {
        "player": fighter(recipe["player"]),
        "enemies": [fighter(spec) for spec in recipe["enemies"]],
        "hand": hand,
        "round_num": recipe.get("round_num", 1),
        "boss_rules": [],
    }


def legal_action_identities(state):
    validate_state(state)
    result = [{"card_idx": None, "target_idx": None}]
    for index, card in enumerate(state["hand"]):
        if _available(state["player"], card) < card["pip_cost"]:
            continue
        targets = (
            range(len(state["enemies"]))
            if card["card_type"] in {"damage", "trap"} and not card["hits_all"]
            else (None,)
        )
        result.extend({"card_idx": index, "target_idx": target} for target in targets)
    return result


def _copy(state):
    def fighter(original):
        changed = dict(original)
        for field in ("blades", "traps", "shields", "dots"):
            changed[field] = [dict(item) for item in original[field]]
        return changed

    return {
        "player": fighter(state["player"]),
        "enemies": [fighter(enemy) for enemy in state["enemies"]],
        "hand": list(state["hand"]),
        "round_num": state["round_num"],
        "boss_rules": [],
    }


def threshold_mass(probability, inclusive=False):
    """Probability of an iid 53-bit draw <= p or < p, including grid endpoints."""
    value = Fraction.from_float(float(probability)) * GRID
    count = (
        value.numerator // value.denominator + 1
        if inclusive
        else -(-value.numerator // value.denominator)
    )
    return Fraction(max(0, min(GRID, count)), GRID)


def _coin(probability, inclusive=False):
    mass = threshold_mass(probability, inclusive)
    if mass:
        yield True, mass, {"method": "random", "args": [], "value": 0.0}
    if mass < 1:
        yield (
            False,
            1 - mass,
            {"method": "random", "args": [], "value": (GRID - 1) / GRID},
        )


def _spend(fighter, card):
    cost = card["pip_cost"]
    worth = 2 if card["element"] == fighter["element"] else 1
    powers = min(fighter["power_pips"], (cost + worth - 1) // worth)
    fighter["power_pips"] -= powers
    remaining = max(0, cost - powers * worth)
    fighter["pips"] = max(0, fighter["pips"] - remaining)


def _take_modifiers(fighter, field, element):
    factor = 1.0
    keep = []
    for charm in fighter[field]:
        if charm["element"] == "neutral" or charm["element"] == element:
            factor = factor * (1.0 + charm["value"])
        else:
            keep.append(charm)
    fighter[field] = keep
    return factor


def _cast(world, card, caster_index, target_indices):
    """Yield a cast's complete accuracy and damage worlds in physical target order."""
    state, weight, tape = world
    paid = _copy(state)
    actor = paid["player"] if caster_index is None else paid["enemies"][caster_index]
    _spend(actor, card)
    for landed, chance, draw in _coin(card["accuracy"], inclusive=True):
        branch = _copy(paid)
        path = (branch, weight * chance, tape + [draw])
        if not landed:
            yield path
            continue
        caster = (
            branch["player"]
            if caster_index is None
            else branch["enemies"][caster_index]
        )
        kind = card["card_type"]
        if kind == "heal":
            caster["hp"] = min(caster["max_hp"], caster["hp"] + card["heal"])
        elif kind == "blade":
            caster["blades"].append(
                {"value": card["modifier"], "element": card["element"]}
            )
        elif kind == "shield":
            caster["shields"].append(
                {"value": -abs(card["modifier"]), "element": card["element"]}
            )
        elif kind == "trap":
            for target_index in target_indices:
                target = (
                    branch["player"]
                    if target_index is None
                    else branch["enemies"][target_index]
                )
                target["traps"].append(
                    {"value": card["modifier"], "element": card["element"]}
                )
        elif kind == "damage":
            alive_targets = [
                index
                for index in target_indices
                if (branch["player"] if index is None else branch["enemies"][index])[
                    "hp"
                ]
                > 0
            ]
            blades = (
                _take_modifiers(caster, "blades", card["element"])
                if alive_targets
                else 1.0
            )
            low, high = card["damage_min"], max(card["damage_min"], card["damage_max"])
            width = high - low + 1

            def damage_targets(
                current,
                offset,
                *,
                alive_targets=alive_targets,
                blades=blades,
                low=low,
                high=high,
                width=width,
            ):
                if offset == len(alive_targets):
                    yield current
                    return
                prior, probability, history = current
                target_index = alive_targets[offset]
                for base in range(low, high + 1):
                    hit = _copy(prior)
                    attacker = (
                        hit["player"]
                        if caster_index is None
                        else hit["enemies"][caster_index]
                    )
                    target = (
                        hit["player"]
                        if target_index is None
                        else hit["enemies"][target_index]
                    )
                    amount = float(base) * blades
                    amount = amount * _take_modifiers(target, "traps", card["element"])
                    amount = amount * _take_modifiers(
                        target, "shields", card["element"]
                    )
                    amount = amount * (
                        1.0 - max(0.0, target["resist"].get(card["element"], 0.0))
                    )
                    amount = amount * (1.0 + target["boost"].get(card["element"], 0.0))
                    dealt = max(0, int(amount))
                    target["hp"] = max(0, target["hp"] - dealt)
                    if card["heal"] > 0 and dealt > 0:
                        attacker["hp"] = min(
                            attacker["max_hp"], attacker["hp"] + dealt // 2
                        )
                    if card["dot_tick"] > 0:
                        target["dots"].append(
                            {
                                "tick": card["dot_tick"],
                                "rounds_left": card["dot_rounds"],
                                "element": card["element"],
                            }
                        )
                    draw = {"method": "randint", "args": [low, high], "value": base}
                    yield from damage_targets(
                        (hit, probability / width, history + [draw]), offset + 1
                    )

            yield from damage_targets(path, 0)
            continue
        yield path


def _enemy_turns(world, index=0):
    state, weight, tape = world
    if index == len(state["enemies"]):
        yield world
        return
    enemy = state["enemies"][index]
    attack = enemy["base_attack"] or DEFAULT_ATTACK
    if (
        enemy["hp"] <= 0
        or state["player"]["hp"] <= 0
        or _available(enemy, attack) < attack["pip_cost"]
    ):
        yield from _enemy_turns(world, index + 1)
        return
    for tries, chance, draw in _coin(0.85):
        branch = (_copy(state), weight * chance, tape + [draw])
        successors = _cast(branch, attack, index, [None]) if tries else (branch,)
        for successor in successors:
            yield from _enemy_turns(successor, index + 1)


def _upkeep(world):
    state, weight, tape = world
    ticked = _copy(state)
    for fighter in [ticked["player"], *ticked["enemies"]]:
        active = []
        for dot in fighter["dots"]:
            elemental = 1.0 - fighter["resist"].get(dot["element"], 0.0)
            enhanced = 1.0 + fighter["boost"].get(dot["element"], 0.0)
            amount = int(dot["tick"] * elemental * enhanced)
            fighter["hp"] = max(0, fighter["hp"] - max(0, amount))
            remaining = dot["rounds_left"] - 1
            if remaining > 0:
                active.append(
                    {
                        "tick": dot["tick"],
                        "rounds_left": remaining,
                        "element": dot["element"],
                    }
                )
        fighter["dots"] = active
    candidates = [
        None,
        *[index for index, enemy in enumerate(ticked["enemies"]) if enemy["hp"] > 0],
    ]

    def regenerate(current, offset):
        prior, probability, history = current
        if offset == len(candidates):
            completed = _copy(prior)
            completed["round_num"] += 1
            yield completed, probability, history
            return
        index = candidates[offset]
        fighter = prior["player"] if index is None else prior["enemies"][index]
        if fighter["pips"] + fighter["power_pips"] >= 7:
            yield from regenerate(current, offset + 1)
            return
        for power, chance, draw in _coin(fighter["power_pip_chance"]):
            changed = _copy(prior)
            recipient = (
                changed["player"] if index is None else changed["enemies"][index]
            )
            recipient["power_pips" if power else "pips"] += 1
            yield from regenerate(
                (changed, probability * chance, history + [draw]), offset + 1
            )

    yield from regenerate((ticked, weight, tape), 0)


def score_successor(state):
    """Independently reconstruct the inspected horizon-1 binary64 objective."""
    if state["player"]["hp"] <= 0:
        return 0.15, "loss"
    if all(enemy["hp"] <= 0 for enemy in state["enemies"]):
        return 1.0 - 0.045, "win"
    player_fraction = state["player"]["hp"] / max(1, state["player"]["max_hp"])
    present, maximum = 0.0, 0.0
    for enemy in state["enemies"]:
        discount = 1.0
        for trap in enemy["traps"]:
            discount = discount * (1.0 + trap["value"])
        attack = enemy["base_attack"]
        pressure = (
            1.0
            if attack is None
            else max(
                0.5, min(2.5, (attack["damage_min"] + attack["damage_max"]) / 400.0)
            )
        )
        present += (enemy["hp"] / max(0.5, discount)) * pressure
        maximum += enemy["max_hp"] * pressure
    for blade in state["player"]["blades"]:
        present *= max(0.65, 1.0 / (1.0 + blade["value"] * 0.5))
    enemy_fraction = present / max(1.0, maximum)
    return max(0.0, min(1.0, 0.5 + 0.5 * (player_fraction - enemy_fraction))), "ongoing"


def enumerate_action(state, action, *, max_paths=250_000, max_seconds=30.0):
    """Yield complete independent leaves with source-compatible draw tapes.

    Consuming only a prefix provides transition witnesses, never an accepted
    expected value. Exhaustion and exact unit mass are required for acceptance.
    """
    actions = legal_action_identities(state)
    if (
        not isinstance(action, dict)
        or set(action) != {"card_idx", "target_idx"}
        or action not in actions
    ):
        raise UnsupportedReference("action: exact legal physical identity required")
    for field in ("card_idx", "target_idx"):
        if action[field] is not None and (
            isinstance(action[field], bool) or not isinstance(action[field], int)
        ):
            raise UnsupportedReference(
                "action: Boolean/noninteger indices are unsupported"
            )
    _integer(max_paths, 1, 250_000, "max_paths")
    _number(max_seconds, 0.000001, 30, "max_seconds")
    deadline = time.perf_counter() + max_seconds
    root = _copy(state)
    index = action["card_idx"]
    if index is None:
        casts = ((root, Fraction(1), []),)
    else:
        card = root["hand"][index]
        root["hand"] = [
            item for offset, item in enumerate(root["hand"]) if offset != index
        ]
        targets = (
            list(range(len(root["enemies"])))
            if card["hits_all"]
            else [action["target_idx"]]
        )
        casts = _cast((root, Fraction(1), []), card, None, targets)
    count = 0
    for cast_world in casts:
        if time.perf_counter() >= deadline:
            raise ReferenceLimitExceeded(
                "reference cooperative time limit before complete enumeration"
            )
        for response in _enemy_turns(cast_world):
            for successor, probability, tape in _upkeep(response):
                count += 1
                if count > max_paths:
                    raise ReferenceLimitExceeded(
                        "reference per-action complete-path allowance exceeded"
                    )
                if time.perf_counter() >= deadline:
                    raise ReferenceLimitExceeded(
                        "reference cooperative time limit before complete enumeration"
                    )
                score, result = score_successor(successor)
                yield {
                    "state": successor,
                    "probability": probability,
                    "tape": tape,
                    "score": score,
                    "result": result,
                }


def _rational(value):
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def evaluate(state, *, max_paths=250_000, max_total_paths=1_000_000, max_seconds=30.0):
    """Return values only after every legal action is completely enumerated."""
    _integer(max_total_paths, 1, 1_000_000, "max_total_paths")
    _integer(max_paths, 1, 250_000, "max_paths")
    _number(max_seconds, 0.000001, 30, "max_seconds")
    started = time.perf_counter()
    values, rows, total = [], [], 0
    for action in legal_action_identities(state):
        remaining = max_seconds - (time.perf_counter() - started)
        if remaining < 0.000001 or total >= max_total_paths:
            raise ReferenceLimitExceeded(
                "reference whole-call allowance exhausted before complete action set"
            )
        mass, value, leaves = Fraction(), Fraction(), 0
        results = {"win": Fraction(), "loss": Fraction(), "ongoing": Fraction()}
        for leaf in enumerate_action(
            state,
            action,
            max_paths=min(max_paths, max_total_paths - total),
            max_seconds=remaining,
        ):
            probability = leaf["probability"]
            mass += probability
            value += probability * Fraction.from_float(leaf["score"])
            results[leaf["result"]] += probability
            leaves += 1
        if mass != 1 or sum(results.values(), Fraction()) != 1:
            raise ArithmeticError(
                "independent reference probability mass is not exactly one"
            )
        total += leaves
        values.append(value)
        rows.append(
            {
                "action": dict(action),
                "expected_value": _rational(value),
                "expected_value_float": float(value),
                "mass": _rational(mass),
                "leaves": leaves,
                "result_mass": {key: _rational(item) for key, item in results.items()},
            }
        )
    # Every complete physical action appends one value and one report row.
    best = max(values)
    result = {
        "model": MODEL,
        "horizon_rounds": 1,
        "terminal_depth": 1,
        "probability_law": "iid_uniform_binary53_and_inclusive_uniform_integer_damage",
        "score_arithmetic": "independently_reconstructed_binary64_successor_score",
        "rows": rows,
        "best_actions": [
            row["action"]
            for row, value in zip(rows, values, strict=True)
            if value == best
        ],
        "total_paths": total,
        "elapsed_seconds": time.perf_counter() - started,
        "completed": True,
    }
    if time.perf_counter() - started >= max_seconds:
        raise ReferenceLimitExceeded(
            "reference cooperative time limit before complete report"
        )
    return result
