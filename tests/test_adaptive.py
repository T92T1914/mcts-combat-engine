"""Manual witnesses and boundaries for the separate two-round objective.

The states are synthetic normalized fixtures. Literal payoff fractions come
from the separately reviewed manual witness, rather than this evaluator's
score function. These checks establish modeled behavior when executed.
"""

from __future__ import annotations

import copy
import unittest
from fractions import Fraction
from unittest.mock import patch

from reference import adaptive

PASS = {"card_idx": None, "target_idx": None}
C3 = Fraction(8872091265919877, 9007199254740992)
C2 = Fraction(4458563631096791, 4503599627370496)
C1 = Fraction(8962163258467287, 9007199254740992)
W1 = Fraction(8601875288277647, 9007199254740992)
W2 = Fraction(8196551321814303, 9007199254740992)
L1 = Fraction(5404319552844595, 72057594037927936)


def card(**changes):
    result = {
        "name": "Synthetic hit",
        "element": "ember",
        "card_type": "damage",
        "pip_cost": 0,
        "accuracy": 1.0,
        "damage_min": 1,
        "damage_max": 1,
        "heal": 0,
        "dot_tick": 0,
        "dot_rounds": 0,
        "modifier": 0.0,
        "hits_all": False,
    }
    result.update(changes)
    return result


def healing(**changes):
    return card(card_type="heal", damage_min=0, damage_max=0, heal=5, **changes)


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


def state(hand=(), *, player=None, enemy=None, round_num=1):
    return {
        "player": fighter("Player") if player is None else copy.deepcopy(player),
        "enemies": [
            fighter("Enemy", hp=3, element="frost", base_attack=card(pip_cost=7))
            if enemy is None
            else copy.deepcopy(enemy)
        ],
        "hand": copy.deepcopy(list(hand)),
        "round_num": round_num,
        "boss_rules": [],
    }


def witness(*, variable=True):
    return state(
        [
            card(name="Variable hit", damage_max=2 if variable else 1),
            card(name="Fixed hit"),
        ]
    )


def ratio(value):
    return Fraction(int(value["numerator"]), int(value["denominator"]))


class AdaptiveReferenceTests(unittest.TestCase):
    def assert_complete_mass(self, report):
        self.assertEqual(report["model"], adaptive.MODEL)
        self.assertEqual(report["horizon_rounds"], 2)
        self.assertEqual(report["probability_model"], adaptive.PROBABILITY_MODEL)
        self.assertEqual(report["value_model"], adaptive.VALUE_MODEL)
        for row in report["actions"]:
            self.assertEqual(ratio(row["total_probability"]), 1)
            self.assertEqual(set(row["masses"]), set(adaptive.MASS_KEYS))
            self.assertEqual(sum(map(ratio, row["masses"].values())), 1)
            self.assertEqual(
                sum(ratio(item["probability"]) for item in row["observations"]),
                1,
            )
            for observed in row["observations"]:
                for continuation in observed["continuations"]:
                    self.assertEqual(ratio(continuation["total_probability"]), 1)
                    self.assertEqual(
                        sum(map(ratio, continuation["masses"].values())), 1
                    )
                    self.assertEqual(ratio(continuation["masses"]["win_depth_1"]), 0)
                    self.assertEqual(ratio(continuation["masses"]["loss_depth_1"]), 0)

    def test_manual_adaptation_prices_every_root_and_offered_continuation(self):
        data = witness()
        before = copy.deepcopy(data)
        report = adaptive.evaluate(data)
        self.assertEqual(data, before)
        self.assert_complete_mass(report)
        self.assertEqual(
            [row["action"] for row in report["actions"]],
            [PASS, {"card_idx": 0, "target_idx": 0}, {"card_idx": 1, "target_idx": 0}],
        )
        self.assertEqual(
            [ratio(row["value"]) for row in report["actions"]],
            [Fraction(17879290520660869, 18014398509481984), C1, C2],
        )
        self.assertEqual(report["optimal_actions"], [1])
        self.assertEqual(ratio(report["best_value"]), C1)
        expected = [
            {3: ([C3, (C2 + C1) / 2, C2], [1], 1)},
            {2: ([C2, C1], [1], 1), 1: ([C1, W2], [0], 0)},
            {2: ([C2, (C1 + W2) / 2], [0], 0)},
        ]
        for row, expected_observations in zip(report["actions"], expected, strict=True):
            self.assertEqual(ratio(row["masses"]["cutoff"]), 1)
            self.assertEqual(len(row["observations"]), len(expected_observations))
            for observed in row["observations"]:
                hp = observed["state"]["enemies"][0]["hp"]
                values, ties, chosen = expected_observations[hp]
                self.assertEqual(
                    [ratio(item["value"]) for item in observed["continuations"]],
                    values,
                )
                self.assertEqual(observed["optimal_actions"], ties)
                self.assertEqual(observed["chosen"], chosen)
                self.assertEqual(ratio(observed["adaptive_value"]), values[chosen])
        varied_observations = report["actions"][1]["observations"]
        for observed in varied_observations:
            self.assertEqual(ratio(observed["probability"]), Fraction(1, 2))
            self.assertEqual(observed["root_hand_indices"], [1])
            self.assertEqual(
                [item["root_card_idx"] for item in observed["continuations"]],
                [None, 1],
            )
            self.assertEqual(
                [item["action"] for item in observed["continuations"]],
                [PASS, {"card_idx": 0, "target_idx": 0}],
            )
        self.assertGreater(C1, max((C2 + C1) / 2, (C1 + W2) / 2))
        self.assertEqual(
            C1 - (C2 + C1) / 2, Fraction(45035996273705, 18014398509481984)
        )

    def test_manual_shared_commitment_control_preserves_exact_ties(self):
        report = adaptive.evaluate(witness(variable=False))
        self.assertEqual(
            [ratio(row["value"]) for row in report["actions"]], [C2, C1, C1]
        )
        self.assertEqual(report["optimal_actions"], [1, 2])
        observed = report["actions"][0]["observations"][0]
        self.assertEqual(observed["optimal_actions"], [1, 2])
        self.assertEqual(observed["chosen"], 1)
        self.assertEqual(len(observed["continuations"]), 3)

    def test_observed_resources_determine_matching_cost_two_legality(self):
        report = adaptive.evaluate(
            state(
                [card(pip_cost=2), healing()],
                player=fighter("Player", hp=95, power_pip_chance=0.5),
            )
        )
        observations = report["actions"][0]["observations"]
        self.assertEqual(len(observations), 2)
        for observed in observations:
            player = observed["state"]["player"]
            expected = (
                [
                    PASS,
                    {"card_idx": 0, "target_idx": 0},
                    {"card_idx": 1, "target_idx": None},
                ]
                if player["power_pips"] == 1
                else [PASS, {"card_idx": 1, "target_idx": None}]
            )
            self.assertEqual(
                [item["action"] for item in observed["continuations"]], expected
            )
            self.assertEqual(observed["root_hand_indices"], [0, 1])
            self.assertEqual(ratio(observed["probability"]), Fraction(1, 2))

    def test_duplicate_copies_remain_distinct_after_removing_either_index(self):
        duplicate = card(name="Identical physical copies")
        report = adaptive.evaluate(state([duplicate, duplicate]))
        self.assertEqual(report["optimal_actions"], [1, 2])
        for root_row, retained in zip(report["actions"][1:], [1, 0], strict=True):
            observed = root_row["observations"][0]
            self.assertEqual(observed["root_hand_indices"], [retained])
            self.assertEqual(observed["state"]["hand"], [duplicate])
            offered = observed["continuations"][1]
            self.assertEqual(offered["action"], {"card_idx": 0, "target_idx": 0})
            self.assertEqual(offered["root_card_idx"], retained)

    def test_fizzle_spends_matching_power_resource_and_removes_the_copy(self):
        report = adaptive.evaluate(
            state(
                [card(pip_cost=2, accuracy=0.5)], player=fighter("Player", power_pips=1)
            )
        )
        observations = report["actions"][1]["observations"]
        expected = {
            2: Fraction(4503599627370497, 9007199254740992),
            3: Fraction(4503599627370495, 9007199254740992),
        }
        self.assertEqual(len(observations), 2)
        for observed in observations:
            successor = observed["state"]
            self.assertEqual(observed["root_hand_indices"], [])
            self.assertEqual(successor["hand"], [])
            self.assertEqual(successor["player"]["pips"], 1)
            self.assertEqual(successor["player"]["power_pips"], 0)
            self.assertEqual(
                ratio(observed["probability"]),
                expected[successor["enemies"][0]["hp"]],
            )

    def test_terminal_win_finishes_regeneration_and_stops_before_round_two(self):
        report = adaptive.evaluate(state([card(damage_min=3, damage_max=3)]))
        row = report["actions"][1]
        observed = row["observations"][0]
        successor = observed["state"]
        self.assertEqual(ratio(row["value"]), W1)
        self.assertEqual(ratio(row["masses"]["win_depth_1"]), 1)
        self.assertEqual(observed["terminal"], "win")
        self.assertEqual(successor["round_num"], 2)
        self.assertEqual(successor["player"]["pips"], 1)
        self.assertEqual(successor["enemies"][0]["hp"], 0)
        self.assertEqual(successor["enemies"][0]["pips"], 0)
        self.assertEqual(observed["continuations"], [])
        self.assertEqual(observed["optimal_actions"], [])
        self.assertIsNone(observed["chosen"])
        self.assertEqual(report["work"]["per_action_transition_leaves"][1], 1)

    def test_depth_one_and_two_losses_keep_full_dead_player_regeneration(self):
        report = adaptive.evaluate(
            state(
                player=fighter("Player", hp=1),
                enemy=fighter("Enemy", element="frost", base_attack=card()),
            )
        )
        row = report["actions"][0]
        attempt = Fraction(7656119366529843, 9007199254740992)
        self.assertEqual(ratio(row["masses"]["loss_depth_1"]), attempt)
        self.assertEqual(ratio(row["masses"]["loss_depth_2"]), (1 - attempt) * attempt)
        self.assertEqual(ratio(row["masses"]["cutoff"]), (1 - attempt) ** 2)
        terminal = next(
            item for item in row["observations"] if item["terminal"] == "loss"
        )
        self.assertEqual(terminal["state"]["player"]["hp"], 0)
        self.assertEqual(terminal["state"]["player"]["pips"], 1)
        self.assertEqual(terminal["state"]["enemies"][0]["pips"], 1)
        self.assertEqual(ratio(terminal["adaptive_value"]), L1)
        survivor = next(
            item for item in row["observations"] if item["terminal"] is None
        )
        masses = survivor["continuations"][0]["masses"]
        self.assertEqual(ratio(masses["loss_depth_2"]), attempt)
        self.assert_complete_mass(report)

    def test_clipped_heal_groups_observations_after_charging_physical_traces(self):
        report = adaptive.evaluate(state([healing(accuracy=0.5)]))
        observations = report["actions"][1]["observations"]
        self.assertEqual(len(observations), 1)
        self.assertEqual(ratio(observations[0]["probability"]), 1)
        self.assertEqual(observations[0]["state"]["player"]["hp"], 100)
        work = report["work"]
        self.assertEqual(work["first_round_transitions"], 3)
        self.assertEqual(work["second_round_transitions"], 4)
        self.assertEqual(work["payoff_evaluations"], 4)
        self.assertEqual(work["observation_group_operations"], 5)
        self.assertEqual(work["work_units"], 16)

    def test_round_thirty_successors_are_not_readmitted_as_input_roots(self):
        report = adaptive.evaluate(state(round_num=30))
        observed = report["actions"][0]["observations"][0]
        self.assertEqual(observed["state"]["round_num"], 31)
        self.assertEqual(len(observed["continuations"]), 1)
        self.assertEqual(ratio(observed["continuations"][0]["masses"]["cutoff"]), 1)
        self.assertEqual(report["work"]["second_round_transitions"], 1)

    def test_observation_key_keeps_complete_fields_and_literal_numeric_types(self):
        data = state()
        with_zero = copy.deepcopy(data)
        with_zero["player"]["resist"] = {"ember": 0}
        with_float = copy.deepcopy(with_zero)
        with_float["player"]["resist"] = {"ember": 0.0}
        with_signed_zero = copy.deepcopy(with_zero)
        with_signed_zero["player"]["resist"] = {"ember": -0.0}
        keys = [
            adaptive._key(item)
            for item in (data, with_zero, with_float, with_signed_zero)
        ]
        self.assertEqual(len(set(keys)), 4)
        report = adaptive.evaluate(with_signed_zero)
        observed = report["actions"][0]["observations"][0]["state"]
        self.assertEqual(observed["player"]["resist"]["ember"].hex(), "-0x0.0p+0")
        self.assertEqual(set(observed), set(data))
        self.assertEqual(set(observed["player"]), set(data["player"]))

    def test_area_damage_keeps_null_target_and_dormant_attack_width(self):
        report = adaptive.evaluate(
            state(
                [card(hits_all=True, damage_max=3)],
                player=fighter("Player", base_attack=card(damage_max=151)),
            )
        )
        self.assertEqual(
            report["actions"][1]["action"], {"card_idx": 0, "target_idx": None}
        )
        self.assert_complete_mass(report)

    def test_binary53_threshold_endpoints_and_positive_grid_atom(self):
        endpoints = [
            (0, True, Fraction(1, adaptive.GRID)),
            (0, False, Fraction(0)),
            (1, True, Fraction(1)),
            (1, False, Fraction(1)),
            (0.5, True, Fraction(4503599627370497, adaptive.GRID)),
            (0.5, False, Fraction(1, 2)),
            (1 / adaptive.GRID, True, Fraction(2, adaptive.GRID)),
            (1 / adaptive.GRID, False, Fraction(1, adaptive.GRID)),
            (0.85, False, Fraction(7656119366529843, adaptive.GRID)),
        ]
        for value, inclusive, expected in endpoints:
            with self.subTest(value=value, inclusive=inclusive):
                self.assertEqual(
                    adaptive.threshold_probability(value, inclusive), expected
                )
        report = adaptive.evaluate(state([card(accuracy=1 / adaptive.GRID)]))
        succeeded = next(
            item
            for item in report["actions"][1]["observations"]
            if item["state"]["enemies"][0]["hp"] == 2
        )
        self.assertEqual(ratio(succeeded["probability"]), Fraction(2, adaptive.GRID))

    def test_unsupported_complete_roots_refuse_without_accepted_values(self):
        cases = [
            ("missing field", lambda data: data.pop("round_num")),
            ("extra field", lambda data: data.update(hidden=0)),
            ("dead player", lambda data: data["player"].update(hp=0)),
            ("boolean HP", lambda data: data["player"].update(hp=True)),
            ("late root", lambda data: data.update(round_num=31)),
            (
                "two enemies",
                lambda data: data["enemies"].append(copy.deepcopy(data["enemies"][0])),
            ),
            ("four cards", lambda data: data.update(hand=[card()] * 4)),
            ("wide damage", lambda data: data.update(hand=[card(damage_max=4)])),
            ("zero accuracy", lambda data: data.update(hand=[card(accuracy=0)])),
            (
                "nonfinite accuracy",
                lambda data: data.update(hand=[card(accuracy=float("nan"))]),
            ),
            ("drain", lambda data: data.update(hand=[card(heal=1)])),
            (
                "damage over time",
                lambda data: data.update(hand=[card(dot_tick=1, dot_rounds=1)]),
            ),
            ("area heal", lambda data: data.update(hand=[healing(hits_all=True)])),
            (
                "initial effect",
                lambda data: data["player"].update(
                    blades=[{"value": 0.1, "element": "ember"}]
                ),
            ),
            ("resistance", lambda data: data["player"].update(resist={"ember": 0.1})),
            ("policy", lambda data: data["enemies"][0].update(policy={"attack": 1})),
            ("boss flag", lambda data: data["enemies"][0].update(is_boss=True)),
            (
                "missing attack",
                lambda data: data["enemies"][0].update(base_attack=None),
            ),
            (
                "wide enemy",
                lambda data: data["enemies"][0].update(base_attack=card(damage_max=4)),
            ),
            (
                "wide dormant attack",
                lambda data: data["player"].update(base_attack=card(damage_max=152)),
            ),
        ]
        for name, modify in cases:
            data = state()
            modify(data)
            before = copy.deepcopy(data)
            with self.subTest(name=name):
                with self.assertRaises(adaptive.UnsupportedState) as caught:
                    adaptive.evaluate(data)
                self.assertFalse(hasattr(caught.exception, "actions"))
                self.assertFalse(hasattr(caught.exception, "best_value"))
                # NaN has no reflexive equality. Compare this case structurally.
                if name != "nonfinite accuracy":
                    self.assertEqual(data, before)

    def test_model_horizon_and_finite_controls_refuse_invalid_scalar_types(self):
        cases = [
            {"model": "another model"},
            {"horizon": 1},
            {"horizon": True},
            {"max_transitions": True},
            {"max_transitions": 1.5},
            {"max_transitions": 1_000_001},
            {"max_per_action": 0},
            {"max_per_action": 250_001},
            {"max_work_units": 3_000_001},
            {"max_work_units": False},
            {"max_seconds": 0},
            {"max_seconds": True},
            {"max_seconds": float("inf")},
            {"max_seconds": 30.0001},
        ]
        for controls in cases:
            with (
                self.subTest(controls=controls),
                self.assertRaises(adaptive.UnsupportedState),
            ):
                adaptive.evaluate(state(), **controls)

    def test_manual_witness_work_accounts_for_every_offered_alternative(self):
        work = adaptive.evaluate(witness())["work"]
        self.assertEqual(work["first_round_transitions"], 4)
        self.assertEqual(work["second_round_transitions"], 11)
        self.assertEqual(work["transition_leaves"], 15)
        self.assertEqual(work["per_action_transition_leaves"], [5, 6, 4])
        self.assertEqual(work["payoff_evaluations"], 11)
        self.assertEqual(work["observation_group_operations"], 8)
        self.assertEqual(work["work_units"], 34)
        self.assertEqual(work["cache_hits"], 0)
        self.assertEqual(work["cache_misses"], 9)

    def test_limits_refuse_whole_request_and_report_cap_exceeding_attempt(self):
        cases = [
            ({"max_transitions": 1}, "transition_leaves", 2),
            ({"max_per_action": 1}, "transition_leaves", 2),
            ({"max_work_units": 1}, "work_units", 2),
        ]
        data = state()
        for controls, counter, attempted in cases:
            with self.subTest(controls=controls):
                with self.assertRaises(adaptive.ReferenceLimitExceeded) as caught:
                    adaptive.evaluate(data, **controls)
                refusal = caught.exception
                self.assertEqual(refusal.work[counter], attempted)
                self.assertNotIn("actions", refusal.work)
                self.assertNotIn("best_value", refusal.work)
                recovered = adaptive.evaluate(data)
                self.assertEqual(recovered["work"]["transition_leaves"], 2)
                self.assertEqual(recovered["work"]["cache_hits"], 0)

    def test_deadline_includes_admission_and_completed_result_assembly(self):
        with patch.object(adaptive.time, "perf_counter", side_effect=[0.0, 1.0]):
            with self.assertRaises(adaptive.ReferenceLimitExceeded) as caught:
                adaptive.evaluate(state(), max_seconds=0.5)
            self.assertEqual(caught.exception.work["transition_leaves"], 0)
        clock = [0.0]
        snapshot = adaptive._Budget.snapshot

        def completed_snapshot(budget, elapsed=None):
            result = snapshot(budget, elapsed)
            clock[0] = 1.0
            return result

        with (
            patch.object(adaptive.time, "perf_counter", side_effect=lambda: clock[0]),
            patch.object(adaptive._Budget, "snapshot", completed_snapshot),
        ):
            with self.assertRaisesRegex(
                adaptive.ReferenceLimitExceeded, "completed assembly"
            ) as caught:
                adaptive.evaluate(state(), max_seconds=0.5)
        self.assertEqual(caught.exception.work["transition_leaves"], 2)
        self.assertNotIn("actions", caught.exception.work)

    def test_interruption_and_arithmetic_failure_allow_a_fresh_request(self):
        for failure, expected in [
            (KeyboardInterrupt(), adaptive.ReferenceInterrupted),
            (
                ArithmeticError("synthetic arithmetic failure"),
                adaptive.ReferenceArithmeticError,
            ),
        ]:
            with self.subTest(failure=type(failure).__name__):
                with patch.object(adaptive, "_score", side_effect=failure):
                    with self.assertRaises(expected):
                        adaptive.evaluate(state())
                report = adaptive.evaluate(state())
                self.assertEqual(report["work"]["cache_hits"], 0)
                self.assertEqual(report["work"]["cache_misses"], 1)
                self.assert_complete_mass(report)

    def test_local_helper_provenance_contains_no_machine_path_or_frozen_hash(self):
        report = adaptive.evaluate(state())
        self.assertEqual(
            report["source_provenance"],
            {
                "transition_helper": "reference/one_round.py",
                "qualification_model": adaptive.MODEL,
            },
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
