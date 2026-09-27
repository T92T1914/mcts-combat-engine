"""Tiny fixtures verify execution identity before the separate measured study."""

import copy
import dataclasses
import json
import random
import subprocess
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import Mock, patch

from engine.parallel import ParallelMCTS, ParallelSearchError, _fixed_search
from game.content import SCENARIOS
from tools import run_same_forest as study


def root_state():
    root, _ = SCENARIOS["duel"](random.Random(1))
    root.player.pips = 7
    return root


def untimed(report):
    return dataclasses.replace(
        report,
        elapsed_s=0.0,
        pool_startup_s=0.0,
        workers=tuple(
            dataclasses.replace(worker, elapsed_s=None) for worker in report.workers
        ),
    )


class SequentialForestTests(unittest.TestCase):
    def test_same_forest_with_uneven_limits_exhaustion_and_pool_reuse(self):
        root = root_state()
        original = root.clone()
        engine = ParallelMCTS(horizon_rounds=3, workers=2)
        try:
            for sims, transitions in ((31, 89), (1, None), (7, 1)):
                arguments = {
                    "mode": "fixed",
                    "max_sims": sims,
                    "max_transitions": transitions,
                    "seed": 42,
                }
                with patch.object(engine, "_ensure_pool", side_effect=AssertionError):
                    sequential = engine.search(
                        root, execution="sequential", **arguments
                    )
                expected = untimed(engine.last_report)
                # Omitting the new argument preserves ordinary process dispatch.
                process = engine.search(root, **arguments)
                self.assertEqual(process, sequential)
                self.assertEqual(untimed(engine.last_report), expected)
                if transitions == 1:
                    self.assertEqual(engine.last_report.simulations, 0)
                    self.assertEqual(engine.last_report.unused_transitions, 1)
                if sims == 31:
                    self.assertEqual(
                        [r.assigned_simulations for r in expected.workers], [16, 15]
                    )
                    self.assertEqual(
                        [r.assigned_transitions for r in expected.workers], [45, 44]
                    )
                    self.assertTrue(
                        all(
                            "transition_allowance" in r.stop_reasons
                            for r in expected.workers
                        )
                    )
                again = engine.search(root, execution="process", **arguments)
                self.assertEqual(again, sequential)
                self.assertEqual(untimed(engine.last_report), expected)
            self.assertEqual(root, original)
        finally:
            engine.close()
        self.assertIsNone(engine._pool)

    def test_sequential_invalid_receipt_retains_unknown_work_without_retry(self):
        engine = ParallelMCTS(horizon_rounds=2, workers=2)

        def mismatched(job):
            receipt = _fixed_search(job)
            return (
                dataclasses.replace(receipt, seed=receipt.seed + 1)
                if job.worker_id == 1
                else receipt
            )

        with (
            patch("engine.parallel._fixed_search", side_effect=mismatched) as run,
            patch.object(engine, "_ensure_pool", side_effect=AssertionError),
            patch.object(engine, "_search_single", side_effect=AssertionError),
            self.assertRaises(ParallelSearchError),
        ):
            engine.search(
                root_state(), mode="fixed", max_sims=7, seed=42, execution="sequential"
            )
        self.assertEqual(run.call_count, 2)
        report = engine.last_report
        self.assertIsNone(report.simulations)
        self.assertEqual(report.known_simulations, 4)
        self.assertEqual(report.workers[1].status, "unreported")
        self.assertEqual(report.workers[1].error, "InvalidWorkerReceipt")

    def test_execution_controls_are_explicit_and_do_not_change_time_mode(self):
        engine = ParallelMCTS(workers=2)
        with patch.object(engine, "_ensure_pool") as pool:
            for kwargs in (
                {"execution": "sequential"},
                {"execution": "threads"},
                {"mode": "fixed", "max_sims": 1, "seed": 0, "execution": True},
            ):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    engine.search(root_state(), **kwargs)
            pool.assert_not_called()
        with patch.object(engine, "_search_single", return_value=[]) as single:
            self.assertEqual(engine.search(root_state(), time_budget_ms=0), [])
            self.assertEqual(
                engine.search(root_state(), time_budget_ms=0, execution="process"), []
            )
            self.assertEqual(single.call_count, 2)


class SameForestStudyTests(unittest.TestCase):
    def setUp(self):
        self.protocol = json.loads(study.PROTOCOL.read_text(encoding="utf-8"))
        self.root = root_state()
        engine = ParallelMCTS(horizon_rounds=2, workers=2)
        rows = engine.search(
            self.root, mode="fixed", max_sims=7, seed=42, execution="sequential"
        )
        self.report = dataclasses.asdict(engine.last_report)
        self.ranked = [dataclasses.asdict(row) for row in rows]

    def cell(self, phase):
        cell = study.new_cell(
            self.protocol["conditions"][0], phase, self.protocol, self.root
        )
        cell.update(
            status="completed",
            report=copy.deepcopy(self.report),
            ranked=copy.deepcopy(self.ranked),
            elapsed_s=1.0,
        )
        return cell

    def test_protocol_is_bounded_and_balances_every_phase_position(self):
        with patch.object(study.os, "cpu_count", return_value=4):
            study.validate_protocol(self.protocol)
        self.assertEqual(len(self.protocol["conditions"]), 6)
        for phase in ("sequential", "cold", "warm"):
            positions = Counter(
                c["order"].index(phase) for c in self.protocol["conditions"]
            )
            self.assertEqual(positions, {0: 2, 1: 2, 2: 2})
        changed = copy.deepcopy(self.protocol)
        changed["search_seed"] = 7
        with self.assertRaises(ValueError):
            study.validate_protocol(changed)
        changed = copy.deepcopy(self.protocol)
        changed["conditions"][0]["order"].reverse()
        with self.assertRaises(ValueError):
            study.validate_protocol(changed)

    def test_comparison_ignores_timing_only_and_rejects_missing_execution(self):
        cells = [self.cell(p) for p in ("warm", "cold", "sequential")]
        cells[0]["elapsed_s"] = 2.0
        cells[0]["report"]["elapsed_s"] += 1.0
        cells[0]["report"]["pool_startup_s"] += 2.0
        cells[0]["report"]["workers"][0]["elapsed_s"] += 3.0
        result = study.compare_condition(cells)
        self.assertTrue(result["matched"])
        self.assertEqual(result["sequential_wall_ratio"], {"cold": 1.0, "warm": 0.5})
        with self.assertRaises(ValueError):
            study.compare_condition(cells[:2])
        for invalid in (0, True, float("nan")):
            cells[0]["elapsed_s"] = invalid
            with self.assertRaises(ValueError):
                study.compare_condition(cells)

    def test_phase_driver_runs_tiny_identical_forests_with_separate_preparation(self):
        protocol = self.protocol | {
            "horizon_rounds": 2,
            "max_simulations": 7,
            "max_transitions": 16,
        }
        cells = []
        for phase in ("sequential", "cold", "warm"):
            cell = study.new_cell(protocol["conditions"][0], phase, protocol, self.root)
            study.execute(self.root, protocol, cell)
            self.assertEqual(cell["status"], "completed")
            self.assertEqual(cell["report"]["simulations"], 7)
            self.assertGreater(cell["elapsed_s"], 0)
            cells.append(cell)
        self.assertEqual(cells[0]["report"]["pool_startup_s"], 0)
        self.assertGreater(cells[1]["report"]["pool_startup_s"], 0)
        self.assertGreater(cells[2]["prepared_pool_startup_s"], 0)
        self.assertEqual(cells[2]["report"]["pool_startup_s"], 0)
        self.assertTrue(study.compare_condition(cells)["matched"])

    def test_phase_driver_retains_a_complete_receipt_below_expected_work(self):
        # Seven simulations split 4/3. Fourteen rounds split 7/7, so the first
        # root cannot fund its fourth two-round simulation. Nothing is borrowed.
        protocol = self.protocol | {
            "horizon_rounds": 2,
            "max_simulations": 7,
            "max_transitions": 14,
        }
        cell = study.new_cell(
            protocol["conditions"][0], "sequential", protocol, self.root
        )
        study.execute(self.root, protocol, cell)
        self.assertEqual(cell["status"], "failed")
        self.assertEqual(cell["error"], "RuntimeError")
        self.assertTrue(cell["report"]["complete"])
        self.assertEqual(cell["report"]["simulations"], 6)
        self.assertEqual(cell["report"]["unused_simulations"], 1)

    def test_mismatches_preserve_counts_seeds_raw_statistics_and_ranked_results(self):
        for field in ("seed", "unused", "statistics", "ranked", "root", "type"):
            cells = [self.cell(p) for p in ("sequential", "cold", "warm")]
            worker = cells[1]["report"]["workers"][0]
            if field == "seed":
                worker["seed"] += 1
            elif field == "unused":
                worker["unused_simulations"] += 1
            elif field == "statistics":
                worker["statistics"] = ()
            elif field == "ranked":
                cells[1]["ranked"][0]["visits"] += 1
            elif field == "root":
                cells[1]["root_pickle_sha256"] = "changed"
            else:
                worker["assigned_simulations"] = float(worker["assigned_simulations"])
            with self.subTest(field=field):
                result = study.compare_condition(cells)
                self.assertFalse(result["matched"])
                self.assertIsNone(result["sequential_wall_ratio"])
                self.assertTrue(result["differing_paths"]["cold"])
                self.assertFalse(result["differing_paths"]["warm"])

    def test_warmup_failure_is_not_retried_or_reported_as_a_warm_search(self):
        engine = Mock()
        engine.warmup.return_value = False
        engine.last_pool_startup_s = 0.25
        engine.last_report = None
        cell = study.new_cell(
            self.protocol["conditions"][0], "warm", self.protocol, self.root
        )
        with patch.object(study, "ParallelMCTS", return_value=engine):
            study.execute(self.root, self.protocol, cell)
        engine.search.assert_not_called()
        engine.close.assert_called_once()
        self.assertEqual(cell["error"], "WarmupFailed")
        self.assertIsNone(cell["elapsed_s"])
        self.assertGreaterEqual(cell["preparation_s"], 0)
        self.assertEqual(cell["prepared_pool_startup_s"], 0.25)

    def test_caller_interrupt_keeps_owned_cleanup_and_unknown_report(self):
        engine = Mock()
        engine.search.side_effect = KeyboardInterrupt
        engine.last_report = None
        cell = study.new_cell(
            self.protocol["conditions"][0], "sequential", self.protocol, self.root
        )
        with (
            patch.object(study, "ParallelMCTS", return_value=engine),
            self.assertRaises(KeyboardInterrupt),
        ):
            study.execute(self.root, self.protocol, cell)
        engine.close.assert_called_once()
        self.assertEqual(cell["status"], "interrupted")
        self.assertIsNone(cell["report"])

    def mock_source(self):
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=study.ROOT, text=True
        ).strip()
        return {"revision": revision, "worktree_clean": True, "sha256": {}}

    def test_runner_checkpoints_before_execution_and_stops_after_first_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "failure.json"

            def failed(root, protocol, cell):
                saved = json.loads(path.read_text())
                self.assertEqual(saved["cells"][-1]["status"], "running")
                cell.update(status="failed", error="fixture")

            with (
                patch.object(study, "source_identity", return_value=self.mock_source()),
                patch.object(study, "execute", side_effect=failed) as execute,
            ):
                result = study.run(path, "Synthetic unit fixture. No study measured.")
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(result["status"], "incomplete")
            self.assertEqual(
                json.loads(path.read_text())["cells"][0]["error"], "fixture"
            )
            with self.assertRaises(ValueError):
                study.run(path, "Never replace the first attempt")

    def test_runner_stops_on_unequal_receipts_and_retains_the_first_group(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mismatch.json"

            def completed(root, protocol, cell):
                cell.update(
                    status="completed",
                    report=copy.deepcopy(self.report),
                    ranked=copy.deepcopy(self.ranked),
                    elapsed_s=1.0,
                )
                if cell["phase"] == "warm":
                    cell["report"]["workers"][0]["seed"] += 1

            with (
                patch.object(study, "source_identity", return_value=self.mock_source()),
                patch.object(study, "execute", side_effect=completed) as execute,
            ):
                result = study.run(path, "Synthetic unit fixture. No study measured.")
            self.assertEqual(execute.call_count, 3)
            self.assertEqual(result["status"], "mismatch")
            self.assertFalse(result["comparisons"][0]["matched"])
            self.assertIsNone(result["comparisons"][0]["sequential_wall_ratio"])

    def test_mocked_success_records_all_declared_executions_in_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mocked.json"

            def completed(root, protocol, cell):
                cell.update(
                    status="completed",
                    report=copy.deepcopy(self.report),
                    ranked=copy.deepcopy(self.ranked),
                    elapsed_s=1.0,
                )

            with (
                patch.object(study, "source_identity", return_value=self.mock_source()),
                patch.object(study, "execute", side_effect=completed),
            ):
                result = study.run(path, "Synthetic unit fixture. No study measured.")
            self.assertEqual(result["status"], "complete")
            self.assertEqual(len(result["comparisons"]), 6)
            expected = [
                (c["scenario"], c["roots"], phase)
                for c in self.protocol["conditions"]
                for phase in c["order"]
            ]
            self.assertEqual(
                [(c["scenario"], c["roots"], c["phase"]) for c in result["cells"]],
                expected,
            )
            self.assertTrue(result["source_unchanged_at_end"])

    def test_existing_temporary_output_dirty_source_and_blank_conditions_fail_closed(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempt.json"
            with self.assertRaises(ValueError):
                study.run(path, " ")
            path.with_name(path.name + ".tmp").write_text("retained")
            with self.assertRaises(ValueError):
                study.run(path, "fixture")
        with (
            patch.object(study.subprocess, "check_output", return_value=" M x.py"),
            self.assertRaises(ValueError),
        ):
            study.source_identity()


if __name__ == "__main__":
    unittest.main()
