"""Custom example reports preserve existing engine inputs and decision evidence."""

import contextlib
import hashlib
import io
import itertools
import json
import random
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path
from unittest.mock import patch

import demo
from engine import Card, Combatant, GameState, legal_actions
from engine.mcts import MCTS
from game.baselines import one_round_decider
from game.decision_report import load_snapshot, normalized
from game.loader import load_cards, load_scenarios


class CustomReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mcts-report-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.cards = self.directory / "caller-cards.json"
        self.scenarios = self.directory / "caller-scenarios.json"
        self.card_data = {
            "cards": [
                {
                    "name": "Pulse",
                    "element": "ember",
                    "type": "damage",
                    "pip_cost": 0,
                    "accuracy": 0.9,
                    "damage_min": 40,
                    "damage_max": 70,
                    "dot_tick": 5,
                    "dot_rounds": 2,
                },
                {
                    "name": "Focus",
                    "element": "neutral",
                    "type": "blade",
                    "modifier": 0.3,
                },
                {
                    "name": "Ward",
                    "element": "neutral",
                    "type": "shield",
                    "modifier": 0.2,
                },
            ]
        }
        self.scenario_data = {
            "scenarios": {
                "trial": {
                    "player": {
                        "name": "Caller",
                        "element": "ember",
                        "hp": 700,
                        "power_pip_chance": 0.4,
                        "boost": {"ember": 0.1},
                    },
                    "deck": ["Pulse", "Focus", "Ward"],
                    "enemies": [
                        {
                            "name": "Target",
                            "element": "frost",
                            "hp": 600,
                            "is_boss": True,
                            "resist": {"ember": 0.15},
                            "attack": {
                                "name": "Reply",
                                "element": "frost",
                                "type": "damage",
                                "damage_min": 30,
                                "damage_max": 45,
                            },
                            "rules": [
                                {"type": "punish_traps"},
                                {"type": "enrage_below_half", "blade": 0.2},
                            ],
                        },
                        {"name": "Target", "element": "frost", "hp": 550},
                    ],
                }
            }
        }
        self.cards.write_bytes(json.dumps(self.card_data).encode("utf-8"))
        self.scenarios.write_bytes(json.dumps(self.scenario_data).encode("utf-8"))

    def arguments(self, *extra):
        return [
            "trial",
            "--cards",
            str(self.cards),
            "--scenarios",
            str(self.scenarios),
            "--json",
            *extra,
        ]

    def invoke(self, arguments):
        out = io.StringIO()
        with (
            patch("sys.argv", ["demo.py", *arguments]),
            contextlib.redirect_stdout(out),
        ):
            demo.main()
        return out.getvalue()

    def report(self, *extra):
        return json.loads(self.invoke(self.arguments(*extra)))

    def reference_state(self, seed=7):
        cards = load_cards(self.cards)
        scenarios = load_scenarios(self.scenarios, cards)
        return scenarios["trial"](random.Random(seed))

    def test_custom_report_has_exact_inputs_full_model_and_no_path_metadata(self):
        before = (self.cards.read_bytes(), self.scenarios.read_bytes())
        report = self.report("--sims", "2", "--horizon", "1")
        state, deck = self.reference_state()
        self.assertEqual(report["format"], "mcts-decision-report")
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["initial_state"], normalized(state))
        self.assertEqual(
            report["scenario"], {"name": "trial", "seed": 7, "deck": normalized(deck)}
        )
        self.assertEqual(
            set(report["initial_state"]), {field.name for field in fields(GameState)}
        )
        self.assertEqual(
            set(report["initial_state"]["player"]),
            {field.name for field in fields(Combatant)},
        )
        self.assertEqual(
            set(report["initial_state"]["hand"][0]),
            {field.name for field in fields(Card)},
        )
        self.assertEqual(
            report["initial_state"]["boss_rules"][0]["parameters"], {"damage": 300}
        )
        self.assertEqual(
            report["initial_state"]["boss_rules"][1]["parameters"], {"blade": 0.2}
        )
        for role, data in zip(("cards", "scenarios"), before, strict=True):
            self.assertEqual(
                report["content"][role],
                {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()},
            )
        self.assertEqual(before, (self.cards.read_bytes(), self.scenarios.read_bytes()))
        self.assertNotIn(str(self.directory), json.dumps(report))
        self.assertNotIn(self.cards.name, json.dumps(report))
        identity = report["implementation"]
        self.assertIn("mcts.py", identity["engine_files_sha256"])
        self.assertIn("py.typed", identity["engine_files_sha256"])
        self.assertIn("game/decision_report.py", identity["example_files_sha256"])
        self.assertEqual(
            identity["example_files_sha256"]["demo.py"],
            hashlib.sha256(Path(demo.__file__).read_bytes()).hexdigest(),
        )

    def test_fixed_report_matches_raw_clockless_search_and_includes_unvisited(self):
        report = self.report("--sims", "1", "--horizon", "1", "--seed", "19")
        self.assertIn(
            "MCTS terminal wins score 1 - 0.045 * min(6, depth)",
            report["value_semantics"],
        )
        self.assertIn(
            "terminal losses score 0.15 * min(depth, h) / h",
            report["value_semantics"],
        )
        state, _ = self.reference_state()
        reference = MCTS(horizon_rounds=1, max_sims=1, rng=random.Random(19))
        expected = reference.search(state, time_budget_ms=None)
        rows = {
            (row["card_idx"], row["target_idx"]): row for row in report["legal_actions"]
        }
        self.assertEqual(
            list(rows), [(a.card_idx, a.target_idx) for a in legal_actions(state)]
        )
        for action, visits, value_sum in reference.last_root_statistics:
            row = rows[(action.card_idx, action.target_idx)]
            self.assertEqual((row["visits"], row["value_sum"]), (visits, value_sum))
            self.assertEqual(row["mean_shaped_reward"], value_sum / visits)
        self.assertTrue(any(row["status"] == "unvisited" for row in rows.values()))
        for row in rows.values():
            if row["status"] == "unvisited":
                self.assertEqual(
                    (row["visits"], row["value_sum"], row["mean_shaped_reward"]),
                    (0, 0.0, None),
                )
        self.assertEqual(
            report["ranking"],
            [
                {"card_idx": row.action.card_idx, "target_idx": row.action.target_idx}
                for row in expected
            ],
        )
        self.assertEqual(
            report["recommendation"],
            {**report["ranking"][0], "label": expected[0].label},
        )
        self.assertEqual(report["work"]["simulations"], reference.last_sims)
        self.assertEqual(report["work"]["transitions"], reference.last_transitions)
        self.assertEqual(
            report["work"]["stop_reasons"], list(reference.last_stop_reasons)
        )

    def test_duplicate_labels_keep_distinct_index_identities(self):
        report = self.report("--sims", "0")
        grouped = {}
        for row in report["legal_actions"]:
            grouped.setdefault(row["label"], []).append(
                (row["card_idx"], row["target_idx"])
            )
        duplicates = [
            identities for identities in grouped.values() if len(identities) > 1
        ]
        self.assertTrue(duplicates)
        for identities in duplicates:
            self.assertEqual(len(identities), len(set(identities)))

    def test_fixed_repeat_preserves_report_except_observed_elapsed(self):
        first = self.report("--sims", "3", "--horizon", "1", "--seed", "19")
        second = self.report("--sims", "3", "--horizon", "1", "--seed", "19")
        first.pop("elapsed_seconds")
        second.pop("elapsed_seconds")
        self.assertEqual(first, second)

    def test_separate_scenario_and_search_seeds(self):
        first = self.report("--sims", "0", "--scenario-seed", "11", "--seed", "19")
        other_search = self.report(
            "--sims", "0", "--scenario-seed", "11", "--seed", "31"
        )
        other_scenario = self.report(
            "--sims", "0", "--scenario-seed", "12", "--seed", "19"
        )
        state, _ = self.reference_state(11)
        self.assertEqual(first["initial_state"], normalized(state))
        self.assertEqual(first["initial_state"], other_search["initial_state"])
        self.assertNotEqual(
            first["initial_state"]["hand"], other_scenario["initial_state"]["hand"]
        )
        self.assertEqual(
            (first["scenario"]["seed"], first["configuration"]["seed"]), (11, 19)
        )

    def test_zero_work_has_null_recommendation_and_ignored_negative_clock(self):
        report = self.report("--sims", "0", "--budget-ms", "-1")
        self.assertIsNone(report["recommendation"])
        self.assertEqual(report["ranking"], [])
        self.assertEqual(report["work"]["simulations"], 0)
        self.assertEqual(report["work"]["transitions"], 0)
        self.assertEqual(report["configuration"]["requested_budget_ms"], -1)
        self.assertIsNone(report["configuration"]["time_budget_ms"])
        self.assertTrue(report["legal_actions"])
        self.assertTrue(
            all(row["status"] == "unvisited" for row in report["legal_actions"])
        )

    def test_fixed_positive_work_ignores_clock_and_clock_jumps(self):
        ticks = itertools.count(step=601.0)
        with patch("time.perf_counter", side_effect=lambda: next(ticks)):
            report = self.report("--sims", "2", "--budget-ms", "-1", "--horizon", "1")
        self.assertEqual(report["work"]["simulations"], 2)
        self.assertIsNone(report["configuration"]["time_budget_ms"])
        self.assertEqual(report["work"]["stop_reasons"], ["simulation_cap"])

    def test_timed_reports_keep_default_and_explicit_clock_stopping(self):
        for arguments, budget in (
            ([], 800),
            (["--budget-ms", "0"], 0),
            (["--budget-ms", "25"], 25),
        ):
            with self.subTest(arguments=arguments):
                ticks = itertools.count(step=601.0)
                with patch("time.perf_counter", side_effect=ticks.__next__):
                    report = self.report(*arguments)
                self.assertEqual(report["configuration"]["time_budget_ms"], budget)
                self.assertEqual(report["configuration"]["mode"], "timed")
                self.assertEqual(report["work"]["stop_reasons"], ["time_limit"])
                self.assertIsNone(report["recommendation"])

    def test_one_round_report_matches_existing_policy_and_distinct_sample_counts(self):
        report = self.report("--one-round-samples", "2", "--seed", "31")
        state, _ = self.reference_state()
        snapshots, receipts = [], []
        choose = one_round_decider(
            2, on_ranking=snapshots.append, on_work=receipts.append
        )
        action = choose(state, random.Random(31))
        self.assertEqual(report["work"], receipts[0])
        self.assertEqual(report["initial_state"], normalized(state))
        rows = {
            (row["card_idx"], row["target_idx"]): row for row in report["legal_actions"]
        }
        for expected in snapshots[0]:
            actual = rows[(expected.action.card_idx, expected.action.target_idx)]
            self.assertEqual(
                (actual["samples"], actual["value_sum"], actual["mean_shaped_reward"]),
                (expected.samples, expected.value_sum, expected.mean_value),
            )
            self.assertNotIn("visits", actual)
            self.assertEqual(actual["status"], "sampled")
        self.assertEqual(
            report["ranking"],
            [
                {"card_idx": row.action.card_idx, "target_idx": row.action.target_idx}
                for row in snapshots[0]
            ],
        )
        self.assertEqual(
            report["recommendation"],
            {
                "card_idx": action.card_idx,
                "target_idx": action.target_idx,
                "label": action.describe(state),
            },
        )
        self.assertIn("not calibrated win probabilities", report["value_semantics"])
        self.assertIn(
            "One-round terminal wins score 1 and losses 0", report["value_semantics"]
        )

    def test_hashes_identify_captured_bytes_after_originals_change(self):
        before = (self.cards.read_bytes(), self.scenarios.read_bytes())
        calls = []

        def load_captured(path):
            calls.append(path)
            self.assertNotEqual(path, self.cards)
            self.cards.write_bytes(b"changed after capture")
            self.scenarios.write_bytes(b"changed after capture")
            return load_cards(path)

        with patch("game.decision_report.load_cards", side_effect=load_captured):
            scenarios, content = load_snapshot(self.cards, self.scenarios)
        state, _ = scenarios["trial"](random.Random(7))
        self.assertEqual(state.player.name, "Caller")
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0].exists())
        for role, data in zip(("cards", "scenarios"), before, strict=True):
            self.assertEqual(content[role]["sha256"], hashlib.sha256(data).hexdigest())

    def refuse(self, arguments, message):
        out, err = io.StringIO(), io.StringIO()
        with (
            patch("sys.argv", ["demo.py", *arguments]),
            patch("demo.MCTS") as search,
            patch("demo.one_round_decider") as comparator,
            patch("demo.report_base") as report,
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            self.assertRaises(SystemExit) as caught,
        ):
            demo.main()
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn(message, err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        search.assert_not_called()
        comparator.assert_not_called()
        report.assert_not_called()

    def test_invalid_pair_unknown_scenario_and_missing_file_refuse_before_work(self):
        self.refuse(
            ["trial", "--cards", str(self.cards), "--json"], "must be supplied together"
        )
        self.refuse(
            self.arguments("--sims", "0") + ["absent"], "unrecognized arguments"
        )
        args = self.arguments("--sims", "0")
        args[0] = "absent"
        self.refuse(args, "unknown scenario 'absent'; available: trial")
        self.cards.unlink()
        self.refuse(self.arguments("--sims", "0"), "cards input could not be read")

    def test_malformed_json_and_container_shapes_refuse_before_work(self):
        cases = [
            (self.cards, b"{", "invalid UTF-8 JSON"),
            (self.cards, b"[]", "cards.json must be an object"),
            (self.cards, b'{"cards": {}}', "cards.json cards must be an array"),
            (self.cards, b'{"cards": [4]}', "cards.json card 0 must be an object"),
            (self.cards, b'{"cards": [{"accuracy": NaN}]}', "nonfinite JSON number"),
            (self.cards, b'{"cards": [{"accuracy": 1e999}]}', "nonfinite JSON number"),
            (self.cards, b"\xff", "invalid UTF-8 JSON"),
            (
                self.scenarios,
                b'{"scenarios": []}',
                "scenarios.json scenarios must be an object",
            ),
            (
                self.scenarios,
                b'{"scenarios": {"trial": []}}',
                "scenario 'trial' must be an object",
            ),
            (
                self.scenarios,
                b'{"scenarios": {"trial": {"deck": "Pulse"}}}',
                "deck must be an array",
            ),
            (
                self.scenarios,
                b'{"scenarios": {"trial": {"player": []}}}',
                "player must be an object",
            ),
            (
                self.scenarios,
                b'{"scenarios": {"trial": {"enemies": [false]}}}',
                "enemy 0 must be an object",
            ),
        ]
        before = (self.cards.read_bytes(), self.scenarios.read_bytes())
        for path, data, message in cases:
            with self.subTest(data=data):
                self.cards.write_bytes(before[0])
                self.scenarios.write_bytes(before[1])
                path.write_bytes(data)
                self.refuse(self.arguments("--sims", "0"), message)

    def test_rule_numeric_overflow_refuses_before_work(self):
        self.scenario_data["scenarios"]["trial"]["enemies"][0]["rules"] = [
            {"type": "enrage_below_half", "blade": 10**400}
        ]
        self.scenarios.write_bytes(json.dumps(self.scenario_data).encode("utf-8"))
        with patch("demo.random.Random") as random_source:
            self.refuse(
                self.arguments("--sims", "1"),
                "numeric value exceeds the supported floating-point range",
            )
        random_source.assert_not_called()

    def test_existing_loader_validation_remains_authoritative(self):
        self.scenario_data["scenarios"]["trial"]["enemies"][0]["rules"] = [
            {"type": "unknown"}
        ]
        self.scenarios.write_bytes(json.dumps(self.scenario_data).encode("utf-8"))
        self.refuse(self.arguments("--sims", "0"), "unknown rule type 'unknown'")
        self.scenario_data["scenarios"]["trial"]["enemies"][0]["rules"] = []
        self.scenario_data["scenarios"]["trial"]["deck"] = ["missing"]
        self.scenarios.write_bytes(json.dumps(self.scenario_data).encode("utf-8"))
        self.refuse(
            self.arguments("--sims", "0"), "deck references unknown card 'missing'"
        )

    def test_builtin_json_and_custom_text_are_both_available(self):
        report = json.loads(self.invoke(["--json", "--sims", "0"]))
        self.assertEqual(report["scenario"]["name"], "boss")
        self.assertEqual(report["content"]["kind"], "built-in")
        self.assertEqual(report["scenario"]["seed"], 7)
        args = self.arguments("--sims", "0")
        args.remove("--json")
        output = self.invoke(args)
        self.assertIn("Scenario: trial", output)
        self.assertIn("rule: Boss hits back for 300", output)
        self.assertIn("no recommendation is available", output)


if __name__ == "__main__":
    unittest.main()
