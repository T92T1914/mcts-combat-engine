"""Bounded public CLI refusals before image or consumer admission."""
from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools import linux_episode as episode


def archive(manifest: object, members: dict[str, bytes] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as target:
        target.writestr("manifest.json", json.dumps(manifest))
        for name, body in (members or {}).items():
            target.writestr(name, body)
    return buffer.getvalue()


class LinuxEpisodeInputs(unittest.TestCase):
    def test_manifest_shape_refuses_before_image_and_preserves_inputs(self):
        for manifest in ([], None, {"payload_files": []}, {"payload_files": None}):
            with self.subTest(manifest=manifest), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                wheel = root / "mcts_combat_engine-0.1.0-py3-none-any.whl"
                companion = root / "companion.zip"
                wheel.write_bytes(b"controlled ordinary input; not an installed wheel")
                companion.write_bytes(archive(manifest))
                before = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                          for path in (wheel, companion)}
                with patch.object(episode, "available", return_value=True):
                    with patch.object(episode.owner, "acquire_image") as acquire:
                        with patch.object(episode.owner, "run_owned_container") as run:
                            with redirect_stdout(io.StringIO()):
                                self.assertEqual(episode.main([
                                    "--wheel", str(wheel),
                                    "--companion", str(companion),
                                    "--output", str(root / "output")]), 1)
                            acquire.assert_not_called()
                            run.assert_not_called()
                self.assertFalse((root / "output").exists())
                self.assertEqual(before, {
                    path: (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in before})

    def test_structural_literal_control_and_independent_identity_mutations(self):
        body = b"# controlled structural worker fixture\n"
        expected = {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        manifest = {"format": "mcts-recording-companion", "schema_version": 1,
                    "payload_files": {episode.WORKER: expected}}
        original = archive(manifest, {episode.WORKER: body})
        self.assertEqual(episode.companion_worker(original), body)
        for replacement in (0, None, False):
            manifest["payload_files"][episode.WORKER]["bytes"] = replacement
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                episode.companion_worker(archive(manifest, {episode.WORKER: body}))
        self.assertEqual(episode.companion_worker(original), body)

    def test_unsafe_member_refuses_without_extraction(self):
        for name in ("../worker.py", "/worker.py", "tools\\worker.py", "a//b.py"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                episode.companion_worker(archive({}, {name: b"x"}))

    def test_unsupported_gate_precedes_all_file_and_workload_operations(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "untouched"
            with patch.object(episode, "available", return_value=False):
                with patch.object(episode.owner, "acquire_image") as acquire:
                    with patch.object(episode.owner, "run_owned_container") as run:
                        with redirect_stdout(io.StringIO()):
                            self.assertEqual(episode.main([
                                "--wheel", "missing.whl", "--companion", "missing.zip",
                                "--output", str(output)]), 2)
                        acquire.assert_not_called()
                        run.assert_not_called()
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
