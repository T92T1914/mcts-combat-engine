"""Finished positions and invalid worker requests must not consume a search pool."""
import random
import unittest
from unittest.mock import patch

from engine.mcts import MCTS
from engine.parallel import ParallelMCTS
from game.content import SCENARIOS


class SearchLifecycleTests(unittest.TestCase):
    def test_terminal_search_has_no_actions_or_simulations_even_with_priors(self):
        for lost in (False, True):
            with self.subTest(lost=lost):
                state, _ = SCENARIOS['duel'](random.Random(1))
                state.player.pips = 7
                if lost:
                    state.player.hp = 0
                else:
                    for enemy in state.enemies:
                        enemy.hp = 0
                engine = MCTS(max_sims=10)
                engine.last_sims = 99
                rng = engine.rng.getstate()
                priors = {card.name: (10, 0.8) for card in state.hand}
                self.assertEqual(engine.search(state, priors=priors), [])
                self.assertEqual(engine.last_sims, 0)
                self.assertEqual(engine.rng.getstate(), rng)

    def test_terminal_parallel_search_does_not_start_workers(self):
        state, _ = SCENARIOS['duel'](random.Random(1))
        state.player.hp = 0
        engine = ParallelMCTS(workers=2)
        engine.last_sims = 99
        with patch.object(engine, '_ensure_pool') as pool:
            self.assertEqual(engine.search(state), [])
        pool.assert_not_called()
        self.assertEqual(engine.last_sims, 0)

    def test_invalid_worker_counts_do_not_silently_choose_a_pool_size(self):
        for workers in (0, -1, True, False, 1.5, '2'):
            with self.subTest(workers=workers), self.assertRaises(ValueError):
                ParallelMCTS(workers=workers)

    def test_only_none_selects_the_automatic_worker_count(self):
        with patch('engine.parallel.mp.cpu_count', return_value=16):
            self.assertEqual(ParallelMCTS().workers, 10)
            self.assertEqual(ParallelMCTS(workers=1).workers, 1)


if __name__ == '__main__':
    unittest.main()
