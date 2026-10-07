"""Mocked scaling-runner failures do not collect a study or start workers."""

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from engine.parallel import FixedWorkReport
from tools import run_parallel_scaling as study


class ScalingCleanupTests(unittest.TestCase):
    def setUp(self):
        self.protocol = json.loads(study.PROTOCOL.read_text())

    def engine(self):
        engine = Mock()
        engine.search.return_value = []
        engine.last_report = FixedWorkReport(
            seed=7, max_simulations=self.protocol["max_simulations"],
            max_transitions=self.protocol["max_transitions"], workers=(),
            complete=True, simulations=self.protocol["max_simulations"],
            transitions=self.protocol["max_transitions"],
            known_simulations=self.protocol["max_simulations"],
            known_transitions=self.protocol["max_transitions"],
            unused_simulations=0, unused_transitions=0,
            elapsed_s=0.01, pool_startup_s=0.0,
        )
        return engine

    def run_fixture(self, path, engine):
        source = {"revision": "source-fixture", "sha256": {}, "worktree_clean": True}
        with (
            patch.object(study, "source_identity", return_value=source),
            patch.object(study.os, "cpu_count", return_value=16),
            patch.object(study, "serialization_probe", return_value={"fixture": True}),
            patch.object(study, "ParallelMCTS", return_value=engine) as factory,
            patch.object(
                study.subprocess, "check_output", return_value="source-fixture"
            ),
        ):
            self.factory = factory
            return study.run(path, "Mocked failure fixture. No study measured.")

    def test_original_failure_survives_cleanup_with_checkpoint_and_no_next_work(self):
        for error_type in (KeyboardInterrupt, SystemExit, RuntimeError):
            with self.subTest(error=error_type.__name__):
                original = error_type("original caller failure")
                engine = self.engine()
                engine.search.side_effect = original
                engine.close.side_effect = OSError("owned cleanup")
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "interrupted.json"
                    with self.assertRaises(error_type) as caught:
                        self.run_fixture(path, engine)
                    saved = json.loads(path.read_text())
                self.assertIs(caught.exception, original)
                self.assertEqual(saved["status"], "interrupted")
                self.assertEqual(saved["interruption"], error_type.__name__)
                self.assertEqual(saved["cleanup_error"], "OSError")
                self.assertEqual(saved["cells"], [])
                self.assertTrue(any("OSError" in note for note in original.__notes__))
                engine.search.assert_called_once()
                engine.close.assert_called_once()
                self.factory.assert_called_once()

    def test_interrupted_warm_call_keeps_exact_saved_cold_cell(self):
        for error_type in (KeyboardInterrupt, SystemExit):
            with self.subTest(error=error_type.__name__):
                original = error_type("warm caller interruption")
                engine = self.engine()
                engine.close.side_effect = OSError("owned cleanup")
                earlier = []
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "interrupted-warm.json"

                    def search(
                        *args, engine=engine, earlier=earlier,
                        path=path, original=original, **kwargs
                    ):
                        if engine.search.call_count == 1:
                            return []
                        earlier.extend(json.loads(path.read_text())["cells"])
                        engine.last_report = dataclasses.replace(
                            engine.last_report, complete=False, simulations=None,
                            transitions=None, unused_simulations=None,
                            unused_transitions=None,
                        )
                        raise original

                    engine.search.side_effect = search
                    with self.assertRaises(error_type) as caught:
                        self.run_fixture(path, engine)
                    saved = json.loads(path.read_text())
                self.assertIs(caught.exception, original)
                self.assertEqual(saved["status"], "interrupted")
                self.assertEqual(saved["interruption"], error_type.__name__)
                self.assertEqual(saved["cleanup_error"], "OSError")
                self.assertEqual(saved["cells"], earlier)
                self.assertEqual(len(earlier), 1)
                self.assertEqual(earlier[0]["phase"], "cold")
                self.assertTrue(earlier[0]["report"]["complete"])
                self.assertEqual(engine.search.call_count, 2)
                engine.close.assert_called_once()
                self.factory.assert_called_once()

    def test_cleanup_only_failure_propagates_exact_object_and_stops_next_engine(self):
        cleanup = OSError("owned cleanup")
        engine = self.engine()
        engine.close.side_effect = cleanup
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cleanup-failed.json"
            with self.assertRaises(OSError) as caught:
                self.run_fixture(path, engine)
            saved = json.loads(path.read_text())
        self.assertIs(caught.exception, cleanup)
        self.assertEqual(saved["status"], "interrupted")
        self.assertEqual(saved["interruption"], "OSError")
        self.assertEqual(saved["cleanup_error"], "OSError")
        self.assertEqual([cell["phase"] for cell in saved["cells"]], ["cold", "warm"])
        self.assertTrue(all(cell["error"] is None for cell in saved["cells"]))
        self.assertEqual(engine.search.call_count, 2)
        engine.close.assert_called_once()
        self.factory.assert_called_once()

    def test_success_keeps_existing_record_and_cell_schema(self):
        engine = self.engine()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mocked-success.json"
            result = self.run_fixture(path, engine)
            saved = json.loads(path.read_text())
        self.assertEqual(result["status"], "complete")
        self.assertEqual(set(saved), {
            "schema_version", "protocol", "protocol_sha256", "source",
            "started_utc", "environment", "status", "cells",
            "source_unchanged_at_end", "ended_utc",
        })
        self.assertEqual(len(saved["cells"]), 54)
        for cell in saved["cells"]:
            self.assertEqual(set(cell), {
                "scenario", "search_seed", "environment_seed", "root_pickle_sha256",
                "workers", "phase", "elapsed_s", "error", "serialization_probe",
                "report", "ranked",
            })
            self.assertIsNone(cell["error"])
        self.assertEqual(engine.search.call_count, 54)
        self.assertEqual(engine.close.call_count, 27)
        self.assertEqual(self.factory.call_count, 27)


if __name__ == "__main__":
    unittest.main()
