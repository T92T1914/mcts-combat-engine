"""Optional saved-state allocation keeps its schedule and passive reader meaning."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import math
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_episode_decision import (
    BinarySink,
    guarded_routes,
    manual_state,
    synthetic_record,
)

import decide_episode
from engine import MCTS, legal_actions
from game import episode_decision as decision
from game import episode_inspection as inspection
from game import episode_record as records
from game.decision_report import normalized
from game.episode_record import EpisodeInputError, canonical, output_bytes


class RootAllocationConsumerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mcts-root-consumer-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.saved = self.directory / "episode.json"
        self.value = synthetic_record()
        self.saved.write_bytes(output_bytes(self.value))

    def report(self, sims=32, **options):
        return decision.episode_decision(
            self.saved, step=1, seed=19, sims=sims, horizon=1,
            root_allocation="sequential_halving", **options)

    def save_report(self, report, name="decision.json"):
        path = self.directory / name
        path.write_bytes(output_bytes(report))
        return path

    def test_report_matches_direct_public_search_and_keeps_physical_duplicates(self):
        before = self.saved.read_bytes()
        state = manual_state()
        captured = canonical(normalized(state))
        direct = MCTS(horizon_rounds=1, max_sims=32, max_transitions=32,
                      exploration=1.2, rng=random.Random(19),
                      root_allocation="sequential_halving")
        ranked = direct.search(state, time_budget_ms=None, priors=None)
        with guarded_routes():
            report = self.report()
        self.assertEqual(report["schema_version"], 3)
        self.assertEqual(report["root_allocation"], direct.last_root_allocation)
        self.assertEqual(report["ranking"], [
            {"card_idx": row.action.card_idx, "target_idx": row.action.target_idx}
            for row in ranked])
        raw = {action: (visits, value) for action, visits, value in
               direct.last_root_statistics}
        for row, action in zip(report["legal_actions"], legal_actions(state),
                               strict=True):
            count, value = raw.get(action, (0, 0.0))
            self.assertEqual(row["visits"], count)
            self.assertEqual(float(row["value_sum"]).hex(), float(value).hex())
            self.assertEqual(row["mean_shaped_reward"],
                             value / count if count else None)
        identities = [(row["card_idx"], row["target_idx"])
                      for row in report["legal_actions"]]
        self.assertIn((1, 1), identities)
        self.assertIn((2, 1), identities)
        self.assertNotIn((1, 0), identities)
        self.assertEqual(canonical(normalized(state)), captured)
        self.assertEqual(self.saved.read_bytes(), before)
        inspection.validate_decision_report(report)

    def test_zero_and_uniform_fallback_keep_unvisited_nulls(self):
        with guarded_routes(no_search=True):
            zero = self.report(0)
        self.assertFalse(zero["search_performed"])
        self.assertEqual(zero["status"], "no_work")
        self.assertEqual(zero["ranking"], [])
        self.assertIsNone(zero["root_allocation"]["winner"])
        self.assertEqual(zero["root_allocation"]["mode"], "uniform_fallback")
        core = MCTS(horizon_rounds=1, max_sims=0, max_transitions=0,
                    root_allocation="sequential_halving")
        core.search(manual_state(), time_budget_ms=None)
        self.assertEqual(zero["root_allocation"], core.last_root_allocation)
        for sims in (1, 21, 22, 64):
            with self.subTest(sims=sims):
                report = self.report(sims)
                allocation = report["root_allocation"]
                self.assertEqual(allocation["mode"],
                                 "uniform_fallback" if sims < 22 else "halving")
                self.assertEqual(allocation["selections"], sims)
                self.assertEqual(report["work"]["transitions"], sims)
                for row in report["legal_actions"]:
                    if not row["visits"]:
                        self.assertIsNone(row["mean_shaped_reward"])
                inspection.validate_decision_report(report)

    def test_pass_only_zero_and_positive_schedules(self):
        for card in self.value["steps"][1]["state"]["hand"]:
            card["pip_cost"] = 14
        self.saved.write_bytes(output_bytes(self.value))
        for sims in (0, 1, 8):
            with self.subTest(sims=sims):
                report = self.report(sims)
                allocation = report["root_allocation"]
                self.assertEqual(len(report["legal_actions"]), 1)
                self.assertEqual(allocation["mode"], "halving")
                self.assertEqual(allocation["phases"], [])
                self.assertEqual(allocation["remainder_samples"], sims)
                state = decision._reconstruct(self.value["steps"][1]["state"], "test")
                direct = MCTS(horizon_rounds=1, max_sims=sims, max_transitions=sims,
                              rng=random.Random(19),
                              root_allocation="sequential_halving")
                direct.search(state, time_budget_ms=None)
                self.assertEqual(allocation, direct.last_root_allocation)

    def test_genuine_record_inspection_and_comparison_are_passive(self):
        genuine = records.record_episode("duel", rounds=1, sims=2, horizon=1)
        self.saved.write_bytes(output_bytes(genuine))
        before = self.saved.read_bytes()
        new = decision.episode_decision(self.saved, step=0, seed=19, sims=32,
                                       horizon=1, root_allocation="sequential_halving")
        old = decision.episode_decision(self.saved, step=0, seed=19, sims=32, horizon=1)
        explicit = decision.episode_decision(self.saved, step=0, seed=19, sims=32,
                                            horizon=1, final_action_rule="visits_mean")
        self.assertEqual(old["schema_version"], 1)
        self.assertEqual(explicit["schema_version"], 2)
        new_path = self.save_report(new)
        for historical in (old, explicit):
            old_path = self.save_report(historical, "historical.json")
            old_bytes = old_path.read_bytes()
            with (guarded_routes(no_search=True), patch.object(
                    decision, "_reconstruct",
                    side_effect=AssertionError("reconstruction"))):
                inspected = inspection.decision_inspection_html(new_path)
                compared = inspection.decision_comparison_html(new_path, old_path)
                reverse = inspection.decision_comparison_html(old_path, new_path)
            for rendered in (inspected, compared, reverse):
                self.assertIn(b"budget_aware_sequential_halving_v1", rendered)
                self.assertIn(b"survivor_mean_visits", rendered)
                self.assertIn(b"Phase means", rendered)
                self.assertNotIn(str(self.directory).encode(), rendered)
            self.assertIn(b"explicit settings differences", compared)
            self.assertEqual(old_path.read_bytes(), old_bytes)
        self.assertEqual(self.saved.read_bytes(), before)
        with self.assertRaisesRegex(EpisodeInputError, "allocation treatment"):
            inspection.decision_ranking(new, "mean_visits")

    def test_malformed_complete_phases_coordinates_and_work_refuse(self):
        report = self.report()
        mutations = [
            lambda value: value["root_allocation"].update(complete=False),
            lambda value: value["root_allocation"].update(mode="uniform_fallback"),
            lambda value: value["root_allocation"].update(reward_updates=31),
            lambda value: value["root_allocation"].update(
                elimination_key_evaluations=0),
            lambda value: value["root_allocation"].update(remainder_samples=0),
            lambda value: value["root_allocation"].update(winner=None),
            lambda value: value["root_allocation"]["phases"].pop(),
            lambda value: value["root_allocation"]["phases"][0].update(quota=2),
            lambda value: value["root_allocation"]["phases"][0].update(
                completed_samples=0),
            lambda value: value["root_allocation"]["phases"][0]["active"].reverse(),
            lambda value: value["root_allocation"]["phases"][0]["statistics"][0].update(
                visits=0),
            lambda value: value["root_allocation"]["phases"][0]["statistics"][0].update(
                mean=None),
            lambda value: value["root_allocation"]["phases"][0]["statistics"][0].update(
                value_sum=-1),
            lambda value: value["root_allocation"]["phases"][0]["survivors"].pop(),
            lambda value: value["root_allocation"]["phases"][0]["survivors"].reverse(),
            lambda value: value["legal_actions"][2].update(target_idx=0),
            lambda value: value["legal_actions"].reverse(),
            lambda value: value["configuration"].update(horizon_rounds=2),
            lambda value: value["configuration"].update(
                final_action_rule="mean_visits"),
            lambda value: value["configuration"].update(priors={}),
            lambda value: value["configuration"].update(parallel=True),
            lambda value: value["work"].update(transitions=31, unused_transitions=1),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                malformed = copy.deepcopy(report)
                mutate(malformed)
                with self.assertRaises(EpisodeInputError):
                    inspection.validate_decision_report(malformed)
        duplicate = copy.deepcopy(report)
        duplicate["root_allocation"]["phases"][0]["active"][1] = copy.deepcopy(
            duplicate["root_allocation"]["phases"][0]["active"][0])
        with self.assertRaises(EpisodeInputError):
            inspection.validate_decision_report(duplicate)
        altered_ranking = copy.deepcopy(report)
        altered_ranking["ranking"][1:] = reversed(altered_ranking["ranking"][1:])
        with self.assertRaisesRegex(EpisodeInputError, "/ranking"):
            inspection.validate_decision_report(altered_ranking)
        altered_survivors = copy.deepcopy(report)
        phase = altered_survivors["root_allocation"]["phases"][0]
        excluded = next(action for action in phase["active"]
                        if action not in phase["survivors"])
        phase["survivors"][0] = copy.deepcopy(excluded)
        phase["survivors"].sort(key=phase["active"].index)
        with self.assertRaisesRegex(EpisodeInputError, "/survivors"):
            inspection.validate_decision_report(altered_survivors)

    def test_saved_phase_grouping_is_not_replaced_by_cumulative_sum_equality(self):
        report = self.report()
        winner = report["root_allocation"]["winner"]
        row = next(row for row in report["legal_actions"]
                   if row["card_idx"] == winner["card_idx"]
                   and row["target_idx"] == winner["target_idx"])
        self.assertGreater(row["value_sum"], 0)
        original = row["value_sum"]
        row["value_sum"] = math.nextafter(original, 0.0)
        row["mean_shaped_reward"] = row["value_sum"] / row["visits"]
        self.assertNotEqual(row["value_sum"].hex(), float(original).hex())
        inspection.validate_decision_report(report)

    def test_failed_or_incomplete_producer_publishes_no_complete_json(self):
        original_search = MCTS.search

        def incomplete(search, state, **kwargs):
            ranked = original_search(search, state, **kwargs)
            search.last_root_allocation["complete"] = False
            return ranked

        for failure in (RuntimeError("fixture search failure"), KeyboardInterrupt()):
            sink = BinarySink()
            with (patch.object(MCTS, "search", side_effect=failure),
                  contextlib.redirect_stdout(sink),
                  contextlib.redirect_stderr(io.StringIO())):
                status = decide_episode.main([
                    str(self.saved), "--step", "1", "--sims", "32", "--horizon", "1",
                    "--root-allocation", "sequential_halving"])
            self.assertEqual(status,
                             130 if isinstance(failure, KeyboardInterrupt) else 1)
            self.assertEqual(sink.data, b"")
        sink = BinarySink()
        with (patch.object(MCTS, "search", incomplete),
              contextlib.redirect_stdout(sink),
              contextlib.redirect_stderr(io.StringIO())):
            status = decide_episode.main([
                str(self.saved), "--step", "1", "--sims", "32", "--horizon", "1",
                "--root-allocation", "sequential_halving"])
        self.assertEqual(status, 1)
        self.assertEqual(sink.data, b"")

    def test_api_and_cli_controls_refuse_before_input_capture(self):
        bad = [
            {"horizon": 2}, {"exploration": 0.6},
            {"final_action_rule": "mean_visits"}, {"root_allocation": "uct"},
            {"root_allocation": True},
        ]
        for options in bad:
            arguments = {"step": 1, "horizon": 1,
                         "root_allocation": "sequential_halving"}
            arguments.update(options)
            with (self.subTest(options=options), patch.object(
                    decision, "_read",
                    side_effect=AssertionError("capture before admission"))):
                with self.assertRaises(EpisodeInputError):
                    decision.episode_decision(self.saved, **arguments)
        suffixes = [[], ["--horizon", "2"], ["--horizon", "1", "--exploration", "2.4"],
                    ["--horizon", "1", "--final-action-rule", "mean_visits"],
                    ["--horizon", "1", "--stability", "--seeds", "7", "11"],
                    ["--horizon", "1", "--extract-cell", "0"]]
        for suffix in suffixes:
            with (self.subTest(suffix=suffix), patch.object(
                    decide_episode, "episode_decision",
                    side_effect=AssertionError("search before admission")),
                    contextlib.redirect_stderr(io.StringIO())):
                with self.assertRaises(SystemExit) as stopped:
                    decide_episode.main([str(self.saved), "--step", "1",
                                         "--root-allocation", "sequential_halving",
                                         *suffix])
                self.assertEqual(stopped.exception.code, 2)
        sink = BinarySink()
        with guarded_routes(no_search=True), contextlib.redirect_stdout(sink):
            status = decide_episode.main([str(self.saved), "--step", "1", "--sims", "0",
                                          "--horizon", "1", "--root-allocation",
                                          "sequential_halving"])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(sink.data)["schema_version"], 3)

    def test_default_and_explicit_old_contracts_keep_original_fields_and_ranking(self):
        for options, version in (({}, 1), ({"exploration": 1.2}, 2)):
            with self.subTest(version=version):
                report = decision.episode_decision(self.saved, step=1, seed=19, sims=8,
                                                   horizon=1, **options)
                direct = MCTS(horizon_rounds=1, max_sims=8, max_transitions=8,
                              rng=random.Random(19))
                ranked = direct.search(manual_state(), time_budget_ms=None)
                self.assertEqual(report["schema_version"], version)
                self.assertNotIn("root_allocation", report)
                self.assertNotIn("sampling_policy", report["configuration"])
                self.assertEqual(report["ranking"], [
                    {"card_idx": row.action.card_idx,
                     "target_idx": row.action.target_idx}
                    for row in ranked])
                inspection.validate_decision_report(report)


if __name__ == "__main__":
    unittest.main()
