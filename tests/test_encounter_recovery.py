"""Synthetic retained evidence has independently declared recovery outcomes."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_encounter_policy_evaluation import episode_fixture, protocol

import recover_encounters
from game import episode_record as records
from tools import encounter_policy_evaluation as capture
from tools import encounter_recovery as recovery
from tools.managed_encounter import ManagedControl


def write_json(path: Path, value: dict) -> None:
    path.write_bytes(records.canonical(value) + b"\n")


class EncounterRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mcts-recovery-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.capture = self.root / "capture"
        self.capture.mkdir()
        (self.capture / "trials").mkdir()
        self.output = self.root / "recovery.json"
        self.protocol = protocol()
        write_json(self.capture / "protocol.json", self.protocol)
        self.protocol_identity = recovery._identity(
            (self.capture / "protocol.json").read_bytes())
        self.inventory = capture._inventory(self.protocol)
        first = episode_fixture(self.inventory[0])
        self.aggregate = {
            "format": "mcts-encounter-policy-evaluation", "schema_version": 1,
            "status": "incomplete", "protocol": {"path": "protocol.json",
                                                     **self.protocol_identity},
            "content": first["content"],
            "implementation": {"episode": first["implementation"], "capture_files": {
                name: recovery._identity(b"synthetic capture source") for name in (
                    "benchmark.py", "tools/encounter_policy_evaluation.py")}},
            "settings": {key: self.protocol[key] for key in (
                "scenarios", "rounds", "sims", "horizon", "trial_timeout_seconds")},
            "trials": copy.deepcopy(self.inventory),
            "summary": capture._summary(self.inventory),
            "failure": None,
        }
        self.receipts: dict[int, dict] = {}
        self.save_aggregate()

    def save_aggregate(self):
        write_json(self.capture / "results.json", self.aggregate)

    def directory(self, index: int) -> Path:
        directory = self.capture / "trials" / f"{index:05d}"
        directory.mkdir(exist_ok=True)
        return directory

    def save_receipt(self, index: int, receipt: dict):
        directory = self.directory(index)
        write_json(directory / "timing.json", {
            "elapsed_subprocess_seconds": receipt["elapsed_subprocess_seconds"],
            "transport": receipt["transport"],
        })
        write_json(directory / "work.json", {"work": receipt["work"]})
        write_json(directory / "error.json", {"error": receipt["error"]})
        write_json(directory / "receipt.json", receipt)
        self.receipts[index] = receipt

    def complete(self, index: int) -> dict:
        trial = self.inventory[index]
        directory = self.directory(index)
        record = episode_fixture(trial)
        emitted = records.output_bytes(record)
        (directory / "episode.json").write_bytes(emitted)
        (directory / "stdout.raw").write_bytes(emitted)
        (directory / "stderr.raw").write_bytes(b"bounded fixture diagnostic\n")
        receipt = {
            "format": "mcts-encounter-trial-receipt", "schema_version": 1,
            "trial": {key: trial[key] for key in recovery.TRIAL_FIELDS},
            "status": "complete", "elapsed_subprocess_seconds": 0.1,
            "transport": {
                "returncode": 0, "elapsed_subprocess_seconds": 0.1,
                "timeout_diagnostics": None, "stdout_observed_bytes": len(emitted),
                "stderr_observed_bytes": 27, "stdout_truncated": False,
                "stderr_truncated": False,
                "stdout": {"path": "stdout.raw", **recovery._identity(emitted)},
                "stderr": {"path": "stderr.raw", **recovery._identity(
                    b"bounded fixture diagnostic\n")},
            },
            "episode": {"path": "episode.json", **recovery._identity(emitted)},
            "error": None,
            "outcome": {"terminal_result": 1.0, "termination": "terminal", "score": 1.0,
                        "rounds": 2},
            "work": {
                "decision_records": [step["work"] for step in record["steps"]],
                "decision_diagnostics": [step["search_diagnostics"]
                                         for step in record["steps"]],
                "simulations": 64, "transitions": 64, "unused_transitions": 0,
                "shortfalls": [], "uniform_fallback_decisions": 0,
            },
            "artifacts": dict(recovery.ARTIFACTS),
        }
        self.save_receipt(index, receipt)
        return receipt

    def incomplete(self, index: int, status: str) -> dict:
        trial = self.inventory[index]
        receipt = {
            "format": "mcts-encounter-trial-receipt", "schema_version": 1,
            "trial": {key: trial[key] for key in recovery.TRIAL_FIELDS},
            "status": status, "elapsed_subprocess_seconds": None, "transport": None,
            "episode": None, "error": {"type": "SyntheticFailure", "message": status},
            "outcome": None, "work": None, "artifacts": dict(recovery.ARTIFACTS),
        }
        self.save_receipt(index, receipt)
        return receipt

    def finish_aggregate(self):
        for index, receipt in self.receipts.items():
            trial = self.aggregate["trials"][index]
            trial.update({
                "status": receipt["status"], "episode": receipt["episode"],
                "elapsed_subprocess_seconds": receipt["elapsed_subprocess_seconds"],
                "receipt_identity": recovery._identity(
                    (self.directory(index) / "receipt.json").read_bytes()),
            })
            if receipt["status"] == "complete":
                trial.update(receipt["outcome"])
                trial["work"] = {key: receipt["work"][key] for key in (
                    "simulations", "transitions", "unused_transitions",
                    "uniform_fallback_decisions")}
        self.aggregate["summary"] = capture._summary(self.aggregate["trials"])
        if all(trial["status"] == "complete" for trial in self.aggregate["trials"]):
            self.aggregate["status"] = "complete"
        self.save_aggregate()

    def inspect(self) -> dict:
        with (patch("subprocess.Popen", side_effect=AssertionError("no subprocess")),
              patch("game.episode_record._record_owner",
                    side_effect=AssertionError("no search")),
              patch("game.episode_record.replay_episode",
                    side_effect=AssertionError("no replay"))):
            return recovery.recover_capture(self.capture, self.output)

    def assert_classification(self, index: int, classification: str):
        report = self.inspect()
        self.assertEqual(report["trials"][index]["classification"], classification)
        return report

    def test_complete_inventory_uses_exact_episode_decisions_and_preserves_inputs(self):
        for index in range(6):
            self.complete(index)
        self.finish_aggregate()
        before = {path.relative_to(self.capture).as_posix():
                  (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in self.capture.rglob("*") if path.is_file()}
        report = self.inspect()
        self.assertEqual([(row["trial"]["scenario"], row["trial"]["policy"])
                          for row in report["trials"]], [
            ("duel", "uct"), ("duel", "sequential_halving"),
            ("gauntlet", "uct"), ("gauntlet", "sequential_halving"),
            ("boss", "uct"), ("boss", "sequential_halving")])
        self.assertEqual(report["summary"]["classifications"]["complete_admitted"], 6)
        self.assertTrue(report["inventory_evidence_consistent"])
        for policy in ("uct", "sequential_halving"):
            row = report["summary"]["policies"][policy]
            self.assertEqual((row["terminal_wins"], row["terminal_losses"],
                              row["round_limit_nonwins"], row["known_simulations"],
                              row["known_transitions"]), (3, 0, 0, 192, 192))
        after = {path.relative_to(self.capture).as_posix():
                 (path.read_bytes(), path.stat().st_mtime_ns)
                 for path in self.capture.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(json.loads(self.output.read_bytes()), report)
        self.assertFalse(report["boundaries"]["origin_authenticated"])
        self.assertFalse(report["boundaries"]["statistical_completeness_established"])

    def test_stale_initial_aggregate_and_unknown_execution_start(self):
        self.complete(0)
        report = self.assert_classification(0, "complete_admitted")
        self.assertEqual(report["trials"][1]["classification"], "no_execution_evidence")
        self.assertEqual(report["trials"][1]["start"], "unknown")
        self.assertEqual(report["summary"]["policies"]["uct"]["known_transitions"], 64)
        self.assertEqual(report["summary"]["policies"]["sequential_halving"]
                         ["known_transitions"], 0)
        self.assertTrue(any("stale" in notice for notice in report["notices"]))
        self.assertTrue(report["inventory_evidence_consistent"])
        self.assertFalse(report["boundaries"]["absent_artifacts_prove_never_started"])

    def test_failure_receipts_preserve_unknown_outcomes_and_do_not_create_work(self):
        for index, status in enumerate(("timeout", "error", "retirement_failure",
                                        "cancelled")):
            self.incomplete(index, status)
        report = self.inspect()
        self.assertEqual(report["summary"]["classifications"]["incomplete_attempt"], 4)
        for row in report["trials"]:
            self.assertIsNone(row["outcome"])
            self.assertIsNone(row["work"])
        self.assertEqual(report["summary"]["policies"]["uct"]
                         ["unknown_or_unadmitted_outcomes"], 3)

    def test_orphan_intent_preserves_unknown_execution_and_outcome(self):
        directory = self.directory(0)
        control = ManagedControl(self.capture, 1_048_576, 268_435_456, 1,
                                 self.root / "unused-cancellation")
        control.before_trial(self.inventory[0], self.aggregate["protocol"], directory)
        intent = json.loads((directory / "admission-intent.json").read_bytes())
        self.assertEqual(set(intent), {"format", "schema_version", "trial", "protocol"})
        self.assertEqual(intent["protocol"], self.protocol_identity)
        (directory / "stdout.raw").write_bytes(b"{incomplete")
        (directory / "episode.json.pending").write_bytes(b"{partial")
        report = self.assert_classification(0, "incomplete_attempt")
        self.assertEqual(report["trials"][0]["start"],
                         "admission_intent_retained_execution_unknown")
        self.assertIsNotNone(report["trials"][0]["admission_intent_identity"])
        self.assertIsNone(report["trials"][0]["outcome"])

    def test_malformed_duplicate_key_and_oversize_receipts_are_corrupt(self):
        payloads = (b"{broken", b'{"status":"error","status":"complete"}',
                    b" " * (recovery.RECEIPT_BYTES + 1))
        for index, payload in enumerate(payloads):
            (self.directory(index) / "receipt.json").write_bytes(payload)
        report = self.inspect()
        self.assertEqual(report["summary"]["classifications"]
                         ["corrupt_or_contradictory"], 3)
        self.assertEqual(report["summary"]["classifications"]["complete_admitted"], 0)

    def test_episode_hash_mismatch_and_missing_claimed_episode_are_contradictory(self):
        self.complete(0)
        (self.directory(0) / "episode.json").write_bytes(b"changed")
        self.complete(1)
        (self.directory(1) / "episode.json").unlink()
        report = self.inspect()
        self.assertEqual(report["summary"]["classifications"]
                         ["corrupt_or_contradictory"], 2)

    def test_wrong_and_duplicate_trial_identity_are_contradictory(self):
        self.complete(0)
        receipt = self.complete(1)
        receipt["trial"] = dict(self.receipts[0]["trial"])
        self.save_receipt(1, receipt)
        report = self.inspect()
        self.assertEqual(report["trials"][0]["classification"], "complete_admitted")
        self.assertEqual(report["trials"][1]["classification"],
                         "corrupt_or_contradictory")

    def test_episode_source_content_and_configuration_join(self):
        for index in range(3):
            receipt = self.complete(index)
            directory = self.directory(index)
            record = json.loads((directory / "episode.json").read_bytes())
            if index == 0:
                record["content"]["cards"]["sha256"] = "f" * 64
            elif index == 1:
                record["implementation"]["platform"] = "different-platform"
            else:
                record["configuration"]["search_seed"] += 1
            emitted = records.output_bytes(record)
            (directory / "episode.json").write_bytes(emitted)
            (directory / "stdout.raw").write_bytes(emitted)
            receipt["episode"] = {"path": "episode.json", **recovery._identity(emitted)}
            receipt["transport"]["stdout"] = {
                "path": "stdout.raw", **recovery._identity(emitted)}
            receipt["transport"]["stdout_observed_bytes"] = len(emitted)
            self.save_receipt(index, receipt)
        report = self.inspect()
        self.assertEqual(report["summary"]["classifications"]
                         ["corrupt_or_contradictory"], 3)

    def test_outcome_and_work_claims_are_checked_against_episode_bytes(self):
        first = self.complete(0)
        first["outcome"]["rounds"] = 1
        self.save_receipt(0, first)
        second = self.complete(1)
        second["work"]["transitions"] = 63
        self.save_receipt(1, second)
        report = self.inspect()
        self.assertEqual(report["summary"]["classifications"]
                         ["corrupt_or_contradictory"], 2)
        self.assertEqual(report["summary"]["policies"]["uct"]["known_transitions"], 0)

    def test_independent_hp_outcome_rejects_shape_consistent_saved_win(self):
        receipt = self.complete(0)
        directory = self.directory(0)
        record = json.loads((directory / "episode.json").read_bytes())
        record["final"]["state"]["player"]["hp"] = 0
        # This remains a structurally accepted saved win. The recovery's HP
        # classifier must reject it even when receipt and both hashes agree.
        records.validate_record(record)
        emitted = records.output_bytes(record)
        (directory / "episode.json").write_bytes(emitted)
        (directory / "stdout.raw").write_bytes(emitted)
        receipt["episode"] = {"path": "episode.json", **recovery._identity(emitted)}
        receipt["transport"]["stdout"] = {
            "path": "stdout.raw", **recovery._identity(emitted)}
        receipt["transport"]["stdout_observed_bytes"] = len(emitted)
        self.save_receipt(0, receipt)
        report = self.assert_classification(0, "corrupt_or_contradictory")
        self.assertIn("HP", report["trials"][0]["issues"][0])

    def test_missing_aggregate_withholds_source_and_complete_admission(self):
        self.complete(0)
        (self.capture / "results.json").unlink()
        report = self.assert_classification(0, "incomplete_attempt")
        self.assertFalse(report["collection_identity_available"])
        self.assertIsNone(report["trials"][0]["outcome"])
        self.assertTrue(any("identity are unknown" in issue
                            for issue in report["issues"]))

    def test_affirmative_aggregate_hash_and_summary_contradictions_remain_visible(self):
        for index in range(6):
            self.complete(index)
        self.finish_aggregate()
        self.aggregate["trials"][0]["receipt_identity"]["sha256"] = "a" * 64
        self.aggregate["summary"]["uct"]["terminal_wins_by_round_cap"] = 0
        self.save_aggregate()
        report = self.assert_classification(0, "corrupt_or_contradictory")
        self.assertFalse(report["inventory_evidence_consistent"])
        self.assertTrue(any("summary contradicts" in issue
                            for issue in report["issues"]))

    def test_not_attempted_status_does_not_hide_affirmative_outcome_claims(self):
        self.complete(0)
        self.aggregate["trials"][0]["terminal_result"] = 1.0
        self.save_aggregate()
        report = self.assert_classification(0, "corrupt_or_contradictory")
        self.assertFalse(report["inventory_evidence_consistent"])
        self.assertIn("affirmative", report["trials"][0]["issues"][0])

    def test_noninitial_incomplete_summary_is_checked_as_an_affirmative_claim(self):
        self.complete(0)
        self.aggregate["summary"]["uct"]["terminal_wins_by_round_cap"] = 3
        self.save_aggregate()
        report = self.assert_classification(0, "complete_admitted")
        self.assertFalse(report["inventory_evidence_consistent"])
        self.assertTrue(any("affirmative summary" in issue
                            for issue in report["issues"]))

    def test_optional_owner_consistency_does_not_authenticate_os(self):
        owner = {
            "format": "mcts-owned-process", "schema_version": 1,
            "established": True, "failure_kind": None, "error": None,
            "launch": {field: True for field in (
                "created_suspended", "membership_verified_before_resume",
                "limits_verified_before_resume", "primary_thread_resumed",
                "job_handle_noninheritable", "process_handles_noninheritable",
                "stdio_handle_list_only")},
            "cleanup": {"retired": True, "worker_reaped": True, "job_empty": True,
                        "readers_retired": True, "handles_closed": True,
                        "final_active_processes": 0, "errors": []},
        }
        for index in range(5):
            receipt = self.complete(index)
            observed = copy.deepcopy(owner)
            if index == 0:
                observed["failure_kind"] = "cancelled"
            elif index == 1:
                observed["cleanup"]["retired"] = False
            elif index == 2:
                observed["launch"]["primary_thread_resumed"] = False
            elif index == 3:
                observed["cleanup"]["member_handles_signaled"] = False
            receipt["transport"]["owner"] = observed
            self.save_receipt(index, receipt)
        report = self.inspect()
        self.assertEqual(report["summary"]["classifications"]
                         ["corrupt_or_contradictory"], 4)
        self.assertEqual(report["trials"][4]["classification"], "complete_admitted")
        self.assertFalse(report["boundaries"]["os_ownership_established"])
        self.assertFalse(report["boundaries"]["origin_authenticated"])

    def test_aggregate_complete_trial_requires_its_retained_final_receipt(self):
        self.complete(0)
        self.finish_aggregate()
        (self.directory(0) / "receipt.json").unlink()
        report = self.assert_classification(0, "corrupt_or_contradictory")
        self.assertIn("without a retained final receipt",
                      report["trials"][0]["issues"][0])

    def test_duplicate_aggregate_trial_disables_collection_identity(self):
        self.complete(0)
        self.aggregate["trials"][1].update({key: self.aggregate["trials"][0][key]
                                            for key in recovery.TRIAL_FIELDS})
        self.save_aggregate()
        report = self.assert_classification(0, "incomplete_attempt")
        self.assertFalse(report["collection_identity_available"])

    def test_limits_and_create_only_output_refuse_before_apparent_report_success(self):
        with self.assertRaisesRegex(recovery.RecoveryRuntimeError,
                                     "total read allowance"):
            recovery.recover_capture(self.capture, self.output, max_read_bytes=1)
        self.assertFalse(self.output.exists())
        with self.assertRaisesRegex(recovery.RecoveryRuntimeError,
                                     "outside the capture"):
            recovery.recover_capture(self.capture, self.capture / "recovery.json")
        self.output.write_bytes(b"preserved existing output")
        with (patch.object(recovery._Snapshot, "read") as read,
              self.assertRaisesRegex(recovery.RecoveryRuntimeError, "new file")):
            recovery.recover_capture(self.capture, self.output)
        read.assert_not_called()
        self.assertEqual(self.output.read_bytes(), b"preserved existing output")

    def test_mutation_during_inspection_refuses_report(self):
        self.complete(0)
        original = recovery._Snapshot.read
        def mutating(snapshot, path, limit):
            data = original(snapshot, path, limit)
            if path.name == "receipt.json":
                with (self.capture / "protocol.json").open("ab") as stream:
                    stream.write(b" ")
            return data
        with (patch.object(recovery._Snapshot, "read", mutating),
              self.assertRaisesRegex(recovery.RecoveryRuntimeError,
                                      "changed during inspection")):
            self.inspect()
        self.assertFalse(self.output.exists())

    def test_symlink_evidence_refuses_without_reading_its_target(self):
        target = self.root / "outside-private.json"
        target.write_bytes(b"must not inspect")
        link = self.directory(0) / "receipt.json"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation is unavailable for this account")
        with self.assertRaisesRegex(recovery.RecoveryRuntimeError, "links and reparse"):
            self.inspect()
        self.assertFalse(self.output.exists())
        self.assertEqual(target.read_bytes(), b"must not inspect")

    def test_cli_delivers_report_and_makes_no_completion_or_execution_claim(self):
        self.complete(0)
        with contextlib.redirect_stdout(io.StringIO()) as text:
            code = recover_encounters.main(
                [str(self.capture), "--output", str(self.output)])
        self.assertEqual(code, 0)
        self.assertIn("1 complete admitted", text.getvalue())
        self.assertIn("5 with no retained execution evidence", text.getvalue())
        with (contextlib.redirect_stderr(io.StringIO()),
              self.assertRaises(SystemExit) as raised):
            recover_encounters.main([
                str(self.capture), "--output", str(self.root / "bad.json"),
                "--max-read-bytes", "0"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
