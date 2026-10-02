"""The fixed-count demo must use the engine's clockless search contract."""
import contextlib
import copy
import io
import itertools
import random
import unittest
from unittest.mock import patch

import demo
from engine.mcts import MCTS
from game.content import SCENARIOS


class DemoFixedWorkTests(unittest.TestCase):
    def run_demo(self, arguments):
        engines = []
        states = []
        budgets = []
        outcomes = []

        class RecordingMCTS(MCTS):
            def search(self, root_state, time_budget_ms=450, priors=None):
                engines.append(self)
                budgets.append(time_budget_ms)
                before = copy.deepcopy(root_state)
                result = super().search(root_state, time_budget_ms, priors)
                states.append((before, root_state))
                outcomes.append(result)
                return result

        output = io.StringIO()
        # Every observed interval exceeds the former hidden ten-minute limit.
        # This is an inert clock boundary fixture, not a timing measurement.
        ticks = itertools.count(start=0.0, step=601.0)
        with (patch("demo.MCTS", RecordingMCTS),
              patch("sys.argv", ["demo.py", "duel", "--horizon", "1", *arguments]),
              patch("time.perf_counter", side_effect=lambda: next(ticks)),
              contextlib.redirect_stdout(output)):
            demo.main()
        self.assertEqual(len(engines), 1)
        before, root = states[0]
        self.assertEqual(root, before)
        return engines[0], budgets[0], outcomes[0], output.getvalue()

    def test_fixed_count_finishes_despite_clock_jump_and_matches_clockless_engine(self):
        actual, budget, ranked, output = self.run_demo(["--sims", "2", "--seed", "19"])
        self.assertEqual(actual.last_sims, 2)
        self.assertIsNone(budget)
        self.assertEqual(actual.last_stop_reasons, ("simulation_cap",))
        state, _ = SCENARIOS["duel"](random.Random(7))
        reference = MCTS(horizon_rounds=1, max_sims=2, rng=random.Random(19))
        expected = reference.search(state, time_budget_ms=None)
        self.assertEqual(ranked, expected)
        self.assertEqual(actual.last_root_statistics, reference.last_root_statistics)
        self.assertEqual(actual.last_transitions, reference.last_transitions)
        self.assertEqual(actual.rng.getstate(), reference.rng.getstate())
        self.assertIn("2 simulations", output)
        self.assertIn("Recommended:", output)

    def test_fixed_count_keeps_precedence_over_an_explicit_zero_time_budget(self):
        engine, budget, _, _ = self.run_demo(["--sims", "2", "--budget-ms", "0"])
        self.assertEqual(engine.last_sims, 2)
        self.assertIsNone(budget)

    def test_zero_fixed_count_spends_no_randomness_and_explains_empty_result(self):
        engine, budget, ranked, output = self.run_demo(["--sims", "0", "--seed", "23"])
        self.assertIsNone(budget)
        self.assertEqual(engine.last_sims, 0)
        self.assertEqual(engine.rng.getstate(), random.Random(23).getstate())
        self.assertEqual(ranked, [])
        self.assertIn("no recommendation is available", output)
        self.assertNotIn("Recommended:", output)

    def test_default_and_explicit_time_budgets_keep_clock_stopping(self):
        for arguments, expected_budget in (([], 800), (["--budget-ms", "25"], 25),
                                          (["--budget-ms", "0"], 0)):
            with self.subTest(arguments=arguments):
                engine, budget, ranked, output = self.run_demo(arguments)
                self.assertEqual(budget, expected_budget)
                self.assertEqual(engine.max_sims, 1_000_000)
                self.assertEqual(engine.last_sims, 0)
                self.assertEqual(engine.last_stop_reasons, ("time_limit",))
                self.assertEqual(ranked, [])
                self.assertEqual(engine.rng.getstate(), random.Random(7).getstate())
                self.assertIn("no recommendation is available", output)


if __name__ == "__main__":
    unittest.main()
