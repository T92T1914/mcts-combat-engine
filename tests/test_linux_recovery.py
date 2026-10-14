"""Independent dispositions for the new passive Linux receipt boundary."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from tools import linux_recovery as recovery


def receipt(*, phase="final", status="complete", admitted=True, retired=True):
    nonce, cid = "a" * 32, "b" * 64
    empty = {"observed_bytes": 0, "retained_bytes": 0,
             "sha256": hashlib.sha256(b"").hexdigest(), "truncated": False}
    return {
        "format": "mcts-linux-owned-container", "schema_version": 1,
        "phase": phase, "work_admitted": admitted,
        "input_files_unchanged": True,
        "request": {"nonce": nonce, "container_name": "mcts-linux-" + nonce,
                    "image_id": "sha256:" + "c" * 64,
                    "memory": 268435456, "memory_swap": 268435456,
                    "pids": 64, "tmpfs": 33554432, "cpus": 1,
                    "wall": 30, "cleanup": 10, "lifetime": 60,
                    "stdout_limit": 65536, "stderr_limit": 65536,
                    "output_limit": 131072, "artifact_limit": 2097152,
                    "artifact_names": []},
        "ownership": {"container_id": cid if admitted else None,
                      "native": {"host_pid": 123, "starttime": 456,
                                 "controller_excluded": True,
                                 "cgroup": "/system.slice/docker-" + cid + ".scope",
                                 "controls": {"memory.max": "268435456",
                                              "memory.swap.max": "0",
                                              "pids.max": "64",
                                              "cpu.max": "100000 100000"}}
                      if admitted else None},
        "outcome": {"status": status, "reason": None,
                    "returncode": 0 if status == "complete" else None},
        "cleanup": {"complete": retired, "container_absent": retired,
                    "pidfd_signalled": retired, "cgroup_empty_or_absent": retired},
        "output": {"stdout": copy.deepcopy(empty), "stderr": copy.deepcopy(empty),
                   "combined_observed_bytes": 0},
        "artifact_identities": {},
    }


class LinuxRecovery(unittest.TestCase):
    def test_complete_initial_and_interrupted_dispositions(self):
        cases = [receipt(), receipt(phase="before_create", status="pending",
                                    admitted=False, retired=False),
                 receipt(phase="admitted", status="pending", retired=False),
                 receipt(status="incomplete", retired=False)]
        for value in cases:
            before = json.dumps(value, sort_keys=True)
            with self.subTest(phase=value["phase"], status=value["outcome"]["status"]):
                result = recovery.inspect_receipt(value)
                self.assertTrue(result["consistent"], result["contradictions"])
                self.assertFalse(result["execution_performed"])
                self.assertFalse(result["cleanup_performed"])
                self.assertIn("not established", result["authentication"])
                self.assertEqual(before, json.dumps(value, sort_keys=True))

    def test_independently_expected_contradictions(self):
        mutations = [
            (("work_admitted",), False),
            (("outcome", "returncode"), False),
            (("outcome", "returncode"), 7),
            (("cleanup", "complete"), False),
            (("cleanup", "pidfd_signalled"), False),
            (("request", "memory"), 0),
            (("request", "pids"), False),
            (("ownership", "container_id"), ""),
            (("ownership", "native", "host_pid"), 0),
            (("ownership", "native", "controller_excluded"), False),
            (("ownership", "native", "controls", "memory.swap.max"), "max"),
            (("output", "stdout", "retained_bytes"), 1),
            (("output", "stdout", "observed_bytes"), None),
            (("output", "stdout", "sha256"), "0" * 64),
            (("output", "combined_observed_bytes"), False),
            (("output", "combined_observed_bytes"), 1),
            (("input_files_unchanged",), False),
        ]
        original = receipt()
        before = copy.deepcopy(original)
        for path, replacement in mutations:
            value = copy.deepcopy(original)
            target = value
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = replacement
            with self.subTest(path=path, replacement=replacement):
                result = recovery.inspect_receipt(value)
                self.assertFalse(result["consistent"])
                self.assertTrue(result["contradictions"])
        self.assertEqual(original, before)

    def test_incomplete_explicit_empty_counts_do_not_become_unknown(self):
        value = receipt(status="incomplete", retired=False)
        self.assertTrue(recovery.inspect_receipt(value)["consistent"])
        value["output"]["combined_observed_bytes"] = None
        self.assertFalse(recovery.inspect_receipt(value)["consistent"])

    def test_admission_phase_requires_its_explicit_work_disposition(self):
        initial = receipt(phase="before_admission", status="pending", retired=False)
        initial["work_admitted"] = False
        self.assertTrue(recovery.inspect_receipt(initial)["consistent"])
        initial["work_admitted"] = True
        self.assertFalse(recovery.inspect_receipt(initial)["consistent"])
        active = receipt(phase="admitted", status="pending", retired=False)
        self.assertTrue(recovery.inspect_receipt(active)["consistent"])
        active["work_admitted"] = False
        self.assertFalse(recovery.inspect_receipt(active)["consistent"])

    def test_declared_envelope_contradictions_and_incomplete_controls(self):
        original = receipt()
        data = b"xy"
        original["output"]["stdout"].update(
            observed_bytes=2, retained_bytes=2, sha256=hashlib.sha256(data).hexdigest())
        original["output"]["combined_observed_bytes"] = 2
        self.assertTrue(recovery.inspect_receipt(original)["consistent"])
        cases = []
        for key, replacement in (("stdout_limit", 1), ("output_limit", 1), ("cpus", 2)):
            value = copy.deepcopy(original)
            value["request"][key] = replacement
            cases.append(value)
        value = copy.deepcopy(original)
        value["ownership"]["native"]["controls"]["cpu.max"] = "200000 100000"
        cases.append(value)
        value = copy.deepcopy(original)
        value["request"]["artifact_names"] = ["missing.json"]
        cases.append(value)
        for sizes in ((1,), (1572864, 1572864), (0,)):
            value = copy.deepcopy(original)
            value["artifact_identities"] = {
                str(index) + ".json": {"bytes": size, "sha256": "c" * 64}
                for index, size in enumerate(sizes)}
            if len(sizes) != 1 or sizes == (0,):
                value["request"]["artifact_names"] = list(value["artifact_identities"])
            cases.append(value)
        for status, events in (("memory_pressure", {"memory.events": {
                "max": 0, "oom": 0, "oom_kill": 0}}),
                ("process_pressure", {"pids.events": {"max": 0}})):
            value = copy.deepcopy(original)
            value["outcome"]["status"] = status
            value["event_deltas"] = events
            cases.append(value)
        value = copy.deepcopy(original)
        del value["input_files_unchanged"]
        cases.append(value)
        for index, value in enumerate(cases):
            with self.subTest(case=index):
                self.assertFalse(recovery.inspect_receipt(value)["consistent"])
        incomplete = copy.deepcopy(original)
        incomplete["outcome"]["status"] = "output_limit"
        incomplete["request"].update(
            stdout_limit=1, artifact_names=["uncollected.json"])
        incomplete["output"]["stdout"].update(
            retained_bytes=1, truncated=True, sha256=hashlib.sha256(b"x").hexdigest())
        self.assertTrue(recovery.inspect_receipt(incomplete)["consistent"])

    def test_admitted_domain_and_truthful_unadmitted_refusal(self):
        changes = (("memory", 536870912), ("pids", 128), ("tmpfs", 67108864),
                   ("wall", 61), ("cleanup", 20), ("lifetime", 120))
        for name, replacement in changes:
            value = receipt()
            value["request"][name] = replacement
            if name == "memory":
                value["request"]["memory_swap"] = replacement
                controls = value["ownership"]["native"]["controls"]
                controls["memory.max"] = str(replacement)
            if name == "pids":
                value["ownership"]["native"]["controls"]["pids.max"] = str(replacement)
            with self.subTest(name=name):
                self.assertFalse(recovery.inspect_receipt(value)["consistent"])
        declined = receipt(status="refused", admitted=False, retired=False)
        declined["request"].update(memory=33554432, memory_swap=33554432)
        self.assertTrue(recovery.inspect_receipt(declined)["consistent"])

    def test_large_bounded_integer_refuses_through_passive_cli(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "receipt.json"
            value = receipt()
            value["request"]["wall"] = 10 ** 4000
            path.write_text(json.dumps(value))
            original = path.read_bytes(), path.stat().st_mtime_ns
            self.assertLess(len(original[0]), recovery.MAX_RECEIPT)
            with patch.dict("sys.modules", {"tools.linux_container": None}):
                with redirect_stdout(StringIO()) as captured:
                    self.assertEqual(recovery.main([str(path)]), 1)
            self.assertFalse(json.loads(captured.getvalue())["consistent"])
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), original)

    def test_passive_cli_preserves_original_and_never_calls_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "receipt.json"
            path.write_text(json.dumps(receipt(status="incomplete", retired=False)))
            original = path.read_bytes(), path.stat().st_mtime_ns
            with patch.dict("sys.modules", {"tools.linux_container": None}):
                with redirect_stdout(StringIO()) as captured:
                    self.assertEqual(recovery.main([str(path)]), 0)
            self.assertFalse(json.loads(captured.getvalue())["cleanup_performed"])
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), original)

    def test_explicit_cleanup_refusal_is_not_a_success_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "receipt.json"
            path.write_text(json.dumps(receipt(phase="admitted", status="pending",
                                                retired=False)))
            original = path.read_bytes(), path.stat().st_mtime_ns
            refused = {"status": "refused", "cleanup": {"complete": False}}
            with patch("tools.linux_container.recover_owned_container",
                       return_value=refused):
                with redirect_stdout(StringIO()) as captured:
                    self.assertEqual(recovery.main([
                        str(path), "--cleanup-owned-container"]), 1)
            report = json.loads(captured.getvalue())
            self.assertTrue(report["consistent"])
            self.assertTrue(report["cleanup_requested"])
            self.assertFalse(report["cleanup_performed"])
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), original)

    def test_already_retired_cleanup_is_success_without_new_exit_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "receipt.json"
            path.write_text(json.dumps(receipt()))
            original = path.read_bytes(), path.stat().st_mtime_ns
            already = {"status": "already_retired", "cleanup": {
                "complete": True, "container_absent": True,
                "cgroup_empty_or_absent": True,
                "historical_root_exit_not_newly_observed": True}}
            with patch("tools.linux_container.recover_owned_container",
                       return_value=already):
                with redirect_stdout(StringIO()) as captured:
                    self.assertEqual(recovery.main([
                        str(path), "--cleanup-owned-container"]), 0)
            report = json.loads(captured.getvalue())
            self.assertTrue(report["cleanup_requested"])
            self.assertFalse(report["cleanup_performed"])
            self.assertTrue(report["cleanup_result"]["cleanup"][
                "historical_root_exit_not_newly_observed"])
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), original)


if __name__ == "__main__":
    unittest.main()
