"""Timed worker outcomes are accepted as one validated batch before merging."""
import copy
import random
import unittest
from unittest.mock import Mock, patch

from engine.actions import Action, is_legal_action
from engine.mcts import MCTS
from engine.parallel import ParallelMCTS, merge_results
from engine.state import Card, Combatant, Element, GameState


def position():
    return GameState(
        Combatant("P", Element.EMBER, 100, 100),
        [Combatant("E", Element.FROST, 100, 100, policy={"shield": 1.0})],
        [Card("First", accuracy=1.0), Card("Second", accuracy=1.0)],
    )


def completed(root, *, simulations=3, priors=None):
    search = MCTS(horizon_rounds=1, max_sims=simulations,
                  rng=random.Random(7))
    search.search(root, time_budget_ms=None, priors=priors)
    return search.last_root_statistics, search.last_sims


def inert_pool(results):
    pool = Mock()
    pool.map_async.return_value.get.return_value = results
    return pool


class TimedWorkerResultTests(unittest.TestCase):
    def setUp(self):
        self.root = position()
        self.original = copy.deepcopy(self.root)
        self.valid = completed(self.root)

    def engine(self, outcomes):
        engine = ParallelMCTS(horizon_rounds=1, workers=2)
        pool = inert_pool(outcomes)
        engine._pool = pool
        self.addCleanup(engine.close)
        return engine, pool

    def assert_fallback(self, outcomes, *, priors=None):
        engine, pool = self.engine(outcomes)
        replacement = [object()]
        with (patch.object(engine, "_search_single",
                           return_value=replacement) as fallback,
              patch("engine.parallel.merge_results", wraps=merge_results) as merge):
            self.assertIs(engine.search(self.root, time_budget_ms=1, priors=priors),
                          replacement)
        merge.assert_not_called()
        fallback.assert_called_once_with(self.root, 1, priors)
        pool.terminate.assert_called_once()
        pool.join.assert_called_once()
        self.assertIsNone(engine._pool)
        self.assertFalse(engine._retirement_pending)
        self.assertIsNone(engine.last_report)
        self.assertEqual(self.root, self.original)

    def test_malformed_outcomes_are_not_recommendations_or_completed_work(self):
        cases = [
            ([(Action(True, 0), 1, 0.5)], 1),
            ([(Action(1.0, 0), 1, 0.5)], 1),
            ([(Action(1, False), 1, 0.5)], 1),
            ([(Action(0, None), 1, 0.5)], 1),
            ([(Action(99, 0), 1, 0.5)], 1),
            ([(object(), 1, 0.5)], 1),
            ([(Action(None), 1, float("nan"))], 1),
            ([(Action(None), 1, float("inf"))], 1),
            ([(Action(None), 1, 10 ** 1000)], 1),
            ([(Action(None), 1, -0.1)], 1),
            ([(Action(None), 1, 1.1)], 1),
            ([(Action(None), 1, True)], 1),
            ([(Action(None), 1, "0.5")], 1),
            ([(Action(None), True, 0.5)], 1),
            ([(Action(None), 1.0, 0.5)], 1),
            ([(Action(None), -1, 0.0)], 1),
            ([(Action(None), 1, 0.5)], -1),
            ([(Action(None), 1, 0.5)], True),
            ([(Action(None), 1, 0.5)], 1.0),
            ([(Action(None), 1, 0.5)], 2),
            ([], 1),
            ([(Action(None), 1, 0.5), (Action(None), 1, 0.5)], 2),
            ([ [Action(None), 1, 0.5] ], 1),
            ([(Action(None), 1)], 1),
            (["bad row"], 1),
            (None, 0),
        ]
        for outcome in cases:
            with self.subTest(outcome=outcome):
                self.assert_fallback([self.valid, outcome])

    def test_missing_or_extra_worker_result_refuses_the_whole_batch(self):
        for outcomes in ([], [self.valid], [self.valid] * 3, (self.valid, self.valid)):
            with self.subTest(outcomes=outcomes):
                self.assert_fallback(outcomes)

    def test_valid_actual_results_preserve_merge_and_pool_reuse(self):
        outcomes = [self.valid, self.valid]
        expected, simulations = merge_results(outcomes, self.root)
        engine, pool = self.engine(outcomes)
        with patch.object(engine, "_search_single") as fallback:
            ranked = engine.search(self.root, time_budget_ms=1)
        fallback.assert_not_called()
        self.assertEqual(ranked, expected)
        self.assertEqual(engine.last_sims, simulations)
        self.assertTrue(all(is_legal_action(self.root, row.action) for row in ranked))
        self.assertEqual(self.root, self.original)
        pool.terminate.assert_not_called()
        pool.join.assert_not_called()
        self.assertIs(engine._pool, pool)

    def test_zero_completed_work_and_empty_rows_are_valid_without_priors(self):
        engine, pool = self.engine([([], 0), ([], 0)])
        with patch.object(engine, "_search_single") as fallback:
            self.assertEqual(engine.search(self.root, time_budget_ms=1), [])
        fallback.assert_not_called()
        self.assertEqual(engine.last_sims, 0)
        pool.terminate.assert_not_called()

    def test_prior_only_and_mixed_work_preserve_virtual_counts(self):
        priors = {"First": (2, 0.75)}
        prior_only = completed(self.root, simulations=0, priors=priors)
        actual = completed(self.root, simulations=2, priors=priors)
        outcomes = [prior_only, actual]
        engine, pool = self.engine(outcomes)
        with patch.object(engine, "_search_single") as fallback:
            ranked = engine.search(self.root, time_budget_ms=1, priors=priors)
        fallback.assert_not_called()
        self.assertEqual((ranked, engine.last_sims), merge_results(outcomes, self.root))
        self.assertEqual(sum(row.visits for row in ranked), 2 + 2 * 6)
        pool.terminate.assert_not_called()
        self.assert_fallback([([], 0), actual], priors=priors)

    def test_each_legal_target_and_duplicate_card_keeps_its_prior_visits(self):
        self.root.hand[1] = self.root.hand[0]
        self.root.enemies.append(self.root.enemies[0].clone())
        self.original = copy.deepcopy(self.root)
        priors = {"First": (100, 0.5)}
        actual = completed(self.root, simulations=0, priors=priors)
        engine, _ = self.engine([actual, actual])
        with patch.object(engine, "_search_single") as fallback:
            ranked = engine.search(self.root, time_budget_ms=1, priors=priors)
        fallback.assert_not_called()
        self.assertEqual(engine.last_sims, 0)
        self.assertEqual(sum(row.visits for row in ranked), 2 * 4 * 30)
        self.assertEqual(
            {row.action for row in ranked},
            {Action(card, target) for card in range(2) for target in range(2)})
        self.assertEqual(self.root, self.original)

    def test_zero_absent_and_empty_name_priors_keep_actual_worker_semantics(self):
        self.root.hand[0].name = ""
        self.original = copy.deepcopy(self.root)
        priors = {"": (9, 0.5), "Second": (0, 1.0), "Absent": (7, 0.5)}
        outcome = completed(self.root, simulations=0, priors=priors)
        self.assertEqual(outcome, ([], 0))
        engine, pool = self.engine([outcome, outcome])
        with patch.object(engine, "_search_single") as fallback:
            self.assertEqual(engine.search(self.root, time_budget_ms=1,
                                           priors=priors), [])
        fallback.assert_not_called()
        pool.terminate.assert_not_called()
        self.assertEqual(self.root, self.original)

    def test_cleanup_failure_keeps_invalid_result_visible_without_fallback(self):
        engine, pool = self.engine([self.valid, ([(Action(None), 1, float("nan"))], 1)])
        pool.terminate.side_effect = OSError("retirement failed")
        with (patch.object(engine, "_search_single") as fallback,
              self.assertRaisesRegex(
                  ValueError, "Invalid timed worker result") as caught):
            engine.search(self.root, time_budget_ms=1)
        fallback.assert_not_called()
        self.assertIs(engine._pool, pool)
        self.assertTrue(engine._retirement_pending)
        self.assertTrue(any("OSError" in note for note in caught.exception.__notes__))
        pool.join.assert_not_called()
        pool.terminate.side_effect = None
        engine.close()

    def test_raw_merge_api_still_accepts_statistics_without_worker_policy(self):
        # Direct merge remains an arithmetic helper, not a worker receipt gate.
        rows, count = merge_results([([(Action(None), 1, 0.5)], 8)], self.root)
        self.assertEqual(count, 8)
        self.assertEqual((rows[0].visits, rows[0].win_rate), (1, 0.5))


if __name__ == "__main__":
    unittest.main()
