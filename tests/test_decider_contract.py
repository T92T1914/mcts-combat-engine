"""Reject search controls that the parallel wrapper cannot honor."""
import random
import unittest
from unittest import mock

from engine import Action, legal_actions
from engine.parallel import ParallelMCTS
from game.baselines import mcts_decider
from game.content import SCENARIOS


class TestDeciderContract(unittest.TestCase):
    def test_parallel_rejects_seed_or_simulation_cap(self):
        for workers in (None, 1, 2):
            for controls in ({"seed": 0}, {"max_sims": 0},
                             {"seed": 7, "max_sims": 10}):
                with self.subTest(workers=workers, controls=controls):
                    with (mock.patch("game.baselines.ParallelMCTS") as factory,
                          self.assertRaisesRegex(ValueError, "single-process")):
                        mcts_decider(parallel=True, workers=workers, **controls)
                    factory.assert_not_called()

    def test_serial_seed_and_cap_remain_supported(self):
        state, _ = SCENARIOS["duel"](random.Random(5))
        state.player.pips = 7

        def run():
            counts = []
            decider = mcts_decider(seed=0, max_sims=30, budget_ms=60_000,
                                   on_search=counts.append)
            action = decider(state, random.Random(99))
            self.assertIn(action, legal_actions(state))
            self.assertEqual(counts, [30])
            return action

        self.assertEqual(run(), run())

    def test_serial_zero_cap_remains_a_valid_no_search(self):
        counts = []
        state, _ = SCENARIOS["duel"](random.Random(5))
        decider = mcts_decider(seed=0, max_sims=0, on_search=counts.append)
        self.assertEqual(decider(state, random.Random(99)), Action(card_idx=None))
        self.assertEqual(counts, [0])

    def test_timed_parallel_still_works_with_one_and_two_workers(self):
        state, _ = SCENARIOS["duel"](random.Random(5))
        state.player.pips = 7
        for workers in (1, 2):
            with self.subTest(workers=workers):
                engine = ParallelMCTS(horizon_rounds=2, workers=workers)
                counts = []
                owned_workers = []
                try:
                    with mock.patch("game.baselines.ParallelMCTS", return_value=engine):
                        decider = mcts_decider(parallel=True, workers=workers,
                                               horizon=2, budget_ms=150,
                                               on_search=counts.append)
                    action = decider(state, random.Random(99))
                    self.assertIn(action, legal_actions(state))
                    self.assertEqual(counts, [engine.last_sims])
                    self.assertGreater(counts[0], 0)
                    if workers == 2:
                        # A silent serial fallback would not verify this path.
                        self.assertIsNotNone(engine._pool)
                        owned_workers = list(engine._pool._pool)
                        self.assertEqual(len(owned_workers), 2)
                finally:
                    engine.close()
                self.assertIsNone(engine._pool)
                self.assertTrue(all(not worker.is_alive() for worker in owned_workers))


if __name__ == "__main__":
    unittest.main(verbosity=2)
