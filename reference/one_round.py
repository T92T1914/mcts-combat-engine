"""Independent bounded one-round reference for normalized example states.

This file reads normalized data and implements the declared finite probability
model. It imports no engine or companion code. Complete values are expectations
of source-order binary64 shaped reward under iid binary53 draws, not win odds.
"""

from __future__ import annotations

import copy
import math
import time
from fractions import Fraction

GRID = 1 << 53
MODEL = "independent_one_round_binary53_shaped_v1"
THREE_ENEMY_MODEL = "independent_one_round_three_enemy_binary53_shaped_v1"
MAX_PATHS = 250_000
MAX_TOTAL_PATHS = 1_000_000
MAX_SECONDS = 30.0
ELEMENTS = {"ember", "frost", "gale", "rune", "verdant", "shade", "aether", "neutral"}
TYPES = {"damage", "heal", "blade", "trap", "shield", "utility"}
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
STATE_FIELDS = {"player", "enemies", "hand", "round_num", "boss_rules"}
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


class UnsupportedState(ValueError):
    """The whole state lies outside this separately declared reference subset."""


class ReferenceLimitExceeded(RuntimeError):
    """No partial expectation is an accepted reference result."""


def _object(value, keys, location):
    if not isinstance(value, dict) or set(value) != keys:
        raise UnsupportedState(f"{location}: complete normalized fields required")


def _integer(value, low, high, location):
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not low <= value <= high
    ):
        raise UnsupportedState(f"{location}: integer in {low}..{high} required")


def _number(value, low, high, location):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not low <= value <= high
        or not math.isfinite(value)
    ):
        raise UnsupportedState(f"{location}: finite number in {low}..{high} required")


def _list(value, low, high, location):
    if not isinstance(value, list) or not low <= len(value) <= high:
        raise UnsupportedState(f"{location}: list with {low}..{high} members required")


def _name(value, location):
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise UnsupportedState(f"{location}: nonempty bounded name required")


def _card(card, location):
    _object(card, CARD_FIELDS, location)
    _name(card["name"], location)
    if (
        not isinstance(card["element"], str)
        or card["element"] not in ELEMENTS
        or not isinstance(card["card_type"], str)
        or card["card_type"] not in TYPES
    ):
        raise UnsupportedState(f"{location}: unknown element or card type")
    _integer(card["pip_cost"], 0, 14, location)
    _number(card["accuracy"], 0, 1, location)
    if card["accuracy"] == 0:
        raise UnsupportedState(f"{location}: zero accuracy is not a loader card")
    for field in ("damage_min", "damage_max", "heal", "dot_tick"):
        _integer(card[field], 0, 1_000_000, location)
    _integer(card["dot_rounds"], 0, 30, location)
    if card["damage_max"] < card["damage_min"]:
        raise UnsupportedState(f"{location}: reversed damage range")
    if card["damage_max"] - card["damage_min"] + 1 > 151:
        raise UnsupportedState(f"{location}: damage range exceeds 151 outcomes")
    if (card["dot_tick"] > 0) != (card["dot_rounds"] > 0):
        raise UnsupportedState(f"{location}: damage-over-time fields must agree")
    _number(card["modifier"], -2, 2, location)
    if not isinstance(card["hits_all"], bool):
        raise UnsupportedState(f"{location}: hits_all must be Boolean")
    if card["card_type"] == "damage" and card["damage_max"] == 0:
        raise UnsupportedState(f"{location}: damage card must have positive damage")
    if card["card_type"] == "heal" and card["heal"] <= 0:
        raise UnsupportedState(f"{location}: heal card must restore positive HP")
    if card["card_type"] in {"blade", "trap", "shield"} and card["modifier"] <= 0:
        raise UnsupportedState(f"{location}: modifier card must have positive modifier")


def _fighter(fighter, location):
    _object(fighter, FIGHTER_FIELDS, location)
    _name(fighter["name"], location)
    if not isinstance(fighter["element"], str) or fighter["element"] not in ELEMENTS:
        raise UnsupportedState(f"{location}: unknown element")
    _integer(fighter["max_hp"], 1, 1_000_000, location)
    _integer(fighter["hp"], 1, fighter["max_hp"], location)
    for name in ("pips", "power_pips"):
        _integer(fighter[name], 0, 7, location)
    if fighter["pips"] + fighter["power_pips"] > 7:
        raise UnsupportedState(f"{location}: at most seven resource slots")
    _number(fighter["power_pip_chance"], 0, 1, location)
    for name in ("resist", "boost"):
        mapping = fighter[name]
        if not isinstance(mapping, dict) or set(mapping) - ELEMENTS:
            raise UnsupportedState(f"{location}/{name}: element mapping required")
        for value in mapping.values():
            _number(value, -1, 1, location)
    for name, low, high in (("blades", 0, 2), ("traps", 0, 2), ("shields", -2, 0)):
        _list(fighter[name], 0, 4, location)
        for charm in fighter[name]:
            _object(charm, {"value", "element"}, location)
            _number(charm["value"], low, high, location)
            if (
                not isinstance(charm["element"], str)
                or charm["element"] not in ELEMENTS
            ):
                raise UnsupportedState(f"{location}: unknown charm element")
    _list(fighter["dots"], 0, 4, location)
    for dot in fighter["dots"]:
        _object(dot, {"tick", "rounds_left", "element"}, location)
        _integer(dot["tick"], 0, 1_000_000, location)
        _integer(dot["rounds_left"], 1, 30, location)
        if not isinstance(dot["element"], str) or dot["element"] not in ELEMENTS:
            raise UnsupportedState(f"{location}: unknown damage-over-time element")
    if fighter["is_boss"] is not False or fighter["policy"] is not None:
        raise UnsupportedState(f"{location}: boss flags and opponent policies excluded")
    if fighter["base_attack"] is not None:
        _card(fighter["base_attack"], location + "/base_attack")
        if fighter["base_attack"]["card_type"] != "damage":
            raise UnsupportedState(f"{location}: enemy attack must be damage type")


def effective_pips(fighter, element):
    return fighter["pips"] + fighter["power_pips"] * (
        2 if element == fighter["element"] else 1
    )


def validate(state, *, model=MODEL):
    """Admit a complete supported root, without calling production validators."""
    if not isinstance(model, str) or model not in (MODEL, THREE_ENEMY_MODEL):
        raise UnsupportedState("model: exact supported reference identity required")
    _object(state, STATE_FIELDS, "state")
    _integer(state["round_num"], 1, 30, "state/round_num")
    if state["boss_rules"] != []:
        raise UnsupportedState("state/boss_rules: rules are excluded")
    _fighter(state["player"], "state/player")
    low, high = (1, 2) if model == MODEL else (3, 3)
    _list(state["enemies"], low, high, "state/enemies")
    for index, enemy in enumerate(state["enemies"]):
        _fighter(enemy, f"state/enemies/{index}")
    _list(state["hand"], 0, 7, "state/hand")
    for index, card in enumerate(state["hand"]):
        _card(card, f"state/hand/{index}")
    affordable = sum(
        effective_pips(enemy, (enemy["base_attack"] or DEFAULT_ATTACK)["element"])
        >= (enemy["base_attack"] or DEFAULT_ATTACK)["pip_cost"]
        for enemy in state["enemies"]
    )
    if affordable > 1:
        raise UnsupportedState(
            "state/enemies: at most one initially affordable response"
        )


def legal_actions(state, *, model=MODEL):
    """Preserve distinct physical hand indices, enemy indices and pass identity."""
    validate(state, model=model)
    choices = [{"card_idx": None, "target_idx": None}]
    for index, card in enumerate(state["hand"]):
        if effective_pips(state["player"], card["element"]) < card["pip_cost"]:
            continue
        if card["card_type"] in {"heal", "blade", "shield"} or card["hits_all"]:
            choices.append({"card_idx": index, "target_idx": None})
        elif card["card_type"] in {"damage", "trap"}:
            choices.extend(
                {"card_idx": index, "target_idx": target}
                for target, enemy in enumerate(state["enemies"])
                if enemy["hp"] > 0
            )
        else:
            choices.append({"card_idx": index, "target_idx": None})
    return choices


def _threshold_probability(value, inclusive):
    numerator, denominator = float(value).as_integer_ratio()
    count = (
        (numerator * GRID) // denominator + 1
        if inclusive
        else (numerator * GRID + denominator - 1) // denominator
    )
    return Fraction(max(0, min(GRID, count)), GRID)


def threshold_branches(value, inclusive, location):
    """Return all positive-mass branches with an actual binary53 representative."""
    probability = _threshold_probability(value, inclusive)
    if probability:
        yield (
            True,
            probability,
            {"method": "random", "args": [], "value": 0.0, "label": location},
        )
    if probability != 1:
        # The first excluded grid point is a valid false-side representative.
        count = probability.numerator * (GRID // probability.denominator)
        yield (
            False,
            1 - probability,
            {"method": "random", "args": [], "value": count / GRID, "label": location},
        )


def _spend(fighter, cost, element):
    multiplier = 2 if element == fighter["element"] else 1
    while cost > 0 and fighter["power_pips"] > 0:
        fighter["power_pips"] -= 1
        cost -= multiplier
    fighter["pips"] = max(0, fighter["pips"] - max(0, cost))


def _charms(fighter, kind, element):
    multiplier = 1.0
    retained = []
    for charm in fighter[kind]:
        if charm["element"] in {"neutral", element}:
            multiplier *= 1.0 + charm["value"]
        else:
            retained.append(charm)
    fighter[kind] = retained
    return multiplier


def _damage(attacker, target, base, card, blades):
    amount = float(base)
    amount *= blades
    amount *= _charms(target, "traps", card["element"])
    amount *= _charms(target, "shields", card["element"])
    amount *= 1.0 - max(0.0, target["resist"].get(card["element"], 0.0))
    amount *= 1.0 + target["boost"].get(card["element"], 0.0)
    dealt = max(0, int(amount))
    target["hp"] = max(0, target["hp"] - dealt)
    if card["heal"] > 0 and dealt > 0:
        attacker["hp"] = min(attacker["max_hp"], attacker["hp"] + dealt // 2)
    if card["dot_tick"] > 0:
        target["dots"].append(
            {
                "tick": card["dot_tick"],
                "rounds_left": card["dot_rounds"],
                "element": card["element"],
            }
        )


def _fighter_at(state, identity):
    return state["player"] if identity is None else state["enemies"][identity]


def _cast_outcomes(state, caster_id, card, target_ids, tape, location):
    paid = copy.deepcopy(state)
    _spend(_fighter_at(paid, caster_id), card["pip_cost"], card["element"])
    for success, weight, draw in threshold_branches(
        card["accuracy"], True, location + "/accuracy"
    ):
        current = copy.deepcopy(paid)
        trace = tape + (draw,)
        if not success:
            yield current, weight, trace
            continue
        caster = _fighter_at(current, caster_id)
        kind = card["card_type"]
        if kind == "damage":
            living = [
                target
                for target in target_ids
                if _fighter_at(current, target)["hp"] > 0
            ]
            blades = _charms(caster, "blades", card["element"]) if living else 1.0

            def damage_targets(
                parent, index, probability, parent_tape, *, living=living, blades=blades
            ):
                if index == len(living):
                    yield parent, probability, parent_tape
                    return
                width = card["damage_max"] - card["damage_min"] + 1
                for base in range(card["damage_min"], card["damage_max"] + 1):
                    child = copy.deepcopy(parent)
                    _damage(
                        _fighter_at(child, caster_id),
                        _fighter_at(child, living[index]),
                        base,
                        card,
                        blades,
                    )
                    draw = {
                        "method": "randint",
                        "args": [card["damage_min"], card["damage_max"]],
                        "value": base,
                        "label": location + "/damage",
                    }
                    yield from damage_targets(
                        child, index + 1, probability / width, parent_tape + (draw,)
                    )

            yield from damage_targets(current, 0, weight, trace)
        else:
            if kind == "heal":
                caster["hp"] = min(caster["max_hp"], caster["hp"] + card["heal"])
            elif kind == "blade":
                caster["blades"].append(
                    {"value": card["modifier"], "element": card["element"]}
                )
            elif kind == "trap":
                for target_id in target_ids:
                    _fighter_at(current, target_id)["traps"].append(
                        {"value": card["modifier"], "element": card["element"]}
                    )
            elif kind == "shield":
                caster["shields"].append(
                    {"value": -abs(card["modifier"]), "element": card["element"]}
                )
            yield current, weight, trace


def _player_outcomes(state, action):
    index = action["card_idx"]
    if index is None:
        yield copy.deepcopy(state), Fraction(1), ()
        return
    card = state["hand"][index]
    if card["hits_all"]:
        targets = [i for i, enemy in enumerate(state["enemies"]) if enemy["hp"] > 0]
    elif action["target_idx"] is not None:
        targets = [action["target_idx"]]
    else:
        targets = [None]
    for current, weight, tape in _cast_outcomes(
        state, None, card, targets, (), "player"
    ):
        current["hand"] = [
            member for i, member in enumerate(current["hand"]) if i != index
        ]
        yield current, weight, tape


def _enemy_outcomes(state, enemy_index, tape):
    enemy = state["enemies"][enemy_index]
    attack = enemy["base_attack"] or DEFAULT_ATTACK
    if (
        enemy["hp"] <= 0
        or state["player"]["hp"] <= 0
        or effective_pips(enemy, attack["element"]) < attack["pip_cost"]
    ):
        yield state, Fraction(1), tape
        return
    for attempt, weight, draw in threshold_branches(
        0.85, False, f"enemy/{enemy_index}/attempt"
    ):
        if not attempt:
            yield state, weight, tape + (draw,)
        else:
            for current, probability, child_tape in _cast_outcomes(
                state,
                enemy_index,
                attack,
                [None],
                tape + (draw,),
                f"enemy/{enemy_index}",
            ):
                yield current, weight * probability, child_tape


def _tick(fighter):
    for dot in fighter["dots"]:
        amount = int(
            dot["tick"]
            * (1.0 - fighter["resist"].get(dot["element"], 0.0))
            * (1.0 + fighter["boost"].get(dot["element"], 0.0))
        )
        fighter["hp"] = max(0, fighter["hp"] - max(0, amount))
        dot["rounds_left"] -= 1
    fighter["dots"] = [dot for dot in fighter["dots"] if dot["rounds_left"] > 0]


def _regen_outcomes(state, identity, tape):
    fighter = _fighter_at(state, identity)
    if fighter["pips"] + fighter["power_pips"] >= 7:
        yield state, Fraction(1), tape
        return
    label = "player" if identity is None else f"enemy/{identity}"
    for power, weight, draw in threshold_branches(
        fighter["power_pip_chance"], False, label + "/regen"
    ):
        current = copy.deepcopy(state)
        _fighter_at(current, identity)["power_pips" if power else "pips"] += 1
        yield current, weight, tape + (draw,)


def score(state):
    """Independent source-order binary64 shaped score at depth one/horizon one."""
    if state["player"]["hp"] <= 0:
        return 0.15 * (min(1, 1) / 1)
    if not any(enemy["hp"] > 0 for enemy in state["enemies"]):
        return 1.0 - 0.045 * min(6, 1)
    player_ratio = state["player"]["hp"] / max(1, state["player"]["max_hp"])
    remaining = 0.0
    maximum = 0.0
    for enemy in state["enemies"]:
        multiplier = 1.0
        for trap in enemy["traps"]:
            multiplier *= 1.0 + trap["value"]
        attack = enemy["base_attack"]
        threat = (
            max(0.5, min(2.5, (attack["damage_min"] + attack["damage_max"]) / 400.0))
            if attack is not None
            else 1.0
        )
        remaining += (enemy["hp"] / max(0.5, multiplier)) * threat
        maximum += enemy["max_hp"] * threat
    for blade in state["player"]["blades"]:
        remaining *= max(0.65, 1.0 / (1.0 + blade["value"] * 0.5))
    enemy_ratio = remaining / max(1.0, maximum)
    return max(0.0, min(1.0, 0.5 + 0.5 * (player_ratio - enemy_ratio)))


def enumerate_action(
    state, action, *, max_paths=MAX_PATHS, max_seconds=MAX_SECONDS, model=MODEL
):
    """Yield successor, exact weight and source-compatible draw tape.

    A prefix supplies transition witnesses only. A complete expectation requires
    exhausting every leaf and checking exact unit mass. Use evaluate for an
    accepted report covering the whole legal action set.
    """
    choices = legal_actions(state, model=model)
    _object(action, {"card_idx", "target_idx"}, "action")
    for field in ("card_idx", "target_idx"):
        value = action[field]
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int)
        ):
            raise UnsupportedState("action: indices must be integers or null")
    if action not in choices:
        raise UnsupportedState("action: complete legal physical action required")
    _integer(max_paths, 1, MAX_PATHS, "max_paths")
    _number(max_seconds, 0.000001, MAX_SECONDS, "max_seconds")
    started = time.monotonic()
    paths = 0

    def check():
        if time.monotonic() - started > max_seconds:
            raise ReferenceLimitExceeded("whole action exceeded cooperative deadline")

    def responses(current, index, probability, tape):
        check()
        if index == len(current["enemies"]):
            yield current, probability, tape
            return
        for child, weight, trace in _enemy_outcomes(current, index, tape):
            yield from responses(child, index + 1, probability * weight, trace)

    def regenerations(current, identities, index, probability, tape):
        check()
        if index == len(identities):
            yield current, probability, tape
            return
        for child, weight, trace in _regen_outcomes(current, identities[index], tape):
            yield from regenerations(
                child, identities, index + 1, probability * weight, trace
            )

    for played, player_weight, player_tape in _player_outcomes(state, action):
        check()
        for responded, probability, tape in responses(
            played, 0, player_weight, player_tape
        ):
            ticked = copy.deepcopy(responded)
            _tick(ticked["player"])
            for enemy in ticked["enemies"]:
                _tick(enemy)
            identities = [None] + [
                i for i, enemy in enumerate(ticked["enemies"]) if enemy["hp"] > 0
            ]
            for final, mass, trace in regenerations(
                ticked, identities, 0, probability, tape
            ):
                paths += 1
                if paths > max_paths:
                    raise ReferenceLimitExceeded(
                        "whole action exceeded finite leaf cap"
                    )
                final["round_num"] += 1
                check()
                yield {
                    "state": final,
                    "probability": mass,
                    "score": score(final),
                    "tape": trace,
                }
    check()


def evaluate(
    state,
    *,
    max_paths=MAX_PATHS,
    max_total_paths=MAX_TOTAL_PATHS,
    max_seconds=MAX_SECONDS,
    model=MODEL,
):
    """Complete action values or a refusal, never a partly priced action set."""
    started = time.monotonic()
    _integer(max_paths, 1, MAX_PATHS, "max_paths")
    _integer(max_total_paths, 1, MAX_TOTAL_PATHS, "max_total_paths")
    _number(max_seconds, 0.000001, MAX_SECONDS, "max_seconds")
    rows = []
    total_leaves = 0
    for action in legal_actions(state, model=model):
        probability = Fraction(0)
        expectation = Fraction(0)
        terminal_win = Fraction(0)
        terminal_loss = Fraction(0)
        leaves = 0
        remaining_seconds = max_seconds - (time.monotonic() - started)
        if remaining_seconds < 0.000001:
            raise ReferenceLimitExceeded("whole report exceeded cooperative deadline")
        for leaf in enumerate_action(
            state,
            action,
            max_paths=max_paths,
            max_seconds=remaining_seconds,
            model=model,
        ):
            leaves += 1
            total_leaves += 1
            if total_leaves > max_total_paths:
                raise ReferenceLimitExceeded("whole report exceeded finite leaf cap")
            mass = leaf["probability"]
            probability += mass
            expectation += mass * Fraction.from_float(leaf["score"])
            if leaf["state"]["player"]["hp"] <= 0:
                terminal_loss += mass
            elif not any(enemy["hp"] > 0 for enemy in leaf["state"]["enemies"]):
                terminal_win += mass
        if probability != 1:
            raise ArithmeticError("complete action probability mass is not one")

        def fraction(value):
            return {
                "numerator": str(value.numerator),
                "denominator": str(value.denominator),
            }

        rows.append(
            {
                "action": action,
                "expected_value": fraction(expectation),
                "expected_value_float": float(expectation),
                "mass": fraction(probability),
                "win_mass": fraction(terminal_win),
                "loss_mass": fraction(terminal_loss),
                "ongoing_mass": fraction(1 - terminal_win - terminal_loss),
                "leaves": leaves,
            }
        )
    maximum = max(
        Fraction(
            int(row["expected_value"]["numerator"]),
            int(row["expected_value"]["denominator"]),
        )
        for row in rows
    )
    elapsed = time.monotonic() - started
    if elapsed > max_seconds:
        raise ReferenceLimitExceeded(
            "whole report exceeded cooperative deadline at completion"
        )
    return {
        "model": model,
        "horizon_rounds": 1,
        "terminal_depth": 1,
        "actions": rows,
        "best_actions": [
            row["action"]
            for row in rows
            if Fraction(
                int(row["expected_value"]["numerator"]),
                int(row["expected_value"]["denominator"]),
            )
            == maximum
        ],
        "total_leaves": total_leaves,
        "elapsed_seconds": elapsed,
        "probability_model": (
            "iid_uniform_binary53_random_and_uniform_inclusive_integer"
        ),
        "value_model": "exact_expectation_of_source_order_binary64_shaped_reward",
    }
