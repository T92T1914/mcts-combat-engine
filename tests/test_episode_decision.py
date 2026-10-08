"""Saved-state admission and reporting agree with tiny direct current searches."""
from __future__ import annotations

import builtins
import contextlib
import copy
import hashlib
import io
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import decide_episode
import engine
import engine.decider
import engine.mcts
import engine.parallel
import engine.simulator
from engine import MCTS, Card, CardType, Charm, Combatant, DoT, Element, GameState
from engine.rules import EnrageBelowHalf, PunishTraps
from game import baselines, decision_report, episode_record, loader, runner
from game import episode_decision as decision
from game.decision_report import normalized
from game.episode_record import EpisodeInputError, canonical, output_bytes

ROOT = Path(__file__).resolve().parent.parent


def manual_state() -> GameState:
    """Independent public objects, not reconstructed by the candidate helper."""
    player = Combatant(
        name="Operator", element=Element.EMBER, hp=90, max_hp=100,
        pips=2, power_pips=1, power_pip_chance=0.4,
        resist={Element.FROST: 0.1}, boost={Element.EMBER: 0},
        blades=[Charm(0.2, Element.EMBER)], traps=[Charm(0.1, Element.NEUTRAL)],
        shields=[Charm(-0.3, Element.FROST)], dots=[DoT(1, 2, Element.FROST)],
        is_boss=False, base_attack=None, policy=None,
    )
    dead = Combatant(
        name="Retained dead", element=Element.SHADE, hp=0, max_hp=90,
        pips=1, power_pips=1, power_pip_chance=0.2,
        resist={Element.EMBER: 0}, boost={Element.SHADE: 0.0},
        blades=[Charm(0.05)], traps=[Charm(0.1)], shields=[Charm(-0.2)],
        dots=[DoT(1, 1, Element.EMBER)], is_boss=False,
        base_attack=None, policy=None,
    )
    attack = Card("Reply", Element.FROST, CardType.DAMAGE, 0, 1.0, 1, 2)
    enemy = Combatant(
        name="Target", element=Element.FROST, hp=45, max_hp=120,
        pips=1, power_pips=2, power_pip_chance=0.55,
        resist={Element.EMBER: 0.1}, boost={Element.FROST: 0.2},
        blades=[Charm(0.1, Element.FROST)], traps=[Charm(0.2, Element.EMBER)],
        shields=[Charm(-0.1)], dots=[DoT(2, 2, Element.EMBER)],
        is_boss=True, base_attack=attack, policy=None,
    )
    second = Combatant(
        "Second target", Element.GALE, 50, 80, power_pip_chance=0.3,
        base_attack=None, policy=None,
    )
    hand = [
        Card("Shifted", Element.NEUTRAL, CardType.UTILITY, accuracy=1),
        Card("Duplicate", Element.EMBER, CardType.DAMAGE, 0, 1.0, 4, 8,
             dot_tick=2, dot_rounds=2),
        Card("Duplicate", Element.EMBER, CardType.DAMAGE, 0, 1.0, 4, 8,
             dot_tick=2, dot_rounds=2),
        Card("Setup", Element.EMBER, CardType.TRAP, accuracy=1.0, modifier=0.2),
        Card("Restore", Element.VERDANT, CardType.HEAL, accuracy=1.0, heal=5),
        Card("Prepare", Element.EMBER, CardType.BLADE, accuracy=1.0, modifier=0.1),
        Card("Last slot", Element.NEUTRAL, CardType.UTILITY, accuracy=1.0),
    ]
    return GameState(player, [dead, enemy, second], hand, round_num=2,
                     boss_rules=[PunishTraps(3), EnrageBelowHalf(0.2)])


def synthetic_record() -> dict:
    """Literal episode envelope for a manual state, never recorded or replayed."""
    selected = normalized(manual_state())
    initial = copy.deepcopy(selected)
    initial["round_num"] = 1
    final = copy.deepcopy(selected)
    final["round_num"] = 3
    digest = "a" * 64
    return {
        "format": "mcts-episode-record", "schema_version": 1,
        "content": {"kind": "custom", "cards": {"bytes": 123, "sha256": digest},
                    "scenarios": {"bytes": 456, "sha256": digest}},
        "scenario": {"name": "Synthetic trial", "environment_seed": 7,
                     "deck": [copy.deepcopy(selected["hand"][1])]},
        "initial_state": initial,
        "implementation": {
            "python": "3.11", "python_implementation": "Stored interpreter",
            "platform": "Stored platform", "engine_import_kind": "site-packages",
            "distribution_version": None, "distribution_matches_import": False,
            "engine_files_sha256": {"engine/state.py": digest},
            "example_files_sha256": {"game/runner.py": digest},
            "entrypoint_files_sha256": {"episode.py": digest},
            "machine": "Stored machine", "pointer_bits": 64,
            "python_full_version": "Stored full version", "python_build": ["", ""],
            "python_cache_tag": None, "rng_state_version": 3,
        },
        "configuration": {
            "method": "mcts", "mode": "serial_clockless", "search_seed": 11,
            "search_rng_mode": "seed_once_continue", "max_rounds": 2,
            "max_sims_per_decision": 8, "horizon_rounds": 1,
            "max_transitions_per_decision": 8, "exploration": 1.2,
            "time_budget_ms": None, "parallel": False, "workers": None,
            "priors": None,
            "policy_rng": {"scheme": "policy-v1", "seed": 0, "used_by_policy": False},
        },
        "environment_rng": {
            "checkpoint_scheme": "python-random-getstate-json-v1", "state_version": 3,
            "after_scenario_sha256": digest, "final_sha256": "b" * 64,
        },
        "steps": [
            {"index": 0, "round_num": 1, "state": copy.deepcopy(initial),
             "action": {"card_idx": None, "target_idx": None, "label": "Stored first"}},
            {"index": 1, "round_num": 2, "state": selected,
             "action": {"card_idx": 1, "target_idx": 0, "label": "Stored claim"}},
        ],
        "final": {"state": final, "score": 0.5, "terminal_result": None,
                  "rounds": 2, "termination": "round_limit"},
    }


@contextlib.contextmanager
def guarded_routes(*, no_search: bool = False):
    """Keep live admission/classes, and witness forbidden consumer routes."""
    attempts = []

    def deny(*args, **kwargs):
        attempts.append("forbidden route")
        raise AssertionError("saved-state consumer called a forbidden route")

    original_import = builtins.__import__

    def admit_import(name, globals=None, locals=None, fromlist=(), level=0):
        if (name == "game.content"
                or (name == "game" and "content" in (fromlist or ()))):
            return deny()
        return original_import(name, globals, locals, fromlist, level)

    blocked = (
        (loader, "load_cards"), (loader, "load_scenarios"),
        (loader, "_parse_combatant"), (decision_report, "load_snapshot"),
        (decision_report, "implementation_identity"),
        (episode_record, "load_snapshot"), (episode_record, "load_content"),
        (episode_record, "observed_identity"),
        (episode_record, "implementation_identity"),
        (episode_record, "_record_owner"), (episode_record, "record_episode"),
        (episode_record, "replay_episode"), (episode_record, "play_game"),
        (runner, "play_game"), (runner, "_refill"), (runner, "advance_round"),
        (baselines, "one_round_decider"), (baselines, "mcts_decider"),
        (baselines, "random_decider"), (baselines, "greedy_decider"),
        (engine, "mcts_decider"), (engine.decider, "mcts_decider"),
    )
    with contextlib.ExitStack() as stack:
        for module, name in blocked:
            stack.enter_context(patch.object(module, name, side_effect=deny))
        stack.enter_context(patch.object(engine.MCTSDecider, "__init__", deny))
        stack.enter_context(patch.object(engine.ParallelMCTS, "__init__", deny))
        stack.enter_context(patch("builtins.__import__", side_effect=admit_import))
        if no_search:
            stack.enter_context(patch.object(random.Random, "__init__", deny))
            stack.enter_context(patch.object(engine.MCTS, "__init__", deny))
            stack.enter_context(patch.object(engine.MCTS, "search", deny))
            for module in (engine, engine.mcts, engine.simulator, baselines):
                stack.enter_context(patch.object(module, "advance_round", deny))
        yield attempts
    if attempts:
        raise AssertionError(f"forbidden route attempts: {attempts}")


class BinarySink:
    def __init__(self, *, short=False, refuse_flush=False):
        self.buffer = self
        self.data = bytearray()
        self.short = short
        self.refuse_flush = refuse_flush
        self.flushes = 0
        self.closed = False

    def write(self, data):
        admitted = data[:5] if self.short else data
        self.data.extend(admitted)
        return len(admitted)

    def flush(self):
        self.flushes += 1
        if self.refuse_flush:
            raise OSError("fixture output flush refusal")

    def close(self):
        self.closed = True


class SavedDecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mcts-saved-decision-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.saved = self.directory / "synthetic-episode.json"
        self.value = synthetic_record()
        self.write()

    def write(self):
        self.saved.write_bytes(canonical(self.value) + b"\n")

    def refuse(self, pattern):
        with guarded_routes(no_search=True):
            with self.assertRaisesRegex(EpisodeInputError, pattern):
                decision.episode_decision(self.saved, step=1, sims=8, horizon=2)

    def test_complete_manual_round_trip_retains_types_slots_and_live_rules(self):
        before = self.saved.read_bytes()
        selected = self.value["steps"][1]["state"]
        original_parse = decision.parse_card
        seen = []

        def live_parse(value, location):
            seen.append(location)
            return original_parse(value, location)

        rule_calls = []
        originals = copy.copy(loader.RULE_REGISTRY)
        with contextlib.ExitStack() as stack:
            read = stack.enter_context(patch.object(decision, "_read",
                                                   wraps=decision._read))
            for kind, (cls, parameters) in originals.items():
                observed = {}
                for name, (validator, requirement) in parameters.items():
                    def live_parameter(value, validator=validator, name=name):
                        rule_calls.append(name)
                        return validator(value)
                    observed[name] = (live_parameter, requirement)
                stack.enter_context(patch.dict(loader.RULE_REGISTRY,
                                               {kind: (cls, observed)}))
            stack.enter_context(patch.object(decision, "parse_card", live_parse))
            with guarded_routes(no_search=True):
                report = decision.episode_decision(self.saved, step=1, sims=0)
        expected = normalized(manual_state())
        self.assertEqual(canonical(report["selected_state"]), canonical(expected))
        self.assertEqual(canonical(selected), canonical(expected))
        self.assertEqual(report["selection"], {
            "step_index": 1, "round_num": 2, "state_pointer": "/steps/1/state"})
        self.assertEqual(len(seen), 8)
        read.assert_called_once_with(self.saved, "record", episode_record.RECORD_BYTES)
        self.assertIn("/steps/1/state/enemies/1/base_attack", seen)
        self.assertCountEqual(rule_calls, ["damage", "blade"])
        self.assertIs(type(report["selected_state"]["player"]["boost"]["ember"]), int)
        self.assertIs(type(report["selected_state"]["hand"][0]["accuracy"]), int)
        choices = [(row["card_idx"], row["target_idx"])
                   for row in report["legal_actions"]]
        self.assertEqual(choices, [(None, None), (0, None), (1, 1), (1, 2),
                                   (2, 1), (2, 2), (3, 1), (3, 2),
                                   (4, None), (5, None), (6, None)])
        self.assertEqual(self.saved.read_bytes(), before)

    def test_two_tiny_seeded_decisions_match_independent_public_searches(self):
        for seed, sims in ((19, 8), (31, 4)):
            with self.subTest(seed=seed):
                state = manual_state()
                root_before = canonical(normalized(state))
                reference = MCTS(horizon_rounds=2, max_sims=sims, exploration=1.2,
                                 max_transitions=sims * 2, rng=random.Random(seed))
                ranked = reference.search(state, time_budget_ms=None, priors=None)
                expected_by_action = {action: (visits, value_sum)
                                      for action, visits, value_sum
                                      in reference.last_root_statistics}
                expected_rows = []
                for action in engine.legal_actions(state):
                    visits, value_sum = expected_by_action.get(action, (0, 0.0))
                    expected_rows.append({
                        "card_idx": action.card_idx, "target_idx": action.target_idx,
                        "label": action.describe(state),
                        "status": "sampled" if visits else "unvisited",
                        "visits": visits, "value_sum": value_sum,
                        "mean_shaped_reward": value_sum / visits if visits else None,
                    })
                original_search = MCTS.search
                original_random_init = random.Random.__init__
                searches = []
                seeds = []

                def search_once(owner, state, time_budget_ms=None, priors=None, *,
                                searches=searches, original_search=original_search):
                    searches.append((owner.max_sims, owner.horizon_rounds,
                                     owner.max_transitions, time_budget_ms, priors))
                    return original_search(owner, state, time_budget_ms, priors)

                def seed_once(owner, value=None, *, seeds=seeds,
                              original_random_init=original_random_init):
                    seeds.append(value)
                    original_random_init(owner, value)

                before = self.saved.read_bytes()
                with guarded_routes(), patch.object(MCTS, "search", search_once), \
                        patch.object(random.Random, "__init__", seed_once):
                    report = decision.episode_decision(self.saved, step=1,
                                                       seed=seed, sims=sims, horizon=2)
                self.assertEqual(searches, [(sims, 2, sims * 2, None, None)])
                self.assertEqual(seeds, [seed])
                self.assertEqual(canonical(report["legal_actions"]),
                                 canonical(expected_rows))
                self.assertEqual(report["ranking"], [
                    {"card_idx": row.action.card_idx,
                     "target_idx": row.action.target_idx}
                    for row in ranked])
                self.assertEqual(report["recommendation"], {
                    "card_idx": ranked[0].action.card_idx,
                    "target_idx": ranked[0].action.target_idx,
                    "label": ranked[0].action.describe(state)})
                self.assertEqual(report["work"], {
                    "simulations": reference.last_sims,
                    "transitions": reference.last_transitions,
                    "unused_transitions": reference.last_unused_transitions,
                    "stop_reasons": list(reference.last_stop_reasons)})
                self.assertEqual(report["configuration"]["seed"], seed)
                self.assertTrue(any(row["status"] == "unvisited"
                                    for row in report["legal_actions"]))
                self.assertEqual(report["source_record"], {
                    "bytes": len(before), "sha256": hashlib.sha256(before).hexdigest()})
                self.assertEqual(canonical(normalized(state)), root_before)
                self.assertEqual(self.saved.read_bytes(), before)

    def test_no_work_retains_claims_without_original_content_or_old_entries(self):
        self.value["steps"][1]["action"]["label"] = "Opaque stored label"
        self.value["implementation"]["python_full_version"] = "Different producer"
        self.write()
        example = self.directory / "example"
        example.mkdir()
        shutil.copytree(ROOT / "game", example / "game",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(ROOT / "decide_episode.py", example / "decide_episode.py")
        with guarded_routes(no_search=True), patch.object(
                decision, "__file__", str(example / "game" / "episode_decision.py")):
            report = decision.episode_decision(self.saved, step=1, seed=11, sims=0)
        self.assertEqual(report["status"], "no_work")
        self.assertFalse(report["search_performed"])
        self.assertEqual(report["elapsed_seconds"], 0.0)
        self.assertEqual(report["work"], {
            "simulations": 0, "transitions": 0, "unused_transitions": 0,
            "stop_reasons": ["zero_requested_simulations"]})
        self.assertEqual(report["ranking"], [])
        self.assertIsNone(report["recommendation"])
        for row in report["legal_actions"]:
            self.assertEqual(row["status"], "unvisited")
            self.assertIs(type(row["value_sum"]), float)
            self.assertEqual(row["value_sum"], 0.0)
            self.assertEqual(row["visits"], 0)
            self.assertIsNone(row["mean_shaped_reward"])
        self.assertEqual(report["stored_action"], self.value["steps"][1]["action"])
        for name, value in report["stored_provenance"].items():
            self.assertEqual(canonical(value), canonical(self.value[name]))
        self.assertFalse(report["identity_comparisons"]["runtime_fields_equal"])
        self.assertFalse(report["identity_comparisons"]["example_files_equal"])
        entry_hash = hashlib.sha256((example / "decide_episode.py").read_bytes())
        self.assertEqual(report["implementation"]["entrypoint_files_sha256"], {
            "decide_episode.py": entry_hash.hexdigest()})
        self.assertFalse((example / "demo.py").exists())
        self.assertFalse((example / "episode.py").exists())
        self.assertFalse((example / "data").exists())

    def test_live_selected_card_and_combatant_refusals_precede_work(self):
        cases = (
            ("damage range", ("hand", 1, "damage_max"), 3, "hand/1.*damage_min"),
            ("DoT pair", ("hand", 1, "dot_rounds"), 0, "hand/1.*set together"),
            ("base attack", ("enemies", 1, "base_attack", "card_type"),
             "utility", "enemies/1/base_attack.*damage card"),
            ("hp relation", ("player", "hp"), 101, "player/hp.*max_hp"),
            ("pip slots", ("player", "pips"), 7, "player.*seven slots"),
            ("expired DoT", ("player", "dots", 0, "rounds_left"), 0,
             "player/dots/0/rounds_left.*positive"),
            ("rule description", ("boss_rules", 0, "description"),
             "Unsupported description", "boss_rules/0.*cannot reproduce"),
        )
        for name, route, replacement, pattern in cases:
            with self.subTest(case=name):
                self.value = synthetic_record()
                parent = self.value["steps"][1]["state"]
                for key in route[:-1]:
                    parent = parent[key]
                parent[route[-1]] = replacement
                self.write()
                self.refuse(pattern)

    def test_terminal_refuses_before_identity_or_rng(self):
        for change in ("player", "enemies"):
            with self.subTest(change=change):
                self.value = synthetic_record()
                state = self.value["steps"][1]["state"]
                if change == "player":
                    state["player"]["hp"] = 0
                else:
                    for enemy in state["enemies"]:
                        enemy["hp"] = 0
                self.write()
                with patch.object(
                        decision, "current_identity",
                        side_effect=AssertionError("identity before refusal")):
                    self.refuse("/steps/1/state.*terminal")

    def test_arguments_refuse_before_open_and_missing_step_after_admission(self):
        invalid = ({"step": True}, {"step": -1}, {"step": 30}, {"step": 1.0},
                   {"step": 1, "seed": True}, {"step": 1, "seed": 2**63},
                   {"step": 1, "sims": True}, {"step": 1, "sims": -1},
                   {"step": 1, "sims": 65}, {"step": 1, "horizon": 0},
                   {"step": 1, "horizon": 9}, {"step": 1, "horizon": False})
        for arguments in invalid:
            with (self.subTest(arguments=arguments), guarded_routes(no_search=True),
                  patch.object(decision, "_read",
                               side_effect=AssertionError("opened"))):
                with self.assertRaises(EpisodeInputError):
                    decision.episode_decision(self.saved, **arguments)
        with guarded_routes(no_search=True):
            with self.assertRaisesRegex(EpisodeInputError, "/steps/2.*does not exist"):
                decision.episode_decision(self.saved, step=2, sims=0)
        sink = BinarySink()
        with (contextlib.redirect_stdout(sink),
              contextlib.redirect_stderr(io.StringIO())):
            with self.assertRaises(SystemExit) as raised:
                decide_episode.main([str(self.saved)])
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(sink.data, b"")

    def test_genuine_parser_and_schema_refusals_precede_work(self):
        malformed = (b"\xff", b"{", b'{"format":1,"format":2}',
                     b'{"x":NaN}', b'{"x":1e9999}')
        for raw in malformed:
            with self.subTest(raw=raw):
                self.saved.write_bytes(raw)
                self.refuse("bounded UTF-8 JSON")
        for route, value in (("schema_version", 2), ("unsupported_rule", "other")):
            with self.subTest(route=route):
                self.value = synthetic_record()
                if route == "schema_version":
                    self.value[route] = value
                else:
                    self.value["steps"][1]["state"]["boss_rules"][0]["type"] = value
                self.write()
                self.refuse("unsupported|integer")
        self.write()
        with (guarded_routes(no_search=True),
              patch.object(decision, "RECORD_BYTES", 8),
              patch.object(decision, "_parse",
                           side_effect=AssertionError("parsed oversized"))):
            with self.assertRaisesRegex(EpisodeInputError, "exceeds 8 bytes"):
                decision.episode_decision(self.saved, step=1)

    def test_schema_admitted_arithmetic_failure_is_contextual_runtime_failure(self):
        state = self.value["steps"][1]["state"]
        state["hand"] = []
        state["player"]["blades"] = [{"value": -2.0, "element": "neutral"}]
        self.write()
        before = self.saved.read_bytes()
        with guarded_routes():
            with self.assertRaisesRegex(decision.DecisionRuntimeError,
                                        "/steps/1/state.*division"):
                decision.episode_decision(self.saved, step=1, sims=1, horizon=1)
        self.assertEqual(self.saved.read_bytes(), before)

    def test_identity_member_bound_and_source_drift_are_runtime_refusals(self):
        with (guarded_routes(no_search=True),
              patch.object(decision, "IDENTITY_FILE_BYTES", 1)):
            with self.assertRaisesRegex(decision.DecisionRuntimeError,
                                        "identity member"):
                decision.episode_decision(self.saved, step=1, sims=0)
        observed = decision.current_identity()
        changed = copy.deepcopy(observed)
        changed["engine_files_sha256"]["state.py"] = "0" * 64
        with guarded_routes(no_search=True), patch.object(
                decision, "current_identity", side_effect=[observed, changed]):
            with self.assertRaisesRegex(decision.DecisionRuntimeError,
                                        "identity changed"):
                decision.episode_decision(self.saved, step=1, sims=0)

    def test_full_output_bound_is_checked_before_stdout(self):
        sink = BinarySink()
        error = io.StringIO()
        with (guarded_routes(no_search=True),
              patch.object(episode_record, "RECORD_BYTES", 1),
              contextlib.redirect_stdout(sink), contextlib.redirect_stderr(error)):
            self.assertEqual(decide_episode.main([str(self.saved), "--step", "1",
                                                  "--sims", "0"]), 1)
        self.assertEqual(sink.data, b"")
        self.assertIn("generated output exceeds", error.getvalue())

    def test_binary_success_short_write_flush_and_interrupt(self):
        for short, flush in ((False, False), (True, False), (False, True)):
            with self.subTest(short=short, flush=flush):
                sink = BinarySink(short=short, refuse_flush=flush)
                error = io.StringIO()
                with guarded_routes(no_search=True), contextlib.redirect_stdout(sink), \
                        contextlib.redirect_stderr(error):
                    status = decide_episode.main([str(self.saved), "--step", "1",
                                                   "--sims", "0"])
                self.assertEqual(status, 1 if short or flush else 0)
                self.assertFalse(sink.closed)
                if not short and not flush:
                    parsed = json.loads(sink.data)
                    self.assertEqual(bytes(sink.data), output_bytes(parsed))
                    self.assertTrue(bytes(sink.data).endswith(b"\n"))
                    self.assertNotIn(b"\r\n", sink.data)
                    self.assertEqual(sink.flushes, 1)
                else:
                    self.assertIn("episode decision:", error.getvalue())
        sink = BinarySink()
        with (patch.object(decide_episode, "episode_decision",
                           side_effect=KeyboardInterrupt),
              contextlib.redirect_stdout(sink),
              contextlib.redirect_stderr(io.StringIO())):
            self.assertEqual(decide_episode.main([str(self.saved), "--step", "1"]), 130)
        self.assertEqual(sink.data, b"")

    def test_plain_search_runtime_error_has_context_and_no_stdout(self):
        sink = BinarySink()
        error = io.StringIO()
        with (guarded_routes(), patch.object(
                MCTS, "search", side_effect=RuntimeError("fixture search failure"))
              as search, contextlib.redirect_stdout(sink),
              contextlib.redirect_stderr(error)):
            self.assertEqual(decide_episode.main([str(self.saved), "--step", "1",
                                                  "--sims", "1", "--horizon", "1"]), 1)
        search.assert_called_once()
        self.assertEqual(sink.data, b"")
        self.assertIn("episode decision: /steps/1/state", error.getvalue())
        self.assertIn("fixture search failure", error.getvalue())

    def test_actual_buffered_flush_refusal_preserves_exit_one(self):
        entry = ROOT / "decide_episode.py"
        wrapper = f'''
import io
import runpy
import sys

class RefusedFlush(io.BufferedWriter):
    def flush(self):
        raise OSError("fixture stdout flush refusal")

sys.path.insert(0, {str(ROOT)!r})
raw = io.FileIO(sys.stdout.fileno(), "wb", closefd=False)
sys.stdout = io.TextIOWrapper(RefusedFlush(raw), encoding="utf-8")
sys.argv = [{str(entry)!r}, {str(self.saved)!r}, "--step", "1", "--sims", "0"]
runpy.run_path({str(entry)!r}, run_name="__main__")
'''
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-B", "-c", wrapper], cwd=self.directory,
            env=environment, stdin=subprocess.DEVNULL, capture_output=True,
            timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(b"episode decision: fixture stdout flush refusal", result.stderr)
        self.assertNotIn(b"Exception ignored", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
