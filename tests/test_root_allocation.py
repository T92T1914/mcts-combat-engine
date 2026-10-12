"""Optional root allocation boundaries and retained UCT compatibility witnesses."""
import json
import random
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from engine.actions import PASS, Action, legal_actions
from engine.mcts import MCTS, _available_actions
from engine.simulator import advance_round
from engine.state import Card, CardType, Combatant, Element, GameState
from game.episode_decision import _reconstruct

ROOT = Path(__file__).resolve().parents[1]


def coordinates(action):
    return {"card_idx": action.card_idx, "target_idx": action.target_idx}


def position(cards=(), enemies=1):
    waiting = Card("Wait", pip_cost=1, accuracy=1)
    return GameState(
        Combatant("P", Element.EMBER, 100, 100, power_pip_chance=0),
        [Combatant(f"E{i}", Element.FROST, 100, 100,
                   power_pip_chance=0, base_attack=waiting)
         for i in range(enemies)],
        list(cards))


def equal_arms(count):
    if count == 8:
        return position([Card("Choice", card_type=CardType.UTILITY, accuracy=1)] * 7)
    duplicate = Card("No damage", accuracy=1)
    cards = [duplicate] * 5
    if count == 12:
        cards.append(Card("Choice", card_type=CardType.UTILITY, accuracy=1))
    return position(cards, enemies=2)


def halving(sims=32, transitions=32, seed=17):
    return MCTS(horizon_rounds=1, max_sims=sims, max_transitions=transitions,
                rng=random.Random(seed), root_allocation="sequential_halving")


class RootAllocationTests(unittest.TestCase):
    def test_pinned_schedules_count_real_calls_and_keep_physical_ties(self):
        schedules = (
            (8, ((8, 1), (4, 3), (2, 6)), 0),
            (11, ((11, 1), (6, 1), (3, 2), (2, 4)), 1),
            (12, ((12, 1), (6, 1), (3, 2), (2, 4)), 0),
        )
        for count, phases, remainder in schedules:
            with self.subTest(actions=count):
                state = equal_arms(count)
                before = state.clone()
                actions = legal_actions(state)
                self.assertEqual(len(actions), count)
                calls = []

                def counted(successor, action, rng, trace=calls):
                    self.assertIn(action, legal_actions(successor))
                    trace.append(action)
                    return advance_round(successor, action, rng)

                search = halving()
                with patch("engine.mcts.advance_round", counted):
                    ranked = search.search(state, time_budget_ms=None)
                expected = [action for size, quota in phases
                            for action in actions[:size] * quota]
                expected += [PASS] * remainder
                self.assertEqual(calls, expected)
                self.assertEqual(state, before)
                self.assertEqual((search.last_sims, search.last_transitions), (32, 32))
                self.assertEqual(search.last_unused_transitions, 0)
                self.assertEqual(search.last_stop_reasons,
                                 ("transition_allowance", "simulation_cap"))
                diagnostic = search.last_root_allocation
                self.assertEqual(diagnostic["policy"],
                                 "budget_aware_sequential_halving_v1")
                self.assertEqual(diagnostic["mode"], "halving")
                self.assertTrue(diagnostic["complete"])
                self.assertEqual(diagnostic["selections"], 32)
                self.assertEqual(diagnostic["reward_updates"], 32)
                self.assertEqual(diagnostic["elimination_rounds"], len(phases))
                self.assertEqual(diagnostic["elimination_key_evaluations"],
                                 sum(size for size, _ in phases))
                self.assertEqual(diagnostic["remainder_samples"], remainder)
                self.assertEqual(diagnostic["winner"], coordinates(PASS))
                for actual, (size, quota) in zip(diagnostic["phases"], phases,
                                                strict=True):
                    self.assertEqual(actual["active"],
                                     [coordinates(a) for a in actions[:size]])
                    self.assertEqual(actual["quota"], quota)
                    self.assertEqual(actual["completed_samples"], size * quota)
                    self.assertEqual(
                        actual["survivors"],
                        [coordinates(a) for a in actions[:(size + 1) // 2]])
                    self.assertEqual(actual["statistics"], [
                        {"action": coordinates(a), "visits": quota,
                         "value_sum": 0.5 * quota, "mean": 0.5}
                        for a in actions[:size]])
                raw = {a: (v, total) for a, v, total in search.last_root_statistics}
                self.assertEqual(set(raw), set(actions))
                self.assertEqual({a: v for a, (v, _) in raw.items()},
                                 dict(Counter(calls)))
                self.assertEqual(sum(v for v, _ in raw.values()), 32)
                for row in ranked:
                    visits, total = raw[row.action]
                    self.assertEqual(row.visits, visits)
                    self.assertEqual(row.win_rate.hex(), (total / visits).hex())
                self.assertEqual(ranked[0].action, PASS)
                json.dumps(diagnostic, allow_nan=False)

    def test_phase_local_elimination_can_override_cumulative_raw_mean(self):
        # Scripted bounded observations isolate allocation bookkeeping. They
        # are not independent evidence for a combat value or policy quality.
        state = position([Card("Choice", card_type=CardType.UTILITY)] * 3)
        actions = legal_actions(state)
        calls = []
        visits = Counter()

        def scripted_transition(_state, action, _rng):
            calls.append(action)
            visits[action] += 1

        def scripted_reward(_state, _depth):
            action = calls[-1]
            first_phase = (1.0, 0.25, 0.125, 0.0)
            if visits[action] <= 3:
                return first_phase[actions.index(action)]
            return 0.5 if action == PASS else 0.625

        search = halving(sims=28, transitions=28)
        with (patch("engine.mcts.advance_round", scripted_transition),
              patch.object(search, "_rollout", scripted_reward)):
            ranked = search.search(state, time_budget_ms=None)
        self.assertEqual(calls, actions * 3 + actions[:2] * 8)
        first, second = search.last_root_allocation["phases"]
        self.assertEqual((first["quota"], second["quota"]), (3, 8))
        self.assertEqual(second["survivors"], [coordinates(Action(0))])
        self.assertEqual([row["value_sum"] for row in second["statistics"]], [4.0, 5.0])
        raw = {a: (v, total) for a, v, total in search.last_root_statistics}
        self.assertEqual(raw[PASS], (11, 7.0))
        self.assertEqual(raw[Action(0)], (11, 5.75))
        self.assertGreater(raw[PASS][1] / 11, raw[Action(0)][1] / 11)
        self.assertEqual(ranked[0].action, Action(0))
        self.assertEqual(ranked[1].action, PASS)
        self.assertEqual((len(calls), search.last_sims, search.last_transitions),
                         (28, 28, 28))

    def test_tiny_allowance_has_no_elimination_or_invented_unvisited_values(self):
        state = equal_arms(8)
        actions = legal_actions(state)
        for usable in (1, 3, 13):
            with self.subTest(usable=usable):
                calls = []

                def counted(successor, action, rng, trace=calls):
                    trace.append(action)
                    return advance_round(successor, action, rng)

                search = halving(sims=100, transitions=usable)
                with patch("engine.mcts.advance_round", counted):
                    ranked = search.search(state, time_budget_ms=None)
                self.assertEqual(calls, [actions[i % 8] for i in range(usable)])
                self.assertEqual(search.last_root_allocation["mode"],
                                 "uniform_fallback")
                self.assertEqual(search.last_root_allocation["phases"], [])
                self.assertEqual(search.last_root_allocation["elimination_rounds"], 0)
                self.assertEqual(
                    search.last_root_allocation["elimination_key_evaluations"], 0)
                self.assertEqual({r.action for r in ranked}, set(calls))
                expected = sorted(set(calls), key=lambda a, trace=calls, order=actions:
                                  (-trace.count(a), order.index(a)))
                self.assertEqual([row.action for row in ranked], expected)
                self.assertEqual(sum(row.visits for row in ranked), usable)
                self.assertEqual(search.last_sims, usable)
                self.assertEqual(search.last_transitions, len(calls))
                self.assertEqual(search.last_unused_transitions, 0)

    def test_minimum_elimination_budget_and_smaller_cap_are_respected(self):
        state = equal_arms(8)
        for sims, transitions, usable, mode in (
                (14, 32, 14, "halving"), (32, 13, 13, "uniform_fallback"),
                (14, None, 14, "halving"), (35, 32, 32, "halving")):
            with self.subTest(sims=sims, transitions=transitions):
                search = halving(sims, transitions)
                with patch("engine.mcts.advance_round", wraps=advance_round) as rounds:
                    search.search(state, time_budget_ms=None)
                self.assertEqual(rounds.call_count, usable)
                self.assertEqual((search.last_sims, search.last_transitions),
                                 (usable, usable))
                self.assertEqual(search.last_root_allocation["usable_allowance"],
                                 usable)
                self.assertEqual(search.last_root_allocation["mode"], mode)
                self.assertTrue(search.last_root_allocation["complete"])

    def test_zero_and_terminal_searches_have_no_randomness_or_fabricated_winner(self):
        for sims, transitions, terminal in ((0, 32, False), (32, 0, False),
                                             (32, 32, True)):
            with self.subTest(sims=sims, transitions=transitions, terminal=terminal):
                state = equal_arms(8)
                if terminal:
                    state.player.hp = 0
                search = halving(sims, transitions)
                before = search.rng.getstate()
                with patch("engine.mcts.advance_round", wraps=advance_round) as rounds:
                    self.assertEqual(search.search(state, time_budget_ms=None), [])
                rounds.assert_not_called()
                self.assertEqual(search.rng.getstate(), before)
                self.assertEqual((search.last_sims, search.last_transitions), (0, 0))
                self.assertEqual(search.last_root_statistics, [])
                self.assertTrue(search.last_root_allocation["complete"])
                self.assertIsNone(search.last_root_allocation["winner"])
                self.assertEqual(search.last_root_allocation["selections"], 0)
                if terminal:
                    self.assertEqual(search.last_stop_reasons, ("terminal",))
                    self.assertEqual(search.last_root_allocation["mode"], "terminal")

    def test_pass_only_root_spends_its_entire_allowance(self):
        search = halving(sims=7, transitions=11)
        with patch("engine.mcts.advance_round", wraps=advance_round) as rounds:
            ranked = search.search(position(), time_budget_ms=None)
        self.assertEqual(rounds.call_count, 7)
        self.assertEqual([(r.action, r.visits, r.win_rate) for r in ranked],
                         [(PASS, 7, 0.5)])
        self.assertEqual(search.last_root_allocation["phases"], [])
        self.assertEqual(search.last_root_allocation["remainder_samples"], 7)
        self.assertEqual(search.last_unused_transitions, 4)
        self.assertEqual(search.last_stop_reasons, ("simulation_cap",))

    def test_unsupported_configurations_refuse_before_sampling(self):
        for policy in (None, True, "unknown", "UCT"):
            rng = random.Random(19)
            before = rng.getstate()
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                MCTS(horizon_rounds=1, rng=rng, root_allocation=policy)
            self.assertEqual(rng.getstate(), before)
        for horizon in (2, 4):
            rng = random.Random(19)
            before = rng.getstate()
            with self.subTest(horizon=horizon), self.assertRaises(ValueError):
                MCTS(horizon_rounds=horizon, rng=rng,
                     root_allocation="sequential_halving")
            self.assertEqual(rng.getstate(), before)
        for arguments in ({"time_budget_ms": 0}, {"time_budget_ms": 450},
                          {"priors": {}}, {"priors": {"Missing": (1, 0.5)}}):
            search = halving()
            before = search.rng.getstate()
            with (self.subTest(arguments=arguments),
                  patch("engine.mcts.advance_round", wraps=advance_round) as rounds,
                  self.assertRaises(ValueError)):
                search.search(position(), **{"time_budget_ms": None, **arguments})
            rounds.assert_not_called()
            self.assertEqual(search.rng.getstate(), before)
            self.assertEqual(search.last_sims, 0)
            self.assertFalse(search.last_root_allocation["complete"])

    def test_mutable_configuration_is_revalidated_after_previous_work(self):
        for field, invalid in (("root_allocation", "unknown"), ("horizon_rounds", 2),
                               ("max_sims", -1), ("max_transitions", -1)):
            with self.subTest(field=field):
                search = halving(sims=14)
                search.search(equal_arms(8), time_budget_ms=None)
                before = search.rng.getstate()
                setattr(search, field, invalid)
                with (patch("engine.mcts.advance_round", wraps=advance_round) as rounds,
                      self.assertRaises(ValueError)):
                    search.search(equal_arms(8), time_budget_ms=None)
                rounds.assert_not_called()
                self.assertEqual(search.rng.getstate(), before)
                self.assertEqual((search.last_sims, search.last_transitions), (0, 0))
                self.assertEqual(search.last_root_statistics, [])
                self.assertFalse(search.last_root_allocation["complete"])

    def test_interruptions_and_failures_leave_partial_work_and_recovery_is_fresh(self):
        for failure in (KeyboardInterrupt, RuntimeError):
            with self.subTest(failure=failure.__name__):
                search = halving()
                rollout = search._rollout
                calls = [0]

                def interrupted(successor, depth, trace=calls,
                                original=rollout, error=failure):
                    trace[0] += 1
                    reward = original(successor, depth)
                    if trace[0] == 2:
                        raise error("interrupted sample")
                    return reward

                with (patch.object(search, "_rollout", interrupted),
                      self.assertRaises(failure)):
                    search.search(equal_arms(8), time_budget_ms=None)
                diagnostic = search.last_root_allocation
                self.assertFalse(diagnostic["complete"])
                self.assertIsNone(diagnostic["winner"])
                self.assertEqual((search.last_sims, search.last_transitions), (1, 2))
                self.assertEqual(
                    (diagnostic["selections"], diagnostic["reward_updates"]), (2, 1))
                self.assertEqual(diagnostic["phases"][0]["completed_samples"], 1)
                self.assertEqual(diagnostic["phases"][0]["survivors"], [])
                self.assertIsNone(diagnostic["phases"][0]["statistics"][1]["mean"])
                json.dumps(diagnostic, allow_nan=False)
                search.search(equal_arms(8), time_budget_ms=None)
                self.assertIsNot(search.last_root_allocation, diagnostic)
                self.assertTrue(search.last_root_allocation["complete"])
                self.assertFalse(diagnostic["complete"])
                self.assertEqual((search.last_sims, search.last_transitions), (32, 32))

    def test_current_availability_cannot_turn_a_missing_scheduled_edge_into_pass(self):
        calls = 0

        def unavailable(state, slots, pool):
            nonlocal calls
            calls += 1
            actions = _available_actions(state, slots, pool)
            if calls == 2:
                actions.pop(Action(0))
            return actions

        search = halving()
        with (patch("engine.mcts._available_actions", unavailable),
              patch("engine.mcts.advance_round", wraps=advance_round) as rounds,
              self.assertRaisesRegex(RuntimeError, "no longer available")):
            search.search(equal_arms(8), time_budget_ms=None)
        self.assertEqual(rounds.call_count, 1)
        self.assertEqual((search.last_sims, search.last_transitions), (1, 1))
        self.assertEqual(search.last_root_allocation["selections"], 1)
        self.assertFalse(search.last_root_allocation["complete"])

    def test_seeded_uct_matches_retained_preexisting_reports(self):
        # These are historical compatibility witnesses, not new mathematics.
        # The candidate does not generate or rewrite its own expected answers.
        for case, seed in (("E2", 301), ("D2", 2001)):
            for sims in (8, 64):
                with self.subTest(case=case, sims=sims):
                    filename = f"{case}.seed-{seed}.sims-{sims}.decision.json"
                    path = ROOT / "docs/search-allowance" / filename
                    saved = json.loads(path.read_bytes())
                    state = _reconstruct(saved["selected_state"], "/selected_state")
                    expected = {Action(row["card_idx"], row["target_idx"]): row
                                for row in saved["legal_actions"]}
                    search = MCTS(1, 1.2, sims, random.Random(seed), sims)
                    ranked = search.search(state, time_budget_ms=None)
                    self.assertEqual([coordinates(r.action) for r in ranked],
                                     saved["ranking"])
                    self.assertEqual(
                        [coordinates(a) for a, _, _ in search.last_root_statistics],
                        saved["root_encounter_order"])
                    for action, visits, total in search.last_root_statistics:
                        row = expected[action]
                        self.assertEqual(visits, row["visits"])
                        self.assertEqual(total.hex(), float(row["value_sum"]).hex())
                        self.assertEqual((total / visits).hex(),
                                         float(row["mean_shaped_reward"]).hex())
                    self.assertEqual(search.root_allocation, "uct")
                    self.assertEqual(search.last_root_allocation["mode"], "uct")
                    self.assertEqual(search.last_sims, saved["work"]["simulations"])
                    self.assertEqual(search.last_transitions,
                                     saved["work"]["transitions"])

    def test_explicit_uct_preserves_positional_fields_seed_and_raw_work(self):
        state = position([Card("Hit", accuracy=0.75, damage_min=3, damage_max=11),
                          Card("Choice", card_type=CardType.UTILITY)])
        for horizon in (1, 3):
            for priors in (None, {"Hit": (2, 0.625)}):
                with self.subTest(horizon=horizon, priors=priors):
                    before = state.clone()
                    implicit = MCTS(horizon, 1.2, 23, random.Random(29), 40)
                    explicit = MCTS(horizon, 1.2, 23, random.Random(29), 40,
                                    root_allocation="uct")
                    self.assertEqual(implicit.search(state, None, priors),
                                     explicit.search(state, None, priors))
                    self.assertEqual(implicit.last_root_statistics,
                                     explicit.last_root_statistics)
                    self.assertEqual(implicit.rng.getstate(), explicit.rng.getstate())
                    self.assertEqual((implicit.last_sims, implicit.last_transitions,
                                      implicit.last_unused_transitions,
                                      implicit.last_stop_reasons),
                                     (explicit.last_sims, explicit.last_transitions,
                                      explicit.last_unused_transitions,
                                      explicit.last_stop_reasons))
                    self.assertEqual(state, before)


if __name__ == "__main__":
    unittest.main()
