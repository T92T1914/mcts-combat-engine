"""JSON flags must not silently become numeric combat content."""
import copy
import json
import random
import tempfile
import unittest
from pathlib import Path

from engine import CardType, Element
from engine.simulator import resolve_damage
from game.loader import load_cards, load_scenarios

_CARD = {
    "name": "Hit", "element": "ember", "type": "damage",
    "pip_cost": 0, "accuracy": 1.0, "damage_min": 20, "damage_max": 20,
}
_SCENARIO = {
    "player": {"name": "P", "element": "ember", "hp": 100},
    "deck": ["Hit"],
    "enemies": [{"name": "E", "element": "frost", "hp": 100}],
}


class JsonBooleanValidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mcts-json-booleans-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cards = self._load_cards(_CARD)

    def _load_cards(self, card):
        path = self.root / "cards.json"
        path.write_text(json.dumps({"cards": [card]}), encoding="utf-8")
        return load_cards(path)

    def _load_scenarios(self, scenario):
        path = self.root / "scenarios.json"
        path.write_text(json.dumps({"scenarios": {"fixture": scenario}}),
                        encoding="utf-8")
        return load_scenarios(path, cards=self.cards)

    def test_card_numeric_fields_reject_json_booleans_at_load_time(self):
        numeric_fields = (
            "pip_cost", "accuracy", "damage_min", "damage_max",
            "heal", "dot_tick", "dot_rounds", "modifier",
        )
        for field in numeric_fields:
            for value in (False, True):
                with self.subTest(field=field, value=value):
                    raw = dict(_CARD, **{field: value})
                    with self.assertRaisesRegex(
                            ValueError, f"cards.json card 'Hit': field '{field}'"):
                        self._load_cards(raw)

    def test_player_and_enemy_hp_reject_json_booleans(self):
        for role in ("player", "enemy"):
            for value in (False, True):
                with self.subTest(role=role, value=value):
                    raw = copy.deepcopy(_SCENARIO)
                    target = raw["player"] if role == "player" else raw["enemies"][0]
                    target["hp"] = value
                    context = "player" if role == "player" else "enemy 0"
                    with self.assertRaisesRegex(
                            ValueError, f"scenario 'fixture' {context}: hp must be"):
                        self._load_scenarios(raw)

    def test_resist_and_boost_reject_json_booleans_for_both_roles(self):
        for role in ("player", "enemy"):
            for field in ("resist", "boost"):
                for value in (False, True):
                    with self.subTest(role=role, field=field, value=value):
                        raw = copy.deepcopy(_SCENARIO)
                        target = (raw["player"] if role == "player"
                                  else raw["enemies"][0])
                        target[field] = {"ember": value}
                        context = "player" if role == "player" else "enemy 0"
                        message = f"scenario 'fixture' {context}: resist/boost"
                        with self.assertRaisesRegex(
                                ValueError, message):
                            self._load_scenarios(raw)

    def test_nested_enemy_attack_uses_the_same_numeric_schema(self):
        raw = copy.deepcopy(_SCENARIO)
        raw["enemies"][0]["attack"] = dict(_CARD, accuracy=True)
        with self.assertRaisesRegex(
                ValueError, "scenario 'fixture' enemy 0 attack: field 'accuracy'"):
            self._load_scenarios(raw)

    def test_numeric_one_keeps_its_card_and_hp_meaning(self):
        fields = ("pip_cost", "accuracy", "damage_min", "damage_max",
                  "heal", "dot_tick", "dot_rounds", "modifier")
        raw = dict(_CARD, **dict.fromkeys(fields, 1))
        card = self._load_cards(raw)["Hit"]
        for field in fields:
            with self.subTest(field=field):
                self.assertEqual(getattr(card, field), 1)
                self.assertIs(type(getattr(card, field)), int)
        raw = copy.deepcopy(_SCENARIO)
        raw["player"]["hp"] = raw["enemies"][0]["hp"] = 1
        state, _ = self._load_scenarios(raw)["fixture"](random.Random(7))
        self.assertIs(type(state.player.hp), int)
        self.assertIs(type(state.enemies[0].hp), int)
        self.assertEqual(state.player.hp, 1)
        self.assertEqual(state.enemies[0].hp, 1)

    def test_valid_numeric_endpoints_and_boolean_flags_keep_their_behavior(self):
        for hits_all in (False, True):
            with self.subTest(hits_all=hits_all):
                cards = self._load_cards(dict(_CARD, hits_all=hits_all))
                self.assertIs(cards["Hit"].hits_all, hits_all)
                self.assertIs(cards["Hit"].card_type, CardType.DAMAGE)
                self.assertEqual(cards["Hit"].pip_cost, 0)
                self.assertEqual(cards["Hit"].accuracy, 1.0)

        for is_boss in (False, True):
            for numeric in (0, 0.0, 1, 1.0, -1, -1.0, 0.25):
                with self.subTest(is_boss=is_boss, numeric=numeric):
                    raw = copy.deepcopy(_SCENARIO)
                    raw["enemies"][0].update({
                        "is_boss": is_boss,
                        "resist": {"ember": numeric},
                        "boost": {"frost": numeric},
                    })
                    state, _ = self._load_scenarios(raw)["fixture"](random.Random(7))
                    enemy = state.enemies[0]
                    self.assertIs(enemy.is_boss, is_boss)
                    self.assertEqual(enemy.resist[Element.EMBER], float(numeric))
                    self.assertEqual(enemy.boost[Element.FROST], float(numeric))
                    dealt = resolve_damage(state.player, enemy, 20, Element.EMBER)
                    expected_damage = int(20 * (1.0 - max(0.0, numeric)))
                    self.assertEqual(dealt, expected_damage)
                    self.assertEqual(enemy.hp, 100 - expected_damage)


if __name__ == "__main__":
    unittest.main()
