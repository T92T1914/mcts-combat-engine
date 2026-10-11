"""Exact identity admission, separate from numerical or historical provenance.

Literal one-round envelopes are invented reader fixtures. Adaptive values use a
tiny modeled state. Neither fixture claims execution by a historical engine.
"""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_adaptive_consumer import adaptation_state
from test_reference_report import (
    literal_decision,
    literal_evaluation,
    literal_implementation,
)

from game import episode_record as records
from reference import adaptive, adaptive_report, consumer, one_round, report

QUALIFIED_MAPS = (
    report.REFERENCE_ENGINE_FILES_SHA256,
    report.QUALIFIED_DOCUMENTATION_ENGINE_FILES_SHA256,
)
PHYSICAL_LIMITS = {"max_paths": 100, "max_total_paths": 1000, "max_seconds": 1}
ADAPTIVE_LIMITS = {
    "max_transitions": 100,
    "max_per_action": 100,
    "max_work_units": 100,
    "max_seconds": 1,
}


def unqualified_maps():
    for admitted in QUALIFIED_MAPS:
        for name in ("mcts.py", "simulator.py"):
            changed = copy.deepcopy(admitted)
            changed[name] = "a" * 64
            yield name, changed
        missing = copy.deepcopy(admitted)
        del missing["state.py"]
        yield "missing", missing
        extra = copy.deepcopy(admitted)
        extra["extra.py"] = "b" * 64
        yield "extra", extra


def physical_base(engine_files):
    decision = literal_decision()
    implementation = literal_implementation(decision)
    implementation["decision_consumer"]["engine_files_sha256"] = copy.deepcopy(
        engine_files
    )
    return report.reference_report_base(
        decision, records.output_bytes(decision), implementation, PHYSICAL_LIMITS
    )


def adaptive_base(engine_files):
    state = adaptation_state()
    implementation = consumer.reference_identity()
    implementation["decision_consumer"]["engine_files_sha256"] = copy.deepcopy(
        engine_files
    )
    return adaptive_report.reference_report_base(
        state,
        records.output_bytes(state),
        implementation,
        ADAPTIVE_LIMITS,
        state_input=True,
    )


class ReferenceEngineIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mcts-reference-identity-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.decision_path = self.directory / "literal-decision.json"
        self.state_path = self.directory / "modeled-state.json"
        self.decision_path.write_bytes(records.output_bytes(literal_decision()))
        self.state_path.write_bytes(records.output_bytes(adaptation_state()))

    def test_only_the_two_complete_literal_maps_are_qualified(self):
        old, documented = QUALIFIED_MAPS
        self.assertEqual(set(old), set(documented))
        self.assertEqual(
            [name for name in old if old[name] != documented[name]], ["mcts.py"]
        )
        self.assertEqual(
            old["mcts.py"],
            "86902c63ed6a2f5bb8acb26413167947dbf2687bf4e7dfb911743851be35c04d",
        )
        self.assertEqual(
            documented["mcts.py"],
            "4cadf249dee661a535cd2d7eae0c9009caf91da88de69550292ca75b04b3c8ca",
        )
        for admitted in QUALIFIED_MAPS:
            with self.subTest(admitted=admitted["mcts.py"]):
                self.assertTrue(report.qualified_engine_files(admitted))
                reordered = dict(reversed(list(admitted.items())))
                self.assertTrue(report.qualified_engine_files(reordered))
        for name, unknown in unqualified_maps():
            with self.subTest(change=name, map=unknown):
                self.assertFalse(report.qualified_engine_files(unknown))
        for other in (None, [], True):
            self.assertFalse(report.qualified_engine_files(other))

    def test_producers_bind_each_qualified_observed_map_without_aliasing(self):
        for admitted in QUALIFIED_MAPS:
            for factory in (physical_base, adaptive_base):
                with self.subTest(factory=factory.__name__, map=admitted):
                    base = factory(admitted)
                    self.assertEqual(base["reference_engine_files_sha256"], admitted)
                    self.assertIsNot(base["reference_engine_files_sha256"], admitted)
                    self.assertIsNot(
                        base["reference_engine_files_sha256"],
                        base["implementation"]["decision_consumer"][
                            "engine_files_sha256"
                        ],
                    )

    def test_unknown_observation_retains_original_refusal_declaration(self):
        for name, unknown in unqualified_maps():
            for factory, reader in (
                (physical_base, report),
                (adaptive_base, adaptive_report),
            ):
                with self.subTest(change=name, family=reader.MODEL):
                    base = factory(unknown)
                    self.assertEqual(
                        base["reference_engine_files_sha256"], QUALIFIED_MAPS[0]
                    )
                    refused = reader.refused_reference_report(
                        base, "engine_mismatch", "Unqualified modeled observation."
                    )
                    self.assertIs(reader.validate_reference_report(refused), refused)
                    tampered = copy.deepcopy(refused)
                    tampered["reference_engine_files_sha256"] = unknown
                    with self.assertRaises(records.EpisodeInputError):
                        reader.validate_reference_report(tampered)

    def test_physical_complete_reports_require_their_own_qualified_map(self):
        for admitted, other in (QUALIFIED_MAPS, tuple(reversed(QUALIFIED_MAPS))):
            base = physical_base(admitted)
            completed = report.complete_reference_report(
                base, literal_evaluation(base["decision_report"])
            )
            before = records.canonical(completed)
            with patch.object(one_round, "evaluate", side_effect=AssertionError):
                self.assertIs(report.validate_reference_report(completed), completed)
            self.assertEqual(records.canonical(completed), before)
            crossed = copy.deepcopy(completed)
            crossed["reference_engine_files_sha256"] = copy.deepcopy(other)
            with self.assertRaises(records.EpisodeInputError):
                report.validate_reference_report(crossed)

    def test_adaptive_complete_reports_require_their_own_qualified_map(self):
        evaluation = adaptive.evaluate(adaptation_state(), **ADAPTIVE_LIMITS)
        for admitted, other in (QUALIFIED_MAPS, tuple(reversed(QUALIFIED_MAPS))):
            completed = adaptive_report.complete_reference_report(
                adaptive_base(admitted), evaluation
            )
            before = records.canonical(completed)
            with patch.object(adaptive, "evaluate", side_effect=AssertionError):
                self.assertIs(
                    adaptive_report.validate_reference_report(completed), completed
                )
            self.assertEqual(records.canonical(completed), before)
            crossed = copy.deepcopy(completed)
            crossed["reference_engine_files_sha256"] = copy.deepcopy(other)
            with self.assertRaises(records.EpisodeInputError):
                adaptive_report.validate_reference_report(crossed)

    def test_prequalification_adaptive_mismatch_remains_passively_readable(self):
        # A retained old producer could declare the original map and observe the
        # later docstring before it was qualified. This is a consistency fixture.
        base = adaptive_base(QUALIFIED_MAPS[1])
        base["reference_engine_files_sha256"] = copy.deepcopy(QUALIFIED_MAPS[0])
        refused = adaptive_report.refused_reference_report(
            base, "engine_mismatch", "Observed a different raw engine source."
        )
        before = records.canonical(refused)
        with patch.object(adaptive, "evaluate", side_effect=AssertionError):
            self.assertIs(adaptive_report.validate_reference_report(refused), refused)
        self.assertEqual(records.canonical(refused), before)
        inconsistent = copy.deepcopy(refused)
        inconsistent["reference_engine_files_sha256"] = copy.deepcopy(QUALIFIED_MAPS[1])
        with self.assertRaises(records.EpisodeInputError):
            adaptive_report.validate_reference_report(inconsistent)

    def test_unknown_maps_are_refused_before_either_evaluator(self):
        before = (self.decision_path.read_bytes(), self.state_path.read_bytes())
        for name, unknown in unqualified_maps():
            observed = consumer.reference_identity()
            observed["decision_consumer"]["engine_files_sha256"] = unknown
            with (
                self.subTest(change=name, map=unknown),
                patch.object(consumer, "reference_identity", return_value=observed),
                patch.object(one_round, "evaluate", side_effect=AssertionError) as one,
                patch.object(adaptive, "evaluate", side_effect=AssertionError) as two,
            ):
                results = (
                    consumer.reference_decision(self.decision_path),
                    consumer.reference_decision(
                        self.state_path,
                        model=adaptive_report.MODEL,
                        method=adaptive_report.METHOD,
                        state_input=True,
                    ),
                )
                for result in results:
                    self.assertEqual(result["status"], "refused")
                    self.assertEqual(result["failure"]["kind"], "engine_mismatch")
                    self.assertIsNone(result["evaluation"])
                    self.assertIsNone(result["diagnostics"])
                    self.assertFalse(result["new_search_performed"])
                one.assert_not_called()
                two.assert_not_called()
        self.assertEqual(
            (self.decision_path.read_bytes(), self.state_path.read_bytes()), before
        )

    def test_both_qualified_maps_reach_each_existing_calculation_path(self):
        for admitted in QUALIFIED_MAPS:
            observed = consumer.reference_identity()
            observed["decision_consumer"]["engine_files_sha256"] = copy.deepcopy(
                admitted
            )
            with (
                self.subTest(map=admitted),
                patch.object(consumer, "reference_identity", return_value=observed),
            ):
                physical = consumer.reference_decision(self.decision_path)
                adaptive_value = consumer.reference_decision(
                    self.state_path,
                    model=adaptive_report.MODEL,
                    method=adaptive_report.METHOD,
                    state_input=True,
                    **ADAPTIVE_LIMITS,
                )
                for result in (physical, adaptive_value):
                    self.assertEqual(result["status"], "complete")
                    self.assertEqual(result["reference_engine_files_sha256"], admitted)


if __name__ == "__main__":
    unittest.main()
