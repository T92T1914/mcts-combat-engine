"""A finite integer resource corpus exercises the ordinary public model.

Expected affordability, payment and regeneration are declared independently.
These supported cases establish neither whole-input coverage nor authentication.
"""
from __future__ import annotations

import copy
import random
import unittest

from engine import (
    Action,
    Card,
    CardType,
    Combatant,
    Element,
    GameState,
    advance_round,
    legal_actions,
)
from engine.actions import is_legal_action

PIP_PAIRS = tuple((normal, power) for normal in range(8)
                  for power in range(8 - normal))
ELEMENT_CASES = ((Element.EMBER, 2), (Element.FROST, 1))


def payment_oracle(normal, power, cost, multiplier):
    """Power-first closed form for independently affordable integer inputs."""
    used_power = min(power, (cost + multiplier - 1) // multiplier)
    return normal - max(0, cost - multiplier * used_power), power - used_power


def resource_state(normal, power, cost=0, element=Element.EMBER, chance=0):
    """One utility card and an enemy unable to respond before this upkeep."""
    return GameState(
        player=Combatant("Operator", Element.EMBER, 100, 100,
                         pips=normal, power_pips=power, power_pip_chance=chance),
        enemies=[Combatant(
            "Idle target", Element.FROST, 100, 100, power_pip_chance=0,
            base_attack=Card("Unavailable reply", Element.FROST, CardType.DAMAGE,
                             pip_cost=14, accuracy=1, damage_min=1, damage_max=1))],
        hand=[Card("Utility", element, CardType.UTILITY,
                   pip_cost=cost, accuracy=1)],
        boss_rules=[],
    )


class BoundedModelAssuranceTests(unittest.TestCase):
    def test_1080_supported_affordability_cases_preserve_inputs(self):
        self.assertEqual(len(PIP_PAIRS), 36)
        global_rng_before = random.getstate()
        observations = {}
        affordable_count = equality_count = 0
        for normal, power in PIP_PAIRS:
            for cost in range(15):
                for element, multiplier in ELEMENT_CASES:
                    with self.subTest(normal=normal, power=power, cost=cost,
                                      element=element):
                        state = resource_state(normal, power, cost, element)
                        before = copy.deepcopy(state)
                        capacity = normal + multiplier * power
                        expected = cost <= capacity
                        action = Action(0)
                        self.assertEqual(state.player.effective_pips(element),
                                         capacity)
                        actual = is_legal_action(state, action)
                        self.assertEqual(actual, expected)
                        self.assertEqual(legal_actions(state),
                                         [Action(None), action] if expected
                                         else [Action(None)])
                        self.assertTrue(is_legal_action(state, Action(None)))
                        self.assertEqual(state, before)
                        observations[normal, power, cost, element] = actual
                        affordable_count += actual
                        equality_count += cost == capacity
        self.assertEqual(len(observations), 1080)
        self.assertEqual(affordable_count, 492)
        self.assertEqual(equality_count, 72)
        self.assertEqual(len(observations) - affordable_count, 588)
        # Literal controls select already executed cases. Two occupied slots
        # provide different matching capacity when they hold normal vs power.
        controls = {
            (0, 0, 0, Element.EMBER): True,
            (0, 0, 1, Element.EMBER): False,
            (3, 0, 3, Element.EMBER): True,
            (2, 0, 3, Element.EMBER): False,
            (0, 2, 3, Element.EMBER): True,
            (0, 2, 3, Element.FROST): False,
            (0, 7, 14, Element.EMBER): True,
            (0, 7, 14, Element.FROST): False,
        }
        for case, expected in controls.items():
            self.assertEqual(observations[case], expected)
        self.assertEqual(random.getstate(), global_rng_before)

    def test_492_affordable_power_first_payments_change_only_disposable_pips(self):
        observations = {}
        for normal, power in PIP_PAIRS:
            for cost in range(15):
                for element, multiplier in ELEMENT_CASES:
                    if cost > normal + multiplier * power:
                        continue
                    with self.subTest(normal=normal, power=power, cost=cost,
                                      element=element):
                        state = resource_state(normal, power, cost, element)
                        expected = copy.deepcopy(state)
                        remaining = payment_oracle(normal, power, cost, multiplier)
                        expected.player.pips, expected.player.power_pips = remaining
                        state.player.spend_pips(cost, element)
                        self.assertEqual(state, expected)
                        self.assertGreaterEqual(state.player.pips, 0)
                        self.assertGreaterEqual(state.player.power_pips, 0)
                        observations[normal, power, cost, element] = (
                            state.player.pips, state.player.power_pips)
        self.assertEqual(len(observations), 492)
        controls = {
            (0, 0, 0, Element.EMBER): (0, 0),
            (1, 2, 0, Element.EMBER): (1, 2),
            (1, 2, 3, Element.EMBER): (1, 0),
            (1, 2, 3, Element.FROST): (0, 0),
            (0, 7, 14, Element.EMBER): (0, 0),
        }
        for case, expected in controls.items():
            self.assertEqual(observations[case], expected)

    def assert_round(self, original, action, expected):
        source_state = copy.deepcopy(original)
        source_rng = random.Random(317)
        source_rng_before = source_rng.getstate()
        round_rng = random.Random(0)
        round_rng.setstate(source_rng_before)
        candidate = original.clone()
        returned = advance_round(candidate, action, round_rng)
        self.assertIs(returned, candidate)
        self.assertEqual(candidate, expected)
        self.assertEqual(original, source_state)
        self.assertEqual(source_rng.getstate(), source_rng_before)

    def test_72_endpoint_regeneration_rounds_preserve_original_state_and_rng(self):
        cases = full_cap = 0
        for normal, power in PIP_PAIRS:
            for chance in (0, 1):
                with self.subTest(normal=normal, power=power, chance=chance):
                    original = resource_state(normal, power, chance=chance)
                    expected = copy.deepcopy(original)
                    if normal + power < 7:
                        expected.player.pips = normal + (chance == 0)
                        expected.player.power_pips = power + (chance == 1)
                    else:
                        full_cap += 1
                    expected.enemies[0].pips = 1
                    expected.round_num = 2
                    self.assert_round(original, Action(None), expected)
                    self.assertLessEqual(expected.player.pips +
                                         expected.player.power_pips, 7)
                    cases += 1
        self.assertEqual(cases, 72)
        self.assertEqual(full_cap, 16)

    def test_two_utility_play_rounds_include_payment_then_regeneration(self):
        # These expected final pairs are literal, independently chosen witnesses.
        # Matching odd cost consumes both power pips, leaves the normal pip and
        # then gains one normal pip. Off-element exact cost spends all three
        # resources, then gains one power pip. Neither round refills the hand.
        cases = (
            (Element.EMBER, 0, (2, 0)),
            (Element.FROST, 1, (0, 1)),
        )
        for element, chance, final_pips in cases:
            with self.subTest(element=element, chance=chance):
                original = resource_state(1, 2, cost=3, element=element,
                                          chance=chance)
                self.assertTrue(is_legal_action(original, Action(0)))
                expected = copy.deepcopy(original)
                expected.player.pips, expected.player.power_pips = final_pips
                expected.hand = []
                expected.enemies[0].pips = 1
                expected.round_num = 2
                self.assert_round(original, Action(0), expected)
        self.assertEqual(len(cases), 2)


if __name__ == "__main__":
    unittest.main()
