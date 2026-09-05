"""Parallel search tests: the root merge is exact, and the pool round-trips."""
import random
import unittest

from engine import Action, legal_actions
from engine.parallel import ParallelMCTS, merge_results
from game.content import SCENARIOS


def _root_state():
    """A duel opening with the whole hand affordable, so the root has several
    legal actions (at zero pips only Pass and free cards are legal)."""
    state, _ = SCENARIOS["duel"](random.Random(1))
    state.player.pips = 7
    return state


class TestMerge(unittest.TestCase):
    def test_visits_and_value_sums_add_across_workers(self):
        state = _root_state()
        a = Action(card_idx=None)                 # Pass
        b = Action(card_idx=0, target_idx=0)      # hand[0] at the enemy
        worker_1 = ([(a, 10, 6.0), (b, 5, 1.0)], 15)
        worker_2 = ([(b, 20, 12.0), (a, 2, 0.0)], 22)
        ranked, total = merge_results([worker_1, worker_2], state)

        self.assertEqual(total, 37)
        by_action = {r.action: r for r in ranked}
        self.assertEqual(by_action[a].visits, 12)
        self.assertAlmostEqual(by_action[a].win_rate, 6.0 / 12)
        self.assertEqual(by_action[b].visits, 25)
        self.assertAlmostEqual(by_action[b].win_rate, 13.0 / 25)
        # 0.52 beats 0.50: ranked by merged mean, not by either worker's
        self.assertEqual(ranked[0].action, b)
        self.assertEqual(ranked[0].label, b.describe(state))

    def test_merge_is_not_an_average_of_rates(self):
        # worker 1 saw action a win 1/1; worker 2 saw it win 10/100. The
        # merged rate must be 11/101, not the mean of 100% and 10%.
        state = _root_state()
        a = Action(card_idx=0, target_idx=0)
        ranked, _ = merge_results([([(a, 1, 1.0)], 1),
                                   ([(a, 100, 10.0)], 100)], state)
        self.assertAlmostEqual(ranked[0].win_rate, 11.0 / 101)


class TestPool(unittest.TestCase):
    def _check(self, engine: ParallelMCTS) -> None:
        state = _root_state()
        self.assertGreater(len(legal_actions(state)), 3)
        try:
            ranked = engine.search(state, time_budget_ms=150)
        finally:
            engine.close()
        # every simulation passes through exactly one root action, so the
        # merged visit counts must add up to the reported total
        self.assertTrue(ranked)
        self.assertEqual(sum(r.visits for r in ranked), engine.last_sims)
        # and every legal root action was expanded by at least one worker
        self.assertEqual({r.label for r in ranked},
                         {a.describe(state) for a in legal_actions(state)})

    def test_two_spawned_workers_merge_to_the_sum_of_their_simulations(self):
        self._check(ParallelMCTS(horizon_rounds=3, workers=2))

    def test_single_worker_falls_through_to_the_plain_search(self):
        self._check(ParallelMCTS(horizon_rounds=3, workers=1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
