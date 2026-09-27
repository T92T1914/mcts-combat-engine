"""Audit retained study accounting without collecting another measurement."""

import copy
import json
import unittest

from tools import render_parallel_scaling as report


class ParallelReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(
            (report.ROOT / "docs/parallel-scaling-results.json").read_text()
        )
        path = report.ROOT / "docs/parallel-scaling-protocol.json"
        cls.protocol = json.loads(path.read_text())
        cls.protocol_hash = report.digest(path)

    def validate(self, data):
        report.validate(data, self.protocol, self.protocol_hash)

    def test_saved_first_attempt_and_both_formats_match(self):
        self.validate(self.data)
        for name, text in (
            ("docs/parallel-scaling-results.md", report.markdown(self.data)),
            ("site/parallel-scaling.html", report.webpage(self.data)),
        ):
            self.assertEqual((report.ROOT / name).read_text("utf-8"), text)
        self.assertEqual(
            sum(c["report"]["simulations"] for c in self.data["cells"]), 648000
        )
        self.assertEqual(
            sum(c["report"]["transitions"] for c in self.data["cells"]), 3240000
        )

    def test_missing_cell_duplicate_cell_and_protocol_drift_are_rejected(self):
        for mutation in (
            lambda d: d["cells"].pop(),
            lambda d: d["cells"].__setitem__(3, d["cells"][2]),
            lambda d: d.__setitem__("protocol_sha256", "0" * 64),
        ):
            data = copy.deepcopy(self.data)
            mutation(data)
            with self.assertRaises(ValueError):
                self.validate(data)

    def test_unknown_failure_and_unused_work_cannot_be_hidden(self):
        for field, value in (
            ("status", "unreported"),
            ("transitions", None),
            ("assigned_simulations", 24000),
            ("unused_simulations", 1),
            ("virtual_visits", 2),
            ("seed", 7),
            ("error", "WorkerError"),
        ):
            data = copy.deepcopy(self.data)
            data["cells"][0]["report"]["workers"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(data)

    def test_aggregate_means_and_action_identity_reconcile_with_raw_statistics(self):
        data = copy.deepcopy(self.data)
        data["cells"][0]["ranked"][0]["win_rate"] += 0.01
        with self.assertRaisesRegex(ValueError, "raw sums"):
            self.validate(data)
        data = copy.deepcopy(self.data)
        data["cells"][0]["ranked"][0]["action"]["card_idx"] = 1
        with self.assertRaisesRegex(ValueError, "action identity"):
            self.validate(data)

    def test_nonfinite_timing_and_warm_pool_startup_are_rejected(self):
        for field, value in (("elapsed_s", float("nan")), ("pool_startup_s", 0.01)):
            data = copy.deepcopy(self.data)
            data["cells"][1]["report"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(data)

    def test_regressed_timing_remains_in_the_summary_and_every_condition(self):
        data = copy.deepcopy(self.data)
        cell = data["cells"][2]
        self.assertEqual((cell["workers"], cell["phase"]), (2, "cold"))
        cell["elapsed_s"] = data["cells"][0]["elapsed_s"] * 2
        self.validate(data)
        self.assertEqual(min(report.ratios(data, 2, "cold")), 0.5)
        markdown = report.markdown(data)
        self.assertIn("35 of 36 paired comparisons", markdown)
        self.assertIn("0.500", markdown)
        self.assertEqual(report.webpage(data).count("<tbody>"), 4)


if __name__ == "__main__":
    unittest.main()
