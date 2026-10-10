"""Saved-decision consumer and output failures preserve complete-report boundaries.

The input envelope is synthetic fixture data. Its search is real and bounded, but
these tests do not claim that an environment recorded or replayed the episode.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_episode_decision import synthetic_record
from test_one_round_reference import card, modeled_state

import reference_episode
from engine import MCTS, simulator
from game.episode_decision import episode_decision
from game.episode_record import EpisodeInputError, canonical, output_bytes
from reference import consumer, one_round
from reference import report as reports


def synthetic_supported_record():
    """Supply a supported literal state without claiming environment provenance."""
    record = synthetic_record()
    initial = modeled_state([card()])
    record["initial_state"] = copy.deepcopy(initial)
    record["scenario"]["deck"] = copy.deepcopy(initial["hand"])
    for index, step in enumerate(record["steps"]):
        state = copy.deepcopy(initial)
        state["round_num"] = index + 1
        step["state"] = state
        step["action"] = {
            "card_idx": 0,
            "target_idx": 0,
            "label": "Synthetic retained action",
        }
    final = copy.deepcopy(initial)
    final["round_num"] = len(record["steps"]) + 1
    record["final"]["state"] = final
    return record


class ShortSink:
    def __init__(self):
        self.data = io.BytesIO()

    def write(self, value):
        return self.data.write(value[:-1])

    def flush(self):
        pass


class FlushFailureSink:
    def __init__(self):
        self.data = io.BytesIO()

    def write(self, value):
        return self.data.write(value)

    def flush(self):
        raise OSError("controlled output flush failure")


class ReferenceConsumerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.episode = self.root / "synthetic-episode.json"
        self.decision = self.root / "saved-decision.json"
        self.episode.write_bytes(canonical(synthetic_supported_record()) + b"\n")
        search = episode_decision(
            self.episode, step=0, sims=4, horizon=1, final_action_rule="mean_visits"
        )
        self.decision.write_bytes(output_bytes(search))

    def assert_refusal(self, result, kind):
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["failure"]["kind"], kind)
        self.assertIsNone(result["evaluation"])
        self.assertIsNone(result["diagnostics"])
        self.assertFalse(result["new_search_performed"])
        reports.validate_reference_report(result)

    def cli(self, arguments, *, sink=None):
        output = io.BytesIO() if sink is None else sink
        errors = io.StringIO()
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
        captured = output.getvalue() if sink is None else sink.data.getvalue()
        return status, captured, errors.getvalue()

    def test_complete_uses_saved_state_without_search_and_preserves_both_inputs(self):
        before_episode = self.episode.read_bytes()
        before_decision = self.decision.read_bytes()
        with (
            patch.object(
                MCTS, "search", side_effect=AssertionError("unexpected search")
            ),
            patch.object(
                simulator,
                "advance_round",
                side_effect=AssertionError("unexpected environment transition"),
            ),
        ):
            result = consumer.reference_decision(self.decision)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["evaluation"]["total_leaves"], 2)
        self.assertEqual(len(result["evaluation"]["actions"]), 2)
        self.assertEqual(
            result["source_report"]["sha256"],
            hashlib.sha256(before_decision).hexdigest(),
        )
        self.assertFalse(result["new_search_performed"])
        self.assertEqual(
            result["decision_report"]["selected_state"], modeled_state([card()])
        )
        self.assertEqual(self.episode.read_bytes(), before_episode)
        self.assertEqual(self.decision.read_bytes(), before_decision)
        reports.validate_reference_report(result)

    def test_genuine_whole_action_cap_refuses_without_accepting_first_action(self):
        result = consumer.reference_decision(self.decision, max_total_paths=1)
        self.assert_refusal(result, "work_limit")
        self.assertEqual(result["limits"]["max_total_paths"], 1)

    def test_horizon_and_engine_mismatch_are_refused_before_arithmetic(self):
        search = episode_decision(
            self.episode, step=0, sims=4, horizon=2, final_action_rule="mean_visits"
        )
        other_horizon = self.root / "two-round-decision.json"
        other_horizon.write_bytes(output_bytes(search))
        with patch.object(
            one_round,
            "evaluate",
            side_effect=AssertionError("mismatched horizon reached arithmetic"),
        ) as evaluate:
            result = consumer.reference_decision(other_horizon)
        self.assert_refusal(result, "horizon_mismatch")
        evaluate.assert_not_called()

        observed = consumer.reference_identity()
        observed["decision_consumer"]["engine_files_sha256"]["state.py"] = "a" * 64
        with (
            patch.object(consumer, "reference_identity", return_value=observed),
            patch.object(
                one_round,
                "evaluate",
                side_effect=AssertionError("mismatched engine reached arithmetic"),
            ) as evaluate,
        ):
            result = consumer.reference_decision(self.decision)
        self.assert_refusal(result, "engine_mismatch")
        evaluate.assert_not_called()

    def test_controlled_failure_outcomes_discard_all_evaluation_values(self):
        for error, kind in (
            (
                one_round.UnsupportedState("controlled unsupported mechanic"),
                "unsupported_state",
            ),
            (
                one_round.ReferenceLimitExceeded("controlled complete-action limit"),
                "work_limit",
            ),
            (MemoryError("controlled allocation failure"), "runtime_failure"),
            (KeyboardInterrupt(), "interrupted"),
        ):
            with self.subTest(kind=kind):
                with patch.object(one_round, "evaluate", side_effect=error) as evaluate:
                    result = consumer.reference_decision(self.decision)
                self.assert_refusal(result, kind)
                evaluate.assert_called_once()

    def test_failed_post_work_identity_observation_discards_complete_values(self):
        observed = consumer.reference_identity()
        with (
            patch.object(
                consumer,
                "reference_identity",
                side_effect=[
                    observed,
                    OSError("controlled identity observation failure"),
                ],
            ),
            patch.object(one_round, "evaluate", wraps=one_round.evaluate) as evaluate,
        ):
            result = consumer.reference_decision(self.decision)
        evaluate.assert_called_once()
        self.assert_refusal(result, "identity_changed")

    def test_invalid_controls_and_bad_saved_input_are_input_errors(self):
        for limits in (
            {"max_paths": True},
            {"max_paths": 0},
            {"max_total_paths": False},
            {"max_total_paths": 1000001},
            {"max_seconds": True},
            {"max_seconds": float("nan")},
            {"max_seconds": float("inf")},
            {"max_seconds": 0},
        ):
            with self.subTest(limits=limits):
                with patch.object(
                    one_round,
                    "evaluate",
                    side_effect=AssertionError("invalid controls reached arithmetic"),
                ) as evaluate:
                    with self.assertRaises(EpisodeInputError):
                        consumer.reference_decision(self.decision, **limits)
                evaluate.assert_not_called()
        bad = self.root / "invalid-decision.json"
        for content in (b"\xff", b"true", b'{"format":"unknown"}', b'{"bad":NaN}'):
            with self.subTest(content=content):
                bad.write_bytes(content)
                with self.assertRaises(EpisodeInputError):
                    consumer.reference_decision(bad)

    def test_cli_delivers_complete_refused_interrupted_and_input_error_statuses(self):
        status, captured, errors = self.cli([str(self.decision)])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(captured)["status"], "complete")
        self.assertEqual(errors, "")

        status, captured, errors = self.cli(
            [str(self.decision), "--max-total-paths", "1"]
        )
        self.assertEqual(status, 1)
        self.assert_refusal(json.loads(captured), "work_limit")
        self.assertIn("episode reference:", errors)

        with patch.object(one_round, "evaluate", side_effect=KeyboardInterrupt):
            status, captured, errors = self.cli([str(self.decision)])
        self.assertEqual(status, 130)
        self.assert_refusal(json.loads(captured), "interrupted")
        self.assertIn("interrupted", errors)

        status, captured, errors = self.cli(
            [str(self.decision), "--max-seconds", "nan"]
        )
        self.assertEqual(status, 2)
        self.assertEqual(captured, b"")
        self.assertIn("max_seconds", errors)

    def test_passive_inspection_and_comparison_call_no_reference_search_or_transition(
        self,
    ):
        result = consumer.reference_decision(self.decision)
        left = self.root / "saved-reference.json"
        right = self.root / "same-reference.json"
        left.write_bytes(output_bytes(result))
        right.write_bytes(output_bytes(result))
        before = (left.read_bytes(), right.read_bytes())
        with (
            patch.object(
                one_round,
                "evaluate",
                side_effect=AssertionError("passive reader recomputed"),
            ) as evaluate,
            patch.object(
                MCTS, "search", side_effect=AssertionError("passive reader searched")
            ) as search,
            patch.object(
                simulator,
                "advance_round",
                side_effect=AssertionError("passive reader transitioned"),
            ) as transition,
        ):
            status, inspection, errors = self.cli([str(left), "--inspect"])
            self.assertEqual((status, errors), (0, ""))
            self.assertIn(b"One-round reference inspection", inspection)
            self.assertIn(b"Saved choice and value loss", inspection)
            status, comparison, errors = self.cli(
                [str(left), "--inspect", "--compare-report", str(right)]
            )
            self.assertEqual((status, errors), (0, ""))
            self.assertIn(b"One-round reference comparison", comparison)
            evaluate.assert_not_called()
            search.assert_not_called()
            transition.assert_not_called()
        self.assertEqual((left.read_bytes(), right.read_bytes()), before)

    def test_cli_short_write_and_flush_failure_cannot_report_delivery_success(self):
        for sink in (ShortSink(), FlushFailureSink()):
            with self.subTest(sink=type(sink).__name__):
                status, captured, errors = self.cli([str(self.decision)], sink=sink)
                self.assertEqual(status, 1)
                self.assertTrue(captured)
                self.assertIn("episode reference:", errors)
                if isinstance(sink, ShortSink):
                    self.assertIn("incomplete document", errors)
                else:
                    self.assertIn("controlled output flush failure", errors)

    def test_cli_rejects_ambiguous_inspection_controls_before_any_calculation(self):
        for controls in (
            ["--inspect", "--max-seconds", "1"],
            ["--compare-report", str(self.decision)],
            ["--appearance", "clair"],
        ):
            with self.subTest(controls=controls):
                with patch.object(
                    one_round,
                    "evaluate",
                    side_effect=AssertionError("bad CLI reached arithmetic"),
                ) as evaluate:
                    status, captured, errors = self.cli([str(self.decision), *controls])
                self.assertEqual(status, 2)
                self.assertEqual(captured, b"")
                self.assertTrue(errors)
                evaluate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
