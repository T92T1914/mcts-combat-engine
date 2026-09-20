"""Opening-book data must not fabricate evidence or poison root statistics."""
import math
import random
import unittest
from unittest.mock import patch

from engine.mcts import MCTS
from engine.parallel import ParallelMCTS
from game.content import SCENARIOS


class PriorTests(unittest.TestCase):
    def setUp(self):
        self.state, _ = SCENARIOS['duel'](random.Random(1))
        self.state.player.pips = 7
        self.name = self.state.hand[0].name

    def test_invalid_book_rejected_before_sampling_or_spawning(self):
        entries = [
            None, (), (1,), (1, .5, 2), 'bad',
            (-1, .5), (True, .5), (1.5, .5), ('1', .5),
            (1, -0.1), (1, 1.1), (1, True), (1, '0.5'),
            (1, float('nan')), (1, float('inf')), (1, 10**400),
        ]
        books = [[], False, {None: (1, .5)}]
        books += [{self.name: entry} for entry in entries]
        # An absent card still belongs to the book's validation boundary.
        books.append({'card not in this hand': (1, float('nan'))})
        for engine in (MCTS(), ParallelMCTS(workers=2)):
            for book in books:
                with self.subTest(engine=type(engine).__name__, book=book):
                    rngs = ([engine.rng] if isinstance(engine, MCTS)
                            else [engine._rng, engine._single.rng])
                    before = [rng.getstate() for rng in rngs]
                    with patch('engine.parallel.ParallelMCTS._ensure_pool') as pool:
                        with self.assertRaises(ValueError):
                            engine.search(self.state, 100, book)
                        pool.assert_not_called()
                    self.assertEqual([rng.getstate() for rng in rngs], before)
                    self.assertEqual(engine.last_sims, 0)

    def test_zero_observations_do_not_create_virtual_visits(self):
        for engine in (MCTS(), ParallelMCTS(workers=2)):
            self.assertEqual(engine.search(self.state, 0, {self.name: (0, .9)}), [])

    def test_valid_json_pairs_keep_capped_visits_and_bounded_rewards(self):
        for games, reward, visits in [(1, 0, 3), (4, .7, 12), (100, 1, 30)]:
            with self.subTest(games=games):
                ranked = MCTS().search(self.state, 0, {self.name: [games, reward]})
                self.assertTrue(ranked)
                self.assertTrue(all(row.visits == visits for row in ranked))
                for row in ranked:
                    self.assertTrue(math.isfinite(row.win_rate))
                    self.assertAlmostEqual(row.win_rate, reward)

    def test_valid_empty_and_zero_books_do_not_change_seeded_search(self):
        def run(book):
            engine = MCTS(max_sims=150, rng=random.Random(42))
            return engine.search(self.state, 60000, book)
        baseline = run(None)
        self.assertEqual(run({}), baseline)
        self.assertEqual(run({self.name: (0, .9)}), baseline)
