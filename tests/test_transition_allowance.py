"""Count actual round calls under complete-simulation and equal-sweep allowances."""
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
from engine import Card, CardType, Combatant, Element, GameState, legal_actions
from engine.mcts import MCTS
from engine.simulator import advance_round
from game.baselines import mcts_decider, one_round_decider


def position(cards=()):
    return GameState(
        Combatant("P", Element.EMBER, hp=100, max_hp=100, pips=7),
        [Combatant("E", Element.FROST, hp=100, max_hp=100, pips=7,
                   policy={"attack": 1.0}, base_attack=Card("No damage"))],
        list(cards))


class TestTransitionSearch(unittest.TestCase):
    def test_whole_horizons_count_both_selection_and_rollout(self):
        search = MCTS(horizon_rounds=4, max_sims=100, max_transitions=27,
                      rng=random.Random(4))
        calls = []
        rollout_depths = []
        original_rollout = search._rollout

        def counted(state, action, rng):
            calls.append(state.round_num)
            return advance_round(state, action, rng)

        def rollout(state, depth):
            rollout_depths.append(depth)
            return original_rollout(state, depth)

        state = position()
        before = state.clone()
        with (mock.patch("engine.mcts.advance_round", counted),
              mock.patch.object(search, "_rollout", rollout)):
            ranked = search.search(state, 60000)
        self.assertEqual(search.last_sims, 6)
        self.assertEqual(search.last_transitions, len(calls))
        self.assertEqual(calls, [1, 2, 3, 4] * 6)
        self.assertEqual(search.last_unused_transitions, 3)
        self.assertEqual(search.last_stop_reasons, ("transition_allowance",))
        self.assertEqual(rollout_depths[:4], [1, 2, 3, 4])
        self.assertEqual(sum(r.visits for r in ranked), 6)
        self.assertEqual(state, before)

    def test_terminal_successor_returns_unused_reservation(self):
        calls = []

        def finish(state, action, rng):
            calls.append(action)
            state.enemies[0].hp = 0
            return state

        search = MCTS(horizon_rounds=4, max_sims=100, max_transitions=11)
        with mock.patch("engine.mcts.advance_round", finish):
            ranked = search.search(position(), 60000)
        self.assertEqual(len(calls), 8)
        self.assertEqual(search.last_sims, 8)
        self.assertEqual(search.last_transitions, 8)
        self.assertEqual(search.last_unused_transitions, 3)
        self.assertEqual(ranked[0].visits, 8)
        self.assertAlmostEqual(ranked[0].win_rate, 0.955)

    def test_zero_and_undersized_core_allowance_do_not_draw(self):
        for allowance in (0, 1, 3):
            search = MCTS(horizon_rounds=4, max_transitions=allowance,
                          rng=random.Random(7))
            before = search.rng.getstate()
            self.assertEqual(search.search(position(), 60000), [])
            self.assertEqual(search.rng.getstate(), before)
            self.assertEqual(search.last_transitions, 0)
            self.assertEqual(search.last_unused_transitions, allowance)
            self.assertEqual(search.last_stop_reasons, ("transition_allowance",))

    def test_finished_root_has_no_work_or_randomness(self):
        search = MCTS(max_transitions=10, rng=random.Random(1))
        state = position()
        state.player.hp = 0
        before = search.rng.getstate()
        self.assertEqual(search.search(state, priors={"Missing": (2, 0.8)}), [])
        self.assertEqual(search.rng.getstate(), before)
        self.assertEqual((search.last_sims, search.last_transitions), (0, 0))
        self.assertEqual(search.last_unused_transitions, 10)
        self.assertEqual(search.last_stop_reasons, ("terminal",))

    def test_invalid_and_mutated_allowances_fail_before_draws(self):
        for value in (-1, True, 1.5, "4", float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                MCTS(max_transitions=value)
        search = MCTS(max_sims=1)
        search.search(position(), 60000)
        before = search.rng.getstate()
        search.max_transitions = -1
        with self.assertRaises(ValueError):
            search.search(position(), 60000)
        self.assertEqual(search.rng.getstate(), before)
        self.assertEqual((search.last_sims, search.last_transitions), (0, 0))
        self.assertIsNone(search.last_unused_transitions)
        self.assertEqual(search.last_stop_reasons, ())

    def test_abundant_allowance_preserves_seeded_search_and_rng(self):
        cards = [Card("Hit", damage_min=10, damage_max=40),
                 Card("Heal", card_type=CardType.HEAL, heal=30)]
        state = position(cards)
        for seed in (0, 7, 42):
            plain = MCTS(4, 1.2, 23, random.Random(seed))
            capped = MCTS(4, 1.2, 23, random.Random(seed), max_transitions=1000)
            self.assertEqual(plain.search(state, 60000), capped.search(state, 60000))
            self.assertEqual(plain.rng.getstate(), capped.rng.getstate())
            self.assertEqual(plain.last_transitions, capped.last_transitions)
            self.assertEqual(capped.last_stop_reasons, ("simulation_cap",))

    def test_time_stop_keeps_complete_simulation_and_distinct_reason(self):
        search = MCTS(horizon_rounds=4, max_transitions=100)
        with mock.patch("engine.mcts.time.perf_counter", side_effect=[0, 0, 60]):
            search.search(position(), 60000)
        self.assertEqual((search.last_sims, search.last_transitions), (1, 4))
        self.assertEqual(search.last_unused_transitions, 96)
        self.assertEqual(search.last_stop_reasons, ("time_limit",))

    def test_exhausted_allowance_needs_no_later_clock_check(self):
        search = MCTS(horizon_rounds=4, max_transitions=5)
        with mock.patch("engine.mcts.time.perf_counter", side_effect=[0, 0]):
            search.search(position(), 60000)
        self.assertEqual(search.last_stop_reasons, ("transition_allowance",))
        self.assertEqual(search.last_unused_transitions, 1)

    def test_wrapper_rejects_unsupported_and_no_sample_controls(self):
        for controls in ({"max_transitions": 10}, {"on_work": lambda work: None}):
            with (mock.patch("game.baselines.ParallelMCTS") as factory,
                  self.assertRaisesRegex(ValueError, "single-process")):
                mcts_decider(parallel=True, **controls)
            factory.assert_not_called()
        with self.assertRaisesRegex(ValueError, "complete horizon"):
            mcts_decider(horizon=4, max_transitions=3)
        records = []
        decide = mcts_decider(horizon=4, max_transitions=10, on_work=records.append)
        with (mock.patch("engine.mcts.time.perf_counter", side_effect=[0, 1]),
              self.assertRaisesRegex(ValueError, "complete simulation")):
            decide(position(), random.Random(1))
        self.assertEqual(records[0]["transitions"], 0)
        self.assertEqual(records[0]["stop_reasons"], ["time_limit"])


class TestTransitionComparator(unittest.TestCase):
    def setUp(self):
        self.state = position([Card("A"), Card("B")])  # pass plus two attacks

    def test_complete_sweeps_use_identical_draws_per_candidate(self):
        observed = {}
        records = []

        def counted(state, action, rng):
            observed.setdefault(action, []).append(rng.getstate())
            return advance_round(state, action, rng)

        before = self.state.clone()
        with mock.patch("game.baselines.advance_round", counted):
            chosen = one_round_decider(max_transitions=11, on_work=records.append)(
                self.state, random.Random(6))
        self.assertIn(chosen, legal_actions(self.state))
        self.assertEqual(self.state, before)
        self.assertEqual(len(observed), 3)
        streams = list(observed.values())
        self.assertEqual(streams, [streams[0]] * 3)
        self.assertEqual(len(streams[0]), 3)
        self.assertEqual(records[0], {
            "max_transitions": 11, "transitions": 9, "unused_transitions": 2,
            "actions": 3, "intended_sweeps": 3, "completed_sweeps": 3,
            "stop_reasons": ["transition_allowance"]})

    def test_undersized_sweep_fails_before_randomness(self):
        for allowance in (0, 1, 2):
            rng = random.Random(7)
            before = rng.getstate()
            with self.assertRaisesRegex(ValueError, "complete sweep"):
                one_round_decider(max_transitions=allowance)(self.state, rng)
            self.assertEqual(rng.getstate(), before)

    def test_expired_huge_allowance_does_not_materialize_seeds(self):
        rng = random.Random(7)
        records = []
        decide = one_round_decider(max_transitions=10**30, time_budget_ms=0,
                                   on_work=records.append)
        with (mock.patch.object(rng, "getrandbits", side_effect=AssertionError),
              self.assertRaisesRegex(ValueError, "complete sweep")):
            decide(self.state, rng)
        self.assertEqual(records[0]["transitions"], 0)
        self.assertEqual(records[0]["stop_reasons"], ["time_limit"])

    def test_time_limit_keeps_whole_sweep(self):
        records = []
        decide = one_round_decider(max_transitions=11, time_budget_ms=1000,
                                   on_work=records.append)
        with mock.patch("game.baselines.time.perf_counter", side_effect=[0, 0, 1]):
            self.assertIn(decide(self.state, random.Random(2)),
                          legal_actions(self.state))
        self.assertEqual(records[0]["transitions"], 3)
        self.assertEqual(records[0]["completed_sweeps"], 1)
        self.assertEqual(records[0]["unused_transitions"], 8)
        self.assertEqual(records[0]["stop_reasons"], ["time_limit"])

    def test_budget_equivalent_to_fixed_samples_and_invalid_settings(self):
        first, second = random.Random(2), random.Random(2)
        self.assertEqual(one_round_decider(3)(self.state, first),
                         one_round_decider(max_transitions=11)(self.state, second))
        self.assertEqual(first.getstate(), second.getstate())
        for value in (-1, True, 1.5, "4", float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                one_round_decider(max_transitions=value)
        with self.assertRaisesRegex(ValueError, "not both"):
            one_round_decider(3, max_transitions=11)
        with self.assertRaises(ValueError):
            one_round_decider(time_budget_ms=-1)


class TestTransitionBenchmark(unittest.TestCase):
    @staticmethod
    def scenario(rng):
        card = Card("Finish", damage_min=100, damage_max=100, accuracy=1)
        return position([card]), [card]

    def run_tiny(self, folder):
        output, markdown = folder / "out.json", folder / "out.md"
        argv = ["benchmark.py", "1", "--transitions", "11", "--seed", "9",
                "--json", str(output), "--markdown", str(markdown)]
        with (mock.patch.object(sys, "argv", argv),
              mock.patch.object(benchmark, "SCENARIOS", {"synthetic": self.scenario}),
              contextlib.redirect_stdout(io.StringIO()) as console):
            benchmark.main()
        return json.loads(output.read_text()), markdown.read_text(), console.getvalue()

    def test_export_reconciles_rounds_actual_calls_and_allowances(self):
        with tempfile.TemporaryDirectory() as temporary:
            report, text, console = self.run_tiny(Path(temporary))
            repeated, _, _ = self.run_tiny(Path(temporary))
        self.assertEqual(report["results"], repeated["results"])
        self.assertEqual(report["schema_version"], 3)
        settings = report["settings"]
        self.assertEqual(settings["mode"], "transition_allowance")
        self.assertEqual(settings["max_simulations"], settings["max_transitions"])
        self.assertEqual(settings["time_limit_ms"], 60000)
        self.assertEqual(settings["one_round_time_limit_ms"], 60000)
        self.assertEqual(settings["search_seed"], 9)
        for label in ("mcts (11 transitions)", "one_round (11 transitions)"):
            result = report["results"]["synthetic"][label]
            work = result["transition_work"]
            self.assertEqual(work["incomplete_decisions"], [])
            self.assertEqual(len(work["decision_records"]),
                             sum(game["rounds"] for game in result["game_results"]))
            for record in work["decision_records"]:
                self.assertEqual(record["transitions"] + record["unused_transitions"],
                                 11)
                self.assertEqual(record["stop_reasons"], ["transition_allowance"])
        for output in (text, console):
            self.assertNotIn("z =", output)
            self.assertNotIn("Wilson", output)
        self.assertIn("unused allowance", text)

    def test_invalid_cli_modes_do_not_start_games(self):
        for extra in (["--transitions", "4"],
                      ["--transitions", "10", "--sims", "2"],
                      ["--transitions", "10", "--one-round-samples", "2"]):
            with (mock.patch.object(sys, "argv", ["benchmark.py", *extra]),
                  mock.patch.object(benchmark, "play_match") as play,
                  contextlib.redirect_stderr(io.StringIO()),
                  self.assertRaises(SystemExit)):
                benchmark.main()
            play.assert_not_called()


if __name__ == "__main__":
    unittest.main()
