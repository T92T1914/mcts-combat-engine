"""Managed decisions preserve the lower-level fixed-work boundary."""

import random
import unittest
from dataclasses import asdict, replace
from unittest.mock import Mock, patch

from engine import (
    Action,
    Card,
    Combatant,
    Element,
    GameState,
    ParallelSearchError,
    mcts_decider,
)


def state():
    return GameState(
        Combatant("Player", Element.NEUTRAL, 100, 100),
        [Combatant("Opponent", Element.NEUTRAL, 100, 100)],
        [Card("Hit", damage_min=10, damage_max=30)],
    )


def policy(**kwargs):
    config = dict(parallel=True, mode="fixed", budget_ms=None,
                  horizon=2, workers=1, seed=7, max_sims=8)
    config.update(kwargs)
    return mcts_decider(**config)


def computational(report):
    record = asdict(report)
    record.pop("elapsed_s")
    record.pop("pool_startup_s")
    for worker in record["workers"]:
        worker.pop("elapsed_s")
    return record


class HostileStop(KeyboardInterrupt):
    def add_note(self, note):
        raise SystemExit("note failed")

    def __str__(self):
        raise RuntimeError("string failed")


class ManagedFixedTests(unittest.TestCase):
    def test_selection_is_explicit_and_controls_are_validated_before_engine(self):
        cases = [dict(mode="other"), dict(parallel=False), dict(budget_ms=300),
                 dict(seed=None), dict(max_sims=None)]
        for name in ("seed", "max_sims", "max_transitions"):
            cases.extend({name: value} for value in (True, -1, 1.5))
        for config in cases:
            with (self.subTest(config=config),
                  patch("engine.decider.ParallelMCTS") as make):
                with self.assertRaises(ValueError):
                    policy(**config)
                make.assert_not_called()

    def test_repeated_seed_and_per_call_override_do_not_advance_default(self):
        rng = random.Random(99)
        before = rng.getstate()
        with policy() as choose:
            first = choose(state(), rng)
            receipt = computational(choose.last_report)
            self.assertEqual(choose(state(), rng), first)
            self.assertEqual(computational(choose.last_report), receipt)
            choose.decide(state(), seed=23)
            self.assertEqual(choose.last_report.seed, 23)
            self.assertEqual(choose.last_report.max_simulations, 8)
            self.assertEqual(choose(state(), rng), first)
            self.assertEqual(computational(choose.last_report), receipt)
        self.assertEqual(rng.getstate(), before)
        self.assertEqual(choose.last_report.seed, 7)

    def test_fixed_work_and_seed_are_forwarded_without_time_budget(self):
        with policy(workers=2, max_transitions=13) as choose:
            with patch.object(choose._engine, "search", return_value=[]) as search:
                with self.assertRaisesRegex(ValueError, "complete simulation"):
                    choose.decide(state(), seed=0)
            search.assert_called_once_with(
                unittest.mock.ANY, mode="fixed", max_sims=8,
                max_transitions=13, seed=0)

    def test_receipt_dictionary_is_detached_and_work_callback_precedes_count(self):
        events = []

        def work(record):
            events.append(("work", record["simulations"]))
            record["workers"][0]["simulations"] = -100

        with policy(on_work=work,
                    on_search=lambda n: events.append(("count", n))) as choose:
            choose.decide(state())
            self.assertEqual(choose.last_report.simulations, 8)
            self.assertEqual(choose.last_report.workers[0].simulations, 8)
        self.assertEqual(events, [("work", 8), ("count", 8)])

    def test_invalid_per_call_seed_clears_receipt_without_search_or_callbacks(self):
        work = Mock()
        with policy(on_work=work) as choose:
            choose.decide(state())
            work.reset_mock()
            for bad in (True, -1, 2.0):
                with patch.object(choose._engine, "search") as search:
                    with self.assertRaises(ValueError):
                        choose.decide(state(), seed=bad)
                    search.assert_not_called()
                self.assertIsNone(choose.last_report)
            work.assert_not_called()

    def test_per_call_seed_requires_fixed_mode(self):
        for config in ({}, dict(parallel=True, workers=1)):
            with mcts_decider(**config) as choose:
                with patch.object(choose._engine, "search") as search:
                    with self.assertRaisesRegex(ValueError, "mode='fixed'"):
                        choose.decide(state(), seed=7)
                    search.assert_not_called()
                self.assertIsNone(choose.last_report)

    def test_zero_and_unfunded_work_never_invent_nonterminal_pass(self):
        for config in (dict(max_sims=0), dict(max_transitions=0),
                       dict(max_transitions=1), dict(workers=2, max_transitions=2)):
            with self.subTest(config=config), policy(**config) as choose:
                with self.assertRaisesRegex(ValueError, "complete simulation"):
                    choose.decide(state())
                self.assertTrue(choose.last_report.complete)
                self.assertEqual(choose.last_report.simulations, 0)
                self.assertEqual(choose.last_report.transitions, 0)
                self.assertIsNone(choose._engine._pool)

    def test_terminal_root_is_pass_with_zero_work(self):
        root = state()
        root.enemies[0].hp = 0
        with policy(workers=2) as choose:
            self.assertEqual(choose.decide(root), Action(None))
            self.assertTrue(choose.last_report.complete)
            self.assertEqual(choose.last_report.simulations, 0)
            self.assertIsNone(choose._engine._pool)

    def test_unknown_partial_work_stays_unknown_and_callback_error_is_secondary(self):
        received = []
        with policy() as choose:
            choose.decide(state())
            good = choose.last_report
            missing = replace(good.workers[0], status="unreported", simulations=None,
                              transitions=None, unused_simulations=None,
                              unused_transitions=None, virtual_visits=None,
                              statistics=(), error="TimeoutError")
            partial = replace(good, complete=False, workers=(missing,),
                              simulations=None, transitions=None,
                              known_simulations=0, known_transitions=0,
                              unused_simulations=None, unused_transitions=None)
            error = ParallelSearchError(partial)

            def fail(*args, **kwargs):
                choose._engine.last_report = partial
                raise error

            def observer(record):
                received.append(record)
                raise OSError("observer failed")

            choose._on_work = observer
            choose._on_search = Mock()
            with patch.object(choose._engine, "search", side_effect=fail) as search:
                with self.assertRaises(ParallelSearchError) as caught:
                    choose.decide(state(), seed=23)
                self.assertIs(caught.exception, error)
                self.assertEqual(search.call_count, 1)
            self.assertIs(choose.last_report, partial)
            self.assertIsNone(received[0]["simulations"])
            self.assertIsNone(received[0]["workers"][0]["transitions"])
            self.assertTrue(any("OSError" in note for note in error.__notes__))
            choose._on_search.assert_not_called()
            choose._on_work = None
            choose.decide(state())
            self.assertEqual(choose.last_report.seed, 7)

    def test_interrupt_primacy_including_failed_diagnostic(self):
        for stop in (KeyboardInterrupt("stop"), SystemExit("stop"), HostileStop()):
            with self.subTest(stop=type(stop)), policy() as choose:
                choose.decide(state())
                receipt = choose.last_report

                def interrupted(*args, report=receipt, error=stop, **kwargs):
                    choose._engine.last_report = report
                    raise error

                choose._on_work = Mock(side_effect=RuntimeError("observer"))
                with patch.object(choose._engine, "search", side_effect=interrupted):
                    with self.assertRaises(type(stop)) as caught:
                        choose.decide(state())
                self.assertIs(caught.exception, stop)
                self.assertIs(choose.last_report, receipt)
                choose._on_work.assert_called_once()

    def test_admitted_attempt_without_report_does_not_retain_old_success(self):
        with policy() as choose:
            choose.decide(state())

            def failed_before_report(*args, **kwargs):
                choose._engine.last_report = None
                raise RuntimeError("no report")

            choose._on_work = Mock()
            with patch.object(choose._engine, "search",
                              side_effect=failed_before_report):
                with self.assertRaisesRegex(RuntimeError, "no report"):
                    choose.decide(state())
            self.assertIsNone(choose.last_report)
            choose._on_work.assert_not_called()

    def test_successful_search_observer_error_propagates_with_receipt_available(self):
        for callback in ("on_work", "on_search"):
            error = RuntimeError("observer failed")
            work = Mock(side_effect=error if callback == "on_work" else None)
            count = Mock(side_effect=error if callback == "on_search" else None)
            choose = policy(on_work=work, on_search=count)
            with (self.subTest(callback=callback),
                  self.assertRaises(RuntimeError) as caught):
                with choose:
                    choose.decide(state())
            self.assertIs(caught.exception, error)
            self.assertTrue(choose.last_report.complete)
            work.assert_called_once()
            self.assertTrue(choose._closed)

    def test_fixed_failed_retirement_refuses_decisions_until_explicit_retry(self):
        choose = policy(workers=2)
        pool = Mock()
        choose._engine._pool = pool
        stop = KeyboardInterrupt("dispatch stopped")
        pool.apply_async.side_effect = stop
        pool.terminate.side_effect = OSError("retirement failed")
        work = Mock()
        choose._on_work = work
        with self.assertRaises(KeyboardInterrupt) as caught:
            with choose:
                choose.decide(state(), seed=23)
        self.assertIs(caught.exception, stop)
        self.assertFalse(choose.last_report.complete)
        self.assertIsNone(choose.last_report.simulations)
        self.assertEqual(choose.last_report.seed, 23)
        self.assertEqual(choose.last_report.workers[1].status, "not_started")
        pool.terminate.assert_called_once()
        pool.join.assert_not_called()
        work.assert_called_once()
        with self.assertRaisesRegex(RuntimeError, "Retry close"):
            choose.decide(state())
        self.assertEqual(choose.last_report.seed, 23)
        pool.terminate.side_effect = None
        choose.close()
        choose.close()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            choose.decide(state(), seed=True)
        self.assertEqual(choose.last_report.seed, 23)


if __name__ == "__main__":
    unittest.main()
