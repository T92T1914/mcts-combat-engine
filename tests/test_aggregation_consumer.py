"""Exercise explicit method delivery, historical reports and passive work admission.

Saved decision envelopes here are synthetic calibration data. They do not claim
that a recorded encounter or search reached the supplied modeled state.
"""

from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_episode_inspection import Artifact
from test_reference_report import literal_three_decision

import reference_episode
from game.episode_record import EpisodeInputError, output_bytes
from reference import aggregation, aggregation_domain, consumer, one_round, report


class AggregationConsumerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.decision_path = self.root / "synthetic-decision.json"
        fixture_path = Path(__file__).parent / "fixtures" / "three-enemy-reference.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        state = next(
            row["state"]
            for row in fixture["cases"]
            if row["id"] == "modeled-three-lawful-wide-area"
        )
        self.decision = literal_three_decision()
        self.decision["selected_state"] = copy.deepcopy(state)
        rows = copy.deepcopy(self.decision["legal_actions"][:2])
        rows[1]["target_idx"] = None
        self.decision["legal_actions"] = rows
        identities = [
            {name: row[name] for name in ("card_idx", "target_idx")} for row in rows
        ]
        self.decision["ranking"] = identities
        self.decision["root_encounter_order"] = identities[::-1]
        self.save_decision(width=3)

    def save_decision(self, *, width):
        self.decision["selected_state"]["hand"][0].update(
            damage_min=1, damage_max=width
        )
        self.decision_path.write_bytes(output_bytes(self.decision))

    def calculate(self, **controls):
        return consumer.reference_decision(
            self.decision_path,
            model=report.THREE_ENEMY_MODEL,
            method=aggregation_domain.METHOD,
            **controls,
        )

    def cli(self, arguments):
        output, errors = io.BytesIO(), io.StringIO()
        with (
            patch.object(
                reference_episode.sys, "stdout", SimpleNamespace(buffer=output)
            ),
            patch.object(reference_episode.sys, "stderr", errors),
        ):
            try:
                status = reference_episode.main(arguments)
            except SystemExit as exc:
                status = exc.code
        return status, output.getvalue(), errors.getvalue()

    def test_wide_explicit_cli_completes_without_changing_saved_input_or_default(self):
        self.save_decision(width=151)
        before = self.decision_path.read_bytes()
        with patch.object(
            one_round,
            "enumerate_action",
            side_effect=AssertionError("physical enumeration"),
        ):
            status, captured, errors = self.cli(
                [
                    str(self.decision_path),
                    "--model",
                    "three-enemy",
                    "--method",
                    "sum-convolution",
                ]
            )
        self.assertEqual((status, errors), (0, ""))
        result = json.loads(captured)
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["computation_method"], aggregation_domain.METHOD)
        rows = result["evaluation"]["actions"]
        self.assertEqual(
            rows[1]["expected_value"],
            {
                "numerator": "8342051988272323598463",
                "denominator": "15505672840654876573696",
            },
        )
        self.assertEqual(
            rows[1]["work"],
            {
                "contributions": 68_403,
                "payoff_evaluations": 451,
                "peak_bins": 451,
                "represented_damage_combinations": 3_442_951,
                "represented_trace_leaves": 3_442_951,
            },
        )
        self.assertEqual(result["evaluation"]["work"]["payoff_evaluations"], 452)
        self.assertNotIn("total_leaves", result["evaluation"])
        self.assertNotIn("leaves", rows[1])
        self.assertFalse(result["new_search_performed"])
        with patch.object(
            aggregation,
            "evaluate",
            side_effect=AssertionError("implicit method change"),
        ):
            default = consumer.reference_decision(
                self.decision_path, model=report.THREE_ENEMY_MODEL, max_paths=1
            )
        self.assertEqual(default["failure"]["kind"], "work_limit")
        self.assertEqual(default["schema_version"], 1)
        self.assertNotIn("computation_method", default)
        self.assertEqual(self.decision_path.read_bytes(), before)

    def test_passive_cross_method_comparison_keeps_raw_values_work_and_old_schema(self):
        # Keep the synthetic legacy search claim distinct from the current
        # qualified reference producer. Mixed engines cannot receive a ranking.
        legacy_aggregate = self.calculate()
        legacy_physical = consumer.reference_decision(
            self.decision_path, model=report.THREE_ENEMY_MODEL
        )
        legacy_paths = [
            self.root / "legacy-physical.json", self.root / "legacy-sum.json"
        ]
        for path, value in zip(
            legacy_paths, (legacy_physical, legacy_aggregate), strict=True
        ):
            path.write_bytes(output_bytes(value))
            self.assertEqual(
                value["diagnostics"]["comparison_eligibility"],
                {"eligible": False, "reasons": ["search_engine_identity_differs"]},
            )
        with patch.dict(
            sys.modules, {"reference.aggregation": None, "reference.one_round": None}
        ):
            legacy_comparison = report.reference_comparison_html(*legacy_paths)
        self.assertIn(b"No winner is declared", legacy_comparison)
        self.assertIn(b"left_search_objective_or_engine_differs", legacy_comparison)
        self.assertIn(b"right_search_objective_or_engine_differs", legacy_comparison)
        self.assertNotIn(b"equal exact one-round value loss", legacy_comparison)

        # This invented same-producer case uses the current qualified source map.
        # It is not a rewritten historical search or evidence of an actual search.
        current_engine = legacy_physical["implementation"]["decision_consumer"][
            "engine_files_sha256"
        ]
        self.assertTrue(report.qualified_engine_files(current_engine))
        self.assertEqual(
            current_engine,
            legacy_aggregate["implementation"]["decision_consumer"][
                "engine_files_sha256"
            ],
        )
        self.assertNotEqual(
            self.decision["implementation"]["engine_files_sha256"], current_engine
        )
        self.decision["implementation"]["engine_files_sha256"] = copy.deepcopy(
            current_engine
        )
        self.save_decision(width=3)
        aggregate = self.calculate()
        physical = consumer.reference_decision(
            self.decision_path, model=report.THREE_ENEMY_MODEL
        )
        for value in (physical, aggregate):
            self.assertTrue(value["identity_comparisons"]["search_engine_files_equal"])
            self.assertEqual(
                value["diagnostics"]["comparison_eligibility"],
                {"eligible": True, "reasons": []},
            )
        aggregate_path = self.root / "sum.json"
        physical_path = self.root / "physical.json"
        aggregate_path.write_bytes(output_bytes(aggregate))
        physical_path.write_bytes(output_bytes(physical))
        original = (aggregate_path.read_bytes(), physical_path.read_bytes())
        old_canonical = output_bytes(physical)
        with (
            patch.dict(
                sys.modules,
                {"reference.aggregation": None, "reference.one_round": None},
            ),
            patch.object(
                consumer,
                "reference_decision",
                side_effect=AssertionError("passive calculation"),
            ),
        ):
            html = report.reference_inspection_html(aggregate_path)
            artifact = Artifact(html)
            self.assertEqual(artifact.fragments["/evaluation"], aggregate["evaluation"])
            self.assertIn(b"Executed integer contribution updates", html)
            self.assertIn(b"Represented positive physical trace leaves", html)
            self.assertIn(b"not enumerated", html)
            compared = report.reference_comparison_html(physical_path, aggregate_path)
            self.assertIn(b"equal exact one-round value loss", compared)
            self.assertIn(aggregation_domain.METHOD.encode(), compared)
            self.assertIn(aggregation_domain.PHYSICAL_METHOD.encode(), compared)
            self.assertNotIn(b"reported_reference_values_disagree", compared)
            self.assertEqual(
                output_bytes(report.validate_reference_report(physical)), old_canonical
            )
        self.assertEqual(
            (aggregate_path.read_bytes(), physical_path.read_bytes()), original
        )
        self.assertEqual(physical["schema_version"], 1)
        self.assertNotIn("computation_method", physical)
        self.assertIn("total_leaves", physical["evaluation"])

    def test_work_mutations_partial_values_and_incompatible_controls_are_rejected(self):
        complete = self.calculate()
        for action_index, name in (
            (None, "contributions"),
            (1, "represented_trace_leaves"),
            (1, "peak_bins"),
        ):
            mutated = copy.deepcopy(complete)
            target = (
                mutated["evaluation"]
                if action_index is None
                else mutated["evaluation"]["actions"][action_index]
            )
            target["work"][name] += 1
            with self.subTest(counter=name), self.assertRaises(EpisodeInputError):
                report.validate_reference_report(mutated)
        omitted = copy.deepcopy(complete)
        omitted["evaluation"]["actions"].pop()
        with self.assertRaises(EpisodeInputError):
            report.validate_reference_report(omitted)
        limited = self.calculate(max_contributions=1)
        self.assertEqual(limited["failure"]["kind"], "work_limit")
        self.assertIsNone(limited["evaluation"])
        self.assertIsNone(limited["diagnostics"])
        with patch.object(aggregation, "evaluate", side_effect=KeyboardInterrupt):
            interrupted = self.calculate()
        self.assertEqual(interrupted["failure"]["kind"], "interrupted")
        self.assertIsNone(interrupted["evaluation"])
        for flags in (
            ["--method", "sum-convolution", "--max-paths", "250000"],
            ["--max-contributions", "1000000"],
            ["--inspect", "--method", "physical"],
        ):
            with self.subTest(flags=flags):
                status, captured, errors = self.cli([str(self.decision_path), *flags])
                self.assertEqual(status, 2)
                self.assertEqual(captured, b"")
                self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
