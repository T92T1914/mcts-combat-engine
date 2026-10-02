"""Owned cleanup failures retain caller errors and uncertain fixed work."""

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
from game.baselines import mcts_decider
from game.content import SCENARIOS


def state():
    root, _ = SCENARIOS["duel"](random.Random(1))
    root.player.pips = 7
    return root


class HostileStop(KeyboardInterrupt):
    def add_note(self, note):
        raise SystemExit("diagnostic failed")

    def __str__(self):
        raise RuntimeError("string conversion failed")


class CleanupPrecedenceTests(unittest.TestCase):
    def assert_pending(self, engine, pool):
        self.assertIs(engine._pool, pool)
        self.assertTrue(engine._retirement_pending)

    def test_timed_stop_survives_failed_retirement_without_fallback(self):
        for stop_type in (KeyboardInterrupt, SystemExit, HostileStop):
            for cleanup_method in ("terminate", "join"):
                with self.subTest(stop_type=stop_type, cleanup=cleanup_method):
                    error = stop_type("caller stop")
                    pool = Mock()
                    pool.map_async.return_value.get.side_effect = error
                    getattr(pool, cleanup_method).side_effect = OSError("cleanup")
                    engine = ParallelMCTS(workers=2)
                    engine._pool = pool
                    with (patch.object(engine, "_search_single") as fallback,
                          self.assertRaises(stop_type) as caught):
                        engine.search(state(), time_budget_ms=1)
                    self.assertIs(caught.exception, error)
                    fallback.assert_not_called()
                    self.assert_pending(engine, pool)
                    self.assertEqual(pool.join.call_count,
                                     int(cleanup_method == "join"))

    def test_ordinary_timed_failure_does_not_retry_while_retirement_pending(self):
        error = TimeoutError("original wait failure")
        pool = Mock()
        pool.map_async.return_value.get.side_effect = error
        pool.terminate.side_effect = OSError("cleanup")
        engine = ParallelMCTS(workers=2)
        engine._pool = pool
        with (patch.object(engine, "_search_single") as fallback,
              self.assertRaises(TimeoutError) as caught):
            engine.search(state(), time_budget_ms=1)
        self.assertIs(caught.exception, error)
        fallback.assert_not_called()
        self.assert_pending(engine, pool)

    def test_public_decider_does_not_publish_action_or_telemetry_after_failure(self):
        error = TimeoutError("original wait failure")
        pool = Mock()
        pool.map_async.return_value.get.side_effect = error
        pool.terminate.side_effect = OSError("cleanup")
        engine = ParallelMCTS(workers=2)
        engine._pool = pool
        observed = Mock()
        with patch("game.baselines.ParallelMCTS", return_value=engine):
            decide = mcts_decider(parallel=True, workers=2, on_search=observed)
        with self.assertRaises(TimeoutError) as caught:
            decide(state(), random.Random(1))
        self.assertIs(caught.exception, error)
        observed.assert_not_called()
        with self.assertRaises(RuntimeError):
            decide(state(), random.Random(1))
        observed.assert_not_called()
        self.assertEqual(pool.map_async.call_count, 1)
        self.assert_pending(engine, pool)

    def test_pending_retirement_blocks_new_work_until_explicit_close_succeeds(self):
        pool = Mock()
        pool.join.side_effect = [OSError("join incomplete"), None]
        engine = ParallelMCTS(workers=2)
        engine._pool = pool
        with self.assertRaises(OSError):
            engine.close()
        self.assert_pending(engine, pool)
        for kwargs in ({"time_budget_ms": 1},
                       {"mode": "fixed", "max_sims": 1, "seed": 1,
                        "execution": "sequential"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(RuntimeError):
                engine.search(state(), **kwargs)
        self.assertFalse(engine.warmup())
        self.assertEqual(pool.terminate.call_count, 1)
        pool.map_async.assert_not_called()
        pool.apply_async.assert_not_called()
        engine.close()
        self.assertIsNone(engine._pool)
        self.assertFalse(engine._retirement_pending)
        engine.close()
        self.assertEqual(pool.join.call_count, 2)

    def test_failed_terminate_does_not_start_potentially_blocking_join(self):
        error = OSError("terminate incomplete")
        pool = Mock()
        pool.terminate.side_effect = error
        engine = ParallelMCTS(workers=2)
        engine._pool = pool
        with self.assertRaises(OSError) as caught:
            engine.close()
        self.assertIs(caught.exception, error)
        pool.join.assert_not_called()
        self.assert_pending(engine, pool)

    def test_startup_stop_survives_queue_or_pool_cleanup_failure(self):
        for stop_type in (KeyboardInterrupt, SystemExit, HostileStop):
            for method in ("queue_close", "queue_join", "terminate", "join"):
                with self.subTest(stop=stop_type, cleanup=method):
                    error = stop_type("readiness stop")
                    pool, queue, context = Mock(), Mock(), Mock()
                    context.Queue.return_value = queue
                    context.Pool.return_value = pool
                    queue.get.side_effect = error
                    target, name = {
                        "queue_close": (queue, "close"),
                        "queue_join": (queue, "join_thread"),
                        "terminate": (pool, "terminate"),
                        "join": (pool, "join"),
                    }[method]
                    getattr(target, name).side_effect = OSError("cleanup")
                    engine = ParallelMCTS(workers=2)
                    with (patch("engine.parallel.mp.get_context", return_value=context),
                          self.assertRaises(stop_type) as caught):
                        engine.warmup()
                    self.assertIs(caught.exception, error)
                    queue.close.assert_called_once()
                    self.assertEqual(queue.join_thread.call_count,
                                     int(method != "queue_close"))
                    if method in ("terminate", "join"):
                        self.assert_pending(engine, pool)
                    else:
                        self.assertIsNone(engine._pool)

    def test_readiness_cleanup_error_after_startup_retires_owned_pool(self):
        error = OSError("readiness close failure")
        pool, queue, context = Mock(), Mock(), Mock()
        context.Queue.return_value = queue
        context.Pool.return_value = pool
        queue.close.side_effect = error
        engine = ParallelMCTS(workers=2)
        with patch("engine.parallel.mp.get_context", return_value=context):
            self.assertFalse(engine.warmup())
        pool.terminate.assert_called_once()
        pool.join.assert_called_once()
        self.assertIsNone(engine._pool)

    def test_fixed_stop_retains_received_work_despite_failed_retirement(self):
        for method in ("terminate", "join"):
            for error_type in (KeyboardInterrupt, SystemExit, HostileStop):
                with self.subTest(cleanup=method, stop=error_type):
                    root = state()
                    error = error_type("fixed wait stop")
                    receipt = _fixed_search(WorkerJob(
                        0, root, 1, worker_seed(1, 0), 1, None, None))
                    received, lost, pool = Mock(), Mock(), Mock()
                    received.get.return_value = receipt
                    lost.get.side_effect = error
                    lost.ready.return_value = False
                    pool.apply_async.side_effect = [received, lost]
                    getattr(pool, method).side_effect = OSError("cleanup")
                    engine = ParallelMCTS(horizon_rounds=1, workers=2)
                    engine._pool = pool
                    with self.assertRaises(error_type) as caught:
                        engine.search(root, mode="fixed", max_sims=2, seed=1)
                    self.assertIs(caught.exception, error)
                    report = engine.last_report
                    self.assertFalse(report.complete)
                    self.assertEqual(report.workers[0], receipt)
                    self.assertEqual(report.known_simulations, 1)
                    self.assertIsNone(report.simulations)
                    self.assertIsNone(report.unused_simulations)
                    self.assertEqual(report.workers[1].status, "unreported")
                    self.assert_pending(engine, pool)
                    self.assertEqual(pool.terminate.call_count, 1)
                    with self.assertRaises(RuntimeError):
                        engine.search(root, mode="fixed", max_sims=2, seed=1)
                    self.assertIs(engine.last_report, report)

    def test_fixed_ordinary_failure_keeps_report_and_cleanup_diagnostic(self):
        pool = Mock()
        pending = pool.apply_async.return_value
        pending.get.side_effect = TimeoutError("work unknown")
        pending.ready.return_value = False
        pool.join.side_effect = OSError("join incomplete")
        engine = ParallelMCTS(workers=2)
        engine._pool = pool
        with self.assertRaises(ParallelSearchError) as caught:
            engine.search(state(), mode="fixed", max_sims=2, seed=1)
        self.assertIs(caught.exception.report, engine.last_report)
        self.assertIsNone(engine.last_report.simulations)
        self.assertTrue(caught.exception.__notes__)
        self.assertEqual(pool.terminate.call_count, 1)
        self.assert_pending(engine, pool)

    def test_complete_ready_report_does_not_hide_failed_retirement_or_retry(self):
        root = state()
        error = TimeoutError("wait failed before ready observation")
        receipts = [_fixed_search(WorkerJob(
            i, root, 1, worker_seed(1, i), 1, None, None)) for i in range(2)]
        first, second, pool = Mock(), Mock(), Mock()
        first.get.side_effect = [error, receipts[0]]
        second.get.return_value = receipts[1]
        first.ready.return_value = second.ready.return_value = True
        pool.apply_async.side_effect = [first, second]
        pool.join.side_effect = OSError("join incomplete")
        engine = ParallelMCTS(horizon_rounds=1, workers=2)
        engine._pool = pool
        with self.assertRaises(TimeoutError) as caught:
            engine.search(root, mode="fixed", max_sims=2, seed=1)
        self.assertIs(caught.exception, error)
        self.assertTrue(engine.last_report.complete)
        self.assertEqual(engine.last_report.simulations, 2)
        self.assert_pending(engine, pool)


if __name__ == "__main__":
    unittest.main()
