"""Validate retained diagnostic evidence without running another measured search."""

import copy
import hashlib
import json
import math
import unittest

from tools import run_serial_profile as study
from tools.validate_serial_profile import validate


class RetainedProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = study.ROOT / "docs/serial-profile-results.json"
        cls.record = json.loads(cls.path.read_text(encoding="utf-8"))

    def test_first_attempt_bytes_and_source_identity_are_preserved(self):
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),
                         "a528960d7c14724dbb4d90b23133310b15"
                         "e52bee7ffcf9a1bf2ec910bbb5df63")
        self.assertEqual(self.record["source"]["revision"],
                         "a8e18580401601846fbd21ab27d4731d19cceef6")
        self.assertTrue(self.record["source_unchanged_at_end"])
        self.assertEqual(self.record["protocol_sha256"], study.digest(study.PROTOCOL))
        self.assertEqual(self.record["status"], "complete")
        validate(self.record)

    def test_every_receipt_matches_fixed_work_and_control(self):
        cells = self.record["cells"]
        self.assertEqual([(c["scenario"], c["mode"]) for c in cells], [
            (s, m) for s in ("duel", "gauntlet", "boss")
            for m in ("control", "profiled")])
        for control, profiled in zip(cells[::2], cells[1::2], strict=True):
            self.assertEqual(control["computation"], profiled["computation"])
            self.assertEqual(control["root_sha256"], profiled["root_sha256"])
            self.assertEqual(control["profile"], [])
            self.assertTrue(profiled["profile"])
            for cell in (control, profiled):
                self.assertEqual(cell["status"], "completed")
                self.assertIsNone(cell["error"])
                self.assertTrue(cell["root_unchanged"])
                self.assertGreater(cell["elapsed_s"], 0)
                self.assertTrue(math.isfinite(cell["elapsed_s"]))
                computation = cell["computation"]
                self.assertEqual(computation["simulations"], 3000)
                self.assertEqual(computation["transitions"], 15000)
                self.assertEqual(computation["unused_transitions"], 0)
                self.assertEqual(set(computation["stop_reasons"]),
                                 {"transition_allowance", "simulation_cap"})
                self.assertEqual(sum(r["visits"] for r in
                                     computation["root_statistics"]), 3000)
                self.assertEqual(cell["observed_simulations"], 3000)
                self.assertEqual(cell["observed_transitions"], 15000)

    def test_profile_rows_are_finite_and_contain_no_absolute_paths(self):
        for cell in self.record["cells"]:
            for row in cell["profile"]:
                self.assertNotIn("\\", row["file"])
                self.assertNotIn(":/", row["file"])
                self.assertFalse(row["file"].startswith("/"))
                self.assertGreaterEqual(row["calls"], row["primitive_calls"])
                self.assertGreaterEqual(row["primitive_calls"], 0)
                for key in ("self_s", "cumulative_s"):
                    self.assertTrue(math.isfinite(row[key]))
                    self.assertGreaterEqual(row[key], 0)

    def test_validator_rejects_matching_bad_work_and_changed_rankings(self):
        for mutation in (
            lambda c: c["computation"].__setitem__("transitions", 14000),
            lambda c: c["computation"]["ranked"][0].__setitem__("win_rate", 0),
            lambda c: c.__setitem__("root_sha256", "0" * 64),
        ):
            record = copy.deepcopy(self.record)
            for cell in record["cells"][:2]:
                mutation(cell)
            with self.assertRaises(ValueError):
                validate(record)
        record = copy.deepcopy(self.record)
        record["cells"][1]["profile"][0]["self_s"] = float("nan")
        with self.assertRaises(ValueError):
            validate(record)


if __name__ == "__main__":
    unittest.main()
