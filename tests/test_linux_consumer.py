"""Check bounded consumer input admission without Docker or installation."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tools import installed_linux_smoke as acceptance_driver
from tools import linux_episode_worker as worker


def decode_wire(text: str) -> bytes:
    chunks = []
    totals = []
    digests = []
    for line in text.splitlines():
        if line.startswith("G4_NATIVE_EVIDENCE_CHUNK "):
            _, sequence, body = line.split(" ", 2)
            index, count = map(int, sequence.split("/"))
            if index != len(chunks):
                raise ValueError("missing, duplicated or unordered chunk")
            chunks.append(base64.b64decode(body, validate=True))
            totals.append(count)
        elif line.startswith("G4_NATIVE_EVIDENCE_DIGEST "):
            digests.append(json.loads(line.split(" ", 1)[1]))
    if len(digests) != 1 or not chunks or any(total != len(chunks) for total in totals):
        raise ValueError("incomplete evidence framing")
    result = b"".join(chunks)
    digest = digests[0]
    if (
        digest["bytes"] != len(result)
        or digest["chunks"] != len(chunks)
        or digest["sha256"] != hashlib.sha256(result).hexdigest()
    ):
        raise ValueError("decoded evidence identity differs")
    return result


class LinuxConsumerInputTests(unittest.TestCase):
    def test_transport_recovers_exact_bytes_with_interleaved_stderr_and_detects_loss(
        self,
    ):
        original = json.dumps({"status": "incomplete", "retained": "x" * 4096}).encode()
        wire = acceptance_driver.evidence_transport(original)
        records = wire.splitlines()
        records.insert(3, "Traceback (most recent call last):")
        records.insert(
            4,
            "ValueError: orphan lacked actual host membership and pinned exit evidence",
        )
        self.assertEqual(decode_wire("\n".join(records)), original)
        self.assertLessEqual(len(wire.encode()), acceptance_driver.EVIDENCE_BYTES)
        for modification in (
            records[:2] + records[3:],
            records[:2] + [records[1]] + records[2:],
        ):
            with self.assertRaises(ValueError):
                decode_wire("\n".join(modification))
        damaged = wire.replace(
            base64.b64encode(original[:1024]).decode(),
            base64.b64encode(b"x" * 1024).decode(),
            1,
        )
        with self.assertRaisesRegex(ValueError, "identity differs"):
            decode_wire(damaged)

    def probe_members(self, orphan_uid=1001):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            stamp = directory.stat()
            witness = acceptance_driver.MemberWitness.__new__(
                acceptance_driver.MemberWitness
            )
            witness.native = {
                "host_pid": 1,
                "cgroup": "/docker/known",
                "stamp": [stamp.st_dev, stamp.st_ino],
                "namespaces": {"pid": 91},
            }
            witness.members, witness.errors = {}, []
            witness.deferred, witness.rejected, witness.deferred_discarded = [], [], 0
            witness.stop = MagicMock()
            witness.stop.is_set.side_effect = [False, True]
            original_stat = Path.stat

            def read_text(path, *args, **kwargs):
                name = path.as_posix()
                pid = int(name.split("/")[2])
                if name.endswith("/status"):
                    uid = 1001 if pid == 4358 else orphan_uid
                    state = "Z (zombie)" if pid == 4358 else "S (sleeping)"
                    return (
                        f"Uid:\t{uid}\t{uid}\t{uid}\t{uid}\n"
                        f"State:\t{state}\nNSpid:\t{pid}\t26\n"
                    )
                return "0::/docker/known\n"

            def selected_stat(path, *args, **kwargs):
                if path.as_posix() == "/proc/4358/ns/pid":
                    raise PermissionError(13, "Permission denied", path.as_posix())
                if path.as_posix() == "/proc/4365/ns/pid":
                    return SimpleNamespace(st_ino=91)
                return original_stat(path, *args, **kwargs)

            with (
                patch.object(
                    acceptance_driver.owner.native, "mount_root", return_value=directory
                ),
                patch.object(
                    acceptance_driver.owner.native,
                    "cgroup_path",
                    return_value=directory,
                ),
                patch.object(
                    acceptance_driver.owner,
                    "sample",
                    return_value={"members": [1, 4358, 4365]},
                ),
                patch.object(
                    acceptance_driver.owner.native,
                    "starttime",
                    side_effect=lambda pid: pid * 10,
                ),
                patch.object(
                    acceptance_driver.owner.native, "exited", return_value=False
                ),
                patch.object(Path, "read_text", read_text),
                patch.object(Path, "stat", selected_stat),
                patch.object(
                    acceptance_driver.os, "pidfd_open", return_value=72, create=True
                ),
                patch.object(acceptance_driver.os, "close"),
            ):
                witness.observe()
            return witness

    def test_denied_candidate_keeps_probe_evidence_and_does_not_hide_qualified_orphan(
        self,
    ):
        witness = self.probe_members()
        self.assertEqual(witness.errors, [])
        self.assertEqual(set(witness.members), {4365})
        self.assertEqual(witness.members[4365][0]["uid"], [1001] * 4)
        denied = witness.deferred[0]
        self.assertEqual(denied["host_pid"], 4358)
        self.assertEqual(denied["uid"], [1001] * 4)
        self.assertEqual(denied["state"], "Z (zombie)")
        self.assertEqual(denied["starttime"], 43580)
        self.assertEqual(denied["cgroup"], "0::/docker/known\n")
        self.assertIsNone(denied["pid_namespace"])
        self.assertEqual(denied["disposition"], "deferred_permission_denied")

    def test_readable_orphan_with_wrong_uid_still_refuses_identity(self):
        witness = self.probe_members(orphan_uid=0)
        self.assertFalse(witness.members)
        self.assertTrue(witness.errors)
        self.assertEqual(witness.rejected[0]["uid"], [0] * 4)

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
            envelope = json.loads(decode_wire(text))
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
            envelope = json.loads(decode_wire(text))
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
