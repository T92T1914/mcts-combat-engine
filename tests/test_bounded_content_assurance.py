"""Finite content and text cases distinguish admission from authenticated origin."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_episode_inspection as inspection_fixtures

from engine import GameState
from game import episode_inspection as inspection
from game import episode_record as records

CONTENT_CASES = (
    ("baseline", 1, True, None),
    ("cards", 128, True, None), ("cards", 129, False, "cards:.*1..128 entries"),
    ("deck", 128, True, None), ("deck", 129, False, "deck:.*1..128 entries"),
    ("scenarios", 16, True, None),
    ("scenarios", 17, False, "scenarios:.*1..16 scenarios"),
    ("enemies", 8, True, None), ("enemies", 9, False, "enemies:.*1..8 entries"),
    ("card_name", 128, True, None),
    ("card_name", 129, False, "cards/0/name:.*1..128 characters"),
    ("combatant_name", 128, True, None),
    ("combatant_name", 129, False, "player/name:.*1..128 characters"),
    ("description", 2048, True, None),
    ("description", 2049, False, "scenarios:.*JSON string:.*2048 characters"),
)
TEXT_CASES = (
    ("markup", 'Quote "<tag>&', b'"name":"Quote \\"<tag>&"'),
    ("non_bmp", "\U0001d11e", b'"name":"\\ud834\\udd1e"'),
    ("surrogate_control", "\ud800\x00", b'"name":"\\ud800\\u0000"'),
)


def passive_guards(*, rendering: bool = False):
    stack = contextlib.ExitStack()
    for name in ("_record_owner", "record_episode", "replay_episode", "play_game"):
        stack.enter_context(patch.object(records, name, inspection_fixtures.forbidden))
    stack.enter_context(patch("subprocess.Popen", inspection_fixtures.forbidden))
    if rendering:
        for name in ("load_content", "load_snapshot", "observed_identity",
                     "implementation_identity", "is_legal_action", "legal_actions"):
            stack.enter_context(patch.object(records, name,
                                            inspection_fixtures.forbidden))
    return stack


class BoundedContentAssuranceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mcts-bounded-content-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    @staticmethod
    def snapshots(paths):
        return {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}

    def content(self, kind, size):
        card = {"name": "C0", "element": "ember", "type": "damage",
                "accuracy": 1.0, "damage_min": 1, "damage_max": 1}
        scenario = {"player": {"name": "P", "element": "ember", "hp": 100},
                    "deck": ["C0"],
                    "enemies": [{"name": "E", "element": "frost", "hp": 100}]}
        cards = {"cards": [card]}
        scenarios = {"scenarios": {"fixture": scenario}}
        if kind == "cards":
            cards["cards"] = [dict(card, name=f"C{index}") for index in range(size)]
        elif kind == "deck":
            scenario["deck"] = ["C0"] * size
        elif kind == "scenarios":
            scenarios["scenarios"] = {f"S{index}": copy.deepcopy(scenario)
                                      for index in range(size)}
        elif kind == "enemies":
            scenario["enemies"] = [dict(scenario["enemies"][0], name=f"E{index}")
                                   for index in range(size)]
        elif kind == "card_name":
            card["name"] = "x" * size
            scenario["deck"] = [card["name"]]
        elif kind == "combatant_name":
            scenario["player"]["name"] = "x" * size
        elif kind == "description":
            scenario["description"] = "x" * size
        paths = self.root / "cards.json", self.root / "scenarios.json"
        for path, value in zip(paths, (cards, scenarios), strict=True):
            path.write_bytes(json.dumps(value, ensure_ascii=True).encode("ascii"))
        return paths

    def typed_equal(self, expected, actual):
        self.assertIs(type(actual), type(expected))
        if isinstance(expected, dict):
            self.assertEqual(set(actual), set(expected))
            for key, value in expected.items():
                self.typed_equal(value, actual[key])
        elif isinstance(expected, list):
            self.assertEqual(len(actual), len(expected))
            for left, right in zip(expected, actual, strict=True):
                self.typed_equal(left, right)
        else:
            self.assertEqual(actual, expected)

    def assert_passive_html(self, output, value, *, expected_tags=None):
        artifact = inspection_fixtures.Artifact(output)
        self.typed_equal(value, artifact.record())
        if expected_tags is not None:
            self.assertEqual(artifact.tags, expected_tags)
        self.assertFalse(set(artifact.tags) & {
            "script", "iframe", "form", "img", "object", "link", "embed", "svg", "math",
        })
        self.assertTrue(all(link.startswith("#") for link in artifact.links))
        self.assertTrue(all(link[1:] in artifact.ids for link in artifact.links))
        self.assertTrue(all(not name.startswith("on")
                            for name, _ in artifact.attributes))
        self.assertIn(b"does not authenticate origin", output)
        return artifact

    def test_exact_content_bounds_precede_staging_and_preserve_inputs(self):
        actual_loader = records.load_snapshot
        for kind, size, admitted, message in CONTENT_CASES:
            with self.subTest(kind=kind, size=size, admitted=admitted):
                paths = self.content(kind, size)
                before = self.snapshots(paths)
                with passive_guards():
                    if not admitted:
                        with (patch.object(records, "load_snapshot") as staged,
                              patch.object(records.tempfile,
                                           "TemporaryDirectory") as stage,
                              self.assertRaisesRegex(records.EpisodeInputError,
                                                     message)):
                            records.load_content(*paths)
                        staged.assert_not_called()
                        stage.assert_not_called()
                    else:
                        with patch.object(records, "load_snapshot",
                                          wraps=actual_loader) as staged:
                            factories, identity = records.load_content(*paths)
                        staged.assert_called_once()
                        self.assertEqual(identity["kind"], "custom")
                        self.assertEqual(len(factories),
                                         size if kind == "scenarios" else 1)
                        for factory in factories.values():
                            state, deck = factory(random.Random(7))
                            self.assertIsInstance(state, GameState)
                            self.assertEqual(len(deck), size if kind == "deck" else 1)
                            self.assertEqual(len(state.enemies),
                                             size if kind == "enemies" else 1)
                            self.assertEqual(state.boss_rules, [])
                            self.assertEqual(len(state.hand), 7)
                            self.assertEqual(state.round_num, 1)
                            player_name = ("x" * size
                                           if kind == "combatant_name" else "P")
                            card_name = "x" * size if kind == "card_name" else "C0"
                            self.assertEqual(state.player.name, player_name)
                            self.assertEqual(deck[0].name, card_name)
                        for role, path in zip(("cards", "scenarios"), paths,
                                              strict=True):
                            self.assertEqual(identity[role], {
                                "bytes": len(before[path][0]),
                                "sha256": hashlib.sha256(before[path][0]).hexdigest()})
                self.assertEqual(self.snapshots(paths), before)

    def test_literal_text_preserves_canonical_fields_and_both_html_editions(self):
        baseline = inspection_fixtures.synthetic_record()
        baseline_path = self.root / "baseline.json"
        baseline_path.write_bytes(records.output_bytes(baseline))
        originals = self.snapshots((baseline_path,))
        for label, decoded, field_bytes in TEXT_CASES:
            with self.subTest(text_case=label):
                value = copy.deepcopy(baseline)
                value["scenario"]["name"] = decoded
                emitted = records.output_bytes(value)
                self.assertIn(field_bytes, emitted)
                saved = self.root / f"{label}.json"
                saved.write_bytes(emitted)
                before = self.snapshots((saved,))
                with passive_guards(rendering=True):
                    for appearance in ("obscur", "clair"):
                        with self.subTest(appearance=appearance):
                            baseline_html = inspection.inspection_html(
                                baseline_path, appearance=appearance)
                            tags = inspection_fixtures.Artifact(baseline_html).tags
                            output = inspection.inspection_html(
                                saved, appearance=appearance)
                            self.assert_passive_html(output, value, expected_tags=tags)
                self.assertEqual(self.snapshots((saved,)), before)
        self.assertEqual(self.snapshots((baseline_path,)), originals)

    def test_raw_identity_differs_for_equal_whitespace_and_key_order_variants(self):
        value = inspection_fixtures.synthetic_record()
        compact = records.output_bytes(value)
        reordered = {key: value[key] for key in reversed(tuple(value))}
        alternate = json.dumps(reordered, ensure_ascii=True, indent=2,
                               allow_nan=False).encode("ascii") + b"\n"
        self.assertNotEqual(compact, alternate)
        self.typed_equal(json.loads(compact), json.loads(alternate))
        digests = [hashlib.sha256(raw).hexdigest() for raw in (compact, alternate)]
        self.assertNotEqual(*digests)
        paths = self.root / "compact.json", self.root / "alternate.json"
        for path, raw in zip(paths, (compact, alternate), strict=True):
            path.write_bytes(raw)
        before = self.snapshots(paths)
        with passive_guards(rendering=True):
            for appearance in ("obscur", "clair"):
                for path, digest in zip(paths, digests, strict=True):
                    output = inspection.inspection_html(path, appearance=appearance)
                    self.assert_passive_html(output, value)
                    self.assertIn(digest.encode("ascii"), output)
        self.assertEqual(self.snapshots(paths), before)


if __name__ == "__main__":
    unittest.main()
