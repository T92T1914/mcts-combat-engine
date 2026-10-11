"""Adaptive consumers retain source identity and reject inconsistent saved math.

The fixtures are explicitly modeled inputs. They do not claim recorded episode
provenance. Manual adaptation values come from the accepted qualification.
"""

from __future__ import annotations

import builtins
import copy
import hashlib
import io
import json
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_episode_inspection import Artifact
from test_one_round_reference import card, fighter, modeled_state
from test_reference_consumer import FlushFailureSink, ShortSink
from test_reference_report import literal_decision, literal_report

import reference_episode
from engine import MCTS, simulator
from game import episode_record as records
from game.episode_inspection import InspectionRuntimeError
from reference import adaptive, adaptive_report, consumer, one_round, report


def adaptation_state():
    return modeled_state(
        [
            card(name="Variable hit", damage_min=1, damage_max=2),
            card(name="Fixed hit", damage_min=1, damage_max=1),
        ],
        enemies=[
            fighter(
                "Enemy",
                hp=3,
                base_attack=card(
                    name="Plain response",
                    element="neutral",
                    pip_cost=7,
                    damage_min=1,
                    damage_max=1,
                ),
            )
        ],
    )


def modeled_decision(*, version=2, no_work=False):
    value = literal_decision(version=version, no_work=no_work)
    value["selected_state"] = adaptation_state()
    value["configuration"]["horizon_rounds"] = 2
    value["configuration"]["max_transitions"] = value["configuration"]["max_sims"] * 2
    value["work"]["unused_transitions"] = (
        value["configuration"]["max_transitions"] - value["work"]["transitions"]
    )
    for row in value["legal_actions"]:
        if row["card_idx"] is not None:
            row["target_idx"] = 0
            row["label"] = value["selected_state"]["hand"][row["card_idx"]]["name"]
    for action in value["ranking"]:
        if action["card_idx"] is not None:
            action["target_idx"] = 0
    if version == 2:
        for action in value["root_encounter_order"]:
            if action["card_idx"] is not None:
                action["target_idx"] = 0
    return value


def rational(value):
    return Fraction(int(value["numerator"]), int(value["denominator"]))


class AdaptiveConsumerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mcts-adaptive-consumer-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.state_path = self.directory / "private-modeled-state.json"
        self.decision_path = self.directory / "private-saved-decision.json"
        self.state_path.write_bytes(records.output_bytes(adaptation_state()))
        self.decision_path.write_bytes(records.output_bytes(modeled_decision()))

    def calculate(self, *, path=None, state_input=True, **controls):
        return consumer.reference_decision(
            self.state_path if path is None else path,
            model=adaptive_report.MODEL,
            method=adaptive_report.METHOD,
            state_input=state_input,
            **controls,
        )

    def assert_refused(self, value, kind):
        self.assertEqual(value["status"], "refused")
        self.assertEqual(value["failure"]["kind"], kind)
        self.assertIsNone(value["evaluation"])
        self.assertIsNone(value["diagnostics"])
        self.assertFalse(value["new_search_performed"])
        self.assertIs(report.validate_reference_report(value), value)

    def cli(self, *arguments, sink=None):
        output = io.BytesIO() if sink is None else sink
        errors = io.StringIO()
        with (
            patch.object(
                reference_episode.sys, "stdout", SimpleNamespace(buffer=output)
            ),
            patch.object(reference_episode.sys, "stderr", errors),
        ):
            try:
                status = reference_episode.main(list(arguments))
            except SystemExit as exc:
                status = exc.code
        return (
            status,
            output.getvalue() if sink is None else sink.data.getvalue(),
            errors.getvalue(),
        )

    def test_direct_state_complete_manual_witness_without_search_or_engine_replay(self):
        before = self.state_path.read_bytes()
        with (
            patch.object(
                MCTS, "search", side_effect=AssertionError("unexpected search")
            ),
            patch.object(
                simulator,
                "advance_round",
                side_effect=AssertionError("unexpected engine replay"),
            ),
            patch.object(
                one_round,
                "evaluate",
                side_effect=AssertionError("unexpected one-round root scoring"),
            ),
        ):
            result = self.calculate()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["format"], adaptive_report.FORMAT)
        self.assertIsNone(result["decision_report"])
        self.assertEqual(result["source_report"]["kind"], "normalized-state")
        self.assertEqual(
            result["source_report"]["sha256"], hashlib.sha256(before).hexdigest()
        )
        self.assertEqual(result["selected_state"], adaptation_state())
        self.assertIsNone(result["diagnostics"]["recommendation"])
        self.assertEqual(self.state_path.read_bytes(), before)
        evaluation = result["evaluation"]
        self.assertEqual(
            [rational(row["value"]) for row in evaluation["actions"]],
            [
                Fraction(17879290520660869, 18014398509481984),
                Fraction(8962163258467287, 9007199254740992),
                Fraction(4458563631096791, 4503599627370496),
            ],
        )
        self.assertEqual(evaluation["optimal_actions"], [1])
        choices = {
            row["state"]["enemies"][0]["hp"]: row["chosen"]
            for row in evaluation["actions"][1]["observations"]
        }
        self.assertEqual(choices, {2: 1, 1: 0})
        for observation in evaluation["actions"][1]["observations"]:
            self.assertEqual(observation["root_hand_indices"], [1])
            self.assertEqual(observation["continuations"][1]["root_card_idx"], 1)
        self.assertEqual(evaluation["work"]["transition_leaves"], 15)
        self.assertEqual(evaluation["work"]["work_units"], 34)

    def test_saved_choice_has_exact_root_expectation_loss_and_preserved_controls(self):
        before = self.decision_path.read_bytes()
        for version in (1, 2):
            saved = modeled_decision(version=version)
            self.decision_path.write_bytes(records.output_bytes(saved))
            result = self.calculate(path=self.decision_path, state_input=False)
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["decision_report"], saved)
            selected = result["diagnostics"]["recommendation"]
            self.assertEqual(selected["action"], {"card_idx": None, "target_idx": None})
            self.assertEqual(
                rational(selected["expected_value"]),
                rational(result["evaluation"]["actions"][0]["value"]),
            )
            self.assertEqual(
                rational(selected["value_loss"]),
                rational(result["evaluation"]["best_value"])
                - rational(selected["expected_value"]),
            )
            self.assertFalse(selected["reference_best"])
            if version == 1:
                self.assertIsNone(result["diagnostics"]["same_statistics"])
            else:
                self.assertEqual(
                    set(result["diagnostics"]["same_statistics"]),
                    {"mean_visits", "visits_mean"},
                )
        self.decision_path.write_bytes(before)

    def test_no_work_saved_decision_retains_no_selected_choice(self):
        self.decision_path.write_bytes(
            records.output_bytes(modeled_decision(no_work=True))
        )
        result = self.calculate(path=self.decision_path, state_input=False)
        self.assertEqual(result["status"], "complete")
        self.assertIsNone(result["diagnostics"]["recommendation"])
        self.assertEqual(
            result["diagnostics"]["same_statistics"],
            {"mean_visits": None, "visits_mean": None},
        )

    def test_horizon_and_contradictory_saved_physical_set_refuse_before_math(self):
        for kind, mutate in (
            (
                "horizon_mismatch",
                lambda value: value["configuration"].update(
                    horizon_rounds=1, max_transitions=16
                ),
            ),
            (
                "unsupported_state",
                lambda value: value["legal_actions"][2].update(target_idx=None),
            ),
            ("unsupported_state", lambda value: value["legal_actions"].reverse()),
        ):
            saved = modeled_decision()
            mutate(saved)
            if kind == "horizon_mismatch":
                saved["work"]["unused_transitions"] = 0
            self.decision_path.write_bytes(records.output_bytes(saved))
            with patch.object(
                adaptive,
                "evaluate",
                side_effect=AssertionError("unsupported input reached math"),
            ):
                self.assert_refused(
                    self.calculate(path=self.decision_path, state_input=False), kind
                )

    def test_work_deadline_and_supported_subset_refusals_have_no_partial_values(self):
        for controls in (
            {"max_transitions": 1},
            {"max_per_action": 1},
            {"max_work_units": 1},
            {"max_seconds": 1e-9},
        ):
            with self.subTest(controls=controls):
                self.assert_refused(self.calculate(**controls), "work_limit")
        for change in (
            lambda state: state["hand"].extend(copy.deepcopy(state["hand"])),
            lambda state: state["player"].update(hp=0),
            lambda state: state.update(round_num=31),
            lambda state: state["enemies"][0].update(base_attack=None),
            lambda state: state["player"]["resist"].update(ember=0.1),
            lambda state: state["hand"][0].update(damage_max=4),
        ):
            state = adaptation_state()
            change(state)
            self.state_path.write_bytes(records.output_bytes(state))
            self.assert_refused(self.calculate(), "unsupported_state")

    def test_exact_source_capture_once_identity_mismatch_and_drift(self):
        original_read = consumer._read
        with patch.object(consumer, "_read", wraps=original_read) as captured:
            result = self.calculate()
        self.assertEqual(captured.call_count, 1)
        self.assertEqual(result["status"], "complete")
        identity = consumer.reference_identity()
        mismatch = copy.deepcopy(identity)
        mismatch["decision_consumer"]["engine_files_sha256"]["simulator.py"] = "a" * 64
        with (
            patch.object(consumer, "reference_identity", return_value=mismatch),
            patch.object(
                adaptive,
                "evaluate",
                side_effect=AssertionError("mismatched engine reached math"),
            ),
        ):
            self.assert_refused(self.calculate(), "engine_mismatch")
        drift = copy.deepcopy(identity)
        drift["reference_files_sha256"]["reference/adaptive.py"] = "b" * 64
        with patch.object(
            consumer, "reference_identity", side_effect=[identity, drift]
        ):
            self.assert_refused(self.calculate(), "identity_changed")

    def test_cli_explicit_controls_binary_output_and_failed_sink(self):
        args = (
            str(self.state_path),
            "--state-input",
            "--model",
            "two-round-adaptive",
            "--method",
            "adaptive-physical",
        )
        status, output, errors = self.cli(
            *args,
            "--max-transitions",
            "100",
            "--max-per-action",
            "100",
            "--max-work-units",
            "100",
        )
        self.assertEqual((status, errors), (0, ""))
        self.assertTrue(output.endswith(b"\n"))
        self.assertNotIn(b"\r\n", output)
        result = json.loads(output)
        self.assertEqual(result["limits"]["max_work_units"], 100)
        self.assertEqual(len(output), len(records.output_bytes(result)))
        for suffix in (
            ("--max-paths", "10"),
            ("--max-contributions", "10"),
            ("--max-seconds", "0"),
            ("--max-work-units", "3000001"),
        ):
            with self.subTest(suffix=suffix):
                actual, captured, _ = self.cli(*args, *suffix)
                self.assertEqual((actual, captured), (2, b""))
        for incomplete in (
            (str(self.state_path), "--state-input"),
            (str(self.state_path), "--model", "two-round-adaptive"),
            (str(self.decision_path), "--max-transitions", "100"),
        ):
            self.assertEqual(self.cli(*incomplete)[:2], (2, b""))
        for sink in (ShortSink(), FlushFailureSink()):
            self.assertEqual(self.cli(*args, sink=sink)[0], 1)

    def test_passive_reads_preserve_fragments_escape_and_privacy(self):
        state = adaptation_state()
        state["hand"][0]["name"] = '<script src="https://invalid.test/x">&'
        self.state_path.write_bytes(records.output_bytes(state))
        result = self.calculate()
        saved = self.directory / "private-adaptive-reference.json"
        saved.write_bytes(records.output_bytes(result))
        before = saved.read_bytes()
        with (
            patch.object(
                adaptive, "evaluate", side_effect=AssertionError("passive math")
            ),
            patch.object(MCTS, "search", side_effect=AssertionError("passive search")),
            patch.object(
                simulator, "advance_round", side_effect=AssertionError("passive replay")
            ),
            patch.object(
                one_round,
                "_player_outcomes",
                side_effect=AssertionError("passive transition"),
            ),
        ):
            for appearance in ("obscur", "clair"):
                output = report.reference_inspection_html(saved, appearance)
                artifact = Artifact(output)
                self.assertEqual(
                    artifact.fragments["/evaluation"], result["evaluation"]
                )
                self.assertEqual(artifact.fragments["/selected_state"], state)
                self.assertIsNone(artifact.fragments["/decision_report"])
                self.assertIn(b"Exact optimal continuation indices", output)
                self.assertIn(b"&lt;script", output)
                self.assertNotIn(b"<script", output)
                self.assertNotIn(b"<iframe", output)
                self.assertNotIn(str(self.directory).encode(), output)
                self.assertNotIn(saved.name.encode(), output)
                self.assertIn(b"@media(max-width:420px)", output)
                self.assertIn(b"summary:focus-visible", output)
                self.assertLessEqual(len(output), records.RECORD_BYTES)
        self.assertEqual(saved.read_bytes(), before)
        self.assertEqual(
            self.cli(str(saved), "--inspect", "--state-input")[:2], (2, b"")
        )

    def test_nested_tampering_refuses_complete_report_without_recomputation(self):
        original = self.calculate()
        mutations = [
            lambda value: value.update(horizon_rounds=1),
            lambda value: value.update(probability_model="another-law"),
            lambda value: value.update(action_semantics="labels-only"),
            lambda value: value["limits"].update(max_transitions=99),
            lambda value: value["evaluation"]["actions"].pop(),
            lambda value: value["evaluation"]["optimal_actions"].append(0),
            lambda value: value["evaluation"]["work"].update(work_units=35),
            lambda value: value["evaluation"]["work"].update(cache_hits=True),
            lambda value: value["evaluation"]["work"][
                "per_action_transition_leaves"
            ].reverse(),
            lambda value: value["evaluation"]["actions"][1]["observations"].pop(),
            lambda value: value["evaluation"]["actions"][1]["observations"][0][
                "root_hand_indices"
            ].__setitem__(0, 0),
            lambda value: value["evaluation"]["actions"][1]["observations"][0][
                "continuations"
            ].pop(),
            lambda value: value["evaluation"]["actions"][1]["observations"][0][
                "continuations"
            ][1].update(root_card_idx=0),
            lambda value: value["evaluation"]["actions"][1]["observations"][0].update(
                chosen=0
            ),
            lambda value: value["evaluation"]["actions"][1]["observations"][0][
                "optimal_actions"
            ].append(0),
            lambda value: value["evaluation"]["actions"][1]["observations"][0][
                "probability"
            ].update(numerator="1", denominator="3"),
            lambda value: value["evaluation"]["actions"][1]["observations"][0][
                "probability"
            ].update(numerator="2", denominator="4"),
            lambda value: value["evaluation"]["actions"][1]["observations"][0]["state"][
                "player"
            ].update(power_pip_chance=0),
            lambda value: value["evaluation"]["actions"][1]["value"].update(
                numerator="0", denominator="1"
            ),
            lambda value: value["evaluation"]["actions"][1]["masses"]["cutoff"].update(
                numerator="0"
            ),
            lambda value: value["evaluation"]["actions"][1]["observations"].append(
                copy.deepcopy(value["evaluation"]["actions"][1]["observations"][0])
            ),
        ]
        with patch.object(
            adaptive, "evaluate", side_effect=AssertionError("passive recomputation")
        ):
            for index, mutate in enumerate(mutations):
                with self.subTest(index=index):
                    value = copy.deepcopy(original)
                    mutate(value)
                    with self.assertRaises(records.EpisodeInputError):
                        report.validate_reference_report(value)

    def test_terminal_observations_and_exact_ties_validate_with_separate_depth_masses(
        self,
    ):
        for state in (
            modeled_state(
                [card(damage_min=1, damage_max=1)],
                enemies=[
                    fighter(
                        "Enemy",
                        hp=1,
                        base_attack=card(pip_cost=7, damage_min=1, damage_max=1),
                    )
                ],
            ),
            modeled_state(
                [],
                player=fighter("Player", hp=1),
                enemies=[
                    fighter(
                        "Enemy",
                        pips=7,
                        base_attack=card(pip_cost=0, damage_min=1, damage_max=1),
                    )
                ],
            ),
            modeled_state(
                [card("heal", heal=1)],
                enemies=[
                    fighter(
                        "Enemy",
                        base_attack=card(pip_cost=7, damage_min=1, damage_max=1),
                    )
                ],
            ),
        ):
            self.state_path.write_bytes(records.output_bytes(state))
            value = self.calculate()
            self.assertEqual(value["status"], "complete")
            report.validate_reference_report(value)
            for row in value["evaluation"]["actions"]:
                self.assertEqual(
                    sum(rational(mass) for mass in row["masses"].values()), 1
                )

    def test_comparison_same_model_and_cross_family_boundaries_and_legacy_lazy_import(
        self,
    ):
        left = self.directory / "left.json"
        right = self.directory / "right.json"
        old = self.directory / "old.json"
        left.write_bytes(records.output_bytes(self.calculate()))
        right.write_bytes(records.output_bytes(self.calculate(max_work_units=100)))
        old_value = literal_report()
        old.write_bytes(records.output_bytes(old_value))
        with patch.object(
            adaptive, "evaluate", side_effect=AssertionError("comparison math")
        ):
            output = report.reference_comparison_html(left, right)
            self.assertIn(b"Comparison eligible</dt><dd>true", output)
            self.assertIn(b"no saved recommendation", output)
            self.assertEqual(
                Artifact(output).fragments["/left/evaluation"],
                json.loads(left.read_bytes())["evaluation"],
            )
            for first, second in ((left, old), (old, left)):
                output = report.reference_comparison_html(first, second)
                self.assertIn(b"reference_report_families_differ", output)
                self.assertIn(b"ineligible", output)
                self.assertNotIn(b"lower exact", output)
        original_import = builtins.__import__

        def isolated_import(name, *arguments, **options):
            if name in (
                "reference.adaptive",
                "reference.adaptive_report",
                "adaptive_report",
            ):
                raise AssertionError("legacy reader imported adaptive modules")
            return original_import(name, *arguments, **options)

        with patch.object(builtins, "__import__", side_effect=isolated_import):
            self.assertIs(report.validate_reference_report(old_value), old_value)
            report.reference_inspection_html(old)
            report.reference_comparison_html(old, old)

    def test_bounded_input_malformed_json_and_adaptive_html_size_refuse(self):
        with (
            patch.object(consumer, "RECORD_BYTES", 8),
            patch.object(
                consumer, "_parse", side_effect=AssertionError("oversize parse")
            ),
        ):
            with self.assertRaises(records.EpisodeInputError):
                self.calculate()
        for malformed in (b'{"player":{},"player":{}}', b"\xff", b"{"):
            self.state_path.write_bytes(malformed)
            with self.assertRaises(records.EpisodeInputError):
                self.calculate()
        document = adaptive_report._Document()
        with patch.object(records, "RECORD_BYTES", 8):
            document.add("1234567")
            self.assertEqual(document.finish(), b"1234567\n")
            with self.assertRaises(InspectionRuntimeError):
                document.add("x")


if __name__ == "__main__":
    unittest.main()
