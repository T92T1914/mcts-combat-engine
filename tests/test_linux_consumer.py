"""Check bounded consumer input admission without Docker or installation."""

from __future__ import annotations

import importlib.util
import io
import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tools import installed_linux_smoke as acceptance_driver
from tools import linux_episode_worker as worker


class LinuxConsumerInputTests(unittest.TestCase):
    def test_partial_evidence_keeps_actual_receipts_and_omits_raw_overflow(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            acceptance = {"status": "incomplete", "error": {"type": "FixtureFailure"}}
            (root / "acceptance.json").write_text(json.dumps(acceptance))
            (root / "control").mkdir()
            owner = {
                "outcome": {"status": "error"},
                "samples": [{"memory.events": {"oom_kill": 0}}],
            }
            (root / "control/ownership.json").write_text(json.dumps(owner))
            (root / "control/stdout.raw").write_bytes(
                b'{"action":"control"}\n{"partial":'
            )
            (root / "output").mkdir()
            overflow = b"raw-overflow-that-must-not-be-printed" * 100
            (root / "output/stdout.raw").write_bytes(overflow)
            before = {
                path: (path.read_bytes(), path.stat().st_mtime_ns)
                for path in root.rglob("*")
                if path.is_file()
            }
            with patch("sys.stdout", new_callable=io.StringIO) as captured:
                acceptance_driver.emit_retained_evidence(root, acceptance)
            text = captured.getvalue()
            envelope = json.loads(
                text.split("G4_NATIVE_EVIDENCE_BEGIN\n", 1)[1].split(
                    "G4_NATIVE_EVIDENCE_END", 1
                )[0]
            )
            self.assertEqual(envelope["retention_status"], "complete")
            self.assertEqual(
                envelope["json_files"]["control/ownership.json"]["value"], owner
            )
            self.assertEqual(
                envelope["json_files"]["acceptance.json"]["value"], acceptance
            )
            self.assertEqual(
                envelope["raw_streams"]["output/stdout.raw"], worker.identity(overflow)
            )
            self.assertNotIn("raw-overflow-that-must-not-be-printed", text)
            self.assertEqual(
                envelope["raw_streams"]["control/stdout.raw"]["parsed_rows"],
                [{"action": "control"}],
            )
            self.assertEqual(
                len(envelope["raw_streams"]["control/stdout.raw"]["parse_errors"]), 1
            )
            self.assertLessEqual(len(text.encode()), acceptance_driver.EVIDENCE_BYTES)
            self.assertEqual(
                before,
                {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in before},
            )

    def test_oversized_evidence_cannot_emit_a_successful_acceptance_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            acceptance = {"status": "complete", "cases": {}}
            (root / "acceptance.json").write_text(json.dumps(acceptance))
            (root / "control").mkdir()
            owner = root / "control/ownership.json"
            owner.write_bytes(b"x" * (acceptance_driver.EVIDENCE_FILE_BYTES + 1))
            before = (owner.read_bytes(), owner.stat().st_mtime_ns)
            with patch("sys.stdout", new_callable=io.StringIO) as captured:
                with self.assertRaisesRegex(
                    ValueError, "native evidence retention failed"
                ):
                    acceptance_driver.emit_retained_evidence(root, acceptance)
            text = captured.getvalue()
            envelope = json.loads(
                text.split("G4_NATIVE_EVIDENCE_BEGIN\n", 1)[1].split(
                    "G4_NATIVE_EVIDENCE_END", 1
                )[0]
            )
            self.assertEqual(envelope["retention_status"], "failed")
            self.assertEqual(envelope["acceptance"]["status"], "retention_failed")
            self.assertFalse(envelope["full_evidence_retained"])
            self.assertEqual((owner.read_bytes(), owner.stat().st_mtime_ns), before)

    def test_request_requires_exact_integer_allowance_and_original_wheel_name(self):
        original = {
            "wheel": "mcts_combat_engine-0.1.0-py3-none-any.whl",
            **worker.REQUEST,
        }
        self.assertEqual(worker.request_from(json.dumps(original).encode()), original)
        changes = (
            {"rounds": True},
            {"sims": 2.0},
            {"horizon": 2},
            {"environment_seed": 7},
            {"search_seed": 7},
            {"wheel": "engine.whl"},
            {"wheel": "../engine-a-b-c-d.whl"},
            {"arbitrary_argv": []},
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                worker.request_from(json.dumps({**original, **change}).encode())

    def archive(
        self, path: Path, *, changed=False, extra=False, duplicate=False, link=False
    ):
        body = b"literal-worker\n"
        payload = {"tools/linux_episode_worker.py": body, "episode.py": b"example\n"}
        manifest = {
            "format": "mcts-recording-companion",
            "schema_version": 1,
            "source_commit": "1" * 40,
            "source_tree": "2" * 40,
            "payload_files": {
                name: worker.identity(value) for name, value in payload.items()
            },
            "reference_engine": {
                "files": {
                    name: worker.identity(b"old\n") for name in worker.ENGINE_NAMES
                }
            },
            "derived_documents": {},
        }
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            for name, value in payload.items():
                if changed and name == "episode.py":
                    value += b"changed\n"
                member = zipfile.ZipInfo(name)
                if link and name == "episode.py":
                    member.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(member, value)
            if extra:
                archive.writestr("unlisted.py", b"extra")
            if duplicate:
                archive.writestr("episode.py", b"duplicate")
        return body

    def test_all_members_are_checked_before_extraction_and_originals_are_preserved(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "valid.zip"
            body = self.archive(archive)
            before = (archive.read_bytes(), archive.stat().st_mtime_ns)
            destination = root / "extracted"
            worker.unpack(archive, destination, body)
            self.assertEqual((destination / "episode.py").read_bytes(), b"example\n")
            self.assertEqual((archive.read_bytes(), archive.stat().st_mtime_ns), before)
            for name in ("changed", "extra", "duplicate", "link"):
                with self.subTest(name=name):
                    selected = root / (name + ".zip")
                    # ZIP's duplicate warning is a fixture construction detail.
                    with patch("warnings.warn"):
                        self.archive(selected, **{name: True})
                    original = (selected.read_bytes(), selected.stat().st_mtime_ns)
                    output = root / name
                    with self.assertRaises(ValueError):
                        worker.unpack(selected, output, body)
                    self.assertFalse(output.exists())
                    self.assertEqual(
                        (selected.read_bytes(), selected.stat().st_mtime_ns), original
                    )

    def test_worker_provenance_refuses_before_any_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "companion.zip"
            self.archive(archive)
            with self.assertRaisesRegex(ValueError, "executing worker differs"):
                worker.unpack(archive, root / "extracted", b"unqualified-worker\n")
            self.assertFalse((root / "extracted").exists())

    def test_native_fixture_refuses_unsupported_or_root_before_fork(self):
        path = Path(__file__).parent / "fixtures/linux_container_fixture.py"
        spec = importlib.util.spec_from_file_location("linux_native_fixture", path)
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        for platform, uid in (("win32", 1001), ("linux", 0)):
            with (
                self.subTest(platform=platform, uid=uid),
                patch.object(fixture.sys, "platform", platform),
                patch.object(fixture.os, "geteuid", return_value=uid, create=True),
                patch.object(fixture.os, "fork", create=True) as fork,
                patch.object(fixture.sys, "argv", ["fixture.py", "memory"]),
                patch("sys.stdout", new_callable=io.StringIO),
            ):
                with self.assertRaisesRegex(ValueError, "admitted nonroot Linux"):
                    fixture.main()
                fork.assert_not_called()


if __name__ == "__main__":
    unittest.main()
