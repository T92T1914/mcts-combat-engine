"""The node counting pass enumerates every chance outcome the engine can take."""
import random
import unittest

from engine import Card, CardType, Combatant, Element, GameState, legal_actions
from engine.actions import PASS, Action
from engine.simulator import advance_round
from tools.endgame_node_count import PathRng, count_tree, outcomes, state_key


def no_damage_enemy(hp=50, pips=7):
    return Combatant("E", Element.FROST, hp=hp, max_hp=hp, pips=pips,
                     policy={"attack": 1.0}, base_attack=Card("No damage"))


def sure_hit_position():
    hit = Card("Hit", card_type=CardType.DAMAGE, accuracy=1.0,
               damage_min=60, damage_max=60)
    return GameState(
        Combatant("P", Element.EMBER, hp=100, max_hp=100, pips=7),
        [no_damage_enemy()], [hit])


def noisy_position():
    cards = [
        Card("Wide", card_type=CardType.DAMAGE, pip_cost=1, accuracy=0.8,
             damage_min=10, damage_max=14),
        Card("Edge", card_type=CardType.BLADE, accuracy=1.0, modifier=0.35),
    ]
    enemy = Combatant(
        "E", Element.FROST, hp=60, max_hp=60, pips=2,
        policy={"attack": 0.5, "shield": 0.3, "blade": 0.2, "heal": 0.0},
        base_attack=Card("Strike", card_type=CardType.DAMAGE, pip_cost=1,
                         accuracy=0.9, damage_min=5, damage_max=7))
    player = Combatant("P", Element.EMBER, hp=100, max_hp=100, pips=2,
                       power_pip_chance=0.6)
    return GameState(player, [enemy], cards)


class OutcomeTests(unittest.TestCase):
    def test_every_sampled_round_is_an_enumerated_outcome(self):
        state = noisy_position()
        for action in legal_actions(state):
            def run(rng, a=action):
                return advance_round(state.clone(), a, rng)
            enumerated = {state_key(after) for after in outcomes(run)}
            for seed in range(400):
                sampled = advance_round(
                    state.clone(), action, random.Random(seed))
                self.assertIn(state_key(sampled), enumerated)

    def test_a_sure_card_has_no_fizzle_branch(self):
        state = sure_hit_position()
        action = Action(card_idx=0, target_idx=0)

        def run(rng):
            return advance_round(state.clone(), action, rng)
        # The enemy is down, both sides hold seven pips and nothing is drawn.
        self.assertEqual(sum(1 for _ in outcomes(run)), 1)

    def test_a_zero_weight_option_is_never_chosen(self):
        rng = PathRng([])
        self.assertEqual(rng.choices(["a", "b"], weights=[0.0, 1.0]), ["b"])
        self.assertEqual(rng.widths, [])

    def test_an_unbranched_draw_is_refused(self):
        with self.assertRaises(NotImplementedError):
            PathRng([]).getrandbits(8)
        with self.assertRaises(NotImplementedError):
            PathRng([]).choices([1, 2], k=2)


class CountTests(unittest.TestCase):
    def test_hand_counted_two_round_tree(self):
        state = sure_hit_position()
        found = count_tree(state, 2, branch_cap=1000)
        # Round one: Hit has one outcome, Pass has a miss and a land that
        # leave the same state. Round two repeats that from the Pass state.
        self.assertEqual(found["status"], "fits")
        self.assertEqual(found["branches"], 6)
        # The start, a win, the Pass state of round two and the round limit.
        self.assertEqual(found["nodes"], 4)

    def test_one_round_tree_ends_at_the_limit(self):
        found = count_tree(sure_hit_position(), 1, branch_cap=1000)
        self.assertEqual((found["branches"], found["nodes"]), (3, 3))

    def test_the_branch_cap_stops_the_count(self):
        found = count_tree(noisy_position(), 6, branch_cap=500)
        self.assertEqual(found["status"], "over_branches")
        self.assertGreater(found["branches"], 500)

    def test_the_cards_in_a_hand_are_a_multiset(self):
        state = noisy_position()
        other = state.clone()
        other.hand.reverse()
        self.assertEqual(state_key(state), state_key(other))
        self.assertNotEqual(state_key(state),
                            state_key(advance_round(state.clone(), PASS,
                                                    random.Random(1))))


if __name__ == "__main__":
    unittest.main()
