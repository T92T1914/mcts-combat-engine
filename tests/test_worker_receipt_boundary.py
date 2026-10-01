"""Malformed fixed-worker actions must retain the incomplete-work report."""

import unittest
from dataclasses import replace
from unittest.mock import patch

from engine.actions import Action, is_legal_action
from engine.parallel import (
    ParallelMCTS,
    ParallelSearchError,
    WorkerJob,
    _fixed_search,
    worker_seed,
)
from engine.state import Card, Combatant, Element, GameState


def position():
    return GameState(
        Combatant("P", Element.EMBER, 1000, 1000),
        [Combatant("E", Element.EMBER, 1000, 1000, policy={"shield": 1})],
        [Card("First", accuracy=1.0), Card("Second", accuracy=1.0)],
    )


class WorkerReceiptBoundaryTests(unittest.TestCase):
    def assert_invalid_receipt(self, root, receipt):
        original = root.clone()
        engine = ParallelMCTS(horizon_rounds=1, workers=1)
        rng_before = engine._rng.getstate()
        with (
            patch("engine.parallel._fixed_search", return_value=receipt) as worker,
            patch.object(engine, "_ensure_pool") as pool,
            patch.object(engine, "_search_single") as fallback,
            self.assertRaises(ParallelSearchError) as caught,
        ):
            engine.search(root, mode="fixed", max_sims=1, seed=4)
        worker.assert_called_once()
        pool.assert_not_called()
        fallback.assert_not_called()
        report = caught.exception.report
        self.assertIs(report, engine.last_report)
        self.assertFalse(report.complete)
        self.assertIsNone(report.simulations)
        self.assertIsNone(report.transitions)
        self.assertIsNone(report.unused_simulations)
        self.assertEqual(report.known_simulations, 0)
        self.assertEqual(report.known_transitions, 0)
        self.assertEqual(report.workers[0].status, "unreported")
        self.assertEqual(report.workers[0].error, "InvalidWorkerReceipt")
        self.assertEqual(engine._rng.getstate(), rng_before)
        self.assertEqual(root, original)

    def test_numeric_aliases_are_not_legal_worker_actions(self):
        root = position()
        job = WorkerJob(0, root, 1, worker_seed(4, 0), 1, None, None)
        valid = _fixed_search(job)
        # These compare equal to Action(1, 0), but are not valid index types.
        for action in (Action(True, 0), Action(1.0, 0),
                       Action(1, False), Action(1, 0.0)):
            with self.subTest(action=action):
                self.assertEqual(action, Action(1, 0))
                self.assertFalse(is_legal_action(root, action))
                bad = replace(valid, statistics=((action, 1, 0.5),))
                self.assert_invalid_receipt(root, bad)

    def test_unrepresentable_value_sum_is_an_invalid_receipt(self):
        root = position()
        job = WorkerJob(0, root, 1, worker_seed(4, 0), 1, None, None)
        valid = _fixed_search(job)
        bad = replace(valid, statistics=((Action(None), 1, 10 ** 1000),))
        self.assert_invalid_receipt(root, bad)

    def test_valid_integer_actions_keep_exact_statistics_and_state(self):
        root = position()
        original = root.clone()
        engine = ParallelMCTS(horizon_rounds=1, workers=1)
        with patch.object(engine, "_ensure_pool") as pool:
            ranked = engine.search(root, mode="fixed", max_sims=3, seed=4)
        pool.assert_not_called()
        self.assertTrue(engine.last_report.complete)
        self.assertEqual(engine.last_report.simulations, 3)
        self.assertEqual(engine.last_report.transitions, 3)
        self.assertEqual(sum(row.visits for row in ranked), 3)
        self.assertTrue(all(is_legal_action(root, row.action) for row in ranked))
        reference = _fixed_search(
            WorkerJob(0, root, 1, worker_seed(4, 0), 3, None, None)
        )
        self.assertEqual(engine.last_report.workers[0].statistics,
                         reference.statistics)
        self.assertEqual(root, original)


if __name__ == "__main__":
    unittest.main()
