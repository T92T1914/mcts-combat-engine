"""Loader tests: shipped data is valid, invalid data fails loudly."""
import json
import random
import unittest

from engine import CardType, Element
from game.content import CARDS, SCENARIOS
from game.loader import load_cards, load_scenarios, parse_card


class TestShippedContent(unittest.TestCase):
    def test_all_scenarios_build(self):
        for name, factory in SCENARIOS.items():
            state, deck = factory(random.Random(7))
            self.assertTrue(state.player.alive, name)
            self.assertTrue(state.enemies, name)
            self.assertEqual(len(state.hand), 7, name)
            self.assertTrue(deck, name)

    def test_boss_scenario_carries_its_rules(self):
        state, _ = SCENARIOS["boss"](random.Random(7))
        self.assertEqual(len(state.boss_rules), 2)
        self.assertTrue(state.enemies[0].is_boss)
        # configured value flows into the rule, not a stale default
        self.assertIn("350", state.boss_rules[0].description)

    def test_rng_stream_parity_with_precomputed_hand(self):
        # pins deck order AND draw order: this exact hand was produced by the
        # pre-data-layer code with the same seed, so content edits that would
        # silently shift every seeded benchmark fail here first
        state, _ = SCENARIOS["duel"](random.Random(7))
        self.assertEqual(
            [c.name for c in state.hand],
            ["Ember Blade", "Fire Blast", "Weakness Mark", "Spark",
             "Flame Dart", "Mend", "Flame Dart"],
        )

    def test_scenario_games_are_independent(self):
        factory = SCENARIOS["boss"]
        a, _ = factory(random.Random(1))
        b, _ = factory(random.Random(2))
        a.enemies[0].hp = 1
        self.assertNotEqual(b.enemies[0].hp, 1)


class TestCardValidation(unittest.TestCase):
    def _card(self, **overrides):
        raw = {"name": "X", "element": "ember", "type": "damage",
               "damage_min": 10, "damage_max": 20}
        raw.update(overrides)
        return raw

    def test_unknown_element_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown element"):
            parse_card(self._card(element="fire"), "test")

    def test_unknown_field_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            parse_card(self._card(dampage_min=10), "test")

    def test_accuracy_range_enforced(self):
        with self.assertRaisesRegex(ValueError, "accuracy"):
            parse_card(self._card(accuracy=1.5), "test")

    def test_dot_fields_must_pair(self):
        with self.assertRaisesRegex(ValueError, "dot_tick and dot_rounds"):
            parse_card(self._card(dot_tick=100), "test")

    def test_modifier_required_for_charms(self):
        with self.assertRaisesRegex(ValueError, "modifier"):
            parse_card({"name": "B", "element": "ember", "type": "blade"}, "test")

    def test_valid_card_parses_to_typed_objects(self):
        card = parse_card(self._card(), "test")
        self.assertIs(card.element, Element.EMBER)
        self.assertIs(card.card_type, CardType.DAMAGE)


class TestScenarioValidation(unittest.TestCase):
    def _write(self, tmp, cards=None, scenarios=None):
        import tempfile
        from pathlib import Path
        d = Path(tempfile.mkdtemp(dir=tmp))
        if cards is not None:
            (d / "cards.json").write_text(json.dumps(cards), encoding="utf-8")
        if scenarios is not None:
            (d / "scenarios.json").write_text(
                json.dumps(scenarios), encoding="utf-8")
        return d

    _MINIMAL_SCENARIO = {
        "player": {"name": "P", "element": "ember", "hp": 100},
        "deck": ["Spark"],
        "enemies": [{"name": "E", "element": "frost", "hp": 100}],
    }

    def test_deck_reference_to_unknown_card_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            bad = {"scenarios": {"s": dict(self._MINIMAL_SCENARIO,
                                           deck=["Nonexistent"])}}
            d = self._write(tmp, scenarios=bad)
            with self.assertRaisesRegex(ValueError, "unknown card"):
                load_scenarios(d / "scenarios.json", cards=CARDS)

    def test_unknown_rule_type_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            enemy = {"name": "E", "element": "frost", "hp": 100,
                     "rules": [{"type": "summon_minions"}]}
            bad = {"scenarios": {"s": dict(self._MINIMAL_SCENARIO,
                                           enemies=[enemy])}}
            d = self._write(tmp, scenarios=bad)
            with self.assertRaisesRegex(ValueError, "unknown rule type"):
                load_scenarios(d / "scenarios.json", cards=CARDS)

    def test_unknown_rule_param_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            enemy = {"name": "E", "element": "frost", "hp": 100,
                     "rules": [{"type": "punish_traps", "dmg": 5}]}
            bad = {"scenarios": {"s": dict(self._MINIMAL_SCENARIO,
                                           enemies=[enemy])}}
            d = self._write(tmp, scenarios=bad)
            with self.assertRaisesRegex(ValueError, "unknown params"):
                load_scenarios(d / "scenarios.json", cards=CARDS)

    def test_resist_range_enforced(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            enemy = {"name": "E", "element": "frost", "hp": 100,
                     "resist": {"ember": 3.0}}
            bad = {"scenarios": {"s": dict(self._MINIMAL_SCENARIO,
                                           enemies=[enemy])}}
            d = self._write(tmp, scenarios=bad)
            with self.assertRaisesRegex(ValueError, "must be in"):
                load_scenarios(d / "scenarios.json", cards=CARDS)

    def _scenario_with_enemy(self, tmp, enemy):
        bad = {"scenarios": {"s": dict(self._MINIMAL_SCENARIO,
                                       enemies=[enemy])}}
        return self._write(tmp, scenarios=bad)

    def test_rule_param_value_validated_not_just_name(self):
        import tempfile
        for damage in ("350", -350, 0):
            with tempfile.TemporaryDirectory() as tmp:
                enemy = {"name": "E", "element": "frost", "hp": 100,
                         "rules": [{"type": "punish_traps",
                                    "damage": damage}]}
                d = self._scenario_with_enemy(tmp, enemy)
                with self.assertRaisesRegex(ValueError, "positive integer",
                                            msg=repr(damage)):
                    load_scenarios(d / "scenarios.json", cards=CARDS)

    def test_power_pip_chance_validated(self):
        import tempfile
        for ppc in ("0.6", 7.5, -0.1):
            with tempfile.TemporaryDirectory() as tmp:
                enemy = {"name": "E", "element": "frost", "hp": 100,
                         "power_pip_chance": ppc}
                d = self._scenario_with_enemy(tmp, enemy)
                with self.assertRaisesRegex(ValueError, "power_pip_chance",
                                            msg=repr(ppc)):
                    load_scenarios(d / "scenarios.json", cards=CARDS)

    def test_is_boss_must_be_boolean(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            enemy = {"name": "E", "element": "frost", "hp": 100,
                     "is_boss": "false"}
            d = self._scenario_with_enemy(tmp, enemy)
            with self.assertRaisesRegex(ValueError, "is_boss"):
                load_scenarios(d / "scenarios.json", cards=CARDS)

    def test_empty_deck_rejected_at_load_time(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            bad = {"scenarios": {"s": dict(self._MINIMAL_SCENARIO, deck=[])}}
            d = self._write(tmp, scenarios=bad)
            with self.assertRaisesRegex(ValueError, "deck"):
                load_scenarios(d / "scenarios.json", cards=CARDS)

    def test_non_damage_attack_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            enemy = {"name": "E", "element": "frost", "hp": 100,
                     "attack": {"name": "Sneaky Heal", "element": "frost",
                                "type": "heal", "heal": 200}}
            d = self._scenario_with_enemy(tmp, enemy)
            with self.assertRaisesRegex(ValueError, "damage-type"):
                load_scenarios(d / "scenarios.json", cards=CARDS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
