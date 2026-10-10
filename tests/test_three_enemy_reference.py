"""Check the explicit three-enemy model against qualified literal inputs.

The fixture labels its captured built-in initial state separately from manually
modeled calibration states. These checks preserve the declared one-round objective.
"""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import one_round_physical_reference as physical
from test_one_round_reference import (
    PASS,
    ForcedRNG,
    card,
    fighter,
    modeled_state,
    public_state,
    ratio,
)

from engine import MCTS, Action
from engine.simulator import advance_round
from game.decision_report import normalized
from reference import one_round as candidate

COMPLETE_CASES = (
    "genuine-gauntlet-initial",
    "modeled-three-target-duplicates",
    "modeled-third-response-suppression",
    "modeled-three-area-one-blade",
    "modeled-three-terminal-ongoing-masses",
    "modeled-three-simultaneous-upkeep",
)
LEAF_COUNTS = {
    "genuine-gauntlet-initial": [16, 496, 496, 496],
    "modeled-three-target-duplicates": [16] * 22,
    "modeled-third-response-suppression": [3, 6, 6, 4],
    "modeled-three-area-one-blade": [8, 24],
    "modeled-three-terminal-ongoing-masses": [1, 9],
    "modeled-three-simultaneous-upkeep": [1],
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class ThreeEnemyReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parent / "fixtures" / "three-enemy-reference.json"
        cls.fixture = json.loads(path.read_text(encoding="utf-8"))
        cls.cases = {row["id"]: row for row in cls.fixture["cases"]}

    def state(self, case_id):
        return copy.deepcopy(self.cases[case_id]["state"])

    def assert_fraction(self, body):
        self.assertEqual(set(body), {"numerator", "denominator"})
        self.assertIs(type(body["numerator"]), str)
        self.assertIs(type(body["denominator"]), str)
        value = ratio(body)
        self.assertEqual(body["numerator"], str(value.numerator))
        self.assertEqual(body["denominator"], str(value.denominator))
        return value

    def assert_manual_report(self, case_id, report):
        rows = report["actions"]
        values = [ratio(row["expected_value"]) for row in rows]
        self.assertEqual([row["leaves"] for row in rows], LEAF_COUNTS[case_id])
        if case_id == "genuine-gauntlet-initial":
            actions = [PASS] + [
                {"card_idx": 2, "target_idx": target} for target in range(3)
            ]
            mean = sum(
                (
                    Fraction.from_float(
                        0.5 + 0.5 * (1.0 - ((2750 - damage) * 0.875) / 2406.25)
                    )
                    for damage in range(65, 96)
                ),
                Fraction(),
            ) / 31
            self.assertEqual(values, [Fraction(1, 2), mean, mean, mean])
            self.assertGreater(mean, Fraction(1, 2))
            best = actions[1:]
        elif case_id == "modeled-three-target-duplicates":
            actions = [PASS] + [
                {"card_idx": index, "target_idx": target}
                for index in range(7)
                for target in range(3)
            ]
            expected = [
                Fraction.from_float(0.5 + 0.5 * (80 / 100 - hp / 600))
                for hp in (220, 205, 200, 195)
            ]
            self.assertEqual(values, expected[:1] + expected[1:] * 7)
            self.assertTrue(expected[3] > expected[2] > expected[1] > expected[0])
            best = [{"card_idx": index, "target_idx": 2} for index in range(7)]
        elif case_id == "modeled-third-response-suppression":
            actions = [PASS] + [
                {"card_idx": 0, "target_idx": target} for target in range(3)
            ]
            hit = Fraction(4503599627370497, 9007199254740992)
            attempt = Fraction(7656119366529843, 9007199254740992)
            loss = Fraction.from_float(0.15)
            unchanged = Fraction.from_float(0.5 + 0.5 * (15 / 100 - 40 / 80))
            earlier_hit = Fraction.from_float(0.5 + 0.5 * (15 / 100 - 34 / 80))
            third_dead = Fraction.from_float(0.5 + 0.5 * (15 / 100 - 35 / 80))
            passed = (1 - attempt) * unchanged + attempt * loss
            earlier = (1 - attempt) * (
                (1 - hit) * unchanged + hit * earlier_hit
            ) + attempt * loss
            third = hit * third_dead + (1 - hit) * passed
            self.assertEqual(values, [passed, earlier, earlier, third])
            self.assertTrue(third > earlier > passed)
            self.assertEqual(
                [ratio(row["loss_mass"]) for row in rows],
                [attempt, attempt, attempt, (1 - hit) * attempt],
            )
            self.assertTrue(all(ratio(row["win_mass"]) == 0 for row in rows))
            best = [actions[3]]
        elif case_id == "modeled-three-terminal-ongoing-masses":
            actions = [PASS, {"card_idx": 0, "target_idx": None}]
            hit = Fraction(4503599627370497, 9007199254740992)
            ongoing = {
                hp: Fraction.from_float(0.5 + 0.5 * (1.0 - hp / 300))
                for hp in (1, 2, 3, 6)
            }
            win = Fraction.from_float(1.0 - 0.045)
            expected = (1 - hit) * ongoing[6] + hit / 8 * (
                win + 3 * ongoing[1] + 3 * ongoing[2] + ongoing[3]
            )
            self.assertEqual(values, [ongoing[6], expected])
            self.assertEqual(ratio(rows[1]["win_mass"]), hit / 8)
            self.assertEqual(ratio(rows[1]["ongoing_mass"]), 1 - hit / 8)
            self.assertEqual(ratio(rows[1]["loss_mass"]), 0)
            self.assertLess(win, ongoing[3])
            self.assertGreater(expected, ongoing[6])
            best = [actions[1]]
        elif case_id == "modeled-three-area-one-blade":
            actions = [PASS, {"card_idx": 0, "target_idx": None}]
            self.assertGreater(values[1], values[0])
            best = [actions[1]]
        else:
            actions = [PASS]
            self.assertEqual(values, [Fraction.from_float(0.15)])
            self.assertEqual(ratio(rows[0]["loss_mass"]), 1)
            best = actions
        self.assertEqual([row["action"] for row in rows], actions)
        self.assertEqual(report["best_actions"], best)
        if case_id in (
            "genuine-gauntlet-initial",
            "modeled-three-target-duplicates",
            "modeled-three-area-one-blade",
        ):
            self.assertTrue(all(ratio(row["ongoing_mass"]) == 1 for row in rows))

    def test_qualified_reports_match_independent_and_manual_expectations(self):
        for case_id in COMPLETE_CASES:
            with self.subTest(case=case_id):
                data = self.state(case_id)
                before = copy.deepcopy(data)
                if case_id == "genuine-gauntlet-initial":
                    self.assertEqual(
                        hashlib.sha256(canonical(data).encode()).hexdigest(),
                        self.cases[case_id]["provenance"]["canonical_state_sha256"],
                    )
                observed = candidate.evaluate(data, model=candidate.THREE_ENEMY_MODEL)
                expected = physical.evaluate(data, model=physical.THREE_ENEMY_MODEL)
                self.assertEqual(canonical(data), canonical(before))
                self.assertEqual(observed["model"], candidate.THREE_ENEMY_MODEL)
                self.assertEqual(expected["model"], candidate.THREE_ENEMY_MODEL)
                self.assertEqual(observed["horizon_rounds"], 1)
                self.assertEqual(observed["terminal_depth"], 1)
                self.assertEqual(observed["total_leaves"], expected["total_paths"])
                self.assertEqual(observed["best_actions"], expected["best_actions"])
                self.assertEqual(len(observed["actions"]), len(expected["rows"]))
                for actual, independent in zip(
                    observed["actions"], expected["rows"], strict=True
                ):
                    self.assertEqual(actual["action"], independent["action"])
                    self.assertEqual(actual["leaves"], independent["leaves"])
                    value = self.assert_fraction(actual["expected_value"])
                    self.assertEqual(value, ratio(independent["expected_value"]))
                    self.assertEqual(actual["expected_value_float"], float(value))
                    self.assertEqual(self.assert_fraction(actual["mass"]), 1)
                    outcomes = []
                    for kind in ("win", "loss", "ongoing"):
                        mass = self.assert_fraction(actual[kind + "_mass"])
                        self.assertEqual(mass, ratio(independent["result_mass"][kind]))
                        self.assertGreaterEqual(mass, 0)
                        outcomes.append(mass)
                    self.assertEqual(sum(outcomes, Fraction()), 1)
                self.assertEqual(
                    observed["total_leaves"], sum(LEAF_COUNTS[case_id])
                )
                self.assert_manual_report(case_id, observed)

    def assert_manual_successor(self, case_id, action, leaf, witnesses):
        data = leaf["state"]
        player, enemies = data["player"], data["enemies"]
        damage = [draw["value"] for draw in leaf["tape"] if draw["method"] == "randint"]
        if case_id == "modeled-three-area-one-blade":
            self.assertEqual(data["round_num"], 4)
            if action == PASS:
                original = self.cases[case_id]["state"]
                self.assertEqual(data["hand"], original["hand"])
                self.assertEqual(player["blades"], original["player"]["blades"])
                self.assertEqual(player["hp"], 30)
                self.assertEqual((player["pips"], player["power_pips"]), (1, 3))
                self.assertEqual([enemy["hp"] for enemy in enemies], [2, 5, 7])
                self.assertEqual(enemies[1]["traps"], original["enemies"][1]["traps"])
                self.assertEqual(
                    enemies[2]["shields"], original["enemies"][2]["shields"]
                )
                self.assertTrue(all(enemy["dots"] == [] for enemy in enemies))
                self.assertTrue(
                    all(enemy["pips"] + enemy["power_pips"] == 1 for enemy in enemies)
                )
                self.assertEqual(len(leaf["tape"]), 4)
                return
            self.assertEqual(player["blades"], [{"element": "frost", "value": 0.25}])
            self.assertEqual((player["pips"], player["power_pips"]), (1, 0))
            self.assertEqual(len(damage), 3)
            nominal = [
                int(damage[0] * 1.5),
                int(damage[1] * 1.5 * 1.25),
                int(damage[2] * 1.5 * 0.5),
            ]
            self.assertEqual(player["hp"], 30 + sum(value // 2 for value in nominal))
            self.assertEqual(
                [enemy["hp"] for enemy in enemies],
                [0, max(0, 5 - nominal[1] - 1), 7 - nominal[2] - 1],
            )
            self.assertEqual(enemies[1]["traps"], [])
            self.assertEqual(enemies[2]["shields"], [])
            for enemy in enemies:
                self.assertEqual(
                    enemy["dots"],
                    [{"tick": 1, "rounds_left": 1, "element": "ember"}],
                )
                self.assertEqual(
                    enemy["pips"] + enemy["power_pips"], int(enemy["hp"] > 0)
                )
            self.assertEqual(len(leaf["tape"]), 6 + int(enemies[1]["hp"] > 0))
            witnesses.add("second-alive" if enemies[1]["hp"] > 0 else "second-dead")
        elif case_id == "modeled-third-response-suppression":
            self.assertEqual(data["round_num"], 2)
            if enemies[2]["hp"] == 0:
                self.assertEqual(action, {"card_idx": 0, "target_idx": 2})
                self.assertEqual(player["hp"], 15)
                self.assertEqual((enemies[2]["pips"], enemies[2]["power_pips"]), (3, 0))
                self.assertEqual(len(leaf["tape"]), 5)
                witnesses.add("third-suppressed")
            if player["hp"] == 0:
                self.assertEqual(leaf["score"], 0.15)
                # Pass retains the initial pip. A played card pays before fizzle.
                expected_pips = 2 if action == PASS else 1
                self.assertEqual(
                    (player["pips"], player["power_pips"]), (expected_pips, 0)
                )
                self.assertEqual((enemies[2]["pips"], enemies[2]["power_pips"]), (1, 0))
                witnesses.add("third-lethal")
        elif case_id == "modeled-three-terminal-ongoing-masses":
            if player["hp"] > 0 and all(enemy["hp"] == 0 for enemy in enemies):
                self.assertEqual(leaf["score"], 1.0 - 0.045)
                self.assertEqual(len(leaf["tape"]), 5)
                witnesses.add("all-three-win")
            if [enemy["hp"] for enemy in enemies] == [0, 0, 1]:
                self.assertEqual(leaf["score"], 0.5 + 0.5 * (1.0 - 1 / 300))
                self.assertEqual(len(leaf["tape"]), 6)
                witnesses.add("third-only-ongoing")
        elif case_id == "modeled-three-simultaneous-upkeep":
            self.assertEqual(action, PASS)
            self.assertEqual(player["hp"], 0)
            self.assertEqual((player["pips"], player["power_pips"]), (1, 0))
            self.assertEqual(player["dots"], [])
            self.assertEqual(data["round_num"], 2)
            self.assertEqual(leaf["score"], 0.15)
            self.assertEqual(len(leaf["tape"]), 1)
            for enemy in enemies:
                self.assertEqual(enemy["hp"], 0)
                self.assertEqual((enemy["pips"], enemy["power_pips"]), (0, 0))
                self.assertEqual(enemy["dots"], [])
        else:
            expected_hp = (
                [900, 750, 1100]
                if case_id == "genuine-gauntlet-initial"
                else [25, 35, 45]
            )
            if action != PASS:
                self.assertEqual(len(damage), 1)
                expected_hp[action["target_idx"]] -= damage[0]
                self.assertEqual(len(data["hand"]), 6)
                if case_id == "genuine-gauntlet-initial":
                    self.assertEqual(action["card_idx"], 2)
                    self.assertTrue(65 <= damage[0] <= 95)
                else:
                    self.assertEqual(damage[0], 10)
            else:
                self.assertEqual(len(data["hand"]), 7)
            self.assertEqual([enemy["hp"] for enemy in enemies], expected_hp)
            self.assertEqual(
                player["hp"], 2600 if case_id == "genuine-gauntlet-initial" else 80
            )
            self.assertEqual(data["round_num"], 2)
            self.assertTrue(
                all(enemy["pips"] + enemy["power_pips"] == 1 for enemy in enemies)
            )
            self.assertEqual(player["pips"] + player["power_pips"], 1)

    def test_positive_successors_match_engine_and_manual_witnesses(self):
        required = {
            "modeled-third-response-suppression": {"third-suppressed", "third-lethal"},
            "modeled-three-area-one-blade": {"second-alive", "second-dead"},
            "modeled-three-terminal-ongoing-masses": {
                "all-three-win", "third-only-ongoing"
            },
        }
        scorer = MCTS(horizon_rounds=1, max_sims=1)
        with patch.object(
            MCTS, "search", side_effect=AssertionError("search forbidden")
        ):
            for case_id in COMPLETE_CASES:
                with self.subTest(case=case_id):
                    data = self.state(case_id)
                    root = public_state(data)
                    before = copy.deepcopy(data)
                    witnesses = set()
                    actions = candidate.legal_actions(
                        data, model=candidate.THREE_ENEMY_MODEL
                    )
                    for index, action in enumerate(actions):
                        mass, count = Fraction(), 0
                        for leaf in candidate.enumerate_action(
                            data, action, model=candidate.THREE_ENEMY_MODEL
                        ):
                            rng = ForcedRNG(leaf["tape"])
                            successor = advance_round(
                                root.clone(), Action(**action), rng
                            )
                            self.assertEqual(rng.position, len(rng.tape))
                            self.assertEqual(
                                canonical(normalized(successor)),
                                canonical(leaf["state"]),
                            )
                            result = successor.result()
                            score = (
                                successor.heuristic_value()
                                if result is None
                                else scorer._terminal_reward(result, 1)
                            )
                            self.assertEqual(score, leaf["score"])
                            self.assertGreater(leaf["probability"], 0)
                            mass += leaf["probability"]
                            count += 1
                            self.assert_manual_successor(
                                case_id, action, leaf, witnesses
                            )
                        self.assertEqual(mass, 1)
                        self.assertEqual(count, LEAF_COUNTS[case_id][index])
                    self.assertTrue(required.get(case_id, set()) <= witnesses)
                    self.assertEqual(canonical(data), canonical(before))
                    self.assertEqual(canonical(normalized(root)), canonical(before))

    def test_historical_default_and_explicit_selection_keep_separate_admission(self):
        historical = modeled_state(
            [card()], enemies=[fighter("First"), fighter("Second")]
        )
        default = candidate.evaluate(historical)
        explicit = candidate.evaluate(historical, model=candidate.MODEL)
        default.pop("elapsed_seconds")
        explicit.pop("elapsed_seconds")
        self.assertEqual(default, explicit)
        self.assertEqual(default["model"], "independent_one_round_binary53_shaped_v1")
        self.assertEqual(
            candidate.legal_actions(historical),
            candidate.legal_actions(historical, model=candidate.MODEL),
        )
        self.assertIsNone(candidate.validate(historical))
        self.assertIsNone(candidate.validate(historical, model=candidate.MODEL))
        for case_id in COMPLETE_CASES:
            with self.subTest(case=case_id):
                with self.assertRaises(candidate.UnsupportedState):
                    candidate.evaluate(self.state(case_id))
        with self.assertRaises(candidate.UnsupportedState):
            candidate.evaluate(historical, model=candidate.THREE_ENEMY_MODEL)

    def test_unknown_model_identity_refuses_in_every_core_entry_before_math(self):
        data = self.state("genuine-gauntlet-initial")
        before = copy.deepcopy(data)
        with patch.object(
            candidate, "_player_outcomes", side_effect=AssertionError("math forbidden")
        ):
            for model in (
                "three-enemy", candidate.THREE_ENEMY_MODEL + "x", None, True, [], {}
            ):
                for operation in (
                    lambda model=model: candidate.validate(data, model=model),
                    lambda model=model: candidate.legal_actions(data, model=model),
                    lambda model=model: list(
                        candidate.enumerate_action(data, PASS, model=model)
                    ),
                    lambda model=model: candidate.evaluate(data, model=model),
                ):
                    with self.subTest(model=model, operation=operation):
                        with self.assertRaises(candidate.UnsupportedState):
                            operation()
        self.assertEqual(canonical(data), canonical(before))

    def test_third_root_fields_and_response_bound_are_not_silently_ignored(self):
        data = self.state("modeled-third-response-suppression")
        edits = (
            ("one", lambda state: state.update(enemies=state["enemies"][:1])),
            ("two", lambda state: state.update(enemies=state["enemies"][:2])),
            (
                "four",
                lambda state: state["enemies"].append(
                    copy.deepcopy(state["enemies"][0])
                ),
            ),
            ("dead-third", lambda state: state["enemies"][2].update(hp=0)),
            ("two-responses", lambda state: state["enemies"][0].update(pips=3)),
            (
                "third-policy",
                lambda state: state["enemies"][2].update(policy={"attack": 1.0}),
            ),
            ("third-boss", lambda state: state["enemies"][2].update(is_boss=True)),
            ("third-boolean", lambda state: state["enemies"][2].update(pips=True)),
            (
                "third-extra-field",
                lambda state: state["enemies"][2].update(hidden=True),
            ),
            ("rules", lambda state: state.update(boss_rules=[{"type": "unknown"}])),
        )
        with patch.object(
            candidate, "_player_outcomes", side_effect=AssertionError("math forbidden")
        ):
            for label, edit in edits:
                changed = copy.deepcopy(data)
                edit(changed)
                before = copy.deepcopy(changed)
                with self.subTest(edit=label):
                    with self.assertRaises(candidate.UnsupportedState):
                        candidate.evaluate(changed, model=candidate.THREE_ENEMY_MODEL)
                    with self.assertRaises(physical.UnsupportedReference):
                        physical.evaluate(changed, model=physical.THREE_ENEMY_MODEL)
                    self.assertEqual(canonical(changed), canonical(before))

    def test_new_model_retains_bounded_whole_report_refusals(self):
        refusals = (
            ("modeled-three-target-duplicates", {"max_total_paths": 17}),
            ("modeled-third-response-suppression", {"max_paths": 1}),
            ("modeled-three-lawful-wide-area", {"max_paths": 2}),
        )
        for case_id, limits in refusals:
            with self.subTest(case=case_id):
                data = self.state(case_id)
                before = copy.deepcopy(data)
                self.assertIsNone(
                    candidate.validate(data, model=candidate.THREE_ENEMY_MODEL)
                )
                with self.assertRaises(candidate.ReferenceLimitExceeded):
                    candidate.evaluate(
                        data, model=candidate.THREE_ENEMY_MODEL, **limits
                    )
                with self.assertRaises(physical.ReferenceLimitExceeded):
                    physical.evaluate(data, model=physical.THREE_ENEMY_MODEL, **limits)
                self.assertEqual(canonical(data), canonical(before))
        data = self.state("genuine-gauntlet-initial")
        with patch.object(candidate.time, "monotonic", side_effect=[0.0, 0.01]):
            with self.assertRaises(candidate.ReferenceLimitExceeded):
                candidate.evaluate(
                    data, model=candidate.THREE_ENEMY_MODEL, max_seconds=0.001
                )


if __name__ == "__main__":
    unittest.main()
