"""Independent resource outcomes for the enemy's two-pip healing policy."""
import random
import unittest

from engine.actions import PASS
from engine.mcts import MCTS
from engine.simulator import advance_round, enemy_act
from engine.state import Combatant, Element, GameState


def position(pips=0, power_pips=1, hp=100, max_hp=1000):
    return GameState(
        Combatant("P", Element.EMBER, 1000, 1000, power_pip_chance=0.0),
        [Combatant("E", Element.FROST, hp, max_hp, pips=pips,
                   power_pips=power_pips, power_pip_chance=0.0,
                   policy={"heal": 1.0})],
        [],
    )


class EnemyPolicyHealTests(unittest.TestCase):
    def test_resource_outcomes_match_hand_checked_payment_table(self):
        # A heal costs two of the enemy's own elemental pips. One power pip
        # pays that cost. Otherwise two normal pips are needed. Expected
        # values do not call effective_pips() or spend_pips().
        cases = [
            # normal, power, healed HP, remaining normal, remaining power
            (0, 0, 100, 0, 0),
            (1, 0, 100, 1, 0),
            (2, 0, 280, 0, 0),
            (3, 0, 280, 1, 0),
            (0, 1, 280, 0, 0),
            (1, 1, 280, 1, 0),
            (2, 1, 280, 2, 0),
            (3, 1, 280, 3, 0),
            (0, 2, 280, 0, 1),
            (1, 2, 280, 1, 1),
            (2, 2, 280, 2, 1),
            (3, 2, 280, 3, 1),
        ]
        for normal, power, healed, left_normal, left_power in cases:
            with self.subTest(normal=normal, power=power):
                state = position(normal, power)
                enemy = state.enemies[0]
                enemy_act(state, enemy, random.Random(7))
                self.assertEqual((enemy.hp, enemy.pips, enemy.power_pips),
                                 (healed, left_normal, left_power))
                self.assertEqual(state.player.hp, 1000)

    def test_healing_is_capped_and_keeps_integer_rounding(self):
        for hp, max_hp, expected in [(950, 1000, 1000), (1, 101, 19)]:
            with self.subTest(hp=hp, max_hp=max_hp):
                state = position(hp=hp, max_hp=max_hp)
                enemy = state.enemies[0]
                enemy_act(state, enemy, random.Random(7))
                self.assertEqual(enemy.hp, expected)
                self.assertEqual((enemy.pips, enemy.power_pips), (0, 0))

    def test_dead_enemy_or_player_does_not_heal_or_spend(self):
        for dead_player in (False, True):
            with self.subTest(dead_player=dead_player):
                state = position()
                if dead_player:
                    state.player.hp = 0
                else:
                    state.enemies[0].hp = 0
                original = state.clone()
                rng = random.Random(7)
                before_rng = rng.getstate()
                enemy_act(state, state.enemies[0], rng)
                self.assertEqual(state, original)
                self.assertEqual(rng.getstate(), before_rng)

    def test_policy_choice_remains_the_only_random_draw_in_healing(self):
        state = position()
        rng = random.Random(7)
        reference_rng = random.Random(7)
        # The existing weighted policy selection draws once even when
        # its heal is unaffordable. The resource correction adds no draw.
        reference_rng.choices(["heal"], [1.0], k=1)
        enemy_act(state, state.enemies[0], rng)
        self.assertEqual(rng.getstate(), reference_rng.getstate())

    def test_round_and_one_simulation_match_independent_hp_oracle(self):
        state = position()
        original = state.clone()
        successor = state.clone()
        advance_round(successor, PASS, random.Random(7))
        # Heal to 280, spend the power pip, then regenerate one normal pip.
        self.assertEqual((successor.enemies[0].hp, successor.enemies[0].pips,
                          successor.enemies[0].power_pips), (280, 1, 0))
        self.assertEqual(successor.round_num, 2)
        # With no cards, the only root edge is Pass. At a one-round horizon,
        # full player HP and enemy HP 280/1000 give value 0.5 + 0.5 * 0.72.
        search = MCTS(horizon_rounds=1, max_sims=1, max_transitions=1,
                      rng=random.Random(7))
        ranked = search.search(state, time_budget_ms=None)
        self.assertEqual([row.action for row in ranked], [PASS])
        self.assertEqual(ranked[0].visits, 1)
        self.assertAlmostEqual(ranked[0].win_rate, 0.86)
        self.assertEqual((search.last_sims, search.last_transitions), (1, 1))
        self.assertEqual(state, original)


if __name__ == "__main__":
    unittest.main()
