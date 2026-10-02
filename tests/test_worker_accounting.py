"""Independent receipts exercise the fixed-work accounting boundary."""

import unittest
from dataclasses import replace
from fractions import Fraction
from unittest.mock import Mock, patch

from engine.actions import Action, legal_actions
from engine.parallel import (
    ParallelMCTS,
    ParallelSearchError,
    WorkerJob,
    WorkerReceipt,
    worker_seed,
)
from engine.state import Card, Combatant, Element, GameState


def position():
    return GameState(
        Combatant("P", Element.EMBER, 100, 100),
        [Combatant("E", Element.EMBER, 100, 100)],
        [Card("First", accuracy=1.0)],
    )


def completed(job):
    # Two completed two-round simulations, plus one unused transition.
    # These sufficient statistics are specified without running MCTS.
    return WorkerReceipt(
        job.worker_id, job.seed, 2, 5, "completed", 2, 4, 0, 1, 0,
        ("transition_allowance", "simulation_cap"),
        ((Action(None), 1, 0.25), (Action(0, 0), 1, 0.75)), 0.125,
    )


class WorkerAccountingTests(unittest.TestCase):
    def setUp(self):
        self.root = position()
        self.job = WorkerJob(0, self.root, 2, worker_seed(4, 0), 2, 5, None)
        self.receipt = completed(self.job)
        self.legal = set(legal_actions(self.root))

    def test_identity_and_allowances_require_integer_types_not_equal_aliases(self):
        aliases = (
            ("worker_id", False), ("worker_id", 0.0),
            ("seed", Fraction(self.job.seed, 1)),
            ("assigned_simulations", 2.0), ("assigned_transitions", 5.0),
            ("unused_simulations", False), ("unused_simulations", 0.0),
            ("unused_transitions", True), ("unused_transitions", 1.0),
        )
        for field, value in aliases:
            with self.subTest(field=field, value=value):
                self.assertEqual(getattr(self.receipt, field), value)
                self.assertFalse(ParallelMCTS._valid_receipt(
                    replace(self.receipt, **{field: value}), self.job, self.legal
                ))

    def test_duration_and_status_fields_cannot_contradict_a_completed_receipt(self):
        for elapsed in (None, True, -1.0, float("nan"), float("inf"), "0.125"):
            with self.subTest(elapsed=elapsed):
                self.assertFalse(ParallelMCTS._valid_receipt(
                    replace(self.receipt, elapsed_s=elapsed), self.job, self.legal
                ))
        self.assertFalse(ParallelMCTS._valid_receipt(
            replace(self.receipt, error="RuntimeError"), self.job, self.legal
        ))

    def test_absent_transition_ceiling_requires_absent_unused_transition_count(self):
        job = replace(self.job, max_transitions=None)
        receipt = replace(self.receipt, assigned_transitions=None,
                          unused_transitions=None, stop_reasons=("simulation_cap",))
        self.assertTrue(ParallelMCTS._valid_receipt(receipt, job, self.legal))
        for value in (0, False, 0.0, 99):
            with self.subTest(value=value):
                self.assertFalse(ParallelMCTS._valid_receipt(
                    replace(receipt, unused_transitions=value), job, self.legal
                ))

    def test_failed_receipt_retains_known_work_without_usable_statistics(self):
        # One complete simulation and one additional returned transition.
        receipt = replace(
            self.receipt, status="failed", simulations=1, transitions=3,
            unused_simulations=1, unused_transitions=2, virtual_visits=None,
            stop_reasons=("worker_error",), statistics=(), error="RuntimeError",
        )
        self.assertTrue(ParallelMCTS._valid_receipt(receipt, self.job, self.legal))
        for field, value in (("virtual_visits", 0), ("error", ""),
                             ("error", 123), ("unused_simulations", True)):
            with self.subTest(field=field, value=value):
                self.assertFalse(ParallelMCTS._valid_receipt(
                    replace(receipt, **{field: value}), self.job, self.legal
                ))
        engine = ParallelMCTS(horizon_rounds=2, workers=1)
        with (patch("engine.parallel._fixed_search", return_value=receipt),
              patch.object(engine, "_search_single") as fallback,
              self.assertRaises(ParallelSearchError) as caught):
            engine.search(self.root, mode="fixed", max_sims=2,
                          max_transitions=5, seed=4)
        fallback.assert_not_called()
        self.assertEqual(caught.exception.report.simulations, 1)
        self.assertEqual(caught.exception.report.transitions, 3)
        self.assertEqual(caught.exception.report.workers[0], receipt)

    def test_statistics_require_an_immutable_tuple_before_iteration(self):
        rows = ((Action(None), 2, 1.0),)
        for statistics in (list(rows), iter(rows), (row for row in rows)):
            with self.subTest(kind=type(statistics).__name__):
                self.assertFalse(ParallelMCTS._valid_receipt(
                    replace(self.receipt, statistics=statistics),
                    self.job, self.legal,
                ))
                self.assertEqual(list(statistics), list(rows))

    def test_one_use_statistics_preserve_other_work_without_a_recommendation(self):
        original = self.root.clone()
        for execution in ("sequential", "process"):
            with self.subTest(execution=execution):
                engine = ParallelMCTS(horizon_rounds=2, workers=2)
                rng_before = engine._rng.getstate()
                jobs = [replace(self.job, worker_id=i, seed=worker_seed(4, i))
                        for i in range(2)]
                receipts = [completed(job) for job in jobs]
                rows = ((Action(True, 0), 2, 1.0),)
                statistics = iter(rows)
                receipts[1] = replace(receipts[1], statistics=statistics)
                handles = [Mock() for _ in jobs]
                for handle, receipt in zip(handles, receipts, strict=True):
                    handle.get.return_value = receipt
                pool = Mock()
                pool.apply_async.side_effect = handles
                with (
                    patch("engine.parallel._fixed_search", side_effect=receipts)
                    as worker,
                    patch.object(engine, "_ensure_pool", return_value=pool),
                    patch.object(engine, "_search_single") as fallback,
                    patch.object(engine, "close") as close,
                    self.assertRaises(ParallelSearchError) as caught,
                ):
                    engine.search(self.root, mode="fixed", max_sims=4,
                                  max_transitions=10, seed=4, execution=execution)
                report = caught.exception.report
                self.assertIs(report, engine.last_report)
                self.assertFalse(report.complete)
                self.assertEqual(report.known_simulations, 2)
                self.assertEqual(report.known_transitions, 4)
                self.assertIsNone(report.simulations)
                self.assertIsNone(report.transitions)
                self.assertIsNone(report.unused_simulations)
                self.assertIsNone(report.unused_transitions)
                self.assertEqual(report.workers[0], receipts[0])
                self.assertEqual(report.workers[1].status, "unreported")
                self.assertEqual(report.workers[1].error, "InvalidWorkerReceipt")
                self.assertEqual(engine.last_sims, 2)
                self.assertEqual(engine._rng.getstate(), rng_before)
                self.assertEqual(self.root, original)
                self.assertEqual(list(statistics), list(rows))
                fallback.assert_not_called()
                close.assert_called_once()
                if execution == "process":
                    worker.assert_not_called()
                    self.assertEqual(pool.apply_async.call_count, 2)
                    for handle in handles:
                        handle.get.assert_called_once()
                else:
                    self.assertEqual(worker.call_count, 2)
                    pool.apply_async.assert_not_called()

    def test_one_invalid_worker_preserves_other_work_in_both_execution_paths(self):
        original = self.root.clone()
        for execution in ("sequential", "process"):
            for malformed in ("unused_simulations", "elapsed_s"):
                with self.subTest(execution=execution, malformed=malformed):
                    engine = ParallelMCTS(horizon_rounds=2, workers=2)
                    rng_before = engine._rng.getstate()
                    jobs = [replace(self.job, worker_id=i, seed=worker_seed(4, i))
                            for i in range(2)]
                    receipts = [completed(job) for job in jobs]
                    value = False if malformed == "unused_simulations" else float("nan")
                    receipts[1] = replace(receipts[1], **{malformed: value})
                    handles = [Mock() for _ in jobs]
                    for handle, receipt in zip(handles, receipts, strict=True):
                        handle.get.return_value = receipt
                    pool = Mock()
                    pool.apply_async.side_effect = handles
                    with (
                        patch("engine.parallel._fixed_search", side_effect=receipts)
                        as worker,
                        patch.object(engine, "_ensure_pool", return_value=pool),
                        patch.object(engine, "_search_single") as fallback,
                        patch.object(engine, "close") as close,
                        self.assertRaises(ParallelSearchError) as caught,
                    ):
                        engine.search(self.root, mode="fixed", max_sims=4,
                                      max_transitions=10, seed=4, execution=execution)
                    report = caught.exception.report
                    self.assertIs(report, engine.last_report)
                    self.assertFalse(report.complete)
                    self.assertEqual(report.known_simulations, 2)
                    self.assertEqual(report.known_transitions, 4)
                    self.assertIsNone(report.simulations)
                    self.assertIsNone(report.transitions)
                    self.assertIsNone(report.unused_simulations)
                    self.assertIsNone(report.unused_transitions)
                    self.assertEqual(report.workers[0], receipts[0])
                    self.assertEqual(report.workers[1].status, "unreported")
                    self.assertEqual(report.workers[1].error, "InvalidWorkerReceipt")
                    self.assertEqual(engine.last_sims, 2)
                    self.assertEqual(engine._rng.getstate(), rng_before)
                    self.assertEqual(self.root, original)
                    fallback.assert_not_called()
                    close.assert_called_once()
                    if execution == "process":
                        worker.assert_not_called()
                        self.assertEqual(pool.apply_async.call_count, 2)
                        for handle in handles:
                            handle.get.assert_called_once()
                    else:
                        self.assertEqual(worker.call_count, 2)
                        pool.apply_async.assert_not_called()

    def test_independent_statistics_merge_with_exact_counts_and_weighted_means(self):
        for execution in ("sequential", "process"):
            with self.subTest(execution=execution):
                engine = ParallelMCTS(horizon_rounds=2, workers=2)

                def receipt_for(job):
                    receipt = completed(job)
                    if job.worker_id == 1:
                        receipt = replace(receipt, statistics=(
                            (Action(None), 2, 1.5), (Action(0, 0), 0, 0.0)
                        ))
                    return receipt

                pool = Mock()

                def submitted(function, args):
                    handle = Mock()
                    handle.get.return_value = receipt_for(args[0])
                    return handle

                pool.apply_async.side_effect = submitted
                with (patch("engine.parallel._fixed_search", side_effect=receipt_for),
                      patch.object(engine, "_ensure_pool", return_value=pool)):
                    rows = engine.search(self.root, mode="fixed", max_sims=4,
                                         max_transitions=10, seed=4,
                                         execution=execution)
                self.assertTrue(engine.last_report.complete)
                self.assertEqual(engine.last_report.simulations, 4)
                self.assertEqual(engine.last_report.transitions, 8)
                self.assertEqual(engine.last_report.unused_transitions, 2)
                by_action = {row.action: row for row in rows}
                self.assertEqual(by_action[Action(None)].visits, 3)
                self.assertEqual(by_action[Action(None)].win_rate, 1.75 / 3)
                self.assertEqual(by_action[Action(0, 0)].visits, 1)
                self.assertEqual(by_action[Action(0, 0)].win_rate, 0.75)
                self.assertEqual(rows[0].action, Action(0, 0))


if __name__ == "__main__":
    unittest.main()
