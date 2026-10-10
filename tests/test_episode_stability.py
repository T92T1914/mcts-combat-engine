"""Fixed-work diagnostic and passive derivation preserve decision boundaries."""
from __future__ import annotations

import contextlib
import copy
import io
import random
import sys
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
from test_episode_inspection import synthetic_decision_report

import decide_episode
from engine import MCTS
from game import episode_decision as decision
from game import episode_inspection as inspection
from game.episode_record import EpisodeInputError, canonical


def literal_decision(seed=7, *, zero=False, reverse=False):
    """Saved representation with intentional mean/visits disagreement, no search."""
    report = synthetic_decision_report(zero=True)
    report.update(schema_version=2, root_encounter_order=[], derivation=None)
    report["configuration"].update(
        seed=seed, max_sims=0 if zero else 64, max_transitions=0 if zero else 128,
        final_action_rule="mean_visits", tie_break="root_encounter_order")
    if zero:
        return report
    rows = report["legal_actions"]
    first, second = ((48, 12.0), (16, 12.0)) if reverse else ((16, 12.0), (48, 24.0))
    for row, (visits, value) in zip(rows[:2], (first, second), strict=True):
        row.update(status="sampled", visits=visits, value_sum=value,
                   mean_shaped_reward=value / visits)
    def identity(row):
        return {name: row[name] for name in ("card_idx", "target_idx")}
    report["root_encounter_order"] = [identity(rows[1]), identity(rows[0])]
    report["ranking"] = [identity(rows[1 if reverse else 0]),
                         identity(rows[0 if reverse else 1])]
    chosen = rows[1 if reverse else 0]
    report["recommendation"] = {**identity(chosen), "label": chosen["label"]}
    report.update(status="decision", search_performed=True, elapsed_seconds=0.25)
    report["work"] = {"simulations": 64, "transitions": 128, "unused_transitions": 0,
                      "stop_reasons": ["transition_allowance", "simulation_cap"]}
    return report


def literal_stability():
    config = inspection.stability_configuration([7, 11], [1.2], 2)
    cells = [literal_decision(7), literal_decision(11, reverse=True)]
    return {"format": "mcts-episode-stability-report", "schema_version": 1,
            "status": "complete", "reference_decision": literal_decision(zero=True),
            "configuration": config, "cells": cells,
            "work": {"completed_search_calls": 2, "simulations": 128,
                     "transitions": 256, "unused_transitions": 0},
            "diagnostics": inspection.stability_diagnostics(cells, config),
            "failure": None}


class StabilityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "episode.json"
        self.path.write_bytes(canonical(synthetic_record()) + b"\n")

    def test_grid_matches_independent_direct_searches_and_preserves_default(self):
        before = self.path.read_bytes()
        report = decision.episode_stability(
            self.path, step=1, seeds=[7, 11], explorations=[0.6, 1.2], horizon=1)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["work"]["completed_search_calls"], 4)
        self.assertEqual(report["work"]["simulations"], 256)
        self.assertLessEqual(report["work"]["transitions"], 256)
        for cell in report["cells"]:
            config = cell["configuration"]
            search = MCTS(horizon_rounds=1, max_sims=64,
                          exploration=config["exploration"], max_transitions=64,
                          rng=random.Random(config["seed"]))
            ranked = search.search(manual_state(), time_budget_ms=None, priors=None)
            self.assertEqual(cell["ranking"], [
                {"card_idx": row.action.card_idx, "target_idx": row.action.target_idx}
                for row in ranked])
            self.assertEqual(cell["root_encounter_order"], [
                {"card_idx": action.card_idx, "target_idx": action.target_idx}
                for action, _, _ in search.last_root_statistics])
        legacy = decision.episode_decision(self.path, step=1, sims=0)
        self.assertEqual(legacy["schema_version"], 1)
        self.assertNotIn("root_encounter_order", legacy)
        explicit = decision.episode_decision(self.path, step=1, sims=0, exploration=1.2)
        self.assertEqual(explicit["schema_version"], 2)
        self.assertEqual(explicit["configuration"]["final_action_rule"], "mean_visits")
        self.assertEqual(self.path.read_bytes(), before)

    def test_passive_extract_inspect_and_compare_use_same_statistics(self):
        saved = literal_stability()
        self.path.write_bytes(canonical(saved) + b"\n")
        group = saved["diagnostics"]["groups"][0]
        self.assertEqual(group["selector_disagreements"], 2)
        self.assertEqual(group["mean_visits"]["seed_pair_disagreements"], 1)
        self.assertEqual(group["mean_visits"]["seed_pair_denominator"], 1)
        with (
            guarded_routes(no_search=True),
            patch.object(decision, "current_identity", side_effect=AssertionError),
            patch.object(decision, "_reconstruct", side_effect=AssertionError),
        ):
            mean = inspection.extract_stability_decision(self.path, cell_index=0)
            robust = inspection.extract_stability_decision(
                self.path, cell_index=0, final_action_rule="visits_mean")
            self.assertNotEqual(mean["recommendation"], robust["recommendation"])
            self.assertEqual(mean["legal_actions"], robust["legal_actions"])
            self.assertEqual(mean["work"], robust["work"])
            self.assertIs(robust["derivation"]["new_search_performed"], False)
            left = self.path.parent / "mean.json"
            right = self.path.parent / "robust.json"
            left.write_bytes(canonical(mean) + b"\n")
            right.write_bytes(canonical(robust) + b"\n")
            self.assertIn(b"/derivation", inspection.decision_inspection_html(right))
            html = inspection.decision_comparison_html(left, right)
            self.assertIn(b"without search", html)
            self.assertIn(b"visits_mean", html)

    def test_full_ties_keep_observed_encounter_order_and_v1_is_not_repaired(self):
        report = literal_decision()
        for row in report["legal_actions"][:2]:
            row.update(visits=32, value_sum=16.0, mean_shaped_reward=0.5)
        report["ranking"] = copy.deepcopy(report["root_encounter_order"])
        chosen = report["legal_actions"][1]
        report["recommendation"] = {name: chosen[name]
                                    for name in ("card_idx", "target_idx", "label")}
        inspection.validate_decision_report(report)
        self.assertEqual(inspection.decision_ranking(report, "visits_mean"),
                         report["root_encounter_order"])
        broken = copy.deepcopy(report)
        broken["root_encounter_order"].reverse()
        with self.assertRaisesRegex(EpisodeInputError, "/ranking"):
            inspection.validate_decision_report(broken)
        inspection.validate_decision_report(synthetic_decision_report())

    def test_adverse_inputs_and_tampered_saved_sweeps_refuse_without_search(self):
        for seeds, coefficients in (([7, 7], [1.2]), ([7, -7], [1.2]),
                                    ([7], [1.2]), (list(range(17)), [1.2]),
                                    ([7, 11], [1.2, 1.2]), ([7, 11], [0.7]),
                                    ([True, 11], [1.2])):
            with guarded_routes(no_search=True), \
                    patch.object(decision, "_read", side_effect=AssertionError):
                with self.assertRaises(EpisodeInputError):
                    decision.episode_stability(self.path, step=0, seeds=seeds,
                                               explorations=coefficients)
        for path, replacement in (
                (("configuration", "maximum_simulations"), 129),
                (("cells", 1, "configuration", "seed"), 7),
                (("cells", 1, "selected_state", "round_num"), 2),
                (("cells", 1, "implementation", "platform"), "tampered"),
                (("cells", 1, "root_encounter_order"), []),
                (("diagnostics", "groups", 0, "selector_disagreements"), 0),
                (("work", "simulations"), 127)):
            report = literal_stability()
            target = report
            for item in path[:-1]:
                target = target[item]
            target[path[-1]] = replacement
            self.path.write_bytes(canonical(report) + b"\n")
            with guarded_routes(no_search=True):
                with self.assertRaises(EpisodeInputError):
                    inspection.extract_stability_decision(self.path, cell_index=0)

    def test_failed_or_interrupted_cell_retains_prefix_and_nonzero_cli_status(self):
        original = self.path.read_bytes()
        failures = ((RuntimeError("fixture failure"), 1), (KeyboardInterrupt(), 130))
        for error, status in failures:
            self.path.write_bytes(original)
            with patch.object(decision, "_decision_from_record", side_effect=[
                    literal_decision(zero=True), literal_decision(), error]):
                partial = decision.episode_stability(
                    self.path, step=0, seeds=[7, 11], explorations=[1.2], horizon=2)
            self.assertEqual(partial["status"], "incomplete")
            self.assertEqual(len(partial["cells"]), 1)
            self.assertEqual(partial["failure"]["cell_index"], 1)
            self.assertIsNone(partial["diagnostics"])
            self.path.write_bytes(canonical(partial) + b"\n")
            with guarded_routes(no_search=True):
                extracted = inspection.extract_stability_decision(
                    self.path, cell_index=0)
                self.assertEqual(extracted["derivation"]["source_report"]["status"],
                                 "incomplete")
                with self.assertRaisesRegex(EpisodeInputError, "no completed decision"):
                    inspection.extract_stability_decision(self.path, cell_index=1)
            sink, errors = BinarySink(), io.StringIO()
            with (
                patch.object(decide_episode, "episode_stability", return_value=partial),
                contextlib.redirect_stdout(sink),
                contextlib.redirect_stderr(errors),
            ):
                result = decide_episode.main([
                    str(self.path), "--step", "0", "--stability", "--seeds", "7", "11"])
            self.assertEqual(result, status)
            self.assertTrue(sink.data.endswith(b"\n"))
            self.assertIn("incomplete sweep", errors.getvalue())

    def test_interruption_after_committed_cell_uses_completed_prefix(self):
        original = self.path.read_bytes()
        for completed in (1, 2):
            self.path.write_bytes(original)

            def interrupt_after_append(frame, event, _argument, completed=completed):
                if (frame.f_code is decision.episode_stability.__code__
                        and event == "line"):
                    cells = frame.f_locals.get("cells")
                    if cells is not None and len(cells) == completed:
                        raise KeyboardInterrupt
                return interrupt_after_append

            previous_trace = sys.gettrace()
            with patch.object(decision, "_decision_from_record", side_effect=[
                    literal_decision(zero=True), literal_decision(),
                    literal_decision(11, reverse=True)]):
                try:
                    sys.settrace(interrupt_after_append)
                    partial = decision.episode_stability(
                        self.path, step=0, seeds=[7, 11], explorations=[1.2],
                        horizon=2)
                finally:
                    sys.settrace(previous_trace)
            self.assertEqual(partial["status"], "incomplete")
            self.assertEqual(len(partial["cells"]), completed)
            self.assertEqual(partial["work"]["completed_search_calls"], completed)
            self.assertEqual(partial["failure"]["stage"],
                             "search" if completed == 1 else "finalization")
            self.assertEqual(partial["failure"]["cell_index"],
                             1 if completed == 1 else None)
            self.assertIs(partial["failure"]["interrupted"], True)
            self.assertIsNone(partial["diagnostics"])
            self.path.write_bytes(canonical(partial) + b"\n")
            with guarded_routes(no_search=True):
                inspection.extract_stability_decision(
                    self.path, cell_index=completed - 1)

    def test_passive_finalization_refuses_an_unfinished_grid(self):
        report = literal_stability()
        report.update(status="incomplete", diagnostics=None, failure={
            "stage": "finalization", "cell_index": None,
            "message": "fixture finalization failure", "interrupted": False,
        })
        report["cells"].pop()
        report["work"] = inspection.stability_work(report["cells"])
        self.path.write_bytes(canonical(report) + b"\n")
        with guarded_routes(no_search=True):
            with self.assertRaisesRegex(EpisodeInputError, "/failure/stage"):
                inspection.extract_stability_decision(self.path, cell_index=0)

    def test_preflight_refuses_oversized_output_before_search(self):
        original = decision.output_bytes
        calls = 0

        def refuse_sweep(value):
            nonlocal calls
            calls += 1
            if value["format"] == "mcts-episode-stability-report":
                raise decision.DecisionRuntimeError("generated output exceeds bound")
            return original(value)

        with guarded_routes(no_search=True), patch.object(
                decision, "output_bytes", side_effect=refuse_sweep):
            with self.assertRaisesRegex(decision.DecisionRuntimeError, "exceeds bound"):
                decision.episode_stability(self.path, step=1, seeds=[7, 11])
        self.assertGreaterEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
