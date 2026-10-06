"""Synthetic repeated receipts test the supplement without timing searches."""

import copy
import dataclasses
import hashlib
import json
import math
import statistics
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from engine.parallel import FixedWorkReport, WorkerReceipt
from tools import render_same_forest_repeatability as report
from tools import run_same_forest_repeatability as study
from tools.run_same_forest import compare_condition


def seal(block):
    return hashlib.sha256(
        (json.dumps(block, indent=2, allow_nan=False) + "\n").encode()
    ).hexdigest()


def fixture():
    original = json.loads((study.ROOT / "docs/same-forest-results.json").read_text())
    templates = {(c["scenario"], c["roots"], c["phase"]): c
                 for c in original["cells"]}
    source = copy.deepcopy(original["source"])
    source["sha256"]["docs/same-forest-repeatability-protocol.json"] = (
        study.digest(study.PROTOCOL)
    )
    source["retained_first_attempt_sha256"] = hashlib.sha256(
        (study.ROOT / "docs/same-forest-results.json").read_bytes()
    ).hexdigest()
    result = {"schema_version": 1, "protocol": "same-forest-repeatability-v1",
              "protocol_sha256": study.digest(study.PROTOCOL), "source": source,
              "source_unchanged_at_end": True, "status": "complete",
              "environment": {"python": "synthetic", "platform": "synthetic",
                              "conditions": "Synthetic receipts, not measurement",
                              "start_method": "spawn", "interpreter_sha256": "a" * 64},
              "process_tree_bound": "synthetic only", "collection_wall_s": 1.0,
              "started_utc": "synthetic", "ended_utc": "synthetic", "blocks": []}
    for b in range(6):
        block = {"block": b, "source": source, "protocol": result["protocol"],
                 "protocol_sha256": result["protocol_sha256"],
                 "source_unchanged_at_end": True, "status": "complete",
                 "schedule": study.schedule(b), "cells": [], "comparisons": []}
        for condition in block["schedule"]:
            group = []
            for phase in condition["order"]:
                cell = copy.deepcopy(templates[(condition["scenario"],
                                                 condition["roots"], phase)])
                cell.update(block=b, iteration=condition["iteration"])
                cell["complete_call_s"] = (
                    cell["elapsed_s"] + cell["preparation_s"] + 0.25
                )
                group.append(cell)
                block["cells"].append(cell)
            comparison = compare_condition(group)
            comparison.update(block=b, iteration=condition["iteration"])
            block["comparisons"].append(comparison)
        controller = sum(c["complete_call_s"] for c in block["cells"]) + 0.1
        result["blocks"].append({"block": b, "returncode": 0, "status": "complete",
                                 "controller_wall_s": controller, "record": block,
                                 "record_sha256": seal(block)})
    result["collection_wall_s"] = sum(b["controller_wall_s"]
                                      for b in result["blocks"]) + 0.1
    return result


class RepeatabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = json.loads(study.PROTOCOL.read_text(encoding="utf-8"))

    def test_protocol_and_orders_preserve_work_and_balance_positions(self):
        study.validate_protocol(self.protocol)
        for scenario, roots in study.CONDITIONS:
            for phase in ("sequential", "cold", "warm"):
                positions = Counter(c["order"].index(phase)
                                    for b in range(6) for c in study.schedule(b)
                                    if (c["scenario"], c["roots"]) == (scenario, roots))
                self.assertEqual(positions, {0: 4, 1: 4, 2: 4})
        for key, value in (("search_seed", 7), ("fresh_process_blocks", 12),
                           ("iterations_per_condition_per_block", True)):
            changed = copy.deepcopy(self.protocol)
            changed[key] = value
            with self.assertRaises(ValueError):
                study.validate_protocol(changed)
        for block in (True, -1, 6, 1.0):
            with self.assertRaises(ValueError):
                study.schedule(block)

    def test_full_retained_synthetic_receipts_validate(self):
        data = fixture()
        report.validate(data, self.protocol)
        self.assertEqual(sum(len(b["record"]["cells"]) for b in data["blocks"]), 216)
        rows = report.summarize(data)
        self.assertEqual(len(rows), 24)
        self.assertTrue(all(r["sampling_units"] == 6 and
                            r["iterations_per_unit"] == 2 and
                            r["degrees_of_freedom"] == 5 for r in rows))

    def test_partial_duplicate_changed_source_and_changed_nested_bytes_rejected(self):
        mutations = [lambda d: d["blocks"].pop(),
                     lambda d: d["blocks"].reverse(),
                     lambda d: d.__setitem__("status", "maximum-cost"),
                     lambda d: d.__setitem__("source_unchanged_at_end", False),
                     lambda d: d["blocks"][0].__setitem__("record_sha256", "0" * 64)]
        for change in mutations:
            data = fixture()
            change(data)
            with self.assertRaises(ValueError):
                report.validate(data, self.protocol)

    def test_matching_invalid_work_and_cross_block_semantic_drift_rejected(self):
        for alteration in ("work", "label", "order", "complete-time"):
            data = fixture()
            item = data["blocks"][1]
            block = item["record"]
            for cell in block["cells"]:
                if alteration == "work":
                    cell["report"]["workers"][0]["assigned_simulations"] += 1
                elif alteration == "label":
                    cell["ranked"][0]["label"] = "Changed across blocks"
                elif alteration == "complete-time":
                    cell["complete_call_s"] = cell["elapsed_s"]
            if alteration == "order":
                block["cells"].reverse()
            item["record_sha256"] = seal(block)
            with self.subTest(alteration=alteration), self.assertRaises(ValueError):
                report.validate(data, self.protocol)

    def test_interval_uses_block_means_not_twelve_independent_ratios(self):
        data = fixture()
        for b, item in enumerate(data["blocks"]):
            for cell in item["record"]["cells"]:
                offset = -0.4 if cell["iteration"] == 0 else 0.4
                ratio = (b + 1) * math.exp(offset)
                cell["elapsed_s"] = 1.0 if cell["phase"] == "sequential" else 1 / ratio
        row = report.summarize(data)[0]
        means = [math.log(b + 1) for b in range(6)]
        mean = statistics.fmean(means)
        half = 2.571 * statistics.stdev(means) / math.sqrt(6)
        self.assertAlmostEqual(row["geometric_mean_ratio"], math.exp(mean))
        self.assertAlmostEqual(row["approximate_95_interval"][0], math.exp(mean - half))
        self.assertAlmostEqual(row["approximate_95_interval"][1], math.exp(mean + half))
        self.assertAlmostEqual(row["mean_within_block_sample_variance"], 0.32)
        wrong = (2.571 * statistics.stdev(sum(row["nested_log_ratios"], []))
                 / math.sqrt(12))
        self.assertNotAlmostEqual(half, wrong)

    def test_search_advantage_can_coexist_with_complete_call_disadvantage(self):
        data = fixture()
        for item in data["blocks"]:
            for cell in item["record"]["cells"]:
                cell["elapsed_s"] = 2.0 if cell["phase"] == "sequential" else 1.0
                cell["complete_call_s"] = 2.5 if cell["phase"] == "sequential" else 5.0
        rows = report.summarize(data)
        self.assertEqual(rows[0]["result"], "bounded advantage")
        self.assertEqual(rows[2]["result"], "bounded disadvantage")
        text = report.markdown(data, rows)
        self.assertIn("not simultaneous", text)
        self.assertIn("not counted as independent", text)
        self.assertIn("Original unfavorable", text)

    def test_maximum_cost_stops_without_execution_or_interval(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "partial.json"
            with (patch.object(study, "source_identity", return_value={}),
                  patch.object(study, "verify_source", return_value=True),
                  patch.object(study.original, "execute") as execute):
                result = study.collect_block(path, 0, deadline=0)
            execute.assert_not_called()
            self.assertEqual(result["status"], "maximum-cost")
            self.assertEqual(result["cells"], [])
            self.assertTrue(json.loads(path.read_text())["source_unchanged_at_end"])

    def test_failed_execution_is_checkpointed_and_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "partial.json"

            def fail(root, protocol, cell):
                saved = json.loads(path.read_text())
                self.assertEqual(saved["cells"][-1]["status"], "running")
                cell.update(status="failed", error="fixture")

            with (patch.object(study, "source_identity", return_value={}),
                  patch.object(study, "verify_source", return_value=True),
                  patch.object(study.original, "execute", side_effect=fail) as execute):
                result = study.collect_block(path, 0, deadline=math.inf)
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(result["status"], "incomplete")
            self.assertEqual(result["cells"][0]["error"], "fixture")
            self.assertGreaterEqual(result["cells"][0]["complete_call_s"], 0)

    def test_collection_validates_producer_tuple_fields_as_retained_json(self):
        original = json.loads(
            (study.ROOT / "docs/same-forest-results.json").read_text()
        )
        templates = {c["phase"]: c for c in original["cells"]
                     if c["scenario"] == "duel" and c["roots"] == 2}
        for invalid_reason in (False, True):
            with self.subTest(invalid_reason=invalid_reason):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "block.json"

                    def produced_receipt(root, protocol, cell,
                                         invalid_reason=invalid_reason):
                        template = copy.deepcopy(templates[cell["phase"]])
                        workers = []
                        for row in template["report"]["workers"]:
                            row["stop_reasons"] = tuple(row["stop_reasons"])
                            if invalid_reason:
                                row["stop_reasons"] = ("incorrect_reason",)
                            row["statistics"] = tuple(
                                tuple(statistic) for statistic in row["statistics"]
                            )
                            workers.append(WorkerReceipt(**row))
                        template["report"]["workers"] = tuple(workers)
                        template["report"] = dataclasses.asdict(
                            FixedWorkReport(**template["report"])
                        )
                        self.assertIsInstance(
                            template["report"]["workers"][0]["stop_reasons"], tuple
                        )
                        cell.update(template)

                    with (patch.object(study, "source_identity", return_value={}),
                          patch.object(study, "verify_source", return_value=True),
                          patch.object(study, "schedule",
                                       return_value=study.schedule(0)[:1]),
                          patch.object(study.original, "execute",
                                       side_effect=produced_receipt) as execute):
                        if invalid_reason:
                            with self.assertRaisesRegex(ValueError,
                                                        "stopping reasons differ"):
                                study.collect_block(path, 0, deadline=math.inf)
                            self.assertEqual(execute.call_count, 1)
                        else:
                            result = study.collect_block(path, 0, deadline=math.inf)
                            self.assertEqual(result["status"], "complete")
                            self.assertEqual(execute.call_count, 3)
                            self.assertTrue(result["comparisons"][0]["matched"])
                    saved = json.loads(path.read_text())
                    self.assertIsInstance(
                        saved["cells"][0]["report"]["workers"][0]["stop_reasons"],
                        list,
                    )
                    self.assertEqual(saved["source_unchanged_at_end"], True)

    def test_interruption_retains_running_call_without_success_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "interrupt.json"
            with (patch.object(study, "source_identity", return_value={}),
                  patch.object(study, "verify_source", return_value=True),
                  patch.object(study.original, "execute",
                               side_effect=KeyboardInterrupt),
                  self.assertRaises(KeyboardInterrupt)):
                study.collect_block(path, 0, deadline=math.inf)
            saved = json.loads(path.read_text())
            self.assertEqual(saved["status"], "interrupted")
            self.assertEqual(saved["interruption"], "KeyboardInterrupt")
            self.assertIsNotNone(saved["cells"][0]["complete_call_s"])

    def test_record_conditions_and_bound_before_directory_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "new"
            for conditions, bound in (("", "job"), ("shared", "")):
                with self.assertRaises(ValueError):
                    study.run(path, conditions, bound)
                self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
