"""Exact identity admission, separate from numerical or historical provenance.

Literal one-round envelopes are invented reader fixtures. Adaptive values use a
tiny modeled state. Neither fixture claims execution by a historical engine.
"""

from __future__ import annotations

import ast
import base64
import copy
import hashlib
import json
import tempfile
import unittest
from itertools import permutations
from pathlib import Path
from unittest.mock import patch

from test_adaptive_consumer import adaptation_state
from test_reference_report import (
    literal_decision,
    literal_evaluation,
    literal_implementation,
)

from engine.rules import EnrageBelowHalf
from game import episode_record as records
from reference import (
    adaptive,
    adaptive_report,
    aggregation,
    aggregation_domain,
    consumer,
    one_round,
    report,
)

HISTORICAL_MAPS = (
    report.REFERENCE_ENGINE_FILES_SHA256,
    report.QUALIFIED_DOCUMENTATION_ENGINE_FILES_SHA256,
    report.QUALIFIED_EDGE_REUSE_ENGINE_FILES_SHA256,
    report.QUALIFIED_ROOT_ALLOCATION_ENGINE_FILES_SHA256,
    report.QUALIFIED_CANONICAL_ROOT_ALLOCATION_ENGINE_FILES_SHA256,
    report.QUALIFIED_CANONICAL_MANAGED_ROOT_ALLOCATION_ENGINE_FILES_SHA256,
    report.QUALIFIED_WINDOWS_MANAGED_ROOT_ALLOCATION_ENGINE_FILES_SHA256,
)
MANAGED_MAPS = HISTORICAL_MAPS[-2:]
EXACT_HALF_MAPS = (
    report.QUALIFIED_CANONICAL_EXACT_HALF_ENGINE_FILES_SHA256,
    report.QUALIFIED_WINDOWS_EXACT_HALF_ENGINE_FILES_SHA256,
)
QUALIFIED_MAPS = HISTORICAL_MAPS + EXACT_HALF_MAPS
PHYSICAL_LIMITS = {"max_paths": 100, "max_total_paths": 1000, "max_seconds": 1}
ADAPTIVE_LIMITS = {
    "max_transitions": 100,
    "max_per_action": 100,
    "max_work_units": 100,
    "max_seconds": 1,
}


def unqualified_maps():
    for admitted in QUALIFIED_MAPS:
        for name in ("decider.py", "mcts.py", "rules.py", "simulator.py"):
            changed = copy.deepcopy(admitted)
            changed[name] = "a" * 64
            yield name, changed
        missing = copy.deepcopy(admitted)
        del missing["state.py"]
        yield "missing", missing
        extra = copy.deepcopy(admitted)
        extra["extra.py"] = "b" * 64
        yield "extra", extra
    for admitted, other in permutations(EXACT_HALF_MAPS, 2):
        for name in admitted:
            if admitted[name] != other[name]:
                yield "mixed " + name, {**admitted, name: other[name]}


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

    def test_historical_complete_literal_maps_remain_qualified(self):
        old, documented, reused = QUALIFIED_MAPS[:3]
        self.assertEqual(len(old), 9)
        for later in (documented, reused):
            self.assertEqual(set(old), set(later))
            self.assertEqual(
                [name for name in old if old[name] != later[name]], ["mcts.py"]
            )
        self.assertEqual(
            old["mcts.py"],
            "86902c63ed6a2f5bb8acb26413167947dbf2687bf4e7dfb911743851be35c04d",
        )
        self.assertEqual(
            documented["mcts.py"],
            "4cadf249dee661a535cd2d7eae0c9009caf91da88de69550292ca75b04b3c8ca",
        )
        self.assertEqual(
            reused["mcts.py"],
            "2a53a16dc96dfaba6ed408a54598bfb61257fe42194d8cf828e11db68761c927",
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

    def test_managed_map_retains_all_eight_qualified_canonical_dependencies(self):
        prior = report.QUALIFIED_CANONICAL_ROOT_ALLOCATION_ENGINE_FILES_SHA256
        current = report.QUALIFIED_CANONICAL_MANAGED_ROOT_ALLOCATION_ENGINE_FILES_SHA256
        self.assertEqual(set(current), set(prior))
        self.assertEqual(len(current), 9)
        self.assertEqual([name for name in prior if prior[name] != current[name]],
                         ["decider.py"])
        self.assertEqual(current["decider.py"],
                         "a9a98022b1bad9db04bcb649aeb110c609f81347155820a566deb3abf3582ac5")
        self.assertEqual(report.MODEL, "independent_one_round_binary53_shaped_v1")
        self.assertEqual(report.THREE_ENEMY_MODEL,
                         "independent_one_round_three_enemy_binary53_shaped_v1")

    def canonical_bodies(self):
        directory = Path(__file__).resolve().parents[1] / "engine"
        return {
            name: (directory / name).read_bytes().replace(b"\r\n", b"\n")
            for name in EXACT_HALF_MAPS[0]
        }

    def historical_rules(self):
        fixture = Path(__file__).with_name("fixtures") / "pre-exact-half-rules.json"
        saved = json.loads(fixture.read_bytes())
        self.assertEqual({key: value for key, value in saved.items()
                          if key != "source_base64"}, {
            "format": "mcts-literal-historical-source", "schema_version": 1,
            "source_commit": "6f1a870307f62cd73634fcbf5603781734151136",
            "source_path": "engine/rules.py",
            "git_blob": "6bdace99b22228524bf0b0a69f2d6dfd0721ba23",
            "bytes": 2590,
            "sha256": (
                "ce82da2e1815dcdb7f4814012fae0c064152e3ad43c7da43743b2d50b5db588b"),
        })
        body = base64.b64decode(saved["source_base64"], validate=True)
        self.assertEqual(len(body), saved["bytes"])
        self.assertEqual(hashlib.sha256(body).hexdigest(), saved["sha256"])
        self.assertEqual(hashlib.sha1(
            b"blob " + str(len(body)).encode("ascii") + b"\0" + body
        ).hexdigest(), saved["git_blob"])
        self.assertNotIn(b"\r", body)
        return body

    def assert_source_projection(self, canonical_bodies, canonical_map, frozen_map):
        self.assertEqual({name: hashlib.sha256(body).hexdigest()
                          for name, body in canonical_bodies.items()}, canonical_map)
        # Only this explicitly pinned CRLF projection is qualified. The live
        # admission predicate still compares complete literal maps unchanged.
        frozen_bodies = {name: body.replace(b"\n", b"\r\n")
                         for name, body in canonical_bodies.items()}
        self.assertEqual({name: hashlib.sha256(body).hexdigest()
                          for name, body in frozen_bodies.items()}, frozen_map)
        for name, frozen in frozen_bodies.items():
            with self.subTest(member=name):
                canonical = canonical_bodies[name]
                self.assertEqual(frozen.replace(b"\r\n", b"\n"), canonical)
                if name.endswith(".py"):
                    frozen_ast = ast.dump(ast.parse(frozen.decode("utf-8")),
                                          include_attributes=False)
                    canonical_ast = ast.dump(ast.parse(canonical.decode("utf-8")),
                                             include_attributes=False)
                    self.assertEqual(frozen_ast, canonical_ast)

    def test_frozen_windows_map_has_one_exact_declared_source_conversion(self):
        historical = self.canonical_bodies()
        historical["rules.py"] = self.historical_rules()
        self.assert_source_projection(historical, *MANAGED_MAPS)

    def test_exact_half_maps_bind_current_source_and_one_predicate_change(self):
        canonical = self.canonical_bodies()
        self.assert_source_projection(canonical, *EXACT_HALF_MAPS)
        old = self.historical_rules()
        old_predicate = b"enemy.hp < enemy.max_hp // 2"
        new_predicate = b"2 * enemy.hp < enemy.max_hp"
        self.assertEqual(old.count(old_predicate), 1)
        self.assertEqual(canonical["rules.py"], old.replace(
            old_predicate, new_predicate))
        for prior, current in zip(MANAGED_MAPS, EXACT_HALF_MAPS, strict=True):
            self.assertEqual(set(prior), set(current))
            self.assertEqual(len(current), 9)
            self.assertEqual([name for name in prior if prior[name] != current[name]],
                             ["rules.py"])
        observed = consumer.reference_identity()["decision_consumer"][
            "engine_files_sha256"]
        self.assertIn(observed, EXACT_HALF_MAPS)
        self.assertTrue(report.qualified_engine_files(observed))

    def test_managed_maps_refuse_any_changed_missing_extra_or_mixed_member(self):
        for admitted in MANAGED_MAPS + EXACT_HALF_MAPS:
            for name in admitted:
                changed = copy.deepcopy(admitted)
                changed[name] = "a" * 64
                with self.subTest(map=admitted["decider.py"], member=name):
                    self.assertFalse(report.qualified_engine_files(changed))
            for name in admitted:
                missing = copy.deepcopy(admitted)
                del missing[name]
                self.assertFalse(report.qualified_engine_files(missing))
            extra = {**admitted, "unqualified.py": "b" * 64}
            self.assertFalse(report.qualified_engine_files(extra))
        for admitted, other in permutations(MANAGED_MAPS + EXACT_HALF_MAPS, 2):
            for name in admitted:
                if admitted[name] == other[name]:
                    continue
                mixed = {**admitted, name: other[name]}
                # Replacing the sole changed rules member can recreate a whole
                # separately qualified historical map. Only unknown mixtures
                # are refused; a recognized complete map remains admissible.
                self.assertEqual(report.qualified_engine_files(mixed),
                                 mixed in QUALIFIED_MAPS)

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
        for admitted, other in permutations(QUALIFIED_MAPS, 2):
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
        for admitted, other in permutations(QUALIFIED_MAPS, 2):
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

    def test_unknown_maps_are_refused_before_any_evaluator(self):
        before = (self.decision_path.read_bytes(), self.state_path.read_bytes())
        for name, unknown in unqualified_maps():
            observed = consumer.reference_identity()
            observed["decision_consumer"]["engine_files_sha256"] = unknown
            with (
                self.subTest(change=name, map=unknown),
                patch.object(consumer, "reference_identity", return_value=observed),
                patch.object(one_round, "evaluate", side_effect=AssertionError) as one,
                patch.object(adaptive, "evaluate", side_effect=AssertionError) as two,
                patch.object(aggregation, "evaluate",
                             side_effect=AssertionError) as three,
            ):
                results = (
                    consumer.reference_decision(self.decision_path),
                    consumer.reference_decision(
                        self.state_path,
                        model=adaptive_report.MODEL,
                        method=adaptive_report.METHOD,
                        state_input=True,
                    ),
                    consumer.reference_decision(
                        self.decision_path, method=aggregation_domain.METHOD),
                )
                for result in results:
                    self.assertEqual(result["status"], "refused")
                    self.assertEqual(result["failure"]["kind"], "engine_mismatch")
                    self.assertIsNone(result["evaluation"])
                    self.assertIsNone(result["diagnostics"])
                    self.assertFalse(result["new_search_performed"])
                one.assert_not_called()
                two.assert_not_called()
                three.assert_not_called()
        self.assertEqual(
            (self.decision_path.read_bytes(), self.state_path.read_bytes()), before
        )

    def test_each_qualified_map_reaches_each_existing_calculation_path(self):
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

    def test_exact_half_maps_do_not_admit_boss_rules_to_any_reference(self):
        rule = {"type": "enrage_below_half", "parameters": {"blade": 0.25},
                "description": EnrageBelowHalf().description}
        decision = literal_decision()
        decision["selected_state"]["boss_rules"] = [copy.deepcopy(rule)]
        state = adaptation_state()
        state["boss_rules"] = [copy.deepcopy(rule)]
        self.decision_path.write_bytes(records.output_bytes(decision))
        self.state_path.write_bytes(records.output_bytes(state))
        before = (self.decision_path.read_bytes(), self.state_path.read_bytes())
        for admitted in EXACT_HALF_MAPS:
            observed = consumer.reference_identity()
            observed["decision_consumer"]["engine_files_sha256"] = copy.deepcopy(
                admitted)
            with patch.object(consumer, "reference_identity", return_value=observed):
                results = (
                    consumer.reference_decision(self.decision_path),
                    consumer.reference_decision(
                        self.decision_path, method=aggregation_domain.METHOD),
                    consumer.reference_decision(
                        self.state_path, model=adaptive_report.MODEL,
                        method=adaptive_report.METHOD, state_input=True,
                        **ADAPTIVE_LIMITS),
                )
            for result in results:
                self.assertEqual(result["status"], "refused")
                self.assertEqual(result["failure"]["kind"], "unsupported_state")
                self.assertIn("boss_rules", result["failure"]["message"])
                self.assertIsNone(result["evaluation"])
                self.assertIsNone(result["diagnostics"])
                self.assertFalse(result["new_search_performed"])
        self.assertEqual(
            (self.decision_path.read_bytes(), self.state_path.read_bytes()), before)


if __name__ == "__main__":
    unittest.main()
