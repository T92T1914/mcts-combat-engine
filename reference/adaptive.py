"""Bounded two-round adaptive reference for complete normalized states.

The accepted one-round module supplies transition primitives only. This
module does not call its root evaluator, whole-round wrapper or one-round score.
Every root action is fixed for round one. A complete observed successor then
permits an optimal legal second action under the separately named objective.

Exact values weight completed source-order binary64 payoff atoms under the iid
binary53 law. They are shaped expectations rather than calibrated win odds.
"""

from __future__ import annotations

import copy
import math
import time
from fractions import Fraction

MODEL = "independent_two_round_adaptive_binary53_shaped_v1"
PROBABILITY_MODEL = "iid_binary53_inclusive_integer_v1"
VALUE_MODEL = "source_order_binary64_shaped_depth_two_v1"
MAX_TRANSITIONS = 1_000_000
MAX_PER_ACTION = 250_000
MAX_WORK_UNITS = 3_000_000
MAX_SECONDS = 30.0
GRID = 1 << 53
MASS_KEYS = ("win_depth_1", "loss_depth_1", "win_depth_2", "loss_depth_2", "cutoff")


class ReferenceRefusal(Exception):
    """No action values from a refused request are an accepted result."""

    def __init__(self, message, *, work=None):
        super().__init__(message)
        self.work = work


class UnsupportedState(ReferenceRefusal, ValueError):
    """The input lies outside the separately declared adaptive reference."""


class ReferenceLimitExceeded(ReferenceRefusal, RuntimeError):
    """A whole request exhausted a finite work limit or cooperative deadline."""


class ReferenceArithmeticError(ReferenceRefusal, ArithmeticError):
    """A complete probability or value invariant failed."""


class ReferenceInterrupted(ReferenceRefusal, RuntimeError):
    """An interrupted request has no accepted partial decision."""


class ReferenceCalculationFailed(ReferenceRefusal, RuntimeError):
    """The request failed before a complete decision could be returned."""


def _fraction(value):
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def _mass_dict(masses):
    return {
        name: _fraction(mass) for name, mass in zip(MASS_KEYS, masses, strict=False)
    }


def _zero_masses():
    return [Fraction(0) for _ in MASS_KEYS]


def _integer(value, low, high, location):
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not low <= value <= high
    ):
        raise UnsupportedState(f"{location}: integer in {low}..{high} required")


def _seconds(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 < value <= MAX_SECONDS
        or not math.isfinite(value)
    ):
        raise UnsupportedState(
            "max_seconds: finite positive number at most 30 required"
        )


def threshold_probability(value, inclusive):
    """Expose the declared grid law, including zero as a direct helper case.

    This helper's zero endpoint does not change root admission: normalized
    source cards with zero accuracy remain unsupported.
    """
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 <= value <= 1
        or not math.isfinite(value)
        or not isinstance(inclusive, bool)
    ):
        raise UnsupportedState(
            "threshold: finite number in 0..1 and Boolean mode required"
        )
    numerator, denominator = float(value).as_integer_ratio()
    if inclusive:
        count = (numerator * GRID) // denominator + 1
    else:
        count = (numerator * GRID + denominator - 1) // denominator
    return Fraction(max(0, min(GRID, count)), GRID)


class _Budget:
    def __init__(
        self, started, max_transitions, max_per_action, max_work_units, max_seconds
    ):
        self.started = started
        self.max_transitions = max_transitions
        self.max_per_action = max_per_action
        self.max_work_units = max_work_units
        self.max_seconds = max_seconds
        self.first_round_transitions = 0
        self.second_round_transitions = 0
        self.payoff_evaluations = 0
        self.observation_group_operations = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.work_units = 0
        self.per_action_transition_leaves = []

    @property
    def transition_leaves(self):
        return self.first_round_transitions + self.second_round_transitions

    def snapshot(self, elapsed=None):
        return {
            "first_round_transitions": self.first_round_transitions,
            "second_round_transitions": self.second_round_transitions,
            "transition_leaves": self.transition_leaves,
            "payoff_evaluations": self.payoff_evaluations,
            "observation_group_operations": self.observation_group_operations,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "work_units": self.work_units,
            "per_action_transition_leaves": list(self.per_action_transition_leaves),
            "elapsed_seconds": elapsed,
            "max_transitions": self.max_transitions,
            "max_per_action": self.max_per_action,
            "max_work_units": self.max_work_units,
            "max_seconds": self.max_seconds,
            "cache_policy": "request_local_complete_continuation_on_miss",
            "work_unit_rule": (
                "transition_leaves + payoff_evaluations + observation_group_operations"
            ),
        }

    def check(self):
        elapsed = time.perf_counter() - self.started
        if elapsed >= self.max_seconds:
            raise ReferenceLimitExceeded(
                "whole request exceeded cooperative deadline",
                work=self.snapshot(elapsed),
            )

    def charge(self, kind, *, root_index=None, depth=None):
        self.check()
        # Charge the executed unit before any resulting leaf/value/group is
        # accepted. A refused attempted unit is retained in exception metadata.
        if kind == "transition":
            if depth == 1:
                self.first_round_transitions += 1
            elif depth == 2:
                self.second_round_transitions += 1
            else:
                raise ReferenceArithmeticError(
                    "transition: unsupported simulated depth"
                )
            self.per_action_transition_leaves[root_index] += 1
        elif kind == "payoff":
            self.payoff_evaluations += 1
        elif kind == "group":
            self.observation_group_operations += 1
        else:
            raise ReferenceArithmeticError("work: unrecognized unit")
        self.work_units += 1
        if self.transition_leaves > self.max_transitions:
            raise ReferenceLimitExceeded(
                "whole request exceeded transition leaf cap", work=self.snapshot()
            )
        if (
            root_index is not None
            and self.per_action_transition_leaves[root_index] > self.max_per_action
        ):
            raise ReferenceLimitExceeded(
                "root action including continuations exceeded transition leaf cap",
                work=self.snapshot(),
            )
        if self.work_units > self.max_work_units:
            raise ReferenceLimitExceeded(
                "whole request exceeded combined work unit cap", work=self.snapshot()
            )
        self.check()


def _load_helpers(budget):
    budget.check()
    # Import inside the timed request. The primitives are stateless, while this
    # evaluator keeps every mutable group and arithmetic cache request-local.
    from . import one_round as helper

    budget.check()
    return helper


def _plain_card(helper, card, location, *, damage_only=False, narrow=True):
    helper._card(card, location)
    kind = card["card_type"]
    if kind not in ({"damage"} if damage_only else {"damage", "heal"}):
        raise UnsupportedState(f"{location}: plain damage or pure healing required")
    if card["dot_tick"] != 0 or card["dot_rounds"] != 0 or card["modifier"] != 0:
        raise UnsupportedState(f"{location}: effect payloads excluded")
    if kind == "damage":
        if card["heal"] != 0:
            raise UnsupportedState(f"{location}: drain payload excluded")
        if narrow and card["damage_max"] - card["damage_min"] + 1 > 3:
            raise UnsupportedState(
                f"{location}: at most three damage integers required"
            )
    elif (
        card["damage_min"] != 0
        or card["damage_max"] != 0
        or card["hits_all"] is not False
    ):
        raise UnsupportedState(
            f"{location}: pure heal cannot carry damage or area payload"
        )


def _plain_fighter(helper, fighter, location, *, enemy=False):
    helper._fighter(fighter, location)
    for kind in ("blades", "traps", "shields", "dots"):
        if fighter[kind] != []:
            raise UnsupportedState(f"{location}/{kind}: initial effects excluded")
    for kind in ("resist", "boost"):
        if any(value != 0 for value in fighter[kind].values()):
            raise UnsupportedState(f"{location}/{kind}: nonzero values excluded")
    attack = fighter["base_attack"]
    if enemy and attack is None:
        raise UnsupportedState(
            f"{location}/base_attack: supplied narrow attack required"
        )
    if attack is not None:
        _plain_card(
            helper, attack, location + "/base_attack", damage_only=True, narrow=enemy
        )


def _admit(helper, state, model, horizon, budget):
    if not isinstance(model, str) or model != MODEL:
        raise UnsupportedState("model: exact two-round adaptive identity required")
    _integer(horizon, 2, 2, "horizon")
    helper._object(state, helper.STATE_FIELDS, "state")
    helper._integer(state["round_num"], 1, 30, "state/round_num")
    if state["boss_rules"] != []:
        raise UnsupportedState("state/boss_rules: rules excluded")
    _plain_fighter(helper, state["player"], "state/player")
    helper._list(state["enemies"], 1, 1, "state/enemies")
    _plain_fighter(helper, state["enemies"][0], "state/enemies/0", enemy=True)
    helper._list(state["hand"], 0, 3, "state/hand")
    for index, card in enumerate(state["hand"]):
        budget.check()
        _plain_card(helper, card, f"state/hand/{index}")
    budget.check()


def _legal_actions(helper, state):
    """Use internal alive successors without treating round 31/32 as roots."""
    if _terminal(state) is not None:
        raise ReferenceArithmeticError(
            "a terminal observation cannot offer continuations"
        )
    choices = [{"card_idx": None, "target_idx": None}]
    for index, card in enumerate(state["hand"]):
        if helper.effective_pips(state["player"], card["element"]) < card["pip_cost"]:
            continue
        choices.append(
            {
                "card_idx": index,
                "target_idx": (
                    0
                    if card["card_type"] == "damage" and not card["hits_all"]
                    else None
                ),
            }
        )
    return choices


def _check_action(action, choices):
    if not isinstance(action, dict) or set(action) != {"card_idx", "target_idx"}:
        raise UnsupportedState("action: exact physical card and target fields required")
    for field in ("card_idx", "target_idx"):
        index = action[field]
        if index is not None and (
            isinstance(index, bool) or not isinstance(index, int)
        ):
            raise UnsupportedState("action: indices must be integers or null")
    if action not in choices:
        raise UnsupportedState("action: complete legal physical action required")


def _terminal(state):
    if state["player"]["hp"] <= 0:
        return "loss"
    if not any(enemy["hp"] > 0 for enemy in state["enemies"]):
        return "win"
    return None


def _score(state, depth):
    """Compute original ordered binary64 atoms at simulated depth and horizon 2."""
    if state["player"]["hp"] <= 0:
        return 0.15 * (min(depth, 2) / 2)
    if not any(enemy["hp"] > 0 for enemy in state["enemies"]):
        return 1.0 - 0.045 * min(6, depth)
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


def _key(value):
    """Preserve all normalized fields, list order and literal numeric types."""
    if isinstance(value, dict):
        return ("dict", tuple((name, _key(value[name])) for name in sorted(value)))
    if isinstance(value, list):
        return ("list", tuple(_key(member) for member in value))
    if value is None:
        return ("none",)
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, int):
        return ("int", value)
    if isinstance(value, float):
        return ("float", value.hex())
    if isinstance(value, str):
        return ("str", value)
    raise ReferenceArithmeticError("observation contains an unregistered value type")


def _round_outcomes(helper, state, action, budget, root_index, depth):
    _check_action(action, _legal_actions(helper, state))
    budget.check()
    for played, player_mass, player_tape in helper._player_outcomes(state, action):
        budget.check()
        for responded, response_mass, response_tape in helper._enemy_outcomes(
            played, 0, player_tape
        ):
            budget.check()
            ticked = copy.deepcopy(responded)
            helper._tick(ticked["player"])
            for enemy in ticked["enemies"]:
                helper._tick(enemy)
            response_probability = player_mass * response_mass
            for (
                player_regen,
                player_regen_mass,
                player_regen_tape,
            ) in helper._regen_outcomes(ticked, None, response_tape):
                budget.check()
                if player_regen["enemies"][0]["hp"] > 0:
                    enemy_regens = helper._regen_outcomes(
                        player_regen, 0, player_regen_tape
                    )
                else:
                    enemy_regens = ((player_regen, Fraction(1), player_regen_tape),)
                for final, enemy_regen_mass, _ in enemy_regens:
                    budget.charge("transition", root_index=root_index, depth=depth)
                    mass = response_probability * player_regen_mass * enemy_regen_mass
                    if not isinstance(mass, Fraction) or mass <= 0:
                        raise ReferenceArithmeticError(
                            "transition probability must be positive exact mass"
                        )
                    final["round_num"] += 1
                    budget.check()
                    yield final, mass
    budget.check()


def _assert_distribution(total, masses):
    if total != 1 or sum(masses, Fraction(0)) != 1 or any(mass < 0 for mass in masses):
        raise ReferenceArithmeticError(
            "complete probability or outcome mass is not exactly one"
        )


def _continuation(helper, state, root_hand_indices, action, budget, root_index, cache):
    cache_key = (
        _key(state),
        tuple(root_hand_indices),
        action["card_idx"],
        action["target_idx"],
    )
    budget.check()
    if cache_key in cache:
        budget.cache_hits += 1
        return cache[cache_key]
    budget.cache_misses += 1
    probability = Fraction(0)
    expectation = Fraction(0)
    masses = _zero_masses()
    for final, mass in _round_outcomes(helper, state, action, budget, root_index, 2):
        budget.charge("payoff")
        atom = _score(final, 2)
        if not math.isfinite(atom):
            raise ReferenceArithmeticError("payoff atom must be finite")
        probability += mass
        expectation += mass * Fraction.from_float(atom)
        terminal = _terminal(final)
        masses[2 if terminal == "win" else 3 if terminal == "loss" else 4] += mass
    _assert_distribution(probability, masses)
    completed = (expectation, probability, tuple(masses))
    budget.check()
    cache[cache_key] = completed
    return completed


def evaluate(
    state,
    *,
    model=MODEL,
    horizon=2,
    max_transitions=MAX_TRANSITIONS,
    max_per_action=MAX_PER_ACTION,
    max_work_units=MAX_WORK_UNITS,
    max_seconds=MAX_SECONDS,
):
    """Return every complete adaptive action value or raise a typed refusal."""
    started = time.perf_counter()
    _integer(max_transitions, 1, MAX_TRANSITIONS, "max_transitions")
    _integer(max_per_action, 1, MAX_PER_ACTION, "max_per_action")
    _integer(max_work_units, 1, MAX_WORK_UNITS, "max_work_units")
    _seconds(max_seconds)
    budget = _Budget(
        started, max_transitions, max_per_action, max_work_units, max_seconds
    )
    continuation_cache = {}
    active_groups = {}
    helper = None
    try:
        helper = _load_helpers(budget)
        _admit(helper, state, model, horizon, budget)
        root = copy.deepcopy(state)
        root_hand_indices = list(range(len(root["hand"])))
        choices = _legal_actions(helper, root)
        budget.per_action_transition_leaves = [0 for _ in choices]
        rows = []
        root_values = []
        for root_index, action in enumerate(choices):
            budget.check()
            active_groups.clear()
            retained_indices = list(root_hand_indices)
            if action["card_idx"] is not None:
                retained_indices.pop(action["card_idx"])
            for final, mass in _round_outcomes(
                helper, root, action, budget, root_index, 1
            ):
                budget.charge("group")
                observation_key = (_key(final), tuple(retained_indices))
                if observation_key in active_groups:
                    active_groups[observation_key]["probability"] += mass
                else:
                    active_groups[observation_key] = {
                        "state": final,
                        "probability": mass,
                    }
            probability = sum(
                (group["probability"] for group in active_groups.values()), Fraction(0)
            )
            if probability != 1:
                raise ReferenceArithmeticError(
                    "complete first-round observation mass is not one"
                )
            value = Fraction(0)
            action_masses = _zero_masses()
            observation_rows = []
            for group in active_groups.values():
                budget.charge("group")
                observed = group["state"]
                observed_probability = group["probability"]
                terminal = _terminal(observed)
                continuations = []
                optimal_actions = []
                chosen = None
                if terminal is not None:
                    budget.charge("payoff")
                    adaptive_value = Fraction.from_float(_score(observed, 1))
                    conditional_masses = _zero_masses()
                    conditional_masses[0 if terminal == "win" else 1] = Fraction(1)
                else:
                    conditional_values = []
                    continuation_masses = []
                    for local_action in _legal_actions(helper, observed):
                        expected, continuation_probability, masses = _continuation(
                            helper,
                            observed,
                            retained_indices,
                            local_action,
                            budget,
                            root_index,
                            continuation_cache,
                        )
                        local_index = local_action["card_idx"]
                        original_index = (
                            None
                            if local_index is None
                            else retained_indices[local_index]
                        )
                        conditional_values.append(expected)
                        continuation_masses.append(masses)
                        continuations.append(
                            {
                                "action": dict(local_action),
                                "root_card_idx": original_index,
                                "value": _fraction(expected),
                                "total_probability": _fraction(
                                    continuation_probability
                                ),
                                "masses": _mass_dict(masses),
                            }
                        )
                    adaptive_value = max(conditional_values)
                    optimal_actions = [
                        index
                        for index, expected in enumerate(conditional_values)
                        if expected == adaptive_value
                    ]
                    chosen = optimal_actions[0]
                    conditional_masses = continuation_masses[chosen]
                value += observed_probability * adaptive_value
                for index, mass in enumerate(conditional_masses):
                    action_masses[index] += observed_probability * mass
                observation_rows.append(
                    {
                        "state": observed,
                        "root_hand_indices": list(retained_indices),
                        "probability": _fraction(observed_probability),
                        "terminal": terminal,
                        "continuations": continuations,
                        "optimal_actions": optimal_actions,
                        "chosen": chosen,
                        "adaptive_value": _fraction(adaptive_value),
                    }
                )
                budget.check()
            _assert_distribution(probability, action_masses)
            root_values.append(value)
            rows.append(
                {
                    "action": dict(action),
                    "value": _fraction(value),
                    "total_probability": _fraction(probability),
                    "masses": _mass_dict(action_masses),
                    "observations": observation_rows,
                }
            )
        best_value = max(root_values)
        result = {
            "model": MODEL,
            "horizon_rounds": 2,
            "probability_model": PROBABILITY_MODEL,
            "value_model": VALUE_MODEL,
            "actions": rows,
            "optimal_actions": [
                index for index, value in enumerate(root_values) if value == best_value
            ],
            "best_value": _fraction(best_value),
            "source_provenance": {
                "transition_helper": "reference/one_round.py",
                "qualification_model": MODEL,
            },
            "observation_key": (
                "complete normalized post-round state with type-tagged numeric values, "
                "ordered physical hand and original root hand indices; no draw tape"
            ),
            "work": budget.snapshot(),
        }
        # The last clock sample occurs after the entire arithmetic envelope and
        # work snapshot have been assembled. It is the acceptance sample.
        elapsed = time.perf_counter() - started
        if elapsed >= max_seconds:
            raise ReferenceLimitExceeded(
                "whole request exceeded cooperative deadline at completed assembly",
                work=budget.snapshot(elapsed),
            )
        result["work"]["elapsed_seconds"] = elapsed
        return result
    except ReferenceRefusal:
        raise
    except KeyboardInterrupt as exc:
        raise ReferenceInterrupted(
            "whole request interrupted", work=budget.snapshot()
        ) from exc
    except ArithmeticError as exc:
        raise ReferenceArithmeticError(
            "whole request arithmetic failed", work=budget.snapshot()
        ) from exc
    except Exception as exc:
        if helper is not None and isinstance(exc, helper.UnsupportedState):
            raise UnsupportedState(str(exc), work=budget.snapshot()) from exc
        raise ReferenceCalculationFailed(
            "whole request failed before completion", work=budget.snapshot()
        ) from exc
    finally:
        continuation_cache.clear()
        active_groups.clear()
        helper = None
