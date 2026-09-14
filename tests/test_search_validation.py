"""Configuration failures must be detected before sampling or spawning."""
import contextlib
import io
import random
import unittest
from unittest.mock import patch

import demo
from engine.mcts import MCTS
from engine.parallel import ParallelMCTS
from game.content import SCENARIOS


class SearchValidationTests(unittest.TestCase):
    def setUp(self):
        self.state, _ = SCENARIOS['duel'](random.Random(1))

    def test_invalid_dataclass_configuration(self):
        for key, values in (
            ('horizon_rounds', (0, -1, True, 1.5)),
            ('max_sims', (-1, True, 2.5)),
            ('exploration', (-1, True, float('nan'), float('inf'))),
        ):
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    MCTS(**{key: value})

    def test_mutated_configuration_is_checked_before_search(self):
        engine = MCTS()
        engine.max_sims = -1
        with self.assertRaises(ValueError):
            engine.search(self.state)
        self.assertEqual(engine.last_sims, 0)

    def test_invalid_budget_never_starts_a_pool_or_changes_rng(self):
        for engine in (MCTS(), ParallelMCTS(workers=2)):
            for budget in (-1, True, '10', float('nan'), float('inf')):
                with self.subTest(engine=type(engine).__name__, budget=budget):
                    rng = engine.rng if isinstance(engine, MCTS) else engine._rng
                    state = rng.getstate()
                    with patch('engine.parallel.ParallelMCTS._ensure_pool') as pool:
                        with self.assertRaises(ValueError):
                            engine.search(self.state, time_budget_ms=budget)
                        pool.assert_not_called()
                    self.assertEqual(rng.getstate(), state)

    def test_zero_budget_preserves_single_search_semantics_without_pool(self):
        priors = {self.state.hand[0].name: (3, .7)}
        single, parallel = MCTS(), ParallelMCTS(workers=2)
        with patch.object(parallel, '_ensure_pool') as pool:
            self.assertEqual(parallel.search(self.state, 0, priors),
                             single.search(self.state, 0, priors))
            pool.assert_not_called()
        self.assertEqual(parallel.last_sims, 0)

    def test_zero_simulation_cap_and_finite_fractional_budget_remain_valid(self):
        engine = MCTS(max_sims=0, exploration=0)
        self.assertEqual(engine.search(self.state, .5), [])

    def test_zero_budget_demo_explains_the_empty_result(self):
        for option in ('--sims', '--budget-ms'):
            output = io.StringIO()
            with (self.subTest(option=option),
                  patch('sys.argv', ['demo.py', option, '0']),
                  contextlib.redirect_stdout(output)):
                demo.main()
                self.assertIn('no recommendation is available', output.getvalue())
                self.assertNotIn('Recommended:', output.getvalue())
