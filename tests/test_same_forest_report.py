"""Audit the retained execution control without collecting another attempt."""

import copy
import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import render_same_forest as report
from tools.run_same_forest import compare_condition


class SameForestReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(report.DATA.read_text(encoding="utf-8"))
        cls.protocol = json.loads(report.PROTOCOL.read_text(encoding="utf-8"))

    def validate(self, data):
        report.validate(data, self.protocol)

    def test_original_bytes_protocol_revision_and_both_formats(self):
        report.check_outputs()
        self.assertEqual(
            hashlib.sha256(report.DATA.read_bytes()).hexdigest(), report.RESULT_SHA256
        )
        self.assertEqual(report.digest(report.PROTOCOL), report.PROTOCOL_SHA256)
        self.assertEqual(self.data["source"]["revision"], report.EVALUATED_REVISION)
        self.assertEqual(
            sum(c["report"]["simulations"] for c in self.data["cells"]), 216000
        )
        self.assertEqual(
            sum(c["report"]["transitions"] for c in self.data["cells"]), 1080000
        )

    def test_incomplete_reordered_or_changed_source_is_rejected(self):
        mutations = [
            lambda d: d["cells"].pop(),
            lambda d: d["cells"].reverse(),
            lambda d: d["cells"].__setitem__(2, d["cells"][1]),
            lambda d: d.__setitem__("status", "incomplete"),
            lambda d: d.__setitem__("source_unchanged_at_end", False),
            lambda d: d["source"].__setitem__("revision", "f" * 40),
            lambda d: d.__setitem__("protocol_sha256", "0" * 64),
        ]
        for change in mutations:
            data = copy.deepcopy(self.data)
            change(data)
            with self.assertRaises(ValueError):
                self.validate(data)

    def test_matching_bad_receipts_are_not_valid_merely_because_they_match(self):
        for field, value in (
            ("seed", 1),
            ("assigned_simulations", 6001),
            ("transitions", 29999),
            ("unused_transitions", None),
            ("virtual_visits", 1),
            ("stop_reasons", ["simulation_cap"]),
            ("status", "unreported"),
            ("error", "WorkerError"),
        ):
            data = copy.deepcopy(self.data)
            for cell in data["cells"][:3]:
                cell["report"]["workers"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(data)

    def test_ranked_means_and_action_identity_are_reconstructed(self):
        changed_mean = math.nextafter(self.data["cells"][0]["ranked"][0]["win_rate"], 1)
        for field, value in (
            ("win_rate", 0.9),
            ("win_rate", changed_mean),
            ("visits", 1),
            ("action", {"card_idx": 100, "target_idx": None}),
        ):
            data = copy.deepcopy(self.data)
            for cell in data["cells"][:3]:
                cell["ranked"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(data)

    def test_comparisons_are_recomputed_and_wrong_ratios_rejected(self):
        data = copy.deepcopy(self.data)
        data["comparisons"][0]["sequential_wall_ratio"]["cold"] = 10.0
        with self.assertRaisesRegex(ValueError, "saved comparisons"):
            self.validate(data)
        data = copy.deepcopy(self.data)
        data["cells"][2]["ranked"][0]["label"] = "Changed identity"
        with self.assertRaisesRegex(ValueError, "forest mismatch"):
            self.validate(data)

    def test_preparation_is_not_conflated_with_search_and_timings_are_finite(self):
        for field, value in (
            ("preparation_s", 0),
            ("prepared_pool_startup_s", 100),
            ("elapsed_s", float("nan")),
            ("elapsed_s", False),
        ):
            data = copy.deepcopy(self.data)
            data["cells"][2][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(data)
        data = copy.deepcopy(self.data)
        data["cells"][2]["report"]["pool_startup_s"] = 0.1
        with self.assertRaisesRegex(ValueError, "warm preparation"):
            self.validate(data)

    def test_slow_process_and_existing_slower_warm_observation_are_retained(self):
        data = copy.deepcopy(self.data)
        data["cells"][1]["elapsed_s"] = data["cells"][0]["elapsed_s"] * 2
        data["comparisons"][0] = compare_condition(data["cells"][:3])
        self.validate(data)
        self.assertIn("0.500", report.markdown(data))
        text = report.markdown(self.data)
        self.assertIn("warm execution took 0.794376 seconds", text)
        self.assertIn("cold execution took 0.759412 seconds", text)
        self.assertIn(
            "literature review below informed this new execution control", text
        )
        self.assertIn("not that earlier protocol", text)
        self.assertIn("not a calibrated win probability", text)
        self.assertEqual(report.webpage(self.data).count("<tbody>"), 3)

    def test_byte_drift_is_rejected_even_when_json_meaning_is_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "same.json"
            path.write_text(json.dumps(self.data), encoding="utf-8")
            with patch.object(report, "DATA", path):
                with self.assertRaisesRegex(ValueError, "first attempt bytes"):
                    report.check_outputs()

    def test_html_escapes_observed_conditions(self):
        data = copy.deepcopy(self.data)
        data["environment"]["conditions"] = "<script>bad</script> & shared"
        self.assertIn(
            "&lt;script&gt;bad&lt;/script&gt; &amp; shared", report.webpage(data)
        )
        self.assertNotIn("<script>bad</script>", report.webpage(data))


if __name__ == "__main__":
    unittest.main()
