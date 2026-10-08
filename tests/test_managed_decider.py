"""Public policy ownership without starting worker processes."""

import inspect
import random
import unittest
from unittest.mock import Mock, patch

from engine import Action, MCTSDecider, mcts_decider
from engine.mcts import MCTS, RankedAction
from engine.parallel import ParallelMCTS
from game.baselines import mcts_decider as game_mcts_decider
from game.content import SCENARIOS


def state():
    root, _ = SCENARIOS["duel"](random.Random(5))
    root.player.pips = 7
    return root


def parallel_policy(**kwargs):
    search = ParallelMCTS(workers=2)
    pool = Mock()
    search._pool = pool
    with patch("engine.decider.ParallelMCTS", return_value=search):
        choose = mcts_decider(parallel=True, workers=2, **kwargs)
    return choose, search, pool


class HostileStop(KeyboardInterrupt):
    def add_note(self, note):
        raise SystemExit("diagnostic failed")

    def __str__(self):
        raise RuntimeError("string conversion failed")


class HostileCleanup(OSError):
    def __str__(self):
        raise SystemExit("cleanup string failed")


class ManagedPolicyTests(unittest.TestCase):
    def test_public_factory_and_game_import_are_the_same(self):
        self.assertIs(game_mcts_decider, mcts_decider)
        self.assertEqual(list(inspect.signature(mcts_decider).parameters), [
            "budget_ms", "horizon", "parallel", "workers", "seed", "max_sims",
            "on_search", "max_transitions", "on_work"])
        choose = game_mcts_decider(60_000, 2, False, None, 7, 3)
        self.assertIsInstance(choose, MCTSDecider)
        self.assertIsInstance(choose._engine, MCTS)
        with choose:
            self.assertIsInstance(choose(state(), random.Random(2)), Action)

    def test_unused_serial_and_parallel_policies_close_without_work(self):
        for kwargs in ({}, {"parallel": True, "workers": 1},
                       {"parallel": True, "workers": 2}):
            with self.subTest(kwargs=kwargs):
                observed = Mock()
                choose = mcts_decider(on_search=observed, **kwargs)
                with patch.object(choose._engine, "search") as search:
                    choose.close()
                    choose.close()
                    with self.assertRaisesRegex(RuntimeError, "closed"):
                        choose(state(), random.Random(2))
                    with self.assertRaisesRegex(RuntimeError, "closed"):
                        choose.__enter__()
                search.assert_not_called()
                observed.assert_not_called()

    def test_serial_context_returns_owner_then_permanently_closes(self):
        counts, work = [], []
        choose = mcts_decider(budget_ms=60_000, horizon=2, seed=7,
                              max_sims=5, on_search=counts.append,
                              max_transitions=10, on_work=work.append)
        policy_rng = random.Random(99)
        before = policy_rng.getstate()
        with choose as entered:
            self.assertIs(entered, choose)
            entered(state(), policy_rng)
        self.assertEqual(policy_rng.getstate(), before)
        self.assertEqual(counts, [5])
        self.assertEqual(work[0]["simulations"], 5)
        self.assertEqual(work[0]["transitions"], 10)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            choose(state(), policy_rng)
        self.assertEqual(counts, [5])

    def test_parallel_calls_reuse_owner_until_explicit_close(self):
        counts = []
        choose, search, pool = parallel_policy(on_search=counts.append)
        result = [RankedAction(Action(None), "Pass", 0.5, 3)]
        search.last_sims = 3
        with patch.object(search, "search", return_value=result) as call:
            self.assertEqual(choose(state(), random.Random(2)), Action(None))
            self.assertEqual(choose(state(), random.Random(2)), Action(None))
            self.assertEqual(call.call_count, 2)
        self.assertEqual(counts, [3, 3])
        pool.terminate.assert_not_called()
        choose.close()
        choose.close()
        pool.terminate.assert_called_once()
        pool.join.assert_called_once()
        self.assertIsNone(search._pool)

    def test_closed_admission_precedes_state_search_and_callbacks(self):
        observed, work = Mock(), Mock()
        choose = mcts_decider(on_search=observed, on_work=work)
        choose.close()
        root, rng = Mock(), random.Random(2)
        before = rng.getstate()
        with patch.object(choose._engine, "search") as search:
            with self.assertRaisesRegex(RuntimeError, "closed"):
                choose(root, rng)
        search.assert_not_called()
        root.is_terminal.assert_not_called()
        observed.assert_not_called()
        work.assert_not_called()
        self.assertEqual(rng.getstate(), before)

    def test_failed_close_retains_ownership_blocks_work_then_retries(self):
        for method in ("terminate", "join"):
            with self.subTest(method=method):
                observed = Mock()
                choose, search, pool = parallel_policy(on_search=observed)
                error = OSError("retirement failed")
                getattr(pool, method).side_effect = error
                with self.assertRaises(OSError) as caught:
                    choose.close()
                self.assertIs(caught.exception, error)
                self.assertIs(choose._engine, search)
                self.assertIs(search._pool, pool)
                self.assertTrue(search._retirement_pending)
                self.assertFalse(choose._closed)
                self.assertEqual(pool.join.call_count, int(method == "join"))
                with patch.object(search, "search") as call:
                    with self.assertRaisesRegex(RuntimeError, "Retry close"):
                        choose(state(), random.Random(2))
                    with self.assertRaisesRegex(RuntimeError, "Retry close"):
                        choose.__enter__()
                call.assert_not_called()
                observed.assert_not_called()
                getattr(pool, method).side_effect = None
                choose.close()
                self.assertIsNone(search._pool)
                self.assertFalse(search._retirement_pending)
                self.assertTrue(choose._closed)
                choose.close()
                self.assertEqual(pool.terminate.call_count, 2)
                with self.assertRaisesRegex(RuntimeError, "closed"):
                    choose(state(), random.Random(2))

    def test_context_cleanup_preserves_body_exception_identity(self):
        for error_type in (RuntimeError, KeyboardInterrupt, SystemExit, HostileStop):
            for method in ("terminate", "join"):
                with self.subTest(error=error_type, method=method):
                    choose, search, pool = parallel_policy()
                    error = error_type("body stopped")
                    getattr(pool, method).side_effect = HostileCleanup()
                    with self.assertRaises(error_type) as caught:
                        with choose:
                            raise error
                    self.assertIs(caught.exception, error)
                    self.assertIs(search._pool, pool)
                    self.assertFalse(choose._closed)
                    if error_type is not HostileStop:
                        self.assertTrue(any("HostileCleanup" in note
                                            for note in error.__notes__))
                    getattr(pool, method).side_effect = None
                    choose.close()

    def test_successful_body_cleanup_error_is_visible_and_retryable(self):
        for error_type in (OSError, KeyboardInterrupt, SystemExit):
            with self.subTest(error=error_type):
                choose, search, pool = parallel_policy()
                error = error_type("cleanup failed")
                pool.join.side_effect = error
                with self.assertRaises(error_type) as caught:
                    with choose:
                        pass
                self.assertIs(caught.exception, error)
                self.assertIs(search._pool, pool)
                with self.assertRaisesRegex(RuntimeError, "Retry close"):
                    choose.__enter__()
                pool.join.side_effect = None
                choose.close()

    def test_context_search_stop_does_not_retry_pending_engine_retirement(self):
        for error_type in (TimeoutError, KeyboardInterrupt, SystemExit, HostileStop):
            with self.subTest(error=error_type):
                observed = Mock()
                choose, search, pool = parallel_policy(on_search=observed)
                error = error_type("search stopped")
                pool.map_async.return_value.get.side_effect = error
                pool.terminate.side_effect = OSError("cleanup failed")
                with (patch.object(search, "_search_single") as fallback,
                      self.assertRaises(error_type) as caught):
                    with choose:
                        choose(state(), random.Random(2))
                self.assertIs(caught.exception, error)
                self.assertIs(search._pool, pool)
                pool.terminate.assert_called_once()
                pool.join.assert_not_called()
                fallback.assert_not_called()
                observed.assert_not_called()
                with self.assertRaisesRegex(RuntimeError, "Retry close"):
                    choose(state(), random.Random(2))
                pool.terminate.side_effect = None
                choose.close()

    def test_caught_cleanup_failure_in_body_cannot_make_exit_succeed(self):
        choose, search, pool = parallel_policy()
        pool.join.side_effect = OSError("close failed")
        with self.assertRaisesRegex(RuntimeError, "Retry close"):
            with choose:
                with self.assertRaises(OSError):
                    choose.close()
        self.assertIs(search._pool, pool)
        pool.join.assert_called_once()
        pool.join.side_effect = None
        choose.close()

    def test_explicit_close_inside_context_is_idempotent_on_exit(self):
        choose, search, pool = parallel_policy()
        with choose:
            choose.close()
        pool.terminate.assert_called_once()
        pool.join.assert_called_once()
        self.assertIsNone(search._pool)

    def test_callback_error_is_primary_if_context_cleanup_fails(self):
        error = RuntimeError("observer failed")
        observed = Mock(side_effect=error)
        choose, search, pool = parallel_policy(on_search=observed)
        pool.join.side_effect = OSError("cleanup failed")
        with (patch.object(search, "search", return_value=[]),
              self.assertRaises(RuntimeError) as caught):
            with choose:
                choose(state(), random.Random(2))
        self.assertIs(caught.exception, error)
        self.assertTrue(any("OSError" in note for note in error.__notes__))
        pool.join.side_effect = None
        choose.close()


if __name__ == "__main__":
    unittest.main()
