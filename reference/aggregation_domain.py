"""Passive admission and accounting for a value-only sum computation method.

Callers first validate the complete normalized one-round model. This narrower
contract imports no transition, search or payoff implementation.
"""

from __future__ import annotations

import math
from fractions import Fraction

METHOD = "integer_sum_convolution_v1"
PHYSICAL_METHOD = "physical_paths_v1"
MAX_CONTRIBUTIONS = 1_000_000
MAX_PAYOFF_EVALUATIONS = 10_000
MAX_SECONDS = 30.0
GRID = 1 << 53
WORK_FIELDS = {
    "contributions",
    "payoff_evaluations",
    "peak_bins",
    "represented_damage_combinations",
    "represented_trace_leaves",
}


class UnsupportedAggregation(ValueError):
    """The selected method cannot compute the whole offered action set."""


def validate_limits(max_contributions, max_payoff_evaluations, max_seconds):
    for name, value, maximum in (
        ("max_contributions", max_contributions, MAX_CONTRIBUTIONS),
        ("max_payoff_evaluations", max_payoff_evaluations, MAX_PAYOFF_EVALUATIONS),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 1 <= value <= maximum
        ):
            raise ValueError(f"{name}: integer in 1..{maximum} required")
    if (
        isinstance(max_seconds, bool)
        or not isinstance(max_seconds, (int, float))
        or not math.isfinite(max_seconds)
        or not 0 < max_seconds <= MAX_SECONDS
    ):
        raise ValueError("max_seconds: finite positive deadline at most 30 required")
    return {
        "max_contributions": max_contributions,
        "max_payoff_evaluations": max_payoff_evaluations,
        "max_seconds": max_seconds,
    }


def threshold_probability(value, *, inclusive):
    """The accepted binary53 grid law, including the inclusive cast boundary."""
    numerator, denominator = float(value).as_integer_ratio()
    count = (
        (numerator * GRID) // denominator + 1
        if inclusive
        else (numerator * GRID + denominator - 1) // denominator
    )
    return Fraction(max(0, min(GRID, count)), GRID)


def _available(fighter, element):
    return fighter["pips"] + fighter["power_pips"] * (
        2 if element == fighter["element"] else 1
    )


def qualify(state):
    """Require integer nonlethal damage, unit threat, and no later score changes.

    The surrounding old model validator supplies schema, ranges and living-root
    checks. Asymmetric current/max HP and an injured player remain admissible.
    """
    for fighter in [state["player"], *state["enemies"]]:
        if any(fighter[name] for name in ("blades", "traps", "shields", "dots")):
            raise UnsupportedAggregation(
                "sum-convolution excludes charms and damage over time"
            )
        if any(
            value != 0
            for name in ("resist", "boost")
            for value in fighter[name].values()
        ):
            raise UnsupportedAggregation(
                "sum-convolution requires zero resistance and boost"
            )
    for enemy in state["enemies"]:
        attack = enemy["base_attack"]
        if attack is not None:
            raise UnsupportedAggregation(
                "sum-convolution excludes custom enemy attacks"
            )
        if _available(enemy, "neutral") >= 3:
            raise UnsupportedAggregation(
                "sum-convolution excludes affordable enemy responses"
            )
    player = state["player"]
    for card in state["hand"]:
        if (
            card["card_type"] != "damage"
            or card["heal"] != 0
            or card["dot_tick"] != 0
            or card["modifier"] != 0
        ):
            raise UnsupportedAggregation(
                "every hand card must be plain unmodified damage without healing"
            )
        if _available(player, card["element"]) < card["pip_cost"]:
            continue
        if any(card["damage_max"] >= enemy["hp"] for enemy in state["enemies"]):
            raise UnsupportedAggregation(
                "every offered damage roll must leave every target alive"
            )


def _regeneration_branches(fighter, *, card=None):
    pips, power = fighter["pips"], fighter["power_pips"]
    if card is not None:
        cost = card["pip_cost"]
        multiplier = 2 if card["element"] == fighter["element"] else 1
        while cost > 0 and power > 0:
            power -= 1
            cost -= multiplier
        pips = max(0, pips - max(0, cost))
    if pips + power >= 7:
        return 1
    probability = threshold_probability(fighter["power_pip_chance"], inclusive=False)
    return 2 if 0 < probability < 1 else 1


def action_work(state, action):
    """Predict bounded counters without evaluating a payoff or constructing bins.

    Represented trace leaves count positive-probability branches the historical
    enumerator would emit, including final resource regeneration. They are not
    visited leaves. A contribution is one integer bin addition during convolution.
    """
    card = None if action["card_idx"] is None else state["hand"][action["card_idx"]]
    regeneration = _regeneration_branches(state["player"], card=card)
    for enemy in state["enemies"]:
        regeneration *= _regeneration_branches(enemy)
    if card is None:
        return dict(
            contributions=0,
            payoff_evaluations=1,
            peak_bins=1,
            represented_damage_combinations=1,
            represented_trace_leaves=regeneration,
        )
    targets = len(state["enemies"]) if card["hits_all"] else 1
    width = card["damage_max"] - card["damage_min"] + 1
    bins = targets * (width - 1) + 1
    combinations = width**targets
    miss = int(threshold_probability(card["accuracy"], inclusive=True) != 1)
    return {
        "contributions": sum(
            (index * (width - 1) + 1) * width for index in range(targets)
        ),
        "payoff_evaluations": bins + miss,
        "peak_bins": bins,
        "represented_damage_combinations": combinations,
        "represented_trace_leaves": (combinations + miss) * regeneration,
    }


def total_work(rows):
    return {
        name: (
            max(row[name] for row in rows)
            if name == "peak_bins"
            else sum(row[name] for row in rows)
        )
        for name in WORK_FIELDS
    }
