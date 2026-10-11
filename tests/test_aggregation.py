"""Check sufficient-statistic values against retained physical arithmetic."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import one_round_physical_reference as physical

from reference import aggregation, one_round


class AggregationArithmeticTests(unittest.TestCase):
    def state(self, *, width=3):
        fixture = json.loads(
            (
                Path(__file__).parent / "fixtures" / "three-enemy-reference.json"
            ).read_text(encoding="utf-8")
        )
        state = next(
            row["state"]
            for row in fixture["cases"]
            if row["id"] == "modeled-three-lawful-wide-area"
        )
        state["hand"][0]["damage_max"] = width
        return state

    def assert_parity(self, state, model=one_round.THREE_ENEMY_MODEL):
        before = copy.deepcopy(state)
        result = aggregation.evaluate(state, model=model)
        physical_model = (
            physical.THREE_ENEMY_MODEL
            if model == one_round.THREE_ENEMY_MODEL
            else physical.MODEL
        )
        expected = physical.evaluate(state, model=physical_model)
        self.assertEqual(state, before)
        self.assertEqual(result["best_actions"], expected["best_actions"])
        for actual, oracle in zip(result["actions"], expected["rows"], strict=True):
            for name in (
                "action",
                "expected_value",
                "expected_value_float",
                "mass",
            ):
                self.assertEqual(actual[name], oracle[name], name)
            for kind in ("win", "loss", "ongoing"):
                self.assertEqual(actual[kind + "_mass"], oracle["result_mass"][kind])
            self.assertEqual(
                actual["work"]["represented_trace_leaves"], oracle["leaves"]
            )
        return result

    def test_small_widths_and_stochastic_regeneration_match_physical_paths(self):
        for width in (1, 2, 3, 5, 9):
            with self.subTest(width=width):
                state = self.state(width=width)
                for fighter in [state["player"], *state["enemies"]]:
                    fighter["power_pip_chance"] = 0.5
                self.assert_parity(state)

    def test_asymmetric_hp_partial_player_shared_accuracy_and_physical_ties(self):
        for count in (1, 2, 3):
            with self.subTest(enemies=count):
                state = self.state()
                state["enemies"] = state["enemies"][:count]
                for enemy, hp, maximum in zip(
                    state["enemies"], (110, 220, 330), (120, 250, 400), strict=False
                ):
                    enemy.update(hp=hp, max_hp=maximum, power_pip_chance=0.25)
                state["player"].update(
                    hp=73, max_hp=100, pips=2, power_pips=1, power_pip_chance=0.5
                )
                card = state["hand"][0]
                card.update(damage_min=0, damage_max=2, pip_cost=1, accuracy=0.5)
                state["hand"] = [copy.deepcopy(card), copy.deepcopy(card)]
                single = copy.deepcopy(card)
                single.update(hits_all=False, damage_min=1, damage_max=3, pip_cost=2)
                state["hand"].extend([single, copy.deepcopy(single)])
                model = one_round.THREE_ENEMY_MODEL if count == 3 else one_round.MODEL
                result = self.assert_parity(state, model)
                self.assertEqual(len(result["actions"]), 3 + 2 * count)
                for best in result["best_actions"]:
                    twin = {**best, "card_idx": best["card_idx"] ^ 1}
                    self.assertIn(twin, result["best_actions"])

    def test_caps_and_deadline_refuse_instead_of_accepting_a_partial_action_set(self):
        state = self.state()
        for controls in ({"max_contributions": 1}, {"max_payoff_evaluations": 1}):
            with (
                self.subTest(controls=controls),
                self.assertRaises(one_round.ReferenceLimitExceeded),
            ):
                aggregation.evaluate(
                    state, model=one_round.THREE_ENEMY_MODEL, **controls
                )
        with patch.object(aggregation.time, "monotonic", side_effect=(0.0, 31.0)):
            with self.assertRaises(one_round.ReferenceLimitExceeded):
                aggregation.evaluate(state, model=one_round.THREE_ENEMY_MODEL)

    def test_response_death_effects_and_custom_threat_are_outside_the_method(self):
        mutations = (
            lambda s: s["enemies"][0].update(pips=3),
            lambda s: s["enemies"][0].update(hp=3),
            lambda s: s["player"]["blades"].append({"value": 0.5, "element": "ember"}),
            lambda s: s["hand"][0].update(heal=1),
            lambda s: s["hand"][0].update(dot_tick=1, dot_rounds=1),
            lambda s: s["enemies"][0].update(base_attack=copy.deepcopy(s["hand"][0])),
        )
        for index, mutate in enumerate(mutations):
            with (
                self.subTest(case=index),
                self.assertRaises(one_round.UnsupportedState),
            ):
                state = self.state()
                mutate(state)
                aggregation.evaluate(state, model=one_round.THREE_ENEMY_MODEL)


if __name__ == "__main__":
    unittest.main()
