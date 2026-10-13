"""Capture admission and failure accounting use synthetic or bounded fixtures."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_episode_decision import synthetic_record

import benchmark
from game import episode_record as records
from game.root_allocation_report import saved_coordinates
from tools import encounter_policy_evaluation as capture


def protocol() -> dict:
    return {
        "schema_version": 1, "scenarios": ["duel", "gauntlet", "boss"],
        "rounds": 30, "sims": 32, "horizon": 1, "trial_timeout_seconds": 1,
        "collection_timeout_seconds": 240,
        "seed_blocks": [{"name": "synthetic-0", "environment_seed": 101,
                         "search_seed": 201,
                         "policy_order": ["uct", "sequential_halving"]}],
    }


def episode_fixture(trial: dict) -> dict:
    """Synthetic successful envelope, without running a built-in encounter."""
    value = synthetic_record()
    value["schema_version"] = 2
    value["configuration"] = records._configuration(30, 32, 1, trial["search_seed"],
                                                    trial["policy"])
    value["scenario"].update(name=trial["scenario"],
                             environment_seed=trial["environment_seed"])
    for step in value["steps"]:
        step["work"] = {"max_transitions": 32, "transitions": 32,
                        "unused_transitions": 0, "simulations": 32,
                        "stop_reasons": ["transition_allowance", "simulation_cap"]}
        step["search_diagnostics"] = {
            "legal_action_count": len(saved_coordinates(step["state"])),
            "allocation_mode": "uct" if trial["policy"] == "uct" else "halving",
            "allocation_complete": True,
        }
    # A synthetic terminal win in two rounds allows a thirty-round declared cap.
    value["final"].update(score=1.0, terminal_result=1.0, termination="terminal")
    for enemy in value["final"]["state"]["enemies"]:
        enemy["hp"] = 0
    return value


def transport(stdout=b"", *, timeout=False, overflow=False) -> dict:
    return {
        "stdout": stdout, "stderr": b"fixture diagnostics",
        "returncode": -9 if timeout else 0, "elapsed_subprocess_seconds": 0.1,
        "timeout_diagnostics": ({"timeout_seconds": 1, "message": "fixture timeout",
                                 "kill_requested": True, "reaped": True}
                                if timeout else None),
        "stdout_observed_bytes": len(stdout) + int(overflow),
        "stderr_observed_bytes": 19,
        "stdout_truncated": overflow, "stderr_truncated": False,
    }


class EncounterCaptureTests(unittest.TestCase):
    def test_transport_retains_only_the_sampled_prefix_when_a_writer_appends(self):
        class GrowingStream(io.BytesIO):
            def seek(self, offset, whence=0):
                position = super().seek(offset, whence)
                return 3 if whence == 2 else position
        # The sampled end is three, while bytes added after that boundary are
        # already visible to read. They belong to a later unobserved snapshot.
        captured, observed = capture._read_transport(GrowingStream(b"old-new"), 64)
        self.assertEqual((captured, observed), (b"old", 3))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mcts-encounter-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.protocol_path = self.directory / "protocol.json"
        self.output = self.directory / "capture"
        self.protocol = protocol()
        self.protocol_path.write_bytes(records.canonical(self.protocol))
        self.trials = capture._inventory(self.protocol)
        fixture = episode_fixture(self.trials[0])
        self.content = fixture["content"]
        self.implementation = {"episode": fixture["implementation"],
                               "capture_files": {}}

    def child_fixture(self, command, timeout):
        trial = {
            "scenario": command[3], "policy": command[-1],
            "environment_seed": int(command[command.index("--environment-seed") + 1]),
            "search_seed": int(command[command.index("--search-seed") + 1]),
        }
        return transport(records.output_bytes(episode_fixture(trial)))

    def run_capture(self, child=None):
        with (patch.object(records, "load_content", return_value=({}, self.content)),
              patch.object(capture, "_source_identity",
                           return_value=self.implementation),
              patch.object(capture, "_child", side_effect=child or self.child_fixture)):
            return capture.run_evaluation(self.protocol_path, self.output,
                                          process_tree_bound="synthetic owner receipt")

    def test_protocol_admission_and_with_replacement_block_identity(self):
        value = protocol()
        value["seed_blocks"].append({**value["seed_blocks"][0], "name": "synthetic-1",
                                     "policy_order": ["sequential_halving", "uct"]})
        capture.validate_protocol(value)
        value["seed_blocks"][1]["name"] = "synthetic-0"
        with self.assertRaisesRegex(records.EpisodeInputError, "duplicate block"):
            capture.validate_protocol(value)
        for key, changed in (("horizon", 2), ("sims", 31), ("rounds", 29),
                             ("collection_timeout_seconds", 1801),
                             ("trial_timeout_seconds", float("nan"))):
            bad = protocol()
            bad[key] = changed
            with self.subTest(key=key), self.assertRaises(records.EpisodeInputError):
                capture.validate_protocol(bad)
        with patch.object(capture, "_child") as child:
            with self.assertRaises(records.EpisodeInputError):
                capture.run_evaluation(self.protocol_path, self.output,
                                       process_tree_bound=" ")
        child.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_full_inventory_and_artifact_hashes_follow_synthetic_records(self):
        report = self.run_capture()
        self.assertEqual(report["status"], "complete")
        self.assertEqual(len(report["trials"]), 6)
        self.assertFalse(report["process_tree_bound_verified_by_collector"])
        self.assertEqual(report["summary"]["uct"]["terminal_wins_by_round_cap"], 3)
        self.assertEqual(report["summary"]["uct"]["known_transitions"], 192)
        for trial in report["trials"]:
            receipt_path = self.output / trial["receipt"]
            receipt_data = receipt_path.read_bytes()
            self.assertEqual(trial["receipt_identity"], capture._identity(receipt_data))
            receipt = json.loads(receipt_data)
            episode_path = receipt_path.parent / receipt["episode"]["path"]
            self.assertEqual(receipt["episode"]["sha256"],
                             capture._identity(episode_path.read_bytes())["sha256"])
            self.assertEqual(len(receipt["work"]["decision_records"]), 2)
            self.assertNotIn("decision_records", trial["work"])
            self.assertFalse((receipt_path.parent / "episode.json.pending").exists())

    def test_timeout_keeps_raw_diagnostics_unknown_work_and_continues_inventory(self):
        calls = 0
        def child(command, timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                return transport(b"partial JSON", timeout=True)
            return self.child_fixture(command, timeout)
        report = self.run_capture(child)
        self.assertEqual(calls, 6)
        self.assertEqual(report["status"], "incomplete")
        failed = report["trials"][0]
        self.assertEqual(failed["status"], "timeout")
        self.assertIsNone(failed["terminal_result"])
        self.assertIsNone(failed["work"])
        directory = self.output / "trials" / "00000"
        self.assertFalse((directory / "episode.json").exists())
        self.assertEqual((directory / "stdout.raw").read_bytes(), b"partial JSON")
        receipt = json.loads((directory / "receipt.json").read_bytes())
        self.assertTrue(receipt["transport"]["timeout_diagnostics"]["reaped"])
        self.assertEqual(report["summary"]["uct"]["terminal_win_count_bounds"], [2, 3])

    def test_overflow_and_work_shortfall_never_publish_complete_episode(self):
        for kind in ("overflow", "shortfall"):
            directory = self.directory / kind
            directory.mkdir()
            value = episode_fixture(self.trials[0])
            if kind == "shortfall":
                value["steps"][0]["work"]["simulations"] = 31
            result = transport(records.output_bytes(value), overflow=kind == "overflow")
            with patch.object(capture, "_child", return_value=result):
                receipt = capture._trial(self.trials[0], self.protocol, directory,
                                         self.content, self.implementation["episode"])
            self.assertEqual(receipt["status"], "error")
            self.assertIsNone(receipt["outcome"])
            self.assertIsNone(receipt["work"])
            self.assertFalse((directory / "episode.json").exists())

    def test_retirement_failure_retains_attempt_and_stops_further_admission(self):
        result = transport(b"started", timeout=True)
        result["retirement_errors"] = ["reap: synthetic failure"]
        with (patch.object(records, "load_content", return_value=({}, self.content)),
              patch.object(capture, "_source_identity",
                           return_value=self.implementation),
              patch.object(capture, "_child",
                           side_effect=capture.EncounterRetirementError(
                               "fixture retirement failure", result)) as child):
            report = capture.run_evaluation(self.protocol_path, self.output,
                                           process_tree_bound="synthetic owner receipt")
        self.assertEqual(child.call_count, 1)
        self.assertEqual(report["trials"][0]["status"], "retirement_failure")
        self.assertTrue(all(trial["status"] == "not_attempted"
                            for trial in report["trials"][1:]))
        self.assertTrue((self.output / report["trials"][0]["receipt"]).exists())
        self.assertEqual(report["summary"]["uct"]["terminal_win_count_bounds"], [0, 3])
        self.assertEqual(report["failure"]["stage"], "retirement")

    def test_deadline_preserves_unattempted_slots_and_source_freeze_refuses(self):
        with (patch.object(records, "load_content", return_value=({}, self.content)),
              patch.object(capture, "_source_identity",
                           return_value=self.implementation),
              patch.object(capture.time, "monotonic", side_effect=[0, 241, 241]),
              patch.object(capture, "_child") as child):
            report = capture.run_evaluation(self.protocol_path, self.output,
                                           process_tree_bound="synthetic owner receipt")
        child.assert_not_called()
        self.assertEqual(report["failure"]["stage"], "collection_deadline")
        self.assertEqual(report["summary"]["uct"]["unknown_outcomes"], 3)
        frozen = copy.deepcopy(self.protocol)
        frozen["metadata"] = {"freeze": {"implementation": {}, "content": self.content}}
        self.protocol_path.write_bytes(records.canonical(frozen))
        with (patch.object(records, "load_content", return_value=({}, self.content)),
              patch.object(capture, "_source_identity",
                           return_value=self.implementation),
              patch.object(capture, "_child") as child,
              self.assertRaisesRegex(records.EpisodeInputError, "freeze mismatch")):
            capture.run_evaluation(self.protocol_path, self.directory / "frozen",
                                   process_tree_bound="synthetic owner receipt")
        child.assert_not_called()

    def test_atomic_receipt_survives_interruption_before_final_inventory_join(self):
        count = 0
        def child(command, timeout):
            nonlocal count
            count += 1
            if count == 2:
                raise KeyboardInterrupt()
            return self.child_fixture(command, timeout)
        with self.assertRaises(KeyboardInterrupt):
            self.run_capture(child)
        initial = json.loads((self.output / "results.json").read_bytes())
        self.assertTrue(all(trial["status"] == "not_attempted"
                            for trial in initial["trials"]))
        retained_path = self.output / "trials" / "00000" / "receipt.json"
        retained = json.loads(retained_path.read_bytes())
        self.assertEqual(retained["status"], "complete")
        self.assertTrue((self.output / "trials" / "00000" / "episode.json").exists())

    def test_hidden_child_timeout_reaps_a_real_sleeping_fixture(self):
        script = self.directory / "sleeping_fixture.py"
        script.write_text("import time\ntime.sleep(20)\n", encoding="utf-8")
        result = capture._child([sys.executable, str(script)], 0.5)
        self.assertTrue(result["timeout_diagnostics"]["kill_requested"])
        self.assertTrue(result["timeout_diagnostics"]["reaped"])
        self.assertIsNotNone(result["returncode"])
        self.assertLess(result["elapsed_subprocess_seconds"], 6)

    def test_child_kill_and_reap_failures_carry_transport(self):
        for method in ("kill", "reap"):
            process = Mock(returncode=None)
            initial = subprocess.TimeoutExpired("fixture", 1)
            process.wait.side_effect = [initial, (OSError("fixture reap")
                                                  if method == "reap" else 0)]
            if method == "kill":
                process.kill.side_effect = OSError("fixture kill")
            with (patch.object(capture.subprocess, "Popen", return_value=process),
                  self.subTest(method=method),
                  self.assertRaises(capture.EncounterRetirementError) as caught):
                capture._child(["synthetic executable"], 1)
            self.assertTrue(caught.exception.transport["retirement_errors"])
            self.assertEqual(caught.exception.transport["stdout"], b"")

    def test_cli_requires_owned_capture_controls_and_returns_incomplete_exit(self):
        for arguments in (["--encounter-protocol", str(self.protocol_path)],
                          ["--process-tree-bound", "fixture"],
                          ["--encounter-protocol", str(self.protocol_path),
                           "--encounter-output", str(self.output),
                           "--process-tree-bound", "fixture", "--sims", "32"]):
            with (patch.object(sys, "argv", ["benchmark.py", *arguments]),
                  patch.object(capture, "run_evaluation") as run,
                  contextlib.redirect_stderr(io.StringIO()),
                  self.assertRaises(SystemExit) as raised):
                benchmark.main()
            self.assertEqual(raised.exception.code, 2)
            run.assert_not_called()
        argv = ["benchmark.py", "--encounter-protocol", str(self.protocol_path),
                "--encounter-output", str(self.output),
                "--process-tree-bound", "fixture"]
        with (patch.object(sys, "argv", argv),
              contextlib.redirect_stdout(io.StringIO()),
              patch.object(capture, "run_evaluation", return_value={
                  "status": "incomplete", "trials": self.trials})):
            self.assertEqual(benchmark.main(), 1)


if __name__ == "__main__":
    unittest.main()
