"""Manual and separately authored checks for complete one-round expectations.

These small normalized fixtures describe modeled states. They are not recorded
episodes or evidence that a particular search or environment reached a state.
"""

from __future__ import annotations

import copy
import json
import unittest
from fractions import Fraction
from unittest.mock import patch

import one_round_physical_reference as physical

from engine import (
    MCTS,
    Action,
    Card,
    CardType,
    Charm,
    Combatant,
    DoT,
    Element,
    GameState,
)
from engine.simulator import advance_round
from game.decision_report import normalized
from reference import one_round as candidate

PASS = {"card_idx": None, "target_idx": None}
HIT = {"card_idx": 0, "target_idx": 0}


def card(kind="damage", **changes):
    result = {
        "name": "Modeled card",
        "element": "ember",
        "card_type": kind,
        "pip_cost": 0,
        "accuracy": 1.0,
        "damage_min": 10,
        "damage_max": 10,
        "heal": 0,
        "dot_tick": 0,
        "dot_rounds": 0,
        "modifier": 0.0,
        "hits_all": False,
    }
    if kind != "damage":
        result.update(damage_min=0, damage_max=0)
    if kind == "heal":
        result["heal"] = 15
    if kind in {"blade", "trap", "shield"}:
        result["modifier"] = 0.35
    result.update(changes)
    return result


def fighter(name, **changes):
    result = {
        "name": name,
        "element": "ember",
        "hp": 100,
        "max_hp": 100,
        "pips": 0,
        "power_pips": 0,
        "power_pip_chance": 0.0,
        "resist": {},
        "boost": {},
        "blades": [],
        "traps": [],
        "shields": [],
        "dots": [],
        "is_boss": False,
        "base_attack": None,
        "policy": None,
    }
    result.update(copy.deepcopy(changes))
    return result


def modeled_state(hand=None, *, player=None, enemies=None):
    return {
        "player": fighter("Player") if player is None else copy.deepcopy(player),
        "enemies": (
            [fighter("Enemy", element="frost")]
            if enemies is None
            else copy.deepcopy(enemies)
        ),
        "hand": [] if hand is None else copy.deepcopy(hand),
        "round_num": 1,
        "boss_rules": [],
    }


def ratio(value):
    return Fraction(int(value["numerator"]), int(value["denominator"]))


def public_state(data):
    """Construct engine objects directly from literal test data."""

    def public_card(item):
        fields = dict(item)
        fields.update(
            element=Element(item["element"]), card_type=CardType(item["card_type"])
        )
        return Card(**fields)

    def public_fighter(item):
        fields = dict(item)
        fields["element"] = Element(item["element"])
        for name in ("resist", "boost"):
            fields[name] = {Element(key): value for key, value in item[name].items()}
        for name in ("blades", "traps", "shields"):
            fields[name] = [
                Charm(charm["value"], Element(charm["element"])) for charm in item[name]
            ]
        fields["dots"] = [
            DoT(dot["tick"], dot["rounds_left"], Element(dot["element"]))
            for dot in item["dots"]
        ]
        fields["base_attack"] = (
            None if item["base_attack"] is None else public_card(item["base_attack"])
        )
        return Combatant(**fields)

    return GameState(
        public_fighter(data["player"]),
        [public_fighter(item) for item in data["enemies"]],
        [public_card(item) for item in data["hand"]],
        round_num=data["round_num"],
        boss_rules=[],
    )


class ForcedRNG:
    """Fail if the engine changes the declared draw order or damage bounds."""

    def __init__(self, tape):
        self.tape = list(tape)
        self.position = 0

    def draw(self, method, args):
        if self.position >= len(self.tape):
            raise AssertionError("engine requested an undeclared random draw")
        item = self.tape[self.position]
        self.position += 1
        if item["method"] != method or item["args"] != list(args):
            raise AssertionError("engine changed random draw kind or arguments")
        return item["value"]

    def random(self):
        return self.draw("random", ())

    def randint(self, low, high):
        return self.draw("randint", (low, high))


class OneRoundReferenceTests(unittest.TestCase):
    def assert_separate_values(self, data):
        before = copy.deepcopy(data)
        observed = candidate.evaluate(data)
        independent = physical.evaluate(data)
        self.assertEqual(data, before)
        self.assertEqual(observed["best_actions"], independent["best_actions"])
        self.assertEqual(observed["total_leaves"], independent["total_paths"])
        for current, other in zip(
            observed["actions"], independent["rows"], strict=True
        ):
            self.assertEqual(current["action"], other["action"])
            self.assertEqual(current["leaves"], other["leaves"])
            self.assertEqual(
                ratio(current["expected_value"]), ratio(other["expected_value"])
            )
            self.assertEqual(ratio(current["mass"]), 1)
            self.assertEqual(ratio(other["mass"]), 1)
            for outcome in ("win", "loss", "ongoing"):
                self.assertEqual(
                    ratio(current[outcome + "_mass"]),
                    ratio(other["result_mass"][outcome]),
                )
            self.assertEqual(
                sum(
                    ratio(current[name + "_mass"])
                    for name in ("win", "loss", "ongoing")
                ),
                1,
            )
        return observed

    def assert_engine_leaves(self, data):
        root = public_state(data)
        scorer = MCTS(horizon_rounds=1, max_sims=1)
        before = normalized(root)
        for action in candidate.legal_actions(data):
            probability = Fraction()
            for leaf in candidate.enumerate_action(data, action):
                rng = ForcedRNG(leaf["tape"])
                successor = advance_round(root.clone(), Action(**action), rng)
                self.assertEqual(rng.position, len(rng.tape))
                self.assertEqual(normalized(successor), leaf["state"])
                terminal = successor.result()
                payoff = (
                    successor.heuristic_value()
                    if terminal is None
                    else scorer._terminal_reward(terminal, 1)
                )
                self.assertEqual(payoff, leaf["score"])
                probability += leaf["probability"]
            self.assertEqual(probability, 1)
        self.assertEqual(normalized(root), before)

    def test_fixed_damage_has_manual_value_and_decimal_string_fractions(self):
        data = modeled_state(
            [card(damage_min=65, damage_max=65)],
            player=fighter("Player", hp=2400, max_hp=2400),
            enemies=[
                fighter(
                    "Enemy",
                    element="frost",
                    hp=2100,
                    max_hp=2100,
                    resist={"ember": 0.15},
                )
            ],
        )
        report = self.assert_separate_values(data)
        self.assertEqual(ratio(report["actions"][0]["expected_value"]), Fraction(1, 2))
        actual = ratio(report["actions"][1]["expected_value"])
        self.assertLessEqual(abs(actual - Fraction(431, 840)), Fraction(1, 10**16))
        self.assertEqual(report["model"], "independent_one_round_binary53_shaped_v1")
        self.assertEqual(report["horizon_rounds"], 1)
        self.assertEqual(report["terminal_depth"], 1)
        for row in json.loads(json.dumps(report))["actions"]:
            for name in (
                "expected_value",
                "mass",
                "win_mass",
                "loss_mass",
                "ongoing_mass",
            ):
                self.assertRegex(row[name]["numerator"], r"^-?[0-9]+$")
                self.assertRegex(row[name]["denominator"], r"^[1-9][0-9]*$")
        self.assert_engine_leaves(data)

    def test_binary53_thresholds_keep_inclusive_accuracy_and_strict_attempt(self):
        for chance, inclusive, count in (
            (0.5, True, 4503599627370497),
            (0.5, False, 4503599627370496),
            (0.85, True, 7656119366529844),
            (0.85, False, 7656119366529843),
        ):
            with self.subTest(chance=chance, inclusive=inclusive):
                expected = Fraction(count, 9007199254740992)
                branches = list(
                    candidate.threshold_branches(chance, inclusive, "manual")
                )
                self.assertEqual(sum(weight for _, weight, _ in branches), 1)
                self.assertEqual(
                    sum(weight for success, weight, _ in branches if success), expected
                )
                self.assertEqual(physical.threshold_mass(chance, inclusive), expected)
                for success, _, draw in branches:
                    self.assertEqual(
                        draw["value"] <= chance
                        if inclusive
                        else draw["value"] < chance,
                        success,
                    )

    def test_fizzle_consumes_card_and_pips_with_exact_weighted_payoff(self):
        data = modeled_state(
            [card(pip_cost=2, accuracy=0.5, damage_min=65, damage_max=65)],
            player=fighter("Player", pips=2, hp=2400, max_hp=2400),
            enemies=[fighter("Enemy", element="frost", hp=1, max_hp=2100)],
        )
        report = self.assert_separate_values(data)
        row = report["actions"][1]
        hit = Fraction(4503599627370497, 9007199254740992)
        expected = hit * Fraction.from_float(1.0 - 0.045) + (
            1 - hit
        ) * Fraction.from_float(0.5 + 0.5 * (1 - 1 / 2100))
        self.assertEqual(ratio(row["win_mass"]), hit)
        self.assertEqual(ratio(row["expected_value"]), expected)
        self.assertGreater(int(row["expected_value"]["denominator"]), 2**53)
        for leaf in candidate.enumerate_action(data, HIT):
            self.assertEqual(leaf["state"]["hand"], [])
            self.assertEqual(leaf["state"]["player"]["pips"], 1)
            self.assertEqual(
                leaf["state"]["enemies"][0]["hp"],
                0 if leaf["score"] == 1.0 - 0.045 else 1,
            )
        self.assert_engine_leaves(data)

    def test_duplicate_physical_cards_remain_distinct_and_shaped_score_is_not_win_odds(
        self,
    ):
        data = modeled_state(
            [card(), card()], enemies=[fighter("Enemy", hp=1, max_hp=100)]
        )
        report = self.assert_separate_values(data)
        self.assertEqual(
            [row["action"] for row in report["actions"]],
            [PASS, HIT, {"card_idx": 1, "target_idx": 0}],
        )
        self.assertEqual(
            report["actions"][1]["expected_value"],
            report["actions"][2]["expected_value"],
        )
        self.assertEqual(ratio(report["actions"][1]["win_mass"]), 1)
        self.assertEqual(
            ratio(report["actions"][1]["expected_value"]),
            Fraction.from_float(1.0 - 0.045),
        )
        self.assertEqual(report["best_actions"], [PASS])
        self.assert_engine_leaves(data)

    def test_aoe_consumes_blade_once_and_power_pips_allow_odd_overpayment(self):
        data = modeled_state(
            [card(pip_cost=5, damage_min=340, damage_max=340, hits_all=True)],
            player=fighter(
                "Player", power_pips=3, blades=[{"value": 0.35, "element": "ember"}]
            ),
            enemies=[
                fighter("First", hp=900, max_hp=900),
                fighter("Second", hp=750, max_hp=750),
            ],
        )
        self.assert_separate_values(data)
        leaves = list(
            candidate.enumerate_action(data, {"card_idx": 0, "target_idx": None})
        )
        self.assertEqual(len(leaves), 1)
        successor = leaves[0]["state"]
        self.assertEqual([enemy["hp"] for enemy in successor["enemies"]], [441, 291])
        self.assertEqual(successor["player"]["blades"], [])
        self.assertEqual(successor["player"]["power_pips"], 0)
        self.assertEqual(successor["player"]["pips"], 1)
        self.assert_engine_leaves(data)

    def test_drain_uses_nominal_dealt_damage_and_same_round_dot_can_add_fifth_effect(
        self,
    ):
        drain = modeled_state(
            [card(damage_min=55, damage_max=55, heal=1)],
            player=fighter("Player", hp=100, max_hp=2400),
            enemies=[fighter("Enemy", hp=10, max_hp=100)],
        )
        self.assert_separate_values(drain)
        leaf = next(candidate.enumerate_action(drain, HIT))
        self.assertEqual(leaf["state"]["player"]["hp"], 127)
        self.assertEqual(leaf["state"]["enemies"][0]["hp"], 0)
        self.assert_engine_leaves(drain)

        dotted = modeled_state(
            [card(damage_min=1, damage_max=1, dot_tick=3, dot_rounds=2)],
            enemies=[
                fighter(
                    "Enemy",
                    dots=[
                        {"tick": 0, "rounds_left": 3, "element": "ember"}
                        for _ in range(4)
                    ],
                )
            ],
        )
        self.assert_separate_values(dotted)
        leaf = next(candidate.enumerate_action(dotted, HIT))
        self.assertEqual(leaf["state"]["enemies"][0]["hp"], 96)
        self.assertEqual(len(leaf["state"]["enemies"][0]["dots"]), 5)
        self.assertEqual(leaf["state"]["enemies"][0]["dots"][-1]["rounds_left"], 1)
        self.assert_engine_leaves(dotted)

    def test_simultaneous_upkeep_death_is_loss_and_only_dead_player_regenerates(self):
        dot = {"tick": 1, "rounds_left": 1, "element": "ember"}
        data = modeled_state(
            [card("utility")],
            player=fighter("Player", hp=1, dots=[dot]),
            enemies=[fighter("Enemy", hp=1, dots=[dot])],
        )
        report = self.assert_separate_values(data)
        for row in report["actions"]:
            self.assertEqual(ratio(row["loss_mass"]), 1)
            self.assertEqual(ratio(row["expected_value"]), Fraction.from_float(0.15))
            for leaf in candidate.enumerate_action(data, row["action"]):
                self.assertEqual(leaf["state"]["player"]["hp"], 0)
                self.assertEqual(leaf["state"]["enemies"][0]["hp"], 0)
                self.assertEqual(leaf["state"]["player"]["pips"], 1)
                self.assertEqual(leaf["state"]["enemies"][0]["pips"], 0)
                self.assertEqual(leaf["state"]["round_num"], 2)
        self.assert_engine_leaves(data)

    def test_all_card_types_match_separate_arithmetic_and_engine_event_order(self):
        for kind in ("damage", "heal", "blade", "trap", "shield", "utility"):
            with self.subTest(kind=kind):
                data = modeled_state(
                    [card(kind, pip_cost=2, accuracy=0.5)],
                    player=fighter(
                        "Player",
                        hp=80,
                        pips=2,
                        power_pips=1,
                        power_pip_chance=0.5,
                        resist={"frost": 0.1},
                        blades=[{"value": 0.2, "element": "ember"}],
                    ),
                    enemies=[
                        fighter(
                            "Enemy",
                            element="frost",
                            hp=40,
                            pips=3,
                            power_pip_chance=0.5,
                            traps=[{"value": 0.3, "element": "ember"}],
                            base_attack=card(
                                element="frost",
                                pip_cost=3,
                                accuracy=0.85,
                                damage_min=8,
                                damage_max=9,
                            ),
                        )
                    ],
                )
                self.assert_separate_values(data)
                self.assert_engine_leaves(data)

    def test_full_slot_neutral_default_and_negative_resistance_preserve_phase_rules(
        self,
    ):
        data = modeled_state(
            [card("utility", hits_all=True)],
            player=fighter(
                "Player",
                hp=2000,
                max_hp=2400,
                pips=6,
                power_pips=1,
                power_pip_chance=0.5,
                resist={"neutral": -0.5, "ember": -0.5},
                dots=[{"tick": 10, "rounds_left": 1, "element": "ember"}],
            ),
            enemies=[
                fighter(
                    "Affordable",
                    element="frost",
                    hp=900,
                    max_hp=900,
                    pips=1,
                    power_pips=2,
                ),
                fighter(
                    "Unaffordable", element="frost", hp=750, max_hp=750, power_pips=2
                ),
            ],
        )
        self.assert_separate_values(data)
        for leaf in candidate.enumerate_action(
            data, {"card_idx": 0, "target_idx": None}
        ):
            player = leaf["state"]["player"]
            self.assertEqual((player["pips"], player["power_pips"]), (6, 1))
            self.assertEqual(player["dots"], [])
            enemy = leaf["state"]["enemies"][1]
            self.assertEqual((enemy["pips"], enemy["power_pips"]), (1, 2))
            damage = [
                draw["value"] for draw in leaf["tape"] if draw["method"] == "randint"
            ]
            self.assertEqual(player["hp"], 2000 - (damage[0] if damage else 0) - 15)
        self.assert_engine_leaves(data)

    def test_unsupported_states_refuse_whole_input_without_dropping_mechanics(self):
        edits = (
            ("boss", lambda data: data["player"].update(is_boss=True)),
            ("rules", lambda data: data.update(boss_rules=[{"type": "unknown"}])),
            ("policy", lambda data: data["enemies"][0].update(policy={"attack": 1})),
            ("dead", lambda data: data["player"].update(hp=0)),
            ("zero_accuracy", lambda data: data["hand"][0].update(accuracy=0)),
            ("wide_damage", lambda data: data["hand"][0].update(damage_max=161)),
            ("boolean_pips", lambda data: data["player"].update(pips=True)),
            ("unmodeled", lambda data: data["hand"][0].update(hidden=True)),
            (
                "negative_blade",
                lambda data: data["player"].update(
                    blades=[{"value": -0.1, "element": "ember"}]
                ),
            ),
            ("unpaired_dot", lambda data: data["hand"][0].update(dot_tick=1)),
        )
        for label, edit in edits:
            with self.subTest(label=label):
                data = modeled_state([card()])
                edit(data)
                before = copy.deepcopy(data)
                with self.assertRaises(candidate.UnsupportedState):
                    candidate.evaluate(data)
                self.assertEqual(data, before)
        too_many = modeled_state(
            enemies=[fighter("First", pips=3), fighter("Second", pips=3)]
        )
        with self.assertRaises(candidate.UnsupportedState):
            candidate.evaluate(too_many)

    def test_illegal_action_indices_and_invalid_limits_refuse(self):
        data = modeled_state([card()])
        for action in (
            {"card_idx": True, "target_idx": 0},
            {"card_idx": 0, "target_idx": False},
            {"card_idx": None, "target_idx": 0},
            {"card_idx": 1, "target_idx": 0},
        ):
            with self.subTest(action=action):
                with self.assertRaises(candidate.UnsupportedState):
                    list(candidate.enumerate_action(data, action))
        for limits in (
            {"max_paths": True},
            {"max_paths": 250001},
            {"max_total_paths": 0},
            {"max_total_paths": 1000001},
            {"max_seconds": 0},
            {"max_seconds": float("nan")},
            {"max_seconds": 31},
        ):
            with self.subTest(limits=limits):
                with self.assertRaises(candidate.UnsupportedState):
                    candidate.evaluate(data, **limits)

    def test_leaf_caps_and_cooperative_deadline_produce_no_partial_report(self):
        data = modeled_state([card(accuracy=0.5, damage_min=10, damage_max=11)])
        before = copy.deepcopy(data)
        with self.assertRaises(candidate.ReferenceLimitExceeded):
            candidate.evaluate(data, max_paths=1)
        with self.assertRaises(candidate.ReferenceLimitExceeded):
            candidate.evaluate(data, max_total_paths=1)
        with patch.object(candidate.time, "monotonic", side_effect=[0.0, 0.01]):
            with self.assertRaises(candidate.ReferenceLimitExceeded):
                candidate.evaluate(data, max_seconds=0.001)
        with patch.object(candidate.time, "monotonic", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                candidate.evaluate(data)
        self.assertEqual(data, before)

    def test_empty_hand_returns_complete_pass_and_equal_utility_tie_is_preserved(self):
        empty = self.assert_separate_values(modeled_state())
        self.assertEqual([row["action"] for row in empty["actions"]], [PASS])
        self.assertEqual(empty["best_actions"], [PASS])
        utility = self.assert_separate_values(modeled_state([card("utility")]))
        self.assertEqual(
            utility["best_actions"], [PASS, {"card_idx": 0, "target_idx": None}]
        )

    def test_completion_deadline_and_report_use_the_same_clock_observation(self):
        data = modeled_state()
        leaf = {"state": data, "probability": Fraction(1), "score": 0.5}
        with (
            patch.object(candidate, "enumerate_action", return_value=iter([leaf])),
            patch.object(candidate.time, "monotonic", side_effect=[0.0, 0.0, 1.0]),
        ):
            result = candidate.evaluate(data, max_seconds=1.0)
        self.assertEqual(result["elapsed_seconds"], 1.0)
        self.assertEqual(result["total_leaves"], 1)


if __name__ == "__main__":
    unittest.main()
