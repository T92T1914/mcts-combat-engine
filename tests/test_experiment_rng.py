"""Regression cases for independent policy and environment randomness."""
import contextlib
import io
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import benchmark
from engine import Action
from game.baselines import greedy_decider, mcts_decider
from game.content import SCENARIOS
from game.runner import play_game, play_match


class TestExperimentRandomness(unittest.TestCase):
    def test_unused_policy_draws_do_not_change_environment(self):
        def play(extra_draws):
            rng = random.Random(12)
            state, deck = SCENARIOS["boss"](rng)

            def policy(state, policy_rng):
                for _ in range(extra_draws):
                    policy_rng.random()
                return greedy_decider(state, policy_rng)

            score = play_game(state, deck, policy, rng)
            return score, state, rng.getstate()

        self.assertEqual(play(0), play(17))

    def test_scenario_order_does_not_change_fixed_budget_results(self):
        def run(names):
            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / "results.json"
                argv = ["benchmark.py", "2", "--sims", "30", "--seed", "7",
                        "--json", str(output)]
                scenarios = {name: SCENARIOS[name] for name in names}
                with (mock.patch.object(sys, "argv", argv),
                      mock.patch.object(benchmark, "SCENARIOS", scenarios),
                      contextlib.redirect_stdout(io.StringIO())):
                    benchmark.main()
                return json.loads(output.read_text(encoding="utf-8"))["results"]

        self.assertEqual(run(["duel", "boss"]), run(["boss", "duel"]))

    def test_explicit_policy_rng_is_used_without_sharing_environment_state(self):
        env_rng = random.Random(12)
        policy_rng = random.Random(99)
        state, deck = SCENARIOS["duel"](env_rng)
        observed = []

        def decide(state, rng):
            observed.append(rng.random())
            return Action(card_idx=None)

        play_game(state, deck, decide, env_rng, max_rounds=2, policy_rng=policy_rng)
        expected = random.Random(99)
        self.assertEqual(observed, [expected.random(), expected.random()])

    def test_policy_rng_cannot_be_the_environment_rng(self):
        rng = random.Random(12)
        state, deck = SCENARIOS["duel"](rng)
        before = rng.getstate()
        with self.assertRaisesRegex(ValueError, "must be separate"):
            play_game(state, deck, greedy_decider, rng, policy_rng=rng)
        self.assertEqual(rng.getstate(), before)

    def test_match_policy_seed_is_independent_of_environment_seed(self):
        draws = []
        environment_openings = []

        def scenario(rng):
            state, deck = SCENARIOS["duel"](rng)
            environment_openings.append(state.clone())
            return state, deck

        def decide(state, rng):
            if state.round_num == 1:
                draws.append(rng.random())
            return Action(card_idx=None)

        for policy_seed in (6, 9, 6):
            play_match(scenario, decide, games=2, seed=4, policy_seed=policy_seed)
        self.assertEqual(draws[:2], draws[4:])
        self.assertNotEqual(draws[:2], draws[2:4])
        self.assertEqual(environment_openings[:2], environment_openings[2:4])
        self.assertEqual(draws[:2], [random.Random(f"policy-v1:{s}").random()
                                          for s in (6, 7)])

    def test_observer_reports_executed_simulations_when_clock_stops_search(self):
        counts = []
        decider = mcts_decider(budget_ms=60_000, seed=7, max_sims=4,
                               on_search=counts.append)
        state, _ = SCENARIOS["duel"](random.Random(4))
        # Deadline at 60, one iteration at 0, then time 61 stops the search.
        with mock.patch("engine.mcts.time.perf_counter", side_effect=[0, 0, 61]):
            decider(state, random.Random(1))
        self.assertEqual(counts, [1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
