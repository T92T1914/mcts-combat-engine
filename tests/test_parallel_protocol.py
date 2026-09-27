"""The study runner preserves the declared design and earlier output."""

import copy
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game.content import SCENARIOS
from tools.run_parallel_scaling import (
    PROTOCOL,
    run,
    serialization_probe,
    validate_protocol,
    write_record,
)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.protocol = json.loads(PROTOCOL.read_text())

    def test_declared_controls_and_bounded_design_are_accepted(self):
        with patch("tools.run_parallel_scaling.os.cpu_count", return_value=16):
            validate_protocol(self.protocol)
        self.assertEqual(len(self.protocol["scenarios"])
                         * len(self.protocol["search_seeds"])
                         * len(self.protocol["worker_orders"][0])
                         * len(self.protocol["pool_phases"]), 54)

    def test_changed_comparison_requires_a_reviewed_protocol(self):
        for key, value in (("max_simulations", 1), ("environment_seed", 301),
                           ("priors", {}), ("pool_phases", ["warm"]),
                           ("worker_orders", [[1, 2, 8]])):
            changed = copy.deepcopy(self.protocol)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_protocol(changed)

    def test_payload_probe_preserves_root_and_is_not_search_work(self):
        root, _ = SCENARIOS["duel"](random.Random(300))
        original = root.clone()
        probe = serialization_probe(root, self.protocol, 2, 7)
        self.assertEqual(root, original)
        self.assertGreater(probe["payload_bytes"], 0)
        self.assertGreaterEqual(probe["encode_s"], 0)
        self.assertIn("not actual IPC", probe["scope"])

    def test_existing_or_interrupted_output_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "study.json"
            for existing in (path, path.with_name(path.name + ".tmp")):
                existing.write_text("retained")
                with self.assertRaises(ValueError):
                    run(path, "fixture")
                self.assertEqual(existing.read_text(), "retained")
                existing.unlink()

    def test_atomic_checkpoint_keeps_a_parseable_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "study.json"
            write_record(path, {"status": "running", "cells": []})
            write_record(path, {"status": "interrupted", "cells": [{"error": "x"}]})
            self.assertEqual(json.loads(path.read_text())["status"], "interrupted")
            self.assertFalse(path.with_name(path.name + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
