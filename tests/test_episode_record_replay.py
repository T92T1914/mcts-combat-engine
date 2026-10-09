"""Episode observations preserve the runner, and replay admits no search."""
import contextlib
import copy
import hashlib
import io
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import episode
from engine import mcts_decider
from game import episode_record as records
from game.decision_report import load_snapshot, normalized
from game.runner import play_game

ROOT = Path(__file__).resolve().parent.parent


def forbidden(*args, **kwargs):
    raise AssertionError("unexpected work")


class EpisodeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mcts-episode-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.cards = self.directory / "caller-cards.json"
        self.scenarios = self.directory / "caller-scenarios.json"
        self.saved = self.directory / "episode.json"
        self.card_data = {"cards": [{
            "name": "Pulse", "element": "ember", "type": "damage",
            "accuracy": 1.0, "damage_min": 20, "damage_max": 30,
            "dot_tick": 2, "dot_rounds": 2,
        }]}
        self.scenario_data = {"scenarios": {"trial": {
            "player": {"name": "Operator", "element": "ember", "hp": 10_000,
                       "power_pip_chance": 0.4},
            "deck": ["Pulse"],
            "enemies": [{
                "name": "Target", "element": "frost", "hp": 1000,
                "is_boss": True,
                "attack": {"name": "Reply", "element": "frost", "type": "damage",
                           "accuracy": 0.8, "damage_min": 1, "damage_max": 2},
                "rules": [{"type": "punish_traps"},
                          {"type": "enrage_below_half", "blade": 0.2}],
            }],
        }}}
        self.write_content()

    def write_content(self):
        self.cards.write_bytes(json.dumps(self.card_data).encode("utf-8"))
        self.scenarios.write_bytes(json.dumps(self.scenario_data).encode("utf-8"))

    def make_record(self, **options):
        defaults = {"rounds": 3, "sims": 8, "horizon": 1}
        defaults.update(options)
        return records.record_episode("trial", cards_path=self.cards,
                                      scenarios_path=self.scenarios, **defaults)

    def save(self, value):
        self.saved.write_bytes(records.output_bytes(value))

    def replay(self, value):
        self.save(value)
        with patch.object(records, "_record_owner", forbidden):
            return records.replay_episode(self.saved, cards_path=self.cards,
                                          scenarios_path=self.scenarios)

    def cli(self, *arguments):
        out, err = io.BytesIO(), io.StringIO()
        text_out = io.TextIOWrapper(out, encoding="ascii", newline="",
                                   write_through=True)
        with contextlib.redirect_stdout(text_out), contextlib.redirect_stderr(err):
            try:
                status = episode.main(list(arguments))
            except SystemExit as exc:
                status = exc.code
        return status, out.getvalue().decode("ascii"), err.getvalue()

    def pair(self):
        return ["--cards", str(self.cards), "--scenarios", str(self.scenarios)]

    def test_recording_is_passive_against_plain_runner(self):
        before = (self.cards.read_bytes(), self.scenarios.read_bytes())
        recorded = self.make_record()
        scenarios, _ = load_snapshot(self.cards, self.scenarios)
        rng = random.Random(7)
        state, deck = scenarios["trial"](rng)
        boundaries, actions = [], []
        with mcts_decider(parallel=False, budget_ms=None, seed=7, max_sims=8,
                          horizon=1, max_transitions=8) as choose:
            def plain(current, policy_rng):
                boundaries.append(normalized(current))
                action = choose(current, policy_rng)
                actions.append((action.card_idx, action.target_idx))
                return action
            score = play_game(state, deck, plain, rng, max_rounds=3,
                              policy_rng=random.Random("policy-v1:0"))
        self.assertEqual([s["state"] for s in recorded["steps"]], boundaries)
        self.assertEqual([(s["action"]["card_idx"], s["action"]["target_idx"])
                          for s in recorded["steps"]], actions)
        self.assertEqual(recorded["final"]["state"], normalized(state))
        self.assertEqual(recorded["final"]["score"], score)
        checkpoint = json.dumps(normalized(rng.getstate()), ensure_ascii=True,
                                sort_keys=True, separators=(",", ":"),
                                allow_nan=False).encode("ascii")
        self.assertEqual(recorded["environment_rng"]["final_sha256"],
                         hashlib.sha256(checkpoint).hexdigest())
        self.assertEqual(len(recorded["steps"][0]["state"]["hand"]), 7)
        self.assertEqual(len(recorded["final"]["state"]["hand"]), 6)
        self.assertEqual(recorded["steps"][0]["state"]["enemies"][0]["dots"], [])
        self.assertTrue(recorded["steps"][1]["state"]["enemies"][0]["dots"])
        self.assertEqual(
            recorded["initial_state"]["boss_rules"][0]["parameters"]["damage"], 300)
        self.assertEqual(before, (self.cards.read_bytes(), self.scenarios.read_bytes()))
        result, status = self.replay(recorded)
        self.assertEqual(status, 0)
        self.assertEqual(result["final"], recorded["final"])
        self.assertFalse(result["search_recomputed"])

    def test_pass_and_round_limit_keep_their_meaning(self):
        self.card_data["cards"][0]["pip_cost"] = 14
        self.write_content()
        recorded = self.make_record(rounds=2, sims=1)
        self.assertTrue(all(step["action"]["card_idx"] is None
                            for step in recorded["steps"]))
        self.assertEqual(recorded["final"]["termination"], "round_limit")
        self.assertIsNone(recorded["final"]["terminal_result"])
        self.assertEqual(len(recorded["final"]["state"]["hand"]), 7)
        self.assertEqual(self.replay(recorded)[1], 0)

    def test_registered_rules_actually_fire_and_replay(self):
        card = self.card_data["cards"][0]
        card.update(type="trap", modifier=0.3, damage_min=0, damage_max=0,
                    dot_tick=0, dot_rounds=0)
        target = self.scenario_data["scenarios"]["trial"]["enemies"][0]
        target["rules"][0]["damage"] = 37
        self.write_content()
        trapped = self.make_record(rounds=1)
        self.assertIsNotNone(trapped["steps"][0]["action"]["card_idx"])
        hp = trapped["final"]["state"]["player"]["hp"]
        self.assertTrue(9961 <= hp <= 9963)  # rule 37 plus at most a two-point reply
        self.assertTrue(trapped["final"]["state"]["enemies"][0]["traps"])
        self.assertEqual(self.replay(trapped)[1], 0)
        card.update(type="damage", damage_min=60, damage_max=60, modifier=0.0)
        target["hp"] = 100
        self.write_content()
        enraged = self.make_record(rounds=1)
        self.assertEqual(enraged["final"]["state"]["enemies"][0]["hp"], 40)
        self.assertEqual(enraged["initial_state"]["enemies"][0]["blades"], [])
        self.assertEqual(enraged["final"]["state"]["enemies"][0]["blades"],
                         [{"value": 0.2, "element": "neutral"}])
        self.assertEqual(self.replay(enraged)[1], 0)

    def test_after_removal_snapshot_uses_shifted_current_indices(self):
        self.card_data["cards"].append({
            "name": "Reserve", "element": "ember", "type": "damage",
            "pip_cost": 14, "accuracy": 1.0, "damage_min": 1, "damage_max": 1,
        })
        self.scenario_data["scenarios"]["trial"]["deck"] = [
            "Pulse", "Pulse", "Reserve", "Pulse", "Pulse", "Reserve",
            "Reserve", "Reserve", "Reserve",
        ]
        self.write_content()
        recorded = self.make_record(rounds=2, sims=4)
        first, second = recorded["steps"]
        index = first["action"]["card_idx"]
        self.assertIsNotNone(index)
        before = [card["name"] for card in first["state"]["hand"]]
        after = [card["name"] for card in second["state"]["hand"]]
        self.assertIn("Reserve", before)
        self.assertGreater(before.count("Pulse"), 1)
        self.assertEqual(after[:6], before[:index] + before[index + 1:])
        current_index = second["action"]["card_idx"]
        self.assertEqual(after[current_index], "Pulse")
        self.assertEqual(self.replay(recorded)[1], 0)

    def test_terminal_on_last_allowed_round_is_terminal(self):
        card = self.card_data["cards"][0]
        card.update(damage_min=2000, damage_max=2000, dot_tick=0, dot_rounds=0)
        self.scenario_data["scenarios"]["trial"]["enemies"][0]["hp"] = 1
        self.write_content()
        # Eight simulations visit Pass and the seven duplicate zero-cost hits.
        recorded = self.make_record(rounds=1, sims=8)
        self.assertEqual(recorded["final"]["termination"], "terminal")
        self.assertEqual(recorded["final"]["terminal_result"], 1.0)
        self.assertEqual(recorded["final"]["rounds"], 1)
        self.assertEqual(self.replay(recorded)[1], 0)
        surplus = copy.deepcopy(recorded)
        surplus["configuration"]["max_rounds"] = 2
        extra = copy.deepcopy(surplus["steps"][0])
        extra.update(index=1, round_num=2)
        extra["state"]["round_num"] = 2
        surplus["steps"].append(extra)
        surplus["final"]["rounds"] = 2
        surplus["final"]["state"]["round_num"] = 3
        result, status = self.replay(surplus)
        self.assertEqual((status, result["reason"]), (1, "extra_step"))

    def test_first_divergence_and_illegal_action_do_not_become_pass(self):
        original = self.make_record()
        variants = []

        def variant(reason):
            value = copy.deepcopy(original)
            variants.append((reason, value))
            return value
        variant("initial_state")["initial_state"]["player"]["hp"] -= 1
        variant("deck")["scenario"]["deck"][0]["name"] = "Other"
        variant("boundary_state")["steps"][0]["state"]["player"]["hp"] -= 1
        variant("illegal_action")["steps"][0]["action"].update(
            card_idx=None, target_idx=0, label="Pass")
        variant("action_label")["steps"][0]["action"]["label"] = "Other"
        variant("final")["final"]["state"]["player"]["hp"] -= 1
        variant("rng_checkpoint")["environment_rng"]["final_sha256"] = "0" * 64
        missing = variant("missing_step")
        missing["steps"] = []
        missing["final"].update(rounds=0, score=0.0, terminal_result=0.0,
                                termination="terminal")
        missing["final"]["state"]["round_num"] = 1
        for reason, value in variants:
            with self.subTest(reason=reason):
                if reason in ("illegal_action", "missing_step"):
                    with patch("game.runner.advance_round", forbidden):
                        result, status = self.replay(value)
                else:
                    result, status = self.replay(value)
                self.assertEqual((status, result["reason"]), (1, reason))
                if reason == "boundary_state":
                    self.assertEqual(result["location"], "/steps/0/state/player/hp")
                if reason == "final":
                    self.assertEqual(result["location"], "/final/state/player/hp")
                if reason == "missing_step":
                    self.assertEqual(result["location"], "/steps/0")

    def test_first_location_orders_keys_and_escapes_canonical_leaf(self):
        self.assertIsNone(records.first_difference({"b": 1, "a": 2},
                                                  {"a": 2, "b": 1}, "/model"))
        self.assertEqual(records.first_difference({"z": 0, "a/b": {"~key": [1]}},
                                                 {"a/b": {"~key": [1.0]}, "z": 9},
                                                 "/model"), "/model/a~1b/~0key/0")
        self.assertEqual(records.first_difference([1], [True], "/model"), "/model/0")

    def test_content_and_code_incompatibility_precede_factory_work(self):
        recorded = self.make_record()
        self.save(recorded)
        self.cards.write_bytes(self.cards.read_bytes() + b"\n")
        with patch.object(records, "play_game", forbidden):
            result, status = records.replay_episode(
                self.saved, cards_path=self.cards, scenarios_path=self.scenarios)
        self.assertEqual((status, result["reason"]), (3, "content"))
        self.write_content()
        changed = copy.deepcopy(recorded["implementation"])
        changed["entrypoint_files_sha256"]["episode.py"] = "0" * 64
        with (patch.object(records, "observed_identity", return_value=changed),
              patch.object(records, "load_content", return_value=(
                  {"trial": forbidden}, recorded["content"]))):
            result, status = records.replay_episode(self.saved)
        self.assertEqual((status, result["reason"]), (3, "implementation"))

    def test_malformed_record_never_loads_content_or_starts_work(self):
        recorded = self.make_record()
        variants = []
        for key, value in (("schema_version", True), ("unexpected", None)):
            altered = copy.deepcopy(recorded)
            altered[key] = value
            variants.append(altered)
        altered = copy.deepcopy(recorded)
        altered["steps"][0]["action"]["card_idx"] = True
        variants.append(altered)
        altered = copy.deepcopy(recorded)
        altered["steps"][0]["index"] = 1
        variants.append(altered)
        altered = copy.deepcopy(recorded)
        altered["steps"].pop()
        variants.append(altered)
        for value in variants:
            with (self.subTest(value=value.get("schema_version")),
                  patch.object(records, "load_content", forbidden)):
                self.save(value)
                with self.assertRaises(records.EpisodeInputError):
                    records.replay_episode(self.saved)

    def test_record_read_and_parse_gate_precedes_content(self):
        for data in (b"\xff", b'{"format":1,"format":2}',
                     b" " * (records.RECORD_BYTES + 1)):
            with (self.subTest(size=len(data)),
                  patch.object(records, "load_content", forbidden),
                  self.assertRaises(records.EpisodeInputError)):
                self.saved.write_bytes(data)
                records.replay_episode(self.saved)

    def test_content_envelope_rejects_before_loader_or_policy(self):
        good = self.cards.read_bytes()
        invalid = [b'{"cards":[],"cards":[]}', b'{"cards":[NaN]}',
                   b'{"cards":[1e400]}', b'{"cards":[]}' + b" " * records.CONTENT_BYTES,
                   b"[" * 17 + b"0" + b"]" * 17]
        for field, value in (("damage_min", True), ("dot_rounds", 31),
                             ("damage_max", 10**100)):
            altered = copy.deepcopy(self.card_data)
            altered["cards"][0][field] = value
            invalid.append(json.dumps(altered).encode("utf-8"))
        for data in invalid:
            self.cards.write_bytes(data)
            with (patch.object(records, "load_snapshot", forbidden),
                  patch.object(records, "_record_owner", forbidden),
                  self.assertRaises(records.EpisodeInputError)):
                self.make_record()
        self.cards.write_bytes(good)
        self.scenario_data["scenarios"]["trial"]["enemies"].append({
            "name": "Other", "element": "frost", "hp": 100,
            "rules": [{"type": "punish_traps"}],
        })
        self.write_content()
        with (patch.object(records, "load_snapshot", forbidden),
              self.assertRaises(records.EpisodeInputError)):
            self.make_record()

    def test_captured_bytes_survive_fixture_replacement(self):
        before = self.cards.read_bytes()
        accepted_loader = records.load_snapshot

        def replace_fixture(cards_path, scenarios_path):
            self.assertEqual(cards_path.read_bytes(), before)
            self.cards.write_bytes(b"fixture replaced after capture")
            return accepted_loader(cards_path, scenarios_path)
        with patch.object(records, "load_snapshot", side_effect=replace_fixture):
            scenarios, identity = records.load_content(self.cards, self.scenarios)
        self.assertIn("trial", scenarios)
        self.assertEqual(identity["cards"]["sha256"],
                         hashlib.sha256(before).hexdigest())

    def test_cli_rejects_arguments_before_content_work(self):
        with patch.object(records, "load_content", forbidden):
            for arguments in (["record", "--rounds", "31"],
                              ["record", "--sims", "0"],
                              ["record", "--environment-seed", str(2**63)],
                              ["record", "--cards", str(self.cards)],
                              ["replay", str(self.saved), "--search-seed", "7"]):
                status, out, err = self.cli(*arguments)
                self.assertEqual(status, 2)
                self.assertEqual(out, "")
                self.assertIn("error", err)

    def test_cleanup_and_post_work_identity_failure_prevent_success_output(self):
        class FailedClose:
            def __enter__(self):
                self.owner = mcts_decider(parallel=False, budget_ms=None, seed=7,
                                          max_sims=1, horizon=1, max_transitions=1)
                return self.owner.__enter__()

            def __exit__(self, *args):
                self.owner.__exit__(*args)
                raise RuntimeError("fixture cleanup failure")
        with patch.object(records, "_record_owner", return_value=FailedClose()):
            status, out, err = self.cli("record", "trial", *self.pair(),
                                        "--rounds", "1", "--sims", "1")
        self.assertEqual((status, out), (1, ""))
        self.assertIn("cleanup failure", err)
        identity = records.observed_identity()
        changed = copy.deepcopy(identity)
        changed["entrypoint_files_sha256"]["episode.py"] = "0" * 64
        with patch.object(records, "observed_identity",
                          side_effect=[identity, changed]):
            status, out, err = self.cli("record", "trial", *self.pair(),
                                        "--rounds", "1", "--sims", "1")
        self.assertEqual((status, out), (1, ""))
        self.assertIn("identity changed", err)
        with patch.object(records, "RECORD_BYTES", 1):
            status, out, err = self.cli("record", "trial", *self.pair(),
                                        "--rounds", "1", "--sims", "1")
        self.assertEqual((status, out), (1, ""))
        self.assertIn("output exceeds", err)

    def test_body_failure_retires_serial_owner_before_error_output(self):
        owner = mcts_decider(parallel=False, budget_ms=None, seed=7, max_sims=1,
                             horizon=1, max_transitions=1)
        with (patch.object(records, "_record_owner", return_value=owner),
              patch.object(records, "play_game",
                           side_effect=RuntimeError("fixture body"))):
            status, out, err = self.cli("record", "trial", *self.pair(),
                                        "--rounds", "1")
        self.assertEqual((status, out), (1, ""))
        self.assertIn("fixture body", err)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            owner.__enter__()

    def process(self, command):
        env = dict(os.environ, PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run(command, cwd=self.directory, env=env, shell=False,
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=20,
                              creationflags=(subprocess.CREATE_NO_WINDOW
                                             if os.name == "nt" else 0))

    def test_actual_command_and_separate_process_replay_without_search(self):
        command = [sys.executable, str(ROOT / "episode.py"), "record", "trial",
                   *self.pair(), "--rounds", "2", "--sims", "8", "--horizon", "1"]
        recorded = self.process(command)
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        self.assertEqual(recorded.stdout.count(b"\n"), 1)
        self.assertNotIn(b"\r\n", recorded.stdout)
        self.saved.write_bytes(recorded.stdout)
        preserved = (self.saved.read_bytes(), self.cards.read_bytes(),
                     self.scenarios.read_bytes())
        script = """
import runpy, sys
sys.path.insert(0, sys.argv.pop(1))
import engine
import game.episode_record as records
def forbidden(*args, **kwargs):
    raise AssertionError('replay attempted policy or search work')
engine.mcts_decider = forbidden
engine.MCTSDecider.__init__ = forbidden
engine.MCTSDecider.__call__ = forbidden
engine.MCTSDecider.decide = forbidden
engine.MCTS.__init__ = forbidden
engine.MCTS.search = forbidden
engine.ParallelMCTS.__init__ = forbidden
engine.ParallelMCTS.search = forbidden
records._record_owner = forbidden
runpy.run_path(sys.argv.pop(1), run_name='__main__')
"""
        replayed = self.process([sys.executable, "-c", script, str(ROOT),
                                 str(ROOT / "episode.py"), "replay", str(self.saved),
                                 *self.pair()])
        self.assertEqual(replayed.returncode, 0, replayed.stderr)
        self.assertEqual(replayed.stdout.count(b"\n"), 1)
        self.assertNotIn(b"\r\n", replayed.stdout)
        result = json.loads(replayed.stdout)
        self.assertEqual(result["status"], "environment_replay_verified")
        self.assertFalse(result["search_recomputed"])
        self.assertEqual(preserved, (self.saved.read_bytes(), self.cards.read_bytes(),
                                     self.scenarios.read_bytes()))


class DeliverySink:
    """An inert caller-owned stream with explicit delivery outcomes."""

    def __init__(self, mode="complete"):
        self.buffer = self
        self.mode = mode
        self.data = bytearray()
        self.writes = 0
        self.flushes = 0
        self.closed = False

    def write(self, data):
        self.writes += 1
        if self.mode == "write_refusal":
            raise OSError("fixture output write refusal")
        if self.mode in ("short", "none", "interrupt_write"):
            self.data.extend(data[:5])
            if self.mode == "interrupt_write":
                raise KeyboardInterrupt
            return None if self.mode == "none" else 5
        self.data.extend(data)
        return len(data)

    def flush(self):
        self.flushes += 1
        if self.mode == "flush_refusal":
            raise OSError("fixture output flush refusal")
        if self.mode == "interrupt_flush":
            raise KeyboardInterrupt

    def close(self):
        self.closed = True


class OutputDeliveryTests(unittest.TestCase):
    """Exercise command delivery without constructing an episode or search."""

    VALUE = {
        "fixture": "caf\u00e9", "items": [None, True, 1, 1.0],
        "negative_zero": -0.0,
    }
    EXPECTED = (
        b'{"fixture":"caf\\u00e9","items":[null,true,1,1.0],'
        b'"negative_zero":-0.0}\n'
    )

    def invoke(self, operation, sink, *, replay_status=0, problem=None):
        value = copy.deepcopy(self.VALUE)
        arguments = ["record"] if operation == "record" else [
            "replay", "unused-episode.json",
        ]
        error = io.StringIO()
        with (
            patch.object(episode, "record_episode", return_value=value,
                         side_effect=problem if operation == "record"
                         else forbidden) as record,
            patch.object(episode, "replay_episode",
                         return_value=(value, replay_status),
                         side_effect=problem if operation == "replay"
                         else forbidden) as replay,
            patch.object(records, "load_content", forbidden),
            patch.object(records, "_record_owner", forbidden),
            patch.object(records, "play_game", forbidden),
            contextlib.redirect_stdout(sink),
            contextlib.redirect_stderr(error),
        ):
            try:
                status = episode.main(arguments)
            except SystemExit as exc:
                status = exc.code
            except KeyboardInterrupt:
                self.fail("Output interruption escaped the command boundary")
            except OSError as exc:
                self.fail(f"Output failure escaped the command boundary: {exc}")
        self.assertEqual(record.call_count, int(operation == "record"))
        self.assertEqual(replay.call_count, int(operation == "replay"))
        self.assertFalse(sink.closed, "main closed caller-owned stdout")
        return status, error.getvalue()

    def test_complete_output_preserves_record_and_replay_statuses(self):
        for operation, selected in (("record", 0), ("replay", 0),
                                    ("replay", 1), ("replay", 3)):
            with self.subTest(operation=operation, status=selected):
                sink = DeliverySink()
                status, error = self.invoke(operation, sink,
                                            replay_status=selected)
                self.assertEqual(status, selected)
                self.assertEqual(error, "")
                self.assertEqual(bytes(sink.data), self.EXPECTED)
                self.assertEqual((sink.writes, sink.flushes), (1, 1))
                self.assertEqual(sink.data.count(b"\n"), 1)
                self.assertNotIn(b"\r\n", sink.data)
                parsed = json.loads(sink.data)
                self.assertEqual(parsed["negative_zero"].hex(), "-0x0.0p+0")
                self.assertIs(type(parsed["items"][2]), int)
                self.assertIs(type(parsed["items"][3]), float)

    def test_short_none_write_and_flush_refusals_are_runtime_failures(self):
        for operation in ("record", "replay"):
            for mode in ("short", "none", "write_refusal", "flush_refusal"):
                with self.subTest(operation=operation, sink=mode):
                    sink = DeliverySink(mode)
                    status, error = self.invoke(operation, sink, replay_status=3)
                    self.assertEqual(status, 1)
                    self.assertIn("episode runtime:", error)
                    self.assertEqual(sink.writes, 1)
                    if mode in ("short", "none"):
                        self.assertIn("incomplete", error)
                        self.assertEqual(bytes(sink.data), self.EXPECTED[:5])
                        self.assertEqual(sink.flushes, 0)
                    elif mode == "write_refusal":
                        self.assertIn("fixture output write refusal", error)
                        self.assertEqual(sink.data, b"")
                        self.assertEqual(sink.flushes, 0)
                    else:
                        self.assertIn("fixture output flush refusal", error)
                        self.assertEqual(bytes(sink.data), self.EXPECTED)
                        self.assertEqual(sink.flushes, 1)

    def test_write_and_flush_interruptions_are_classified_for_both_dispatches(self):
        for operation in ("record", "replay"):
            for mode in ("interrupt_write", "interrupt_flush"):
                with self.subTest(operation=operation, sink=mode):
                    sink = DeliverySink(mode)
                    status, error = self.invoke(operation, sink, replay_status=3)
                    self.assertEqual(status, 130)
                    self.assertIn("episode interrupted", error)
                    self.assertEqual(sink.writes, 1)
                    if mode == "interrupt_write":
                        self.assertEqual(bytes(sink.data), self.EXPECTED[:5])
                        self.assertEqual(sink.flushes, 0)
                    else:
                        self.assertEqual(bytes(sink.data), self.EXPECTED)
                        self.assertEqual(sink.flushes, 1)

    def test_pre_output_failures_remain_empty_for_both_dispatches(self):
        cases = (
            (records.EpisodeInputError("fixture invalid input"), 2, "error:"),
            (RuntimeError("fixture pre-output failure"), 1, "episode runtime:"),
            (KeyboardInterrupt(), 130, "episode interrupted"),
        )
        for operation in ("record", "replay"):
            for problem, expected, diagnostic in cases:
                with self.subTest(operation=operation, status=expected):
                    sink = DeliverySink()
                    status, error = self.invoke(operation, sink, problem=problem)
                    self.assertEqual(status, expected)
                    self.assertIn(diagnostic, error)
                    self.assertEqual(sink.data, b"")
                    self.assertEqual((sink.writes, sink.flushes), (0, 0))

    def test_actual_buffered_flush_refusal_preserves_exit_one(self):
        entry = ROOT / "episode.py"
        before = entry.read_bytes()
        wrapper = f'''
import io
import runpy
import sys

sys.path.insert(0, {str(ROOT)!r})
import engine
import game.episode_record as records

def forbidden(*args, **kwargs):
    raise AssertionError("output fixture attempted environment or search work")

for owner in (engine.MCTS, engine.ParallelMCTS):
    owner.__init__ = forbidden
    owner.search = forbidden
records.load_content = forbidden
records._record_owner = forbidden
records.play_game = forbidden
records.replay_episode = forbidden
calls = 0

def literal_record(*args, **kwargs):
    global calls
    calls += 1
    return {{"fixture": "buffered delivery"}}

records.record_episode = literal_record

class RefusedFlush(io.BufferedWriter):
    def flush(self):
        raise OSError("fixture stdout flush refusal")

raw = io.FileIO(sys.stdout.fileno(), "wb", closefd=False)
sys.stdout = io.TextIOWrapper(RefusedFlush(raw), encoding="utf-8")
sys.argv = [{str(entry)!r}, "record"]
try:
    runpy.run_path({str(entry)!r}, run_name="__main__")
except SystemExit:
    assert calls == 1, "literal producer was not called exactly once"
    raise
'''
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        with tempfile.TemporaryDirectory(prefix="mcts-output-test-") as temporary:
            result = subprocess.run(
                [sys.executable, "-B", "-c", wrapper], cwd=temporary,
                env=environment, stdin=subprocess.DEVNULL, capture_output=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        self.assertEqual(entry.read_bytes(), before)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(b"episode runtime: fixture stdout flush refusal", result.stderr)
        self.assertNotIn(b"Exception ignored", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
