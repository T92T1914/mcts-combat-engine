"""Managed admission, publication and cumulative artifact accounting."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from test_encounter_policy_evaluation import episode_fixture, protocol, transport

from game import episode_record as records
from tools import encounter_policy_evaluation as capture
from tools import managed_encounter as managed


class ManagedCaptureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mcts-managed-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.protocol = self.root / "input.json"
        self.protocol.write_bytes(records.canonical(protocol()))

    def test_cumulative_reservation_counts_replacements_and_denies_before_write(self):
        budget = managed.ArtifactBudget(self.root, 7)
        target = self.root / "record"
        budget.write_bytes(target, b"old")
        budget.write_bytes(target, b"new")
        with self.assertRaises(managed.ArtifactLimit):
            budget.write_bytes(target, b"xx")
        self.assertEqual(target.read_bytes(), b"new")
        self.assertEqual(budget.used, 6)
        self.assertFalse(target.with_name("record.pending").exists())
        with self.assertRaises(managed.ArtifactLimit):
            budget.append(self.root.parent / "escape", b"x")

    def test_concurrent_stream_reservations_never_exceed_allowance(self):
        budget = managed.ArtifactBudget(self.root, 101)
        failures = []

        def append(name):
            try:
                for _ in range(100):
                    budget.append(self.root / name, b"x")
            except managed.ArtifactLimit:
                failures.append(name)

        threads = [threading.Thread(target=append, args=(name,))
                   for name in ("stdout", "stderr")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(budget.used, 101)
        self.assertEqual(sum(path.stat().st_size for path in self.root.iterdir()
                             if path.name in {"stdout", "stderr"}), 101)
        self.assertIn(len(failures), (1, 2))

    def test_managed_failure_stops_inventory_without_replacement(self):
        fixture = episode_fixture(capture._inventory(protocol())[0])
        content = fixture["content"]
        implementation = {"episode": fixture["implementation"], "capture_files": {}}
        for retired in (True, False):
            with self.subTest(retired=retired):
                output = self.root / str(retired)
                control = managed.ManagedControl(output, 1024 * 1024,
                                                 128 * managed.MIB, 1,
                                                 self.root / "cancel")
                failed = transport(b"partial", timeout=True)
                failed["owner"] = {
                    "established": True, "failure_kind": "timeout",
                    "cleanup": {"retired": retired},
                }
                with (patch.object(records, "load_content", return_value=({}, content)),
                      patch.object(capture, "_source_identity",
                                   return_value=implementation),
                      patch.object(control, "child", return_value=failed) as child):
                    report = capture.run_evaluation(
                        self.protocol, output, process_tree_bound="synthetic owner",
                        control=control)
                self.assertEqual(child.call_count, 1)
                self.assertEqual(len(report["trials"]), 6)
                self.assertEqual(report["status"], "incomplete")
                self.assertEqual(report["trials"][0]["status"],
                                 "timeout" if retired else "retirement_failure")
                self.assertEqual([row["status"] for row in report["trials"]][1:],
                                 ["not_attempted"] * 5)
                self.assertFalse((output / "trials/00000/episode.json").exists())
                intent = output / "trials/00000/admission-intent.json"
                self.assertTrue(intent.exists())

    def test_cancellation_before_admission_has_no_child_or_intent(self):
        cancel = self.root / "cancel"
        cancel.touch()
        control = managed.ManagedControl(self.root, 1024, 128 * managed.MIB, 1, cancel)
        with self.assertRaisesRegex(capture.EncounterRuntimeError, "cancellation"):
            control.before_trial(capture._inventory(protocol())[0], {}, self.root)
        self.assertFalse((self.root / "admission-intent.json").exists())

    def test_nonwindows_strict_refusal_precedes_input_and_output(self):
        output = self.root / "refused"
        with patch.object(managed.sys, "platform", "linux"), self.assertRaises(
                managed.EnforcementUnavailable):
            managed.run_managed(self.root / "missing.json", output)
        self.assertFalse(output.exists())

    def invoke_controller(self, output, *, mutate=False, owner_failure=None):
        def owned(command, **options):
            plan = json.loads((output / "worker-plan.json").read_bytes())
            self.assertEqual(Path(plan["protocol_path"]).read_bytes(),
                             records.canonical(protocol()))
            if mutate:
                self.protocol.write_bytes(b"{}")
            result = transport(records.canonical({
                "format": "mcts-managed-worker-result", "schema_version": 1,
                "status": "complete", "intended_trials": 6, "complete_trials": 6,
                "artifact_content_bytes_written": 100,
            }))
            result["owner"] = {"established": True, "failure_kind": owner_failure,
                               "cleanup": {"retired": True}}
            return result

        with patch.object(managed.sys, "platform", "win32"), patch.object(
                managed, "run_owned", side_effect=owned):
            return managed.run_managed(self.protocol, output)

    def test_snapshot_retained_and_original_mutation_withholds_completion(self):
        result, code = self.invoke_controller(self.root / "mutated", mutate=True)
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "incomplete")
        self.assertFalse(result["original_input_unchanged"])
        self.assertEqual((self.root / "mutated/protocol-input.json").read_bytes(),
                         records.canonical(protocol()))

    def test_success_claim_requires_clean_owner_and_memory_observation(self):
        for failure in (None, "memory_limit_observation", "retirement_failure"):
            with self.subTest(failure=failure):
                result, code = self.invoke_controller(self.root / str(failure),
                                                     owner_failure=failure)
                self.assertEqual(code, 0 if failure is None else 1)
                self.assertEqual(result["status"],
                                 "complete" if failure is None else "incomplete")


if __name__ == "__main__":
    unittest.main()
