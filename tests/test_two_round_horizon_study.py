"""Study accounting and joins, with independent literal arithmetic controls."""

import copy
import json
import tempfile
import unittest
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from game import episode_record as records
from reference import adaptive_report, consumer
from tools import two_round_horizon_study as study


class TwoRoundHorizonStudyTests(unittest.TestCase):
    def setUp(self):
        self.state = json.loads((study.DATA / "inputs.json").read_bytes())["cases"][
            "E1"
        ]

    def reference(self, state):
        with tempfile.TemporaryDirectory(prefix="mcts-horizon-test-") as directory:
            path = Path(directory) / "state.json"
            path.write_bytes(study.encoded(state))
            return consumer.reference_decision(
                path,
                model=adaptive_report.MODEL,
                method=adaptive_report.METHOD,
                state_input=True,
                max_transitions=10000,
                max_per_action=2500,
                max_work_units=25000,
                max_seconds=10,
            )

    def test_public_model_and_both_actual_work_counts_preserve_root(self):
        state = study.construct_state(self.state)
        before = records.canonical(records.normalized(state))
        # Deliberately invented all-tie prices test accounting, not real values.
        values = {
            (None, None): Fraction(0),
            (0, 0): Fraction(0),
            (1, 0): Fraction(0),
            (2, None): Fraction(0),
        }
        for horizon, expected_simulations in ((1, 64), (2, 32)):
            cell = study.collect_one(state, 19, horizon, values)
            self.assertEqual(cell["simulations"], expected_simulations)
            self.assertEqual(cell["transitions"], 64)
            self.assertEqual(cell["counted_advance_round_calls"], 64)
            self.assertEqual(cell["unused_transitions"], 0)
            self.assertEqual(study.fraction(cell["loss"]), 0)
        self.assertEqual(records.canonical(records.normalized(state)), before)

    def test_complete_oracle_join_rejects_different_root_without_search(self):
        reference = self.reference(self.state)
        prior = study.encoded(reference)
        values = study.price_actions(reference, self.state)
        self.assertEqual(set(values), {(None, None), (0, 0), (1, 0), (2, None)})
        changed = copy.deepcopy(self.state)
        changed["player"]["hp"] += 1
        with patch.object(study, "MCTS", side_effect=AssertionError("search")):
            with self.assertRaisesRegex(ValueError, "root differs"):
                study.price_actions(reference, changed)
        self.assertEqual(study.encoded(reference), prior)

    def test_complete_first_terminal_support_refuses_equal_work_admission(self):
        changed = copy.deepcopy(self.state)
        changed["enemies"][0]["hp"] = 1
        reference = self.reference(changed)
        self.assertEqual(reference["status"], "complete")
        with patch.object(study, "MCTS", side_effect=AssertionError("search")):
            with self.assertRaisesRegex(ValueError, "first-round branch is terminal"):
                study.price_actions(reference, changed)

    def test_unknown_selected_physical_action_is_not_imputed(self):
        state = study.construct_state(self.state)
        with self.assertRaisesRegex(ValueError, "unknown selected physical action"):
            study.collect_one(state, 19, 1, {(None, 999): Fraction(0)})

    def test_unknown_engine_refuses_before_oracle_or_search(self):
        observed = consumer.reference_identity()
        observed["decision_consumer"]["engine_files_sha256"]["mcts.py"] = "a" * 64
        with tempfile.TemporaryDirectory(prefix="mcts-horizon-source-") as directory:
            output = Path(directory) / "not-admitted"
            with (
                patch.object(consumer, "reference_identity", return_value=observed),
                patch.object(
                    consumer, "reference_decision", side_effect=AssertionError
                ),
                patch.object(study, "MCTS", side_effect=AssertionError),
            ):
                with self.assertRaisesRegex(ValueError, "unqualified engine"):
                    study.run("exploratory", output)
            self.assertFalse(output.exists())

    def test_rational_enclosures_against_independent_decimal_operations(self):
        with localcontext() as context:
            context.prec = 90
            bound = study.logarithm_upper()
            observed = Decimal(bound.numerator) / Decimal(bound.denominator)
            expected = Decimal(80).ln()
            self.assertGreaterEqual(observed, expected)
            self.assertLess(observed - expected, Decimal("1e-37"))
            for literal in ("0", "1", "2", "0.125"):
                value = Fraction(literal)
                bound = study.sqrt_upper(value)
                observed = Decimal(bound.numerator) / Decimal(bound.denominator)
                expected = Decimal(literal).sqrt()
                self.assertGreaterEqual(observed, expected)
                self.assertLessEqual(observed - expected, Decimal("1e-18"))

    def test_primary_block_unit_and_unbiased_variance_from_literal_table(self):
        cells = []
        for block, losses in enumerate(((1, 0), (0, 1))):
            for horizon, loss in enumerate(losses, 1):
                cells.append(
                    {
                        "block": block,
                        "case": "synthetic",
                        "horizon": horizon,
                        "loss": study.ratio(Fraction(loss)),
                    }
                )
        summary = study.summarize(
            cells, ["synthetic"], 2, {"synthetic": {(None, None): Fraction(0)}}
        )
        self.assertEqual(study.fraction(summary["mean_difference"]), 0)
        self.assertEqual(study.fraction(summary["sample_variance"]), 2)
        self.assertEqual(summary["positive_zero_negative_blocks"], [1, 0, 1])
        self.assertEqual(
            summary["direction_under_declared_assumptions"], "inconclusive"
        )
        self.assertEqual(study.fraction(summary["interval"]["lower"]), -1)
        self.assertEqual(study.fraction(summary["interval"]["upper"]), 1)


if __name__ == "__main__":
    unittest.main()
