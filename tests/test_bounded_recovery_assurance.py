"""Declared transport and sidecar dispositions use the real recovery fixture."""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

import test_encounter_recovery as fixtures

from game import episode_record as records
from tools import encounter_recovery as recovery


class BoundedRecoveryAssuranceTests(unittest.TestCase):
    def fixture(self):
        fixture = fixtures.EncounterRecoveryTests(methodName="runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def inspect(self, fixture, classification, consistent, issue=None):
        before = {
            path.relative_to(fixture.capture).as_posix():
            (path.read_bytes(), path.stat().st_mtime_ns)
            for path in fixture.capture.rglob("*") if path.is_file()
        }
        # Existing guards deny subprocesses, search, replay and recorder retry.
        with (patch.object(records, "load_content", side_effect=AssertionError(
                "passive recovery cannot load model content")),
              patch.object(records, "play_game", side_effect=AssertionError(
                  "passive recovery cannot run a model"))):
            report = fixture.inspect()
        row = report["trials"][0]
        self.assertEqual(row["classification"], classification)
        self.assertIs(report["inventory_evidence_consistent"], consistent)
        if issue is not None:
            self.assertTrue(any(issue in value for value in row["issues"]),
                            row["issues"])
        if classification != "complete_admitted":
            self.assertIsNone(row["outcome"])
            self.assertIsNone(row["work"])
            for policy in report["summary"]["policies"].values():
                self.assertEqual(policy["known_simulations"], 0)
                self.assertEqual(policy["known_transitions"], 0)
        for name in ("search_performed", "replay_performed", "retry_performed",
                     "original_evidence_modified", "origin_authenticated"):
            self.assertIs(report["boundaries"][name], False)
        after = {
            path.relative_to(fixture.capture).as_posix():
            (path.read_bytes(), path.stat().st_mtime_ns)
            for path in fixture.capture.rglob("*") if path.is_file()
        }
        self.assertEqual(before, after)
        return report

    def test_observed_lengths_have_independently_declared_dispositions(self):
        cases = (
            (0, "complete_admitted", True, None),
            (-1, "corrupt_or_contradictory", False, "smaller than retained"),
            (1, "corrupt_or_contradictory", False, "untruncated transport size"),
        )
        count = 0
        for role in ("stdout", "stderr"):
            for delta, classification, consistent, issue in cases:
                with self.subTest(role=role, delta=delta):
                    fixture = self.fixture()
                    receipt = fixture.complete(0)
                    receipt["transport"][role + "_observed_bytes"] += delta
                    # Update the timing join so only the transport case decides.
                    fixture.save_receipt(0, receipt)
                    fixture.finish_aggregate()
                    self.inspect(fixture, classification, consistent, issue)
                    count += 1
        self.assertEqual(count, 6)

    def test_complete_truncated_transport_is_contradictory(self):
        fixture = self.fixture()
        receipt = fixture.complete(0)
        receipt["transport"]["stdout_truncated"] = True
        receipt["transport"]["stdout_observed_bytes"] += 1
        fixture.save_receipt(0, receipt)
        fixture.finish_aggregate()
        self.inspect(fixture, "corrupt_or_contradictory", False,
                     "complete receipt has failed, incomplete or truncated")

    def test_final_incomplete_truncated_fragment_keeps_outcome_and_work_unknown(self):
        fixture = self.fixture()
        receipt = fixture.incomplete(0, "timeout")
        directory = fixture.directory(0)
        streams = {"stdout": b'{"partial":', "stderr": b"interrupted\n"}
        receipt["elapsed_subprocess_seconds"] = 0.1
        receipt["transport"] = {
            "returncode": None, "elapsed_subprocess_seconds": 0.1,
            "timeout_diagnostics": {"kind": "synthetic timeout"},
            "stdout_observed_bytes": len(streams["stdout"]) + 1,
            "stderr_observed_bytes": len(streams["stderr"]),
            "stdout_truncated": True, "stderr_truncated": False,
        }
        for role, data in streams.items():
            (directory / (role + ".raw")).write_bytes(data)
            receipt["transport"][role] = {
                "path": role + ".raw", **recovery._identity(data)}
        fixture.save_receipt(0, receipt)
        fixture.finish_aggregate()
        report = self.inspect(fixture, "incomplete_attempt", True)
        self.assertEqual(report["trials"][0]["recorded_status"], "timeout")

    def test_sidecar_only_mismatches_are_contradictory(self):
        for role, field, value in (("work", "work", None),
                                   ("timing", "elapsed_subprocess_seconds", 0.2)):
            with self.subTest(role=role):
                fixture = self.fixture()
                receipt = fixture.complete(0)
                fixture.finish_aggregate()
                path = fixture.directory(0) / (role + ".json")
                if role == "work":
                    sidecar = {"work": copy.deepcopy(receipt["work"])}
                else:
                    sidecar = {"elapsed_subprocess_seconds": 0.1,
                               "transport": copy.deepcopy(receipt["transport"])}
                sidecar[field] = value
                fixtures.write_json(path, sidecar)
                self.inspect(fixture, "corrupt_or_contradictory", False,
                             "sidecar differs from receipt: " + role + ".json")


if __name__ == "__main__":
    unittest.main()
