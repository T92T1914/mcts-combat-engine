"""Verify the separate complete layout without executing its engine/examples."""
from __future__ import annotations

import io
import json
import unittest
import zipfile

import test_episode_example_kit as reader_tests

from tools import build_episode_companion as companion
from tools import build_episode_examples as kit


class CompanionTests(unittest.TestCase):
    git = reader_tests.ExampleKitTests.git
    commit = reader_tests.ExampleKitTests.commit
    blob = reader_tests.ExampleKitTests.blob
    tearDown = reader_tests.ExampleKitTests.tearDown

    def setUp(self) -> None:
        reader_tests.ExampleKitTests.setUp(self)
        for name in companion.FIXED_PAYLOAD - kit.FIXED_PAYLOAD:
            path = self.root.joinpath(*name.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(kit.ROOT.joinpath(*name.split("/")).read_bytes())
        self.commit("complete companion fixture")

    def test_literal_complete_payload_and_separate_engine(self) -> None:
        archive, sidecar, manifest = companion.prepare(self.root)
        self.assertEqual(companion.prepare(self.root), (archive, sidecar, manifest))
        self.assertEqual(sidecar, (kit.digest(archive) + "  " +
                                  companion.ZIP_NAME + "\n").encode("ascii"))
        expected = companion.FIXED_PAYLOAD | {
            "game/" + name for name in reader_tests.GAME_FILES}
        self.assertEqual(len(expected), 22)
        self.assertEqual(manifest["format"], "mcts-recording-companion")
        self.assertEqual(set(manifest["payload_files"]), expected)
        self.assertEqual(set(manifest["reference_engine"]["files"]), kit.ENGINE_NAMES)
        with zipfile.ZipFile(io.BytesIO(archive)) as opened:
            self.assertEqual(set(opened.namelist()), expected | {"manifest.json"})
            self.assertEqual(opened.testzip(), None)
            self.assertEqual(json.loads(opened.read("manifest.json")), manifest)
            for name in expected:
                self.assertEqual(opened.read(name), self.blob(name))
            self.assertEqual(manifest["derived_documents"], {})
            self.assertFalse(any(name.startswith("engine/") or name.endswith(".whl")
                                 for name in opened.namelist()))

    def test_reader_kit_preserves_its_existing_payload_and_derivation(self) -> None:
        archive, _, manifest = kit.prepare(self.root)
        with zipfile.ZipFile(io.BytesIO(archive)) as opened:
            self.assertEqual(len(opened.namelist()), 17)
            self.assertNotIn("episode.py", opened.namelist())
            self.assertNotIn("demo.py", opened.namelist())
            self.assertEqual(manifest["format"], "mcts-saved-episode-example-kit")
            self.assertNotIn(kit.REPLAY_MARKER, opened.read(kit.GUIDE))

    def test_missing_identity_file_refused_before_delivery(self) -> None:
        (self.root / "demo.py").unlink()
        self.commit("missing identity participant")
        with self.assertRaisesRegex(kit.KitError, "missing or unexpected"):
            companion.build(self.root)
        self.assertFalse((self.root / "_site").exists())

    def test_separate_outputs_and_public_download_links(self) -> None:
        old = kit.build(self.root)
        before = {name: (self.root / "_site" / name).read_bytes()
                  for name in old["files"]}
        result = companion.build(self.root)
        self.assertEqual(set(result["files"]), companion.OUTPUT_NAMES)
        self.assertEqual(before, {name: (self.root / "_site" / name).read_bytes()
                                  for name in before})
        links = reader_tests.Links()
        links.feed((kit.ROOT / "site/index.html").read_text(encoding="utf-8"))
        targets = {link["href"]: link for link in links.links}
        self.assertIn("download", targets[companion.ZIP_NAME])
        self.assertIn(companion.SIDECAR_NAME, targets)


if __name__ == "__main__":
    unittest.main()
