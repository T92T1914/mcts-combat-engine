"""Bounded exact sum convolution for an explicitly admitted one-round domain.

This computes values and outcome masses only. It does not enumerate transitions,
produce successor distributions, or select subsequent actions.
"""

from __future__ import annotations

import time
from fractions import Fraction

from . import aggregation_domain as domain
from . import one_round


class _Budget:
    def __init__(self, limits, start):
        self.limits = limits
        self.start = start
        self.contributions = 0
        self.payoffs = 0

    def check(self):
        if time.monotonic() - self.start > self.limits["max_seconds"]:
            raise one_round.ReferenceLimitExceeded("sum-convolution deadline exceeded")

    def contribution(self):
        self.check()
        if self.contributions >= self.limits["max_contributions"]:
            raise one_round.ReferenceLimitExceeded(
                "sum-convolution contribution limit exceeded"
            )
        self.contributions += 1

    def payoff(self, state, damage):
        self.check()
        if self.payoffs >= self.limits["max_payoff_evaluations"]:
            raise one_round.ReferenceLimitExceeded(
                "sum-convolution payoff evaluation limit exceeded"
            )
        self.payoffs += 1
        # Unit source threat and nonlethal integer damage make every accumulated
        # HP contribution exact. Keep the original binary64 operation order after
        # those sums, rather than evaluating at a mean or substituting real EVs.
        remaining = float(sum(enemy["hp"] for enemy in state["enemies"]) - damage)
        maximum = float(sum(enemy["max_hp"] for enemy in state["enemies"]))
        player = state["player"]
        player_ratio = player["hp"] / max(1, player["max_hp"])
        enemy_ratio = remaining / max(1.0, maximum)
        value = max(0.0, min(1.0, 0.5 + 0.5 * (player_ratio - enemy_ratio)))
        return Fraction.from_float(value)


def _fraction(value):
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def evaluate(
    state,
    *,
    model=one_round.MODEL,
    max_contributions=domain.MAX_CONTRIBUTIONS,
    max_payoff_evaluations=domain.MAX_PAYOFF_EVALUATIONS,
    max_seconds=30.0,
):
    """Complete every physical action or raise, with no accepted partial ranking."""
    limits = domain.validate_limits(
        max_contributions, max_payoff_evaluations, max_seconds
    )
    start = time.monotonic()
    one_round.validate(state, model=model)
    try:
        domain.qualify(state)
    except domain.UnsupportedAggregation as exc:
        raise one_round.UnsupportedState(str(exc)) from exc
    actions = one_round.legal_actions(state, model=model)
    budget = _Budget(limits, start)
    rows = []
    for action in actions:
        before_contributions, before_payoffs = budget.contributions, budget.payoffs
        work = domain.action_work(state, action)
        if action["card_idx"] is None:
            value = budget.payoff(state, 0)
            peak_bins = 1
        else:
            card = state["hand"][action["card_idx"]]
            targets = len(state["enemies"]) if card["hits_all"] else 1
            counts = {0: 1}
            peak_bins = 1
            for _ in range(targets):
                following = {}
                for total, multiplicity in counts.items():
                    for damage in range(card["damage_min"], card["damage_max"] + 1):
                        budget.contribution()
                        key = total + damage
                        following[key] = following.get(key, 0) + multiplicity
                counts = following
                peak_bins = max(peak_bins, len(counts))
            combinations = (card["damage_max"] - card["damage_min"] + 1) ** targets
            if sum(counts.values()) != combinations:
                raise RuntimeError("sum-convolution multiplicity mass is incomplete")
            success = domain.threshold_probability(card["accuracy"], inclusive=True)
            value = (
                success
                * sum(
                    (
                        multiplicity * budget.payoff(state, damage)
                        for damage, multiplicity in counts.items()
                    ),
                    Fraction(),
                )
                / combinations
            )
            if success != 1:
                value += (1 - success) * budget.payoff(state, 0)
        actual = {
            **work,
            "contributions": budget.contributions - before_contributions,
            "payoff_evaluations": budget.payoffs - before_payoffs,
            "peak_bins": peak_bins,
        }
        if actual != work:
            raise RuntimeError(
                "sum-convolution executed work disagrees with its declared accounting"
            )
        rows.append(
            {
                "action": dict(action),
                "expected_value": _fraction(value),
                "expected_value_float": float(value),
                "mass": _fraction(Fraction(1)),
                "win_mass": _fraction(Fraction()),
                "loss_mass": _fraction(Fraction()),
                "ongoing_mass": _fraction(Fraction(1)),
                "work": actual,
            }
        )
    maximum = max(
        Fraction(
            int(row["expected_value"]["numerator"]),
            int(row["expected_value"]["denominator"]),
        )
        for row in rows
    )
    result = {
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
        "work": domain.total_work([row["work"] for row in rows]),
        "elapsed_seconds": 0.0,
        "probability_model": (
            "iid_uniform_binary53_random_and_uniform_inclusive_integer"
        ),
        "value_model": "exact_expectation_of_source_order_binary64_shaped_reward",
    }
    elapsed = time.monotonic() - start
    if elapsed > limits["max_seconds"]:
        raise one_round.ReferenceLimitExceeded("sum-convolution deadline exceeded")
    result["elapsed_seconds"] = elapsed
    return result
