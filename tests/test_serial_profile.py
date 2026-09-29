"""Tiny fixtures check diagnostic accounting without running the measured study."""

import copy
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game.content import SCENARIOS
from tools import run_serial_profile as study


class SerialProfileTests(unittest.TestCase):
    def setUp(self):
        self.protocol = json.loads(study.PROTOCOL.read_text(encoding="utf-8"))

    def test_fixed_controls_reject_budget_and_scenario_drift(self):
        study.validate_protocol(self.protocol)
        for key, changed in (("max_simulations", 3001),
                             ("scenarios", ["boss"]),
                             ("schema_version", True)):
            protocol = copy.deepcopy(self.protocol)
            protocol[key] = changed
            with self.subTest(key=key), self.assertRaises(ValueError):
                study.validate_protocol(protocol)

    def test_instrumented_work_matches_control_including_random_state(self):
        protocol = dict(self.protocol, max_simulations=7, max_transitions=35)
        root, _ = SCENARIOS["duel"](random.Random(300))
        root.player.pips = 7
        original = study.object_digest(root)
        control = {"mode": "control"}
        profiled = {"mode": "profiled"}
        study.execute(root, protocol, control)
        study.execute(root, protocol, profiled)
        self.assertEqual(control["computation"], profiled["computation"])
        self.assertEqual(control["observed_simulations"], 7)
        self.assertEqual(study.object_digest(root), original)
        self.assertEqual(control["profile"], [])
        self.assertTrue(profiled["profile"])
        self.assertTrue(all(not Path(row["file"]).is_absolute()
                            for row in profiled["profile"]))

    def test_timeout_is_retained_as_incomplete_not_a_small_success(self):
        protocol = dict(self.protocol, max_simulations=7, time_budget_ms=0)
        root, _ = SCENARIOS["duel"](random.Random(300))
        cell = {"mode": "profiled"}
        with self.assertRaisesRegex(RuntimeError, "IncompleteFixedWork"):
            study.execute(root, protocol, cell)
        self.assertEqual(cell["status"], "failed")
        self.assertEqual(cell["observed_simulations"], 0)
        self.assertIn("time_limit", cell["computation"]["stop_reasons"])

    def test_existing_attempt_and_empty_conditions_fail_before_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "attempt.json"
            path.write_text("retained", encoding="utf-8")
            with patch.object(study, "execute") as execute:
                with self.assertRaises(ValueError):
                    study.run(path, "observed conditions")
                self.assertEqual(path.read_text(encoding="utf-8"), "retained")
                with self.assertRaises(ValueError):
                    study.run(Path(folder) / "new.json", " ")
                execute.assert_not_called()

    def test_profile_paths_do_not_export_external_directories(self):
        self.assertEqual(study.safe_filename(str(study.ROOT / "engine/mcts.py")),
                         "engine/mcts.py")
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(study.safe_filename(str(Path(folder) / "other.py")),
                             "external/other.py")

    def test_failure_and_source_change_keep_first_attempt_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "attempt.json"

            def failed(root, protocol, cell):
                cell.update(status="failed", observed_simulations=2,
                            observed_transitions=10, error="FixtureFailure")
                raise RuntimeError("FixtureFailure")

            with (
                patch.object(study, "source_identity", side_effect=[
                    {"revision": "fixture", "sha256": {}}, ValueError("dirty")
                ]),
                patch.object(study, "execute", side_effect=failed) as execute,
                self.assertRaisesRegex(RuntimeError, "FixtureFailure"),
            ):
                study.run(path, "fixture only")
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(record["status"], "source_changed")
            self.assertFalse(record["source_unchanged_at_end"])
            self.assertEqual(record["cells"][0]["observed_simulations"], 2)
            self.assertEqual(record["error"], "RuntimeError: FixtureFailure")
            self.assertIn("ended_utc", record)


if __name__ == "__main__":
    unittest.main()
