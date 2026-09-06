"""Regressions for stochastic availability and shifting hand positions."""
import random
import unittest
from unittest.mock import patch

from engine.actions import PASS, Action, legal_actions
from engine.mcts import MCTS, _available_actions
from engine.simulator import advance_round
from engine.state import Card, CardType, Combatant, Element, GameState


def position():
    return GameState(
        Combatant('P', Element.EMBER, 1000, 1000, pips=1, power_pip_chance=0.5),
        [Combatant('E', Element.EMBER, 10000, 10000, policy={'shield': 1})],
        [Card('Hit A', Element.EMBER, CardType.DAMAGE, 3, 1, 50, 50),
         Card('Heal', Element.EMBER, CardType.HEAL, 2, 1, heal=100),
         Card('Hit B', Element.EMBER, CardType.DAMAGE, 1, 1, 300, 300)],
    )


class ActionIdentityTests(unittest.TestCase):
    def test_stable_edges_survive_hand_removal_and_duplicate_instances(self):
        state = position()
        state.player.pips = 7
        duplicate = state.hand[0]
        state.hand = [duplicate, duplicate, state.hand[1]]
        slots = [0, 1, 2]
        before = _available_actions(state, slots)
        advance_round(state, before[Action(0, 0)], random.Random(0))
        slots.pop(0)
        state.player.pips = 7
        after = _available_actions(state, slots)
        self.assertNotIn(Action(0, 0), after)
        self.assertEqual(after[Action(1, 0)], Action(0, 0))
        self.assertEqual(after[Action(2)], Action(1))
        self.assertIs(state.hand[after[Action(1, 0)].card_idx], duplicate)

    def test_availability_is_recomputed_after_pips_and_targets_change(self):
        state = position()
        self.assertNotIn(Action(0, 0), _available_actions(state, [0, 1, 2]))
        state.player.power_pips = 1
        self.assertIn(Action(0, 0), _available_actions(state, [0, 1, 2]))
        state.enemies[0].hp = 0
        self.assertNotIn(Action(0, 0), _available_actions(state, [0, 1, 2]))

    def test_invalid_indices_and_targets_behave_exactly_like_pass(self):
        for action in [Action(-1, 0), Action(100, 0), Action(2),
                       Action(2, -1), Action(2, 100), Action(1, 0)]:
            with self.subTest(action=action):
                state = position()
                state.player.pips = 7
                expected = state.clone()
                advance_round(state, action, random.Random(9))
                advance_round(expected, PASS, random.Random(9))
                self.assertEqual(state, expected)

    def test_every_simulated_action_is_legal_under_stochastic_pips(self):
        calls = 0
        max_round = 0

        def checked(state, action, rng):
            nonlocal calls, max_round
            self.assertIn(action, legal_actions(state))
            calls += 1
            max_round = max(max_round, state.round_num)
            return advance_round(state, action, rng)

        search = MCTS(horizon_rounds=6, max_sims=1500, rng=random.Random(0))
        with patch('engine.mcts.advance_round', checked):
            ranked = search.search(position(), time_budget_ms=60000)
        self.assertEqual(search.last_sims, 1500)
        self.assertGreater(calls, 1500)
        self.assertLessEqual(max_round, 6)
        self.assertTrue(all(r.action in legal_actions(position()) for r in ranked))
        self.assertEqual(sum(r.visits for r in ranked), 1500)
