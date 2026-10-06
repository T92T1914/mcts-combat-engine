"""Exercise the delivered retained-data consumers without running searches."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import derive_same_forest_public_receipts as public_receipts
from tools import render_same_forest_repeatability as report
from tools import render_same_forest_repeatability_figure as figure


class RepeatabilityOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(report.DATA.read_text(encoding="utf-8"))
        cls.failed = json.loads(report.FAILED.read_text(encoding="utf-8"))
        cls.provenance = json.loads(report.PROVENANCE.read_text(encoding="utf-8"))

    def test_exact_public_derivatives_and_generated_outputs(self):
        record, summary = report.check_outputs()
        manifest = figure.check_outputs()
        self.assertEqual(
            hashlib.sha256(report.DATA.read_bytes()).hexdigest(), report.RESULT_SHA256
        )
        self.assertEqual(
            hashlib.sha256(report.FAILED.read_bytes()).hexdigest(), report.FAILED_SHA256
        )
        self.assertEqual(record["source"]["revision"], report.MEASURED_REVISION)
        self.assertEqual(len(summary), 24)
        self.assertFalse(manifest["evidence"]["search_rerun"])
        self.assertEqual(len(manifest["evidence"]["values"]), 24)
        self.assertEqual(manifest["evidence"]["x_axis"], [0.5, 5.0])
        self.assertEqual(len(manifest["outputs_sha256"]), 8)

    def test_derivation_changes_only_declared_metadata_and_preserves_metrics(self):
        # Synthetic private fingerprints surround the actual public receipt values.
        # The exact private-input preservation check is retained separately.
        private = copy.deepcopy(self.data)
        del private["publication_derivative"]
        private["environment"].update(
            python="3.11.8 (synthetic compiler build)",
            platform="Windows-synthetic-build",
            interpreter_sha256="f" * 64,
        )
        for index, item in enumerate(private["blocks"]):
            del item["record_hash_kind"]
            item["record"]["pid"] = 10000 + index
            item["record_sha256"] = public_receipts.identity(
                public_receipts.canonical(item["record"])
            )["sha256"]
        raw = public_receipts.canonical(private)
        derived = public_receipts.derive(private, public_receipts.identity(raw))
        self.assertEqual(report.summarize(private), report.summarize(derived))
        self.assertNotIn("interpreter_sha256", derived["environment"])
        self.assertEqual(derived["environment"]["python"], "3.11.8")
        self.assertEqual(derived["environment"]["platform"], "Windows")
        restored = copy.deepcopy(derived)
        del restored["publication_derivative"]
        restored["environment"] = copy.deepcopy(private["environment"])
        for original, public, item in zip(
            private["blocks"], derived["blocks"], restored["blocks"], strict=True
        ):
            self.assertEqual(public["record"]["cells"], original["record"]["cells"])
            self.assertEqual(
                public["record"]["schedule"], original["record"]["schedule"]
            )
            self.assertNotIn("pid", public["record"])
            del item["record_hash_kind"]
            item["record"]["pid"] = original["record"]["pid"]
            item["record_sha256"] = original["record_sha256"]
        self.assertEqual(restored, private)
        self.assertEqual(public_receipts.canonical(private), raw)
        for field, value in (("python", "unparsed"), ("platform", "unknown")):
            changed = copy.deepcopy(private)
            changed["environment"][field] = value
            with self.assertRaises(ValueError):
                public_receipts.derive(changed, public_receipts.identity(raw))

    def test_published_snapshot_maps_source_without_rewriting_measurement(self):
        snapshot = self.provenance["measurement_source_snapshot"]
        self.assertEqual(
            snapshot["recorded_local_revision"], self.data["source"]["revision"]
        )
        self.assertNotEqual(
            snapshot["public_equivalent_revision"], self.data["source"]["revision"]
        )
        self.assertEqual(snapshot["recorded_git_tree"], snapshot["public_git_tree"])
        text = report.markdown(self.data, report.summarize(self.data), self.provenance)
        self.assertIn("/tree/" + snapshot["public_equivalent_revision"], text)
        self.assertIn("not preservation of the original commit identity", text)
        self.assertIn("not the measured source", text)
        for field, value in (
            ("recorded_local_revision", snapshot["public_equivalent_revision"]),
            ("public_git_tree", "0" * 40),
            ("public_equivalent_revision", "0" * 40),
            ("original_commit_identity_preserved", True),
            ("retained_receipt_revisions_rewritten", True),
            ("search_rerun_for_publication", True),
        ):
            changed = copy.deepcopy(self.provenance)
            changed["measurement_source_snapshot"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                ValueError, "source snapshot mapping differs"
            ):
                report.validate_provenance(changed, self.data, self.failed)

    def test_meaning_preserving_raw_reformat_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "changed.json"
            path.write_text(json.dumps(self.data, indent=3), encoding="utf-8")
            with patch.object(report, "DATA", path):
                with self.assertRaisesRegex(ValueError, "retained attempt bytes"):
                    report.check_outputs()

    def test_stale_generated_report_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "changed.md"
            path.write_text(report.REPORT.read_text() + "Changed output\n", "utf-8")
            with patch.object(report, "REPORT", path):
                with self.assertRaisesRegex(ValueError, "generated report differs"):
                    report.check_outputs()

    def test_failed_attempt_disposition_and_resource_claims_are_checked(self):
        for key, field, value in (
            ("failed_attempt", "performance_evidence", True),
            ("corrected_collection", "partial_blocks_reused", True),
            ("analysis", "search_rerun_for_analysis", True),
            ("complete_attempt", "owned_processes_after_retirement", 1),
            ("resource_bounds", "maximum_search_workers", 8),
        ):
            changed = copy.deepcopy(self.provenance)
            changed[key][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                report.validate_provenance(changed, self.data, self.failed)

    def test_html_table_contains_every_value_and_escapes_conditions(self):
        summary = report.summarize(self.data)
        changed = copy.deepcopy(self.data)
        changed["environment"]["conditions"] = "<script>bad()</script> & shared"
        text = report.webpage(changed, summary, self.provenance)
        self.assertNotIn("<script>bad()", text)
        self.assertIn("&lt;script&gt;bad()&lt;/script&gt; &amp; shared", text)
        self.assertEqual(text.count('<th scope="col">'), 7)
        self.assertEqual(text.count("<tr>"), 25)
        for row in summary:
            low, high = row["approximate_95_interval"]
            self.assertIn(f"<td>{row['geometric_mean_ratio']:.3f}</td>", text)
            self.assertIn(f"<td>{low:.3f} to {high:.3f}</td>", text)
        self.assertIn('tabindex="0" role="region"', text)
        self.assertIn("First failed attempt", text)

    def test_changed_figure_value_or_bytes_are_rejected(self):
        original = json.loads(figure.MANIFEST.read_text(encoding="utf-8"))
        for mutation in ("value", "hash"):
            changed = copy.deepcopy(original)
            if mutation == "value":
                changed["evidence"]["values"][0]["geometric_mean_ratio"] += 1
            else:
                key = next(iter(changed["outputs_sha256"]))
                changed["outputs_sha256"][key] = "0" * 64
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "changed.json"
                path.write_text(json.dumps(changed), encoding="utf-8")
                with patch.object(figure, "MANIFEST", path):
                    with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                        figure.check_outputs()


if __name__ == "__main__":
    unittest.main()
