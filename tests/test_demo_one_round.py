"""Exercise the reference consumer without changing its decision or root."""
import contextlib
import copy
import io
import random
import unittest
from unittest.mock import patch

import demo
from engine import Action
from game.baselines import one_round_decider
from game.content import SCENARIOS


class DemoOneRoundTests(unittest.TestCase):
    def test_three_scenarios_match_direct_policy_and_keep_root(self):
        for scenario in ("duel", "gauntlet", "boss"):
            with self.subTest(scenario=scenario):
                state, _ = SCENARIOS[scenario](random.Random(7))
                before = copy.deepcopy(state)
                rule_state = [(id(rule), copy.deepcopy(vars(rule)))
                              for rule in state.boss_rules]
                # Rules use identity equality, so compare their data separately.
                before.boss_rules = state.boss_rules
                captured = []
                expected = one_round_decider(3, on_ranking=captured.append)(
                    state, random.Random(19))
                output = io.StringIO()
                with (patch("demo.SCENARIOS", {
                        scenario: unittest.mock.Mock(return_value=(state, None))}),
                      patch("demo.MCTS") as search,
                      patch("sys.argv", ["demo.py", scenario,
                                         "--one-round-samples", "3", "--seed", "19"]),
                      contextlib.redirect_stdout(output)):
                    demo.main()
                search.assert_not_called()
                self.assertEqual(state, before)
                self.assertEqual([(id(rule), vars(rule))
                                  for rule in state.boss_rules], rule_state)
                text = output.getvalue()
                rows = captured[-1]
                self.assertIn(f"{len(rows) * 3} sampled rounds", text)
                self.assertIn("3 complete sweeps", text)
                self.assertIn("not win probabilities", text)
                self.assertNotIn("visits", text)
                self.assertIn(f"Recommended: {expected.describe(state)} "
                              f"(hand={expected.card_idx}, "
                              f"target={expected.target_idx})", text)
                for row in rows:
                    self.assertIn(f"{row.mean_value:>8.3f}{row.samples:>10,}", text)

    def test_same_labels_keep_distinct_hand_and_target_indexes(self):
        state, _ = SCENARIOS["gauntlet"](random.Random(7))
        # An inert consumer fixture makes equal labels and ties explicit.
        state.hand = [state.hand[0], state.hand[0]]
        state.enemies[1].name = state.enemies[0].name
        actions = (Action(None), Action(0, 0), Action(1, 0), Action(1, 1))
        from game.baselines import OneRoundActionValue
        rows = tuple(OneRoundActionValue(action, 2, 1.0) for action in actions)

        def policy(samples, *, on_ranking):
            def choose(root, rng):
                on_ranking(rows)
                return rows[0].action
            return choose

        output = io.StringIO()
        with (patch("demo.one_round_decider", policy),
              contextlib.redirect_stdout(output)):
            demo.show_one_round(state, 2, 7)
        lines = output.getvalue().splitlines()
        for action in actions[1:]:
            self.assertTrue(any(
                line.startswith(action.describe(state))
                and line.split()[-4:] == [str(action.card_idx),
                                         str(action.target_idx), "0.500", "2"]
                for line in lines))
        self.assertIn("Recommended: Pass (hand=None, target=None)", output.getvalue())

    def test_invalid_or_conflicting_modes_fail_before_scenario_creation(self):
        cases = (["--one-round-samples", "0"],
                 ["--one-round-samples", "-2"],
                 ["--one-round-samples", "x"],
                 ["--one-round-samples", "2", "--sims", "2"],
                 ["--one-round-samples", "2", "--budget-ms", "0"],
                 ["--one-round-samples", "2", "--horizon", "1"])
        for arguments in cases:
            with self.subTest(arguments=arguments):
                scenario = unittest.mock.Mock()
                with (patch("demo.SCENARIOS", {"boss": scenario}),
                      patch("sys.argv", ["demo.py", *arguments]),
                      contextlib.redirect_stderr(io.StringIO()),
                      self.assertRaises(SystemExit) as caught):
                    demo.main()
                self.assertEqual(caught.exception.code, 2)
                scenario.assert_not_called()

    def test_terminal_reference_has_no_sampled_recommendation(self):
        state, _ = SCENARIOS["duel"](random.Random(7))
        for enemy in state.enemies:
            enemy.hp = 0
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            demo.show_one_round(state, 2, 7)
        self.assertIn("0 actions, 0 complete sweeps, 0 sampled rounds",
                      output.getvalue())
        self.assertIn("no recommendation is available", output.getvalue())
        self.assertNotIn("Recommended:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
