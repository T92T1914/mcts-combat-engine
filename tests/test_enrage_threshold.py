"""Strict half-health expectations use the public rule, loader and full round."""
from __future__ import annotations

import copy
import json
import random
import tempfile
import unittest
from pathlib import Path

from engine import Action, Charm, Element, advance_round
from engine.rules import EnrageBelowHalf, RuleEvent
from game.loader import load_cards, load_scenarios

ROOT = Path(__file__).resolve().parents[1]


def under_half(maximum: int, hp: int) -> bool:
    """Integer oracle: living current health is less than missing health."""
    return hp > 0 and hp < maximum - hp


class EnrageThresholdTests(unittest.TestCase):
    def setUp(self):
        self.sources = {ROOT / name: self.snapshot(ROOT / name) for name in (
            "engine/rules.py", "data/cards.json", "data/scenarios.json")}
        self.addCleanup(self.assert_unchanged, self.sources)
        self.template, _ = load_scenarios()["boss"](random.Random(0))
        self.rule = next(rule for rule in self.template.boss_rules
                         if isinstance(rule, EnrageBelowHalf))

    @staticmethod
    def snapshot(path: Path) -> tuple[bytes, int]:
        return path.read_bytes(), path.stat().st_mtime_ns

    def assert_unchanged(self, snapshots):
        self.assertEqual(snapshots, {path: self.snapshot(path) for path in snapshots})

    def state(self, maximum: int, hp: int, *, boss: bool = True):
        state = self.template.clone()
        enemy = state.enemies[0]
        enemy.max_hp, enemy.hp, enemy.is_boss = maximum, hp, boss
        enemy.blades.clear()
        return state

    def custom_state(self, *, maximum: int = 5, dot_tick: int = 0):
        temporary = tempfile.TemporaryDirectory(prefix="mcts-enrage-json-")
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        spec = copy.deepcopy(json.loads((ROOT / "data/scenarios.json").read_bytes())
                             ["scenarios"]["boss"])
        spec["deck"] = ["Boundary hit"]
        spec["enemies"][0].update(hp=maximum, resist={})
        card = {"name": "Boundary hit", "element": "ember", "type": "damage",
                "pip_cost": 0, "accuracy": 1.0, "damage_min": 3, "damage_max": 3}
        if dot_tick:
            card.update(dot_tick=dot_tick, dot_rounds=1)
        cards_path = directory / "cards.json"
        scenarios_path = directory / "scenarios.json"
        cards_path.write_bytes(json.dumps({"cards": [card]}).encode("utf-8"))
        scenarios_path.write_bytes(json.dumps({"scenarios": {"boss": spec}})
                                   .encode("utf-8"))
        inputs = {path: self.snapshot(path) for path in (cards_path, scenarios_path)}
        self.addCleanup(self.assert_unchanged, inputs)
        factories = load_scenarios(scenarios_path, load_cards(cards_path))
        state, _ = factories["boss"](random.Random(0))
        return state

    def test_all_integer_health_states_match_independent_oracle(self):
        for maximum in range(1, 33):
            for hp in range(maximum + 1):
                with self.subTest(maximum=maximum, hp=hp):
                    state = self.state(maximum, hp)
                    self.rule.apply(state, RuleEvent("round_end"), random.Random(0))
                    expected = [Charm(self.rule.blade, Element.NEUTRAL)] \
                        if under_half(maximum, hp) else []
                    self.assertEqual(state.enemies[0].blades, expected)

    def test_known_even_odd_and_equality_boundaries(self):
        cases = ((5, 2, True), (5, 3, False), (6, 2, True), (6, 3, False),
                 (1, 0, False), (1, 1, False), (2, 1, False),
                 (3000, 1499, True), (3000, 1500, False), (3000, 1501, False))
        for maximum, hp, expected in cases:
            with self.subTest(maximum=maximum, hp=hp):
                state = self.state(maximum, hp)
                self.rule.apply(state, RuleEvent("round_end"), random.Random(0))
                self.assertEqual(bool(state.enemies[0].blades), expected)

    def test_dead_nonboss_and_wrong_event_controls(self):
        cases = ((0, True, "round_end"), (2, False, "round_end"),
                 (2, True, "cast"), (2, True, "enemy_turn"))
        for hp, boss, event in cases:
            with self.subTest(hp=hp, boss=boss, event=event):
                state = self.state(5, hp, boss=boss)
                self.rule.apply(state, RuleEvent(event), random.Random(0))
                self.assertEqual(state.enemies[0].blades, [])

    def test_each_living_boss_gains_one_blade_without_replacing_existing_charms(self):
        state = self.state(5, 2)
        cases = ((5, 2, True, True), (6, 2, True, True),
                 (5, 0, True, False), (5, 2, False, False))
        state.enemies = [self.state(maximum, hp, boss=boss).enemies[0]
                         for maximum, hp, boss, _ in cases]
        original = Charm(0.1, Element.FROST)
        for enemy in state.enemies:
            enemy.blades.append(original)
        self.rule.apply(state, RuleEvent("round_end"), random.Random(0))
        for enemy, (_, _, _, expected) in zip(state.enemies, cases, strict=True):
            self.assertEqual(enemy.blades, [original] +
                             ([Charm(self.rule.blade, Element.NEUTRAL)]
                              if expected else []))

    def test_supported_custom_json_round_enrages_at_five_to_two_hp(self):
        state = self.custom_state()
        self.assertEqual((state.enemies[0].hp, state.enemies[0].max_hp), (5, 5))
        self.assertTrue(state.enemies[0].is_boss)
        self.assertTrue(any(isinstance(rule, EnrageBelowHalf)
                            for rule in state.boss_rules))
        self.assertEqual(state.enemies[0].blades, [])
        returned = advance_round(state, Action(0, 0), random.Random(0))
        self.assertIs(returned, state)
        self.assertEqual((state.enemies[0].hp, state.round_num), (2, 2))
        self.assertEqual(len(state.hand), 6)
        self.assertEqual(state.enemies[0].blades, [Charm(0.25, Element.NEUTRAL)])
        advance_round(state, Action(None), random.Random(0))
        self.assertEqual((state.enemies[0].hp, state.round_num), (2, 3))
        self.assertEqual(state.enemies[0].blades,
                         [Charm(0.25, Element.NEUTRAL), Charm(0.25, Element.NEUTRAL)])

    def test_supported_custom_json_round_excludes_exact_even_half(self):
        state = self.custom_state(maximum=6)
        advance_round(state, Action(0, 0), random.Random(0))
        self.assertEqual((state.enemies[0].hp, state.enemies[0].max_hp), (3, 6))
        self.assertEqual(state.enemies[0].blades, [])

    def test_upkeep_death_precedes_round_end_enrage(self):
        state = self.custom_state(dot_tick=2)
        advance_round(state, Action(0, 0), random.Random(0))
        self.assertEqual((state.enemies[0].hp, state.round_num), (0, 2))
        self.assertEqual(state.enemies[0].blades, [])
        self.assertEqual(state.enemies[0].dots, [])
        self.assertEqual(state.result(), 1.0)


if __name__ == "__main__":
    unittest.main()
