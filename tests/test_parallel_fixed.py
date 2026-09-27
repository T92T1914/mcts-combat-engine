"""Fixed total allowances remain reproducible and do not hide failed work."""

import random
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from engine.actions import Action, legal_actions
from engine.mcts import MCTS
from engine.parallel import (
    ParallelMCTS,
    ParallelSearchError,
    WorkerJob,
    _fixed_search,
    allocate,
    merge_results,
    worker_seed,
)
from engine.simulator import advance_round
from game.content import SCENARIOS


def state():
    root, _ = SCENARIOS["duel"](random.Random(1))
    root.player.pips = 7
    return root


class FixedContractTests(unittest.TestCase):
    def test_allocations_preserve_nondivisible_zero_and_tiny_totals(self):
        for total, workers, expected in (
                (11, 3, (4, 4, 3)), (0, 4, (0, 0, 0, 0)),
                (2, 4, (1, 1, 0, 0)), (7, 1, (7,))):
            self.assertEqual(allocate(total, workers), expected)
            self.assertEqual(sum(expected), total)
        for total in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                allocate(total, 2)

    def test_fixed_controls_and_modes_are_validated_before_pool_start(self):
        bad = [
            {"mode": "unknown"}, {"max_sims": 1}, {"seed": 1},
            {"max_transitions": 1}, {"mode": "fixed"},
            {"mode": "fixed", "max_sims": 2},
            {"mode": "fixed", "seed": 3},
        ]
        good = {"mode": "fixed", "seed": 3, "max_sims": 2}
        for key, values in (
                ("max_sims", (-1, True, 1.5)), ("seed", (-1, True, 1.5)),
                ("max_transitions", (-1, True, 1.5)),
                ("time_budget_ms", (0, 100)),
                ("worker_timeout_s", (0, -1, True, float("inf")))):
            bad.extend(good | {key: value} for value in values)
        engine = ParallelMCTS(workers=2)
        rng_before = engine._rng.getstate()
        with patch.object(engine, "_ensure_pool") as pool:
            for kwargs in bad:
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    engine.search(state(), **kwargs)
            pool.assert_not_called()
        self.assertEqual(engine._rng.getstate(), rng_before)

    def test_seed_derivation_has_a_stable_known_value(self):
        # SHA256("mcts-root-v1:7:0") begins 71c60637d8e327fe.
        self.assertEqual(worker_seed(7, 0), 8198247008606300158)
        self.assertEqual(len({worker_seed(7, i) for i in range(4)}), 4)

    def test_serial_fixed_search_does_not_consult_a_stopping_clock(self):
        engine = MCTS(max_sims=3, rng=random.Random(7))
        with patch("engine.mcts.time.perf_counter", side_effect=AssertionError):
            ranked = engine.search(state(), None)
        self.assertEqual(sum(row.visits for row in ranked), 3)

    def test_single_worker_matches_its_declared_serial_tree(self):
        root = state()
        reference = MCTS(horizon_rounds=3, max_sims=17,
                         max_transitions=31, rng=random.Random(worker_seed(7, 0)))
        expected = reference.search(root, None)
        engine = ParallelMCTS(horizon_rounds=3, workers=1)
        with patch.object(engine, "_ensure_pool") as pool:
            ranked = engine.search(root, mode="fixed", max_sims=17,
                                   max_transitions=31, seed=7)
            pool.assert_not_called()
        self.assertEqual({r.action: r for r in ranked},
                         {r.action: r for r in expected})
        self.assertEqual(engine.last_sims, reference.last_sims)
        report = engine.last_report
        self.assertTrue(report.complete)
        self.assertEqual(report.transitions, reference.last_transitions)
        self.assertEqual(report.unused_transitions, 31 - report.transitions)

    def test_zero_budget_and_terminal_roots_do_not_spawn(self):
        engine = ParallelMCTS(workers=4)
        root = state()
        priors = {root.hand[0].name: (2, .75)}
        with patch.object(engine, "_ensure_pool") as pool:
            ranked = engine.search(root, mode="fixed", max_sims=0,
                                   max_transitions=7, seed=0, priors=priors)
            self.assertTrue(ranked)
            report = engine.last_report
            self.assertEqual(report.simulations, 0)
            self.assertEqual(report.transitions, 0)
            self.assertEqual(report.unused_transitions, 7)
            self.assertEqual(sum(r.visits for r in ranked),
                             sum(w.virtual_visits for w in report.workers))
            root.player.hp = 0
            self.assertEqual(engine.search(root, mode="fixed", max_sims=11,
                                           max_transitions=23, seed=1,
                                           priors=priors), [])
            report = engine.last_report
            self.assertEqual(report.unused_simulations, 11)
            self.assertEqual(report.unused_transitions, 23)
            self.assertTrue(all(w.stop_reasons == ("terminal",)
                                for w in report.workers))
            pool.assert_not_called()

    def test_priors_are_separate_from_completed_simulations(self):
        root = state()
        priors = {root.hand[0].name: (5, .7)}
        engine = ParallelMCTS(horizon_rounds=2, workers=1)
        ranked = engine.search(root, mode="fixed", max_sims=9,
                               seed=8, priors=priors)
        receipt = engine.last_report.workers[0]
        self.assertEqual(receipt.simulations, 9)
        self.assertGreater(receipt.virtual_visits, 0)
        self.assertEqual(sum(r.visits for r in ranked), 9 + receipt.virtual_visits)
        self.assertEqual(receipt.virtual_visits, 15)
        means = {r.action: r.win_rate for r in ranked}
        for action, visits, value_sum in receipt.statistics:
            self.assertEqual(means[action], value_sum / visits)

    def test_duplicate_root_copies_and_simulated_actions_remain_legal(self):
        root = state()
        root.hand = [root.hand[0], root.hand[0]]
        original = root.clone()
        legal = set(legal_actions(root))

        def checked(current, action, rng):
            self.assertIn(action, legal_actions(current))
            return advance_round(current, action, rng)

        with patch("engine.mcts.advance_round", checked):
            engine = ParallelMCTS(horizon_rounds=3, workers=1)
            rows = engine.search(root, mode="fixed", max_sims=75, seed=9)
        self.assertEqual({r.action for r in rows}, legal)
        self.assertEqual(root, original)
        self.assertEqual(sum(r.visits for r in rows), 75)

    def test_merge_is_independent_of_worker_completion_order(self):
        a, b = Action(None), Action(0, 0)
        jobs = [([(a, 2, .9), (b, 1, .5)], 3),
                ([(b, 3, 1.5), (a, 1, .6)], 4)]
        ranked, sims = merge_results(jobs, state())
        self.assertEqual(merge_results(reversed(jobs), state()), (ranked, sims))
        by_action = {row.action: row for row in ranked}
        self.assertEqual((by_action[a].visits, by_action[b].visits), (3, 4))
        self.assertEqual(by_action[a].win_rate, .5)
        self.assertEqual(by_action[b].win_rate, .5)


class FixedPoolTests(unittest.TestCase):
    def test_repeatable_pool_reuse_and_unused_worker_allowances(self):
        root = state()
        engine = ParallelMCTS(horizon_rounds=3, workers=2)
        original = root.clone()
        try:
            rows = engine.search(root, mode="fixed", max_sims=31,
                                 max_transitions=89, seed=7)
            first = engine.last_report
            children = list(engine._pool._pool)
            again = engine.search(root, mode="fixed", max_sims=31,
                                  max_transitions=89, seed=7)
            second = engine.last_report
            self.assertEqual(rows, again)
            self.assertEqual([replace(r, elapsed_s=None) for r in first.workers],
                             [replace(r, elapsed_s=None) for r in second.workers])
            self.assertEqual(sum(r.visits for r in rows), first.simulations)
            self.assertEqual([r.assigned_simulations for r in first.workers], [16, 15])
            self.assertEqual([r.assigned_transitions for r in first.workers], [45, 44])
            self.assertGreater(first.pool_startup_s, 0)
            self.assertEqual(second.pool_startup_s, 0)
            self.assertLessEqual(first.transitions, 89)
            self.assertEqual(first.unused_transitions, 89 - first.transitions)
            self.assertEqual(root, original)
            tiny = engine.search(root, mode="fixed", max_sims=1, seed=8)
            self.assertEqual(sum(r.visits for r in tiny), 1)
            self.assertEqual([r.simulations for r in engine.last_report.workers],
                             [1, 0])
        finally:
            engine.close()
        self.assertIsNone(engine._pool)
        self.assertTrue(all(not child.is_alive() for child in children))


class FixedFailureTests(unittest.TestCase):
    def test_known_worker_error_preserves_work_and_never_retries(self):
        calls = 0

        def fail_on_fourth(current, action, rng):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise RuntimeError("fixture")
            return advance_round(current, action, rng)

        engine = ParallelMCTS(horizon_rounds=2, workers=1)
        with (patch("engine.mcts.advance_round", fail_on_fourth),
              patch.object(engine, "_search_single") as fallback,
              self.assertRaises(ParallelSearchError) as caught):
            engine.search(state(), mode="fixed", max_sims=7, seed=4)
        fallback.assert_not_called()
        report = caught.exception.report
        self.assertFalse(report.complete)
        self.assertEqual(report.simulations, 1)
        self.assertEqual(report.transitions, 3)
        self.assertEqual(report.workers[0].status, "failed")
        self.assertEqual(report.workers[0].error, "RuntimeError")
        self.assertEqual(calls, 4)

    def test_timeout_retains_ready_receipt_and_marks_missing_work_unknown(self):
        root = state()
        receipt = _fixed_search(WorkerJob(0, root, 2, worker_seed(4, 0), 3, None, None))
        ready = Mock()
        ready.get.return_value = receipt
        lost = Mock()
        lost.get.side_effect = TimeoutError("fixture")
        lost.ready.return_value = False
        pool = Mock()
        pool.apply_async.side_effect = [ready, lost]
        engine = ParallelMCTS(horizon_rounds=2, workers=2)
        with (patch.object(engine, "_ensure_pool", return_value=pool),
              patch.object(engine, "close") as close,
              patch.object(engine, "_search_single") as fallback,
              self.assertRaises(ParallelSearchError)):
            engine.search(root, mode="fixed", max_sims=5, seed=4)
        fallback.assert_not_called()
        close.assert_called()
        report = engine.last_report
        self.assertEqual(report.known_simulations, 3)
        self.assertIsNone(report.simulations)
        self.assertIsNone(report.unused_simulations)
        self.assertEqual(report.workers[1].status, "unreported")
        self.assertEqual(pool.apply_async.call_count, 2)

    def test_dispatch_failure_does_not_claim_unstarted_work_was_spent(self):
        engine = ParallelMCTS(workers=2)
        with (patch.object(engine, "_ensure_pool", side_effect=OSError),
              self.assertRaises(ParallelSearchError)):
            engine.search(state(), mode="fixed", max_sims=5, seed=4)
        report = engine.last_report
        self.assertFalse(report.complete)
        self.assertEqual(report.simulations, 0)
        self.assertEqual(report.unused_simulations, 5)
        self.assertTrue(all(r.status == "not_started" for r in report.workers))

    def test_invalid_statistics_are_not_accepted_as_a_complete_search(self):
        root = state()
        job = WorkerJob(0, root, 2, worker_seed(4, 0), 3, None, None)
        valid = _fixed_search(job)
        bad_records = [
            replace(valid, simulations=4), replace(valid, worker_id=2),
            replace(valid, statistics=((Action(999, 0), 3, 1.5),)),
            replace(valid, statistics=((Action(None), 3, float("nan")),)),
            replace(valid, statistics=valid.statistics * 2),
        ]
        for bad in bad_records:
            engine = ParallelMCTS(horizon_rounds=2, workers=1)
            with (self.subTest(bad=bad), patch("engine.parallel._fixed_search",
                                             return_value=bad),
                  self.assertRaises(ParallelSearchError)):
                engine.search(root, mode="fixed", max_sims=3, seed=4)
            self.assertIsNone(engine.last_report.simulations)

    def test_warmup_failure_does_not_change_the_requested_worker_count(self):
        engine = ParallelMCTS(workers=2)
        with patch.object(engine, "_ensure_pool", side_effect=OSError):
            self.assertFalse(engine.warmup())
            with self.assertRaises(ParallelSearchError):
                engine.search(state(), mode="fixed", max_sims=3, seed=1)
            with patch.object(engine, "_search_single", return_value=[]) as fallback:
                self.assertEqual(engine.search(state(), time_budget_ms=1), [])
                fallback.assert_called_once()
        self.assertEqual(engine.workers, 2)


if __name__ == "__main__":
    unittest.main()
