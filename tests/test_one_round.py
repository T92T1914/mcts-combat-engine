"""One-round enumeration can value actions the damage-only baseline ignores."""
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
from engine import Action, Card, CardType, Combatant, Element, GameState, legal_actions
from engine.simulator import advance_round
from game.baselines import greedy_decider, one_round_decider
from game.content import SCENARIOS


def _state(*cards, enemy_hp=1000):
    return GameState(
        player=Combatant("P", Element.EMBER, hp=200, max_hp=1000, pips=7),
        enemies=[Combatant(
            "E", Element.FROST, hp=enemy_hp, max_hp=1000, pips=7,
            policy={"attack": 1.0},
            base_attack=Card("Hit", accuracy=1.0, damage_min=300, damage_max=300))],
        hand=list(cards))


ATTACK = Card("Hit", accuracy=1.0, damage_min=100, damage_max=100)
HEAL = Card("Heal", card_type=CardType.HEAL, accuracy=1.0, heal=600)
SHIELD = Card("Shield", card_type=CardType.SHIELD, accuracy=1.0, modifier=0.7)


class TestOneRound(unittest.TestCase):
    def test_heals_when_every_attack_dies(self):
        state = _state(ATTACK, HEAL)
        self.assertEqual(greedy_decider(state, random.Random(1)), Action(0, 0))
        self.assertEqual(one_round_decider()(state, random.Random(1)), Action(1))

    def test_defends_when_no_heal_is_available(self):
        state = _state(ATTACK, SHIELD)
        self.assertEqual(one_round_decider()(state, random.Random(1)), Action(1))

    def test_terminal_win_is_preferred_to_healing(self):
        state = _state(HEAL, ATTACK, enemy_hp=100)
        self.assertEqual(one_round_decider()(state, random.Random(1)), Action(1, 0))

    def test_finished_position_consumes_no_samples(self):
        state = _state(ATTACK, enemy_hp=0)
        rng = random.Random(7)
        initial = rng.getstate()
        counts = []
        self.assertEqual(one_round_decider(on_evaluation=counts.append)(state, rng),
                         Action(None))
        self.assertEqual(rng.getstate(), initial)
        self.assertEqual(counts, [0])

    def test_shared_starting_samples_and_work_counts_preserve_root(self):
        state = _state(ATTACK, HEAL, SHIELD)
        original = state.clone()
        sampled = {}
        counts = []

        def capture(successor, action, rng):
            sampled.setdefault(action, []).append(rng.getstate())
            return advance_round(successor, action, rng)

        with mock.patch("game.baselines.advance_round", capture):
            chosen = one_round_decider(3, on_evaluation=counts.append)(
                state, random.Random(5))
        self.assertEqual(state, original)
        self.assertIn(chosen, legal_actions(state))
        actions = legal_actions(state)
        self.assertEqual(counts, [3 * len(actions)])
        self.assertEqual(len(sampled), len(actions))
        for seeds in sampled.values():
            self.assertEqual(seeds, sampled[actions[0]])

    def test_candidate_enumeration_order_and_ties_do_not_change_choice(self):
        state, _ = SCENARIOS["duel"](random.Random(7))
        state.player.pips = 7
        actions = legal_actions(state)
        policy = one_round_decider(4)
        forward = policy(state, random.Random(9))
        with mock.patch("game.baselines.legal_actions", return_value=actions[::-1]):
            backward = policy(state, random.Random(9))
        self.assertEqual(forward, backward)
        # Duplicate attacks have equal successor values. Stable hand index wins.
        tied = _state(ATTACK, ATTACK, enemy_hp=100)
        with mock.patch("game.baselines.legal_actions",
                        return_value=legal_actions(tied)[::-1]):
            self.assertEqual(policy(tied, random.Random(9)), Action(0, 0))

    def test_invalid_sample_counts_fail_before_a_policy_is_created(self):
        for samples in (0, -1, True, 1.5, "8"):
            with self.subTest(samples=samples), self.assertRaises(ValueError):
                one_round_decider(samples)

    def test_none_selects_the_documented_default_eight_samples(self):
        # None now distinguishes the default from an explicit sample cap when
        # callers select the alternative transition-allowance mode.
        state = _state(ATTACK, HEAL)
        default_rng, explicit_rng = random.Random(4), random.Random(4)
        counts = []
        chosen = one_round_decider(None, on_evaluation=counts.append)(
            state, default_rng)
        expected = one_round_decider(8)(state, explicit_rng)
        self.assertEqual(chosen, expected)
        self.assertEqual(default_rng.getstate(), explicit_rng.getstate())
        self.assertEqual(counts, [8 * len(legal_actions(state))])

    def test_cli_records_comparator_and_separate_work_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "result.json"
            markdown = Path(tmp) / "result.md"
            argv = ["benchmark.py", "1", "--sims", "3", "--one-round-samples", "2",
                    "--json", str(output), "--markdown", str(markdown)]
            with (mock.patch.object(sys, "argv", argv),
                  contextlib.redirect_stdout(io.StringIO())):
                benchmark.main()
            report = json.loads(output.read_text("utf-8"))
            self.assertEqual(report["settings"]["one_round_samples_per_action"], 2)
            for row in report["results"].values():
                work = row["one_round (2 samples/action)"]["one_round_work"]
                self.assertEqual(work["samples_per_action"], 2)
                self.assertEqual(work["horizon_rounds"], 1)
                self.assertTrue(work["decision_transitions"])
                self.assertTrue(all(n >= 2 and n % 2 == 0
                                    for n in work["decision_transitions"]))
                self.assertEqual(row["mcts (3 sims)"]["search_work"]
                                 ["below_requested_simulations"], 0)
                for result in row.values():
                    games = result["game_results"]
                    self.assertEqual(len(games), result["games"])
                    self.assertEqual([g["environment_seed"] for g in games], [0])
                    self.assertEqual([g["policy_seed"] for g in games], [0])
                    self.assertEqual(sum(g["clean_win"] for g in games), result["wins"])
                    self.assertEqual(sum(g["score"] for g in games) / len(games),
                                     result["avg_score"])
            text = markdown.read_text("utf-8")
            self.assertIn("successor transitions", text)
            self.assertIn("Compute is not equalized", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
