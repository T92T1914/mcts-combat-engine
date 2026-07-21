"""Engine tests: mechanics, search sanity, and 'beats the baselines'.

Pure standard library — run with ``python -m pytest`` or ``python -m unittest``.
"""
import random
import unittest

from engine import (Action, Card, CardType, Charm, Combatant, Element,
                    GameState, advance_round, legal_actions)
from engine.mcts import MCTS
from engine.simulator import resolve_damage
from game.baselines import greedy_decider, mcts_decider, random_decider
from game.content import SCENARIOS
from game.runner import play_match

E = Element.EMBER


def _combatant(**kw):
    base = dict(name="X", element=E, hp=1000, max_hp=1000)
    base.update(kw)
    return Combatant(**base)


class TestMechanics(unittest.TestCase):
    def test_blade_multiplies_then_is_consumed(self):
        atk = _combatant(blades=[Charm(0.35, E)])
        tgt = _combatant()
        dealt = resolve_damage(atk, tgt, 100, E)
        self.assertEqual(dealt, 135)          # 100 * 1.35
        self.assertEqual(atk.blades, [])       # blade spent

    def test_shield_reduces_incoming(self):
        tgt = _combatant(shields=[Charm(-0.70, E)])
        dealt = resolve_damage(_combatant(), tgt, 100, E)
        self.assertEqual(dealt, 30)            # 100 * 0.30

    def test_resist_and_offschool_charm_not_consumed(self):
        tgt = _combatant(resist={E: 0.25}, traps=[Charm(0.30, Element.FROST)])
        dealt = resolve_damage(_combatant(), tgt, 100, E)
        self.assertEqual(dealt, 75)            # frost trap ignored, 25% resist
        self.assertEqual(len(tgt.traps), 1)    # off-element trap survives

    def test_power_pips_double_on_element(self):
        c = _combatant(element=E, pips=1, power_pips=2)
        self.assertEqual(c.effective_pips(E), 5)          # 1 + 2*2
        self.assertEqual(c.effective_pips(Element.FROST), 3)  # 1 + 2*1

    def test_dot_ticks_then_expires(self):
        state = GameState(
            player=_combatant(name="P"),
            enemies=[_combatant(name="Boss", is_boss=True, hp=1000, max_hp=1000)],
            hand=[Card("Burn", E, CardType.DAMAGE, pip_cost=0, accuracy=1.0,
                       damage_min=0, damage_max=0, dot_tick=100, dot_rounds=2)],
        )
        rng = random.Random(0)
        # fully deterministic: the card is 100% accurate with 0 direct damage,
        # the enemy has no resist and never damages itself — so each tick is
        # exactly 100 and there are exactly two of them
        advance_round(state, Action(card_idx=0, target_idx=0), rng)  # applies DoT + 1 tick
        self.assertEqual(state.enemies[0].hp, 900)
        advance_round(state, Action(card_idx=None), rng)             # 2nd tick
        self.assertEqual(state.enemies[0].hp, 800)
        advance_round(state, Action(card_idx=None), rng)             # expired
        self.assertEqual(state.enemies[0].hp, 800)
        self.assertEqual(len(state.enemies[0].dots), 0)


class TestActions(unittest.TestCase):
    def test_pass_always_legal_unaffordable_excluded(self):
        state = GameState(
            player=_combatant(pips=0, power_pips=0),
            enemies=[_combatant(name="e")],
            hand=[Card("Pricey", E, CardType.DAMAGE, pip_cost=5)],
        )
        acts = legal_actions(state)
        self.assertTrue(any(a.is_pass for a in acts))
        self.assertTrue(all(a.card_idx is None for a in acts))  # can't afford

    def test_damage_card_enumerates_one_action_per_living_enemy(self):
        state = GameState(
            player=_combatant(pips=7),
            enemies=[_combatant(name="a"), _combatant(name="b", hp=0, max_hp=1000)],
            hand=[Card("Hit", E, CardType.DAMAGE, pip_cost=1)],
        )
        targeted = [a for a in legal_actions(state) if a.card_idx == 0]
        self.assertEqual(len(targeted), 1)     # only the living enemy


class TestSearch(unittest.TestCase):
    def test_clone_is_deep_where_it_must_be(self):
        state, _ = SCENARIOS["duel"](random.Random(1))
        enemy_hp = state.enemies[0].hp
        enemy_pips = (state.enemies[0].pips, state.enemies[0].power_pips)
        clone = state.clone()
        advance_round(clone, Action(card_idx=None), random.Random(1))
        # mutating the clone must not touch the original — including the
        # enemies, whose pips regenerated inside the clone
        self.assertEqual(state.round_num, 1)
        self.assertIsNot(state.player, clone.player)
        self.assertIsNot(state.enemies[0], clone.enemies[0])
        self.assertEqual(state.enemies[0].hp, enemy_hp)
        self.assertEqual(
            (state.enemies[0].pips, state.enemies[0].power_pips), enemy_pips)

    def test_search_finds_lethal_over_stalling(self):
        # one Fire Blast (440-520) kills a 300-HP enemy; Pass does not
        state = GameState(
            player=_combatant(name="P", pips=7, hp=2000, max_hp=2000),
            enemies=[_combatant(name="Wisp", hp=300, max_hp=300)],
            hand=[Card("Fire Blast", E, CardType.DAMAGE, pip_cost=4,
                       accuracy=1.0, damage_min=440, damage_max=520)],
        )
        ranked = MCTS(horizon_rounds=3).search(state, time_budget_ms=200)
        self.assertFalse(ranked[0].action.is_pass)
        self.assertGreater(ranked[0].win_rate, 0.9)

    def test_determinism_under_fixed_seed(self):
        # a wall-clock budget varies the sim count run to run, so pin the
        # stopping criterion to max_sims — then a fixed seed must reproduce
        # the tree statistics exactly
        def run():
            m = MCTS(horizon_rounds=4)
            m.max_sims = 1500
            m.rng = random.Random(123)
            s, _ = SCENARIOS["duel"](random.Random(1))
            return [(r.label, r.visits)
                    for r in m.search(s, time_budget_ms=60_000)]
        self.assertEqual(run(), run())


class TestBeatsBaselines(unittest.TestCase):
    """The headline claim: search dominates the naive policies on the boss.

    The boss is tuned to be genuinely hard, so the claim is a wide MARGIN
    over the baselines, not a near-certain win. Deterministic because game
    seeds are paired across policies AND the search pins both its seed and
    its simulation count — a seed alone is not enough, since a wall-clock
    budget stops at a machine-dependent number of simulations.
    """

    def test_mcts_beats_random_and_greedy_on_the_boss(self):
        games = 30
        mcts = mcts_decider(budget_ms=60_000, horizon=5, seed=42,
                            max_sims=3000)
        rnd = play_match(SCENARIOS["boss"], random_decider, games=games)
        grd = play_match(SCENARIOS["boss"], greedy_decider, games=games)
        mct = play_match(SCENARIOS["boss"], mcts, games=games)
        self.assertGreaterEqual(mct["win_rate"], grd["win_rate"] + 0.25)
        self.assertGreaterEqual(mct["win_rate"], rnd["win_rate"] + 0.25)
        self.assertGreater(mct["win_rate"], 0.4)
        self.assertGreater(mct["avg_score"], rnd["avg_score"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
