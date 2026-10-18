"""Deterministic boundaries of the retained shaped objective, not policy claims."""
import unittest

from engine import Combatant, Element, GameState
from engine.mcts import MCTS


class RewardContract(unittest.TestCase):
    def test_terminal_win_discount_stops_at_depth_six(self):
        scorer = MCTS(horizon_rounds=8)
        for depth, expected in ((0, 1.0), (5, 0.775), (6, 0.73), (7, 0.73)):
            with self.subTest(depth=depth):
                self.assertEqual(scorer._terminal_reward(1.0, depth), expected)

    def test_terminal_loss_depth_scales_then_stops_at_each_horizon(self):
        # Power-of-two horizons give exact binary64 scaling of the saved 0.15.
        # Expected payoffs are declared independently of the product formula.
        cases = {
            4: ((0, 0.0), (1, 0.0375), (2, 0.075), (4, 0.15), (5, 0.15)),
            8: ((0, 0.0), (1, 0.01875), (4, 0.075), (8, 0.15), (9, 0.15)),
        }
        for horizon, payoffs in cases.items():
            scorer = MCTS(horizon_rounds=horizon)
            for depth, expected in payoffs:
                with self.subTest(horizon=horizon, depth=depth):
                    self.assertEqual(scorer._terminal_reward(0.0, depth), expected)

    def test_living_horizon_state_can_score_below_a_terminal_loss(self):
        state = GameState(
            player=Combatant(name="P", element=Element.EMBER, hp=1, max_hp=100),
            enemies=[Combatant(name="E", element=Element.EMBER, hp=100, max_hp=100)],
            hand=[],
        )
        self.assertIsNone(state.result())
        ongoing = state.heuristic_value()
        self.assertGreater(ongoing, 0.0)
        self.assertLess(ongoing, 0.01)
        self.assertLess(ongoing, MCTS(horizon_rounds=4)._terminal_reward(0.0, 1))


if __name__ == "__main__":
    unittest.main()
