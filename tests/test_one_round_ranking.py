"""Inspect reference values without changing the comparator's sampling policy."""
import dataclasses
import random
import unittest
from unittest.mock import patch

from engine import Action, Card, CardType, Combatant, Element, GameState, legal_actions
from game.baselines import one_round_decider
from game.content import SCENARIOS
from game.runner import play_game


def position(*cards):
    return GameState(
        Combatant("P", Element.EMBER, hp=200, max_hp=1000, pips=7,
                  power_pip_chance=0.0),
        [Combatant("E", Element.FROST, hp=1000, max_hp=1000, pips=7,
                   policy={"attack": 1.0}, power_pip_chance=0.0,
                   base_attack=Card("Reply", accuracy=1.0,
                                    damage_min=300, damage_max=300))],
        list(cards),
    )


ATTACK = Card("Hit", accuracy=1.0, damage_min=100, damage_max=100)
HEAL = Card("Heal", card_type=CardType.HEAL, accuracy=1.0, heal=600)
SHIELD = Card("Shield", card_type=CardType.SHIELD, accuracy=1.0, modifier=0.7)


class OneRoundRankingTests(unittest.TestCase):
    def test_hand_checked_heal_shield_and_losing_actions(self):
        state = position(ATTACK, HEAL, SHIELD)
        before = state.clone()
        rankings, evaluations, work = [], [], []
        chosen = one_round_decider(
            3, on_ranking=rankings.append, on_evaluation=evaluations.append,
            on_work=work.append,
        )(state, random.Random(7))
        self.assertEqual(chosen, Action(1))
        self.assertEqual(len(rankings), 1)
        ranking = rankings[0]
        self.assertIsInstance(ranking, tuple)
        self.assertEqual([row.action for row in ranking],
                         [Action(1), Action(2), Action(None), Action(0, 0)])
        # Heal leaves 500/1000 player HP, shield leaves 110/1000, and
        # both attacks/pass die. Enemy HP remains full except after attack,
        # but a terminal loss is 0 rather than partial heuristic credit.
        expected = [0.25, 0.055, 0.0, 0.0]
        for row, value in zip(ranking, expected, strict=True):
            self.assertEqual(row.samples, 3)
            self.assertAlmostEqual(row.mean_value, value)
            self.assertAlmostEqual(row.value_sum, 3 * value)
        self.assertEqual(evaluations, [12])
        self.assertEqual(work[0]["completed_sweeps"], 3)
        self.assertEqual(state, before)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            ranking[0].samples = 999
        with self.assertRaises(dataclasses.FrozenInstanceError):
            ranking[0].action.card_idx = 999

    def test_terminal_successor_and_duplicate_actions_keep_identity(self):
        finish = Card("Finish", accuracy=1.0, damage_min=1000, damage_max=1000)
        state = position(finish, finish, HEAL)
        actions = legal_actions(state)
        rankings = []
        with patch("game.baselines.legal_actions", return_value=actions[::-1]):
            chosen = one_round_decider(2, on_ranking=rankings.append)(
                state, random.Random(2))
        self.assertEqual(chosen, Action(0, 0))
        first, second = rankings[0][:2]
        self.assertEqual((first.action, second.action), (Action(0, 0), Action(1, 0)))
        self.assertEqual((first.value_sum, second.value_sum), (2.0, 2.0))
        self.assertEqual((first.mean_value, second.mean_value), (1.0, 1.0))
        self.assertEqual({row.action for row in rankings[0]}, set(actions))

    def test_collecting_rankings_preserves_choice_rng_and_work(self):
        for scenario in SCENARIOS:
            state, _ = SCENARIOS[scenario](random.Random(7))
            state.player.pips = 7
            for controls in ({"samples_per_action": 3}, {"max_transitions": 31}):
                with self.subTest(scenario=scenario, controls=controls):
                    plain_rng, observed_rng = random.Random(9), random.Random(9)
                    plain_work, observed_work, rankings = [], [], []
                    plain = one_round_decider(on_work=plain_work.append, **controls)
                    observed = one_round_decider(
                        on_work=observed_work.append, on_ranking=rankings.append,
                        **controls)
                    expected = plain(state, plain_rng)
                    chosen = observed(state, observed_rng)
                    self.assertEqual(chosen, expected)
                    self.assertEqual(chosen, rankings[0][0].action)
                    self.assertEqual(plain_rng.getstate(), observed_rng.getstate())
                    self.assertEqual(plain_work, observed_work)
                    record = observed_work[0]
                    self.assertEqual(sum(row.samples for row in rankings[0]),
                                     record["transitions"])
                    self.assertTrue(all(row.samples == record["completed_sweeps"]
                                        for row in rankings[0]))

    def test_partial_time_allowance_reports_only_the_completed_sweep(self):
        state = position(ATTACK, HEAL, SHIELD)
        rankings, work = [], []
        rng = random.Random(3)
        reference = random.Random(3)
        reference.getrandbits(64)  # One seed for all four candidates.
        choose = one_round_decider(
            max_transitions=19, time_budget_ms=1000,
            on_ranking=rankings.append, on_work=work.append)
        with patch("game.baselines.time.perf_counter", side_effect=[0, 0, 1]):
            chosen = choose(state, rng)
        self.assertEqual(chosen, rankings[0][0].action)
        self.assertEqual([row.samples for row in rankings[0]], [1] * 4)
        self.assertEqual(work[0]["transitions"], 4)
        self.assertEqual(work[0]["unused_transitions"], 15)
        self.assertEqual(work[0]["stop_reasons"], ["time_limit"])
        self.assertEqual(rng.getstate(), reference.getstate())

    def test_existing_episode_caller_preserves_outcome_and_both_random_streams(self):
        # The benchmark passes this Decider into the same episode runner.
        # Three ordinary rounds exercise refilling and changing hand indexes
        # without collecting another study or writing an outcome export.
        def run(reporting):
            env_rng = random.Random(12)
            policy_rng = random.Random(7)
            state, deck = SCENARIOS["duel"](env_rng)
            decisions, rankings = [], []
            choose = one_round_decider(
                2, on_ranking=rankings.append if reporting else None)

            def record(current, rng):
                action = choose(current, rng)
                decisions.append(action)
                if reporting:
                    self.assertEqual(rankings[-1][0].action, action)
                    self.assertEqual({row.action for row in rankings[-1]},
                                     set(legal_actions(current)))
                return action

            score = play_game(state, deck, record, env_rng, max_rounds=3,
                              policy_rng=policy_rng)
            return (score, state, decisions, env_rng.getstate(),
                    policy_rng.getstate()), rankings

        plain, _ = run(False)
        observed, snapshots = run(True)
        self.assertEqual(plain, observed)
        self.assertEqual(len(snapshots), len(observed[2]))
        self.assertEqual(len(snapshots), 3)

    def test_no_completed_sweep_emits_no_unevaluated_candidate(self):
        state = position(ATTACK, HEAL)
        rng = random.Random(4)
        before_rng = rng.getstate()
        rankings, work = [], []
        choose = one_round_decider(
            max_transitions=10, time_budget_ms=0,
            on_ranking=rankings.append, on_work=work.append)
        with (patch("game.baselines.time.perf_counter", side_effect=[0, 0]),
              self.assertRaisesRegex(ValueError, "complete sweep")):
            choose(state, rng)
        self.assertEqual(rankings, [()])
        self.assertEqual(work[0]["transitions"], 0)
        self.assertEqual(rng.getstate(), before_rng)

        rankings.clear()
        with self.assertRaisesRegex(ValueError, "complete sweep"):
            one_round_decider(max_transitions=2, on_ranking=rankings.append)(state, rng)
        self.assertEqual(rankings, [])
        self.assertEqual(rng.getstate(), before_rng)

    def test_terminal_root_and_later_decisions_have_separate_snapshots(self):
        state = position(ATTACK, HEAL)
        snapshots = []
        choose = one_round_decider(1, on_ranking=snapshots.append)
        rng = random.Random(4)
        choose(state, rng)
        first = snapshots[0]
        retained = tuple((row.action, row.samples, row.value_sum) for row in first)
        state.player.hp = 0
        before_rng = rng.getstate()
        self.assertEqual(choose(state, rng), Action(None))
        self.assertEqual(snapshots[1], ())
        self.assertEqual(rng.getstate(), before_rng)
        self.assertEqual(
            tuple((row.action, row.samples, row.value_sum) for row in first), retained)


if __name__ == "__main__":
    unittest.main()
