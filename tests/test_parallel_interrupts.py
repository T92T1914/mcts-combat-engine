"""Caller interruption retires accepted work without inventing its outcome."""

import random
import unittest
from unittest.mock import Mock, patch

from engine.parallel import (
    ParallelMCTS,
    ParallelSearchError,
    WorkerJob,
    _fixed_search,
    worker_seed,
)
from game.content import SCENARIOS


def root_state():
    state, _ = SCENARIOS["duel"](random.Random(1))
    state.player.pips = 7
    return state


class CallerInterruptTests(unittest.TestCase):
    def assert_retired(self, engine, pool):
        pool.terminate.assert_called_once_with()
        pool.join.assert_called_once_with()
        self.assertIsNone(engine._pool)

    def test_startup_interrupt_retires_pool_and_closes_readiness_queue(self):
        for error_type in (KeyboardInterrupt, SystemExit):
            with self.subTest(error_type=error_type):
                error = error_type("caller stopped startup")
                queue, pool = Mock(), Mock()
                queue.get.side_effect = error
                context = Mock()
                context.Queue.return_value = queue
                context.Pool.return_value = pool
                engine = ParallelMCTS(workers=2)
                with (patch("engine.parallel.mp.get_context", return_value=context),
                      self.assertRaises(error_type) as caught):
                    engine.warmup()
                self.assertIs(caught.exception, error)
                self.assert_retired(engine, pool)
                queue.close.assert_called_once_with()
                queue.join_thread.assert_called_once_with()
                self.assertEqual(engine.workers, 2)

    def test_timed_wait_interrupt_retires_pool_without_serial_fallback(self):
        for error_type in (KeyboardInterrupt, SystemExit):
            with self.subTest(error_type=error_type):
                error = error_type("caller stopped timed search")
                pool = Mock()
                pool.map_async.return_value.get.side_effect = error
                engine = ParallelMCTS(workers=2)
                engine._pool = pool
                with (patch.object(engine, "_ensure_pool", return_value=pool),
                      patch.object(engine, "_search_single") as fallback,
                      self.assertRaises(error_type) as caught):
                    engine.search(root_state(), time_budget_ms=1)
                self.assertIs(caught.exception, error)
                fallback.assert_not_called()
                self.assert_retired(engine, pool)

    def test_fixed_wait_interrupt_preserves_received_work_and_unknown_remainder(self):
        for error_type in (KeyboardInterrupt, SystemExit):
            with self.subTest(error_type=error_type):
                error = error_type("caller stopped fixed search")
                state = root_state()
                receipt = _fixed_search(WorkerJob(
                    0, state, 2, worker_seed(4, 0), 3, 6, None))
                ready, pending = Mock(), Mock()
                ready.get.return_value = receipt
                pending.get.side_effect = error
                pending.ready.return_value = False
                pool = Mock()
                pool.apply_async.side_effect = [ready, pending]
                engine = ParallelMCTS(horizon_rounds=2, workers=2)
                engine._pool = pool
                with (patch.object(engine, "_ensure_pool", return_value=pool),
                      patch.object(engine, "_search_single") as fallback,
                      self.assertRaises(error_type) as caught):
                    engine.search(state, mode="fixed", max_sims=5,
                                  max_transitions=11, seed=4)
                self.assertIs(caught.exception, error)
                fallback.assert_not_called()
                self.assert_retired(engine, pool)
                report = engine.last_report
                self.assertFalse(report.complete)
                self.assertEqual(report.workers[0], receipt)
                self.assertEqual(report.known_simulations, receipt.simulations)
                self.assertEqual(report.known_transitions, receipt.transitions)
                self.assertIsNone(report.simulations)
                self.assertIsNone(report.unused_simulations)
                self.assertIsNone(report.transitions)
                self.assertEqual(report.workers[1].status, "unreported")
                self.assertEqual(report.workers[1].error, error_type.__name__)
                self.assertEqual(pool.apply_async.call_count, 2)

    def test_dispatch_interrupt_keeps_possible_enqueued_work_unknown(self):
        error = KeyboardInterrupt("after queueing a job")
        state = root_state()
        receipt = _fixed_search(WorkerJob(
            0, state, 2, worker_seed(4, 0), 2, None, None))
        ready = Mock()
        ready.get.return_value = receipt
        ready.ready.return_value = True
        pool = Mock()
        accepted = []

        def dispatch(function, args):
            accepted.append(args[0].worker_id)
            if len(accepted) == 2:
                raise error
            return ready

        pool.apply_async.side_effect = dispatch
        engine = ParallelMCTS(horizon_rounds=2, workers=3)
        engine._pool = pool
        with (patch.object(engine, "_ensure_pool", return_value=pool),
              self.assertRaises(KeyboardInterrupt) as caught):
            engine.search(state, mode="fixed", max_sims=6, seed=4)
        self.assertIs(caught.exception, error)
        self.assert_retired(engine, pool)
        report = engine.last_report
        self.assertEqual(accepted, [0, 1])
        self.assertEqual(report.workers[0], receipt)
        self.assertEqual(report.workers[1].status, "unreported")
        self.assertIsNone(report.workers[1].simulations)
        self.assertEqual(report.workers[2].status, "not_started")
        self.assertEqual(report.workers[2].simulations, 0)
        self.assertEqual(report.workers[2].unused_simulations, 2)
        self.assertIsNone(report.simulations)

    def test_inline_interrupt_marks_attempted_work_unknown_and_propagates(self):
        error = SystemExit("during an inline simulator call")
        engine = ParallelMCTS(horizon_rounds=2, workers=2)
        with (patch("engine.parallel._fixed_search", side_effect=error) as search,
              patch.object(engine, "_ensure_pool") as pool,
              self.assertRaises(SystemExit) as caught):
            engine.search(root_state(), mode="fixed", max_sims=4, seed=4,
                          execution="sequential")
        self.assertIs(caught.exception, error)
        search.assert_called_once()
        pool.assert_not_called()
        report = engine.last_report
        self.assertEqual(report.workers[0].status, "unreported")
        self.assertEqual(report.workers[1].status, "not_started")
        self.assertIsNone(report.simulations)

    def test_ready_receipt_is_retained_after_interrupted_wait_without_retry(self):
        error = KeyboardInterrupt("caller stopped while waiting")
        state = root_state()
        receipts = [_fixed_search(WorkerJob(
            ident, state, 2, worker_seed(4, ident), 2, None, None))
            for ident in range(2)]
        first, second = Mock(), Mock()
        first.get.side_effect = [error, receipts[0]]
        first.ready.return_value = True
        second.get.return_value = receipts[1]
        second.ready.return_value = True
        pool = Mock()
        pool.apply_async.side_effect = [first, second]
        engine = ParallelMCTS(horizon_rounds=2, workers=2)
        engine._pool = pool
        with (patch.object(engine, "_ensure_pool", return_value=pool),
              self.assertRaises(KeyboardInterrupt) as caught):
            engine.search(state, mode="fixed", max_sims=4, seed=4)
        self.assertIs(caught.exception, error)
        self.assert_retired(engine, pool)
        self.assertTrue(engine.last_report.complete)
        self.assertEqual(engine.last_report.workers, tuple(receipts))
        self.assertEqual(engine.last_report.simulations, 4)
        self.assertEqual(pool.apply_async.call_count, 2)
        # The second read retrieves already completed work with no wait.
        self.assertEqual(first.get.call_args_list[-1].kwargs, {"timeout": 0})

    def test_harvest_interrupt_still_retires_pool_and_preserves_later_ready_work(self):
        error = SystemExit("caller stopped during receipt collection")
        state = root_state()
        receipt = _fixed_search(WorkerJob(
            1, state, 2, worker_seed(4, 1), 2, None, None))
        lost, ready = Mock(), Mock()
        lost.get.side_effect = TimeoutError("first wait failed")
        lost.ready.side_effect = error
        ready.ready.return_value = True
        ready.get.return_value = receipt
        pool = Mock()
        pool.apply_async.side_effect = [lost, ready]
        engine = ParallelMCTS(horizon_rounds=2, workers=2)
        engine._pool = pool
        with (patch.object(engine, "_ensure_pool", return_value=pool),
              self.assertRaises(SystemExit) as caught):
            engine.search(state, mode="fixed", max_sims=4, seed=4)
        self.assertIs(caught.exception, error)
        self.assert_retired(engine, pool)
        self.assertEqual(engine.last_report.workers[0].status, "unreported")
        self.assertEqual(engine.last_report.workers[1], receipt)
        self.assertIsNone(engine.last_report.simulations)

    def test_ordinary_dispatch_failure_retains_uncertain_attempted_allowance(self):
        pool = Mock()
        pool.apply_async.side_effect = OSError("dispatch outcome unavailable")
        engine = ParallelMCTS(workers=2)
        engine._pool = pool
        with (patch.object(engine, "_ensure_pool", return_value=pool),
              self.assertRaises(ParallelSearchError)):
            engine.search(root_state(), mode="fixed", max_sims=4, seed=4)
        self.assert_retired(engine, pool)
        self.assertEqual(engine.last_report.workers[0].status, "unreported")
        self.assertEqual(engine.last_report.workers[1].status, "not_started")
        self.assertIsNone(engine.last_report.simulations)


if __name__ == "__main__":
    unittest.main()
