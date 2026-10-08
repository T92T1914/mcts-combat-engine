"""Finite source/distribution checks, without importing the example or engine."""

from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

from tools import build_episode_examples as kit

GAME_FILES = (
    "__init__.py", "baselines.py", "content.py", "decision_report.py",
    "episode_decision.py", "episode_inspection.py", "episode_record.py",
    "loader.py", "runner.py", "stats.py",
)


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "a":
            self.links.append(dict(attrs))


class ExampleKitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_parent = Path(tempfile.gettempdir()).resolve()
        self.temporary = tempfile.TemporaryDirectory(prefix="mcts-example-kit-")
        self.root = Path(self.temporary.name).resolve()
        self.assertEqual(self.root.parent, self.temp_parent)
        self.hooks = self.root / "empty-hooks"
        self.hooks.mkdir()
        self.git("init", "--initial-branch=main", "--object-format=sha1")
        self.git("config", "core.symlinks", "false")
        names = kit.FIXED_PAYLOAD | kit.ENGINE_NAMES | {
            "game/" + name for name in GAME_FILES
        } | {"pyproject.toml", "tools/build_episode_examples.py"}
        for name in names:
            destination = self.root.joinpath(*name.split("/"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(kit.ROOT.joinpath(*name.split("/")).read_bytes())
        (self.root / ".gitignore").write_bytes(b"_site/\n")
        (self.root / ".gitattributes").write_bytes(b"* text eol=lf\n")
        self.commit("fixture")

    def tearDown(self) -> None:
        # Verify the actual recursive cleanup target before TemporaryDirectory uses it.
        resolved = Path(self.temporary.name).resolve()
        self.assertEqual(resolved, self.root)
        self.assertEqual(resolved.parent, self.temp_parent)
        self.assertTrue(resolved.name.startswith("mcts-example-kit-"))
        self.temporary.cleanup()

    def git(self, *args: str, data: bytes | None = None) -> bytes:
        environment = {key: value for key, value in os.environ.items()
                       if not key.upper().startswith("GIT_")}
        result = subprocess.run(
            ["git", "-c", "user.name=Example kit fixture",
             "-c", "user.email=example-kit@example.invalid",
             "-c", "core.hooksPath=" + str(self.hooks),
             "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false",
             "-c", "core.fsmonitor=false", "-c", "core.autocrlf=false",
             "-C", str(self.root), *args],
            input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=30, shell=False, env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        return result.stdout

    def commit(self, message: str) -> None:
        self.git("add", "--all")
        self.git("commit", "-m", message)

    def blob(self, name: str) -> bytes:
        return self.git("show", "HEAD:" + name)

    def assert_no_outputs(self) -> None:
        self.assertFalse((self.root / "_site").exists())

    def test_complete_canonical_kit_and_fixed_revision_determinism(self) -> None:
        before = {name: self.root.joinpath(*name.split("/")).read_bytes()
                  for name in kit.FIXED_PAYLOAD | kit.ENGINE_NAMES |
                  {"game/" + name for name in GAME_FILES} | {"pyproject.toml"}}
        archive, sidecar, manifest = kit.prepare(self.root)
        self.assertEqual(kit.prepare(self.root), (archive, sidecar, manifest))
        self.assertEqual(sidecar, (hashlib.sha256(archive).hexdigest() +
                                  "  episode-examples.zip\n").encode("ascii"))
        expected = kit.FIXED_PAYLOAD | {"game/" + name for name in GAME_FILES}
        self.assertEqual(len(expected), 16)
        self.assertEqual(set(manifest["payload_files"]), expected)
        self.assertEqual(set(manifest["reference_engine"]["files"]), kit.ENGINE_NAMES)
        self.assertNotIn("manifest.json", manifest["payload_files"])
        self.assertEqual(manifest["source_commit"],
                         self.git("rev-parse", "HEAD").decode().strip())
        self.assertEqual(manifest["source_tree"],
                         self.git("rev-parse", "HEAD^{tree}").decode().strip())
        with zipfile.ZipFile(io.BytesIO(archive)) as opened:
            names = opened.namelist()
            self.assertEqual(names, sorted(expected | {"manifest.json"},
                                           key=lambda name: name.encode("utf-8")))
            self.assertEqual(len(names), len(set(names)))
            for info in opened.infolist():
                self.assertFalse(info.is_dir())
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(info.create_system, 3)
                self.assertEqual(info.external_attr >> 16, stat.S_IFREG | 0o644)
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
                self.assertEqual((info.extra, info.comment), (b"", b""))
            self.assertEqual(json.loads(opened.read("manifest.json")), manifest)
            for name in expected:
                data = opened.read(name)
                self.assertEqual(manifest["payload_files"][name], {
                    "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
                if name != kit.GUIDE:
                    self.assertEqual(data, self.blob(name))
            original = self.blob(kit.GUIDE)
            emitted = opened.read(kit.GUIDE)
            url = ("(https://github.com/T92T1914/mcts-combat-engine/blob/" +
                   manifest["source_commit"] + "/docs/episode-record-replay.md)")
            self.assertEqual(emitted, original.replace(kit.REPLAY_MARKER,
                                                       url.encode("ascii")))
            derived = manifest["derived_documents"][kit.GUIDE]
            self.assertEqual(derived["canonical"], {
                "bytes": len(original), "sha256": hashlib.sha256(original).hexdigest()})
            self.assertEqual(derived["emitted"], manifest["payload_files"][kit.GUIDE])
            self.assertEqual(derived["transformation"]["to"], url)
            self.assertFalse(any(name.startswith("engine/") for name in names))
            self.assertNotIn("episode.py", names)
            self.assertFalse(any(name.endswith(".whl") for name in names))
        for name, data in before.items():
            self.assertEqual(self.root.joinpath(*name.split("/")).read_bytes(), data)
        self.assertEqual(self.git("status", "--porcelain"), b"")
        result = kit.build(self.root)
        self.assertEqual(result["manifest"], manifest)
        self.assertEqual((self.root / "_site" / kit.ZIP_NAME).read_bytes(), archive)
        self.assertEqual((self.root / "_site" / kit.SIDECAR_NAME).read_bytes(), sidecar)
        self.assertEqual(kit.build(self.root), result)

    def test_clean_crlf_emits_the_same_canonical_zip(self) -> None:
        (self.root / ".gitattributes").write_bytes(b"* text eol=crlf\n")
        self.commit("clean CRLF fixture policy")
        expected = kit.prepare(self.root)
        for name in kit.FIXED_PAYLOAD | kit.ENGINE_NAMES | {
            "game/" + name for name in GAME_FILES
        } | {"pyproject.toml"}:
            path = self.root.joinpath(*name.split("/"))
            path.write_bytes(self.blob(name).replace(b"\n", b"\r\n"))
        self.git("add", "--renormalize", "--all")
        self.assertEqual(self.git("write-tree"), self.git("rev-parse", "HEAD^{tree}"))
        self.assertEqual(self.git("status", "--porcelain"), b"")
        self.assertEqual(kit.prepare(self.root), expected)

    def test_complete_game_inventory_includes_new_python_member(self) -> None:
        (self.root / "game" / "extra_helper.py").write_bytes(b"# extra helper\n")
        self.commit("extra helper")
        archive, _, manifest = kit.prepare(self.root)
        self.assertIn("game/extra_helper.py", manifest["payload_files"])
        with zipfile.ZipFile(io.BytesIO(archive)) as opened:
            self.assertEqual(opened.read("game/extra_helper.py"),
                             self.blob("game/extra_helper.py"))

    def test_nonpython_game_member_refuses_instead_of_omission(self) -> None:
        (self.root / "game" / "unexpected.txt").write_bytes(b"extra\n")
        self.commit("unexpected game member")
        with self.assertRaisesRegex(kit.KitError, "only committed Python"):
            kit.build(self.root)
        self.assert_no_outputs()

    def test_valid_toml_with_wrong_project_shape_refuses_contextually(self) -> None:
        (self.root / "pyproject.toml").write_bytes(b'project = "wrong"\n')
        self.commit("wrong project shape")
        with self.assertRaisesRegex(kit.KitError, "metadata must be a table"):
            kit.build(self.root)
        self.assert_no_outputs()

    def test_long_toml_integer_refuses_contextually_without_outputs(self) -> None:
        (self.root / "pyproject.toml").write_bytes(
            b"oversized_integer = " + b"9" * 5000 + b"\n"
        )
        self.commit("long TOML integer")
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(kit, "ROOT", self.root):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(kit.main(), 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("reference project metadata could not be parsed",
                      stderr.getvalue())
        self.assert_no_outputs()

    def test_inherited_foreign_git_context_cannot_change_source_identity(self) -> None:
        expected_commit = self.git("rev-parse", "HEAD").decode().strip()
        foreign = self.root / "_site" / "foreign"
        foreign.mkdir(parents=True)
        self.git("-C", str(foreign), "init", "--initial-branch=main",
                 "--object-format=sha1")
        self.git("-C", str(foreign), "commit", "--allow-empty", "-m", "foreign")
        foreign_commit = self.git("-C", str(foreign), "rev-parse", "HEAD")
        self.assertNotEqual(foreign_commit.decode().strip(), expected_commit)
        overrides = {
            "GIT_DIR": str(foreign / ".git"), "GIT_WORK_TREE": str(self.root),
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.untrackedCache",
            "GIT_CONFIG_VALUE_0": "true",
        }
        with mock.patch.dict(os.environ, overrides):
            _, _, manifest = kit.prepare(self.root)
            self.assertEqual(manifest["source_commit"], expected_commit)
            self.assertEqual(os.environ["GIT_DIR"], overrides["GIT_DIR"])
        self.assertFalse((self.root / "_site" / kit.ZIP_NAME).exists())
        self.assertFalse((self.root / "_site" / kit.SIDECAR_NAME).exists())

    def test_committed_c1_control_name_refuses_without_reading_missing_file(
        self,
    ) -> None:
        name = "game/\u0085.py"
        oid = self.git("rev-parse", "HEAD:game/stats.py").decode().strip()
        self.git("update-index", "--add", "--cacheinfo", "100644," + oid + "," + name)
        self.git("commit", "-m", "control name")
        self.git("update-index", "--skip-worktree", "--", name)
        self.assertEqual(self.git("status", "--porcelain"), b"")
        with self.assertRaisesRegex(kit.KitError, "unsafe archive/source name"):
            kit.build(self.root)
        self.assert_no_outputs()

    def test_dirty_tracked_and_nonignored_untracked_sources_refuse(self) -> None:
        path = self.root / "decide_episode.py"
        original = path.read_bytes()
        path.write_bytes(original + b"# changed\n")
        with self.assertRaisesRegex(kit.KitError, "no tracked"):
            kit.build(self.root)
        path.write_bytes(original)
        (self.root / "untracked.txt").write_bytes(b"untracked\n")
        with self.assertRaisesRegex(kit.KitError, "nonignored untracked"):
            kit.build(self.root)
        self.assert_no_outputs()

    def test_missing_required_member_refuses(self) -> None:
        (self.root / "docs" / "episode-decision.md").unlink()
        self.commit("missing guide")
        with self.assertRaisesRegex(kit.KitError, "missing or unexpected"):
            kit.build(self.root)
        self.assert_no_outputs()

    def test_assumed_unchanged_index_does_not_admit_arbitrary_raw_change(self) -> None:
        self.git("update-index", "--assume-unchanged", "decide_episode.py")
        path = self.root / "decide_episode.py"
        path.write_bytes(path.read_bytes() + b"# different bytes\n")
        self.assertEqual(self.git("status", "--porcelain"), b"")
        with self.assertRaisesRegex(kit.KitError, "beyond UTF-8 CRLF"):
            kit.build(self.root)
        self.assert_no_outputs()

    def test_nonregular_git_mode_refuses_without_native_symlink(self) -> None:
        target = b"relative-target"
        oid = self.git("hash-object", "-w", "--stdin", data=target).decode().strip()
        (self.root / "game" / "stats.py").write_bytes(target)
        self.git("update-index", "--cacheinfo", "120000," + oid + ",game/stats.py")
        self.git("commit", "-m", "nonregular mode")
        self.assertEqual(self.git("status", "--porcelain"), b"")
        with self.assertRaisesRegex(kit.KitError, "nonregular committed"):
            kit.build(self.root)
        self.assert_no_outputs()

    def test_unsafe_or_casefold_duplicate_metadata_refuses(self) -> None:
        original_git = kit._git
        commit = self.git("rev-parse", "HEAD").decode().strip()
        listing = original_git(self.root, "ls-tree", "-rlz", "--full-tree",
                               commit, "--", *sorted(kit.FIXED_PAYLOAD),
                               "game/", "engine/", "pyproject.toml")
        row = next(item for item in listing.split(b"\0")
                   if item.endswith(b"\tgame/stats.py"))
        cases = (
            listing.replace(b"\tgame/stats.py\0", b"\tgame/../stats.py\0"),
            listing + row.replace(b"\tgame/stats.py", b"\tgame/STATS.py") + b"\0",
        )
        for changed in cases:
            with self.subTest(metadata=changed[-80:]):
                def patched(root: Path, *args: str, data: bytes | None = None,
                            limit: int = kit.MIB, metadata: bytes = changed) -> bytes:
                    if args[0] == "ls-tree":
                        return metadata
                    return original_git(root, *args, data=data, limit=limit)

                with mock.patch.object(kit, "_git", side_effect=patched):
                    with self.assertRaises(kit.KitError):
                        kit.build(self.root)
                self.assert_no_outputs()

    def test_member_payload_count_and_archive_bounds_refuse(self) -> None:
        for constant in ("MEMBER_BYTES", "PAYLOAD_BYTES",
                         "PAYLOAD_MEMBERS", "ZIP_BYTES"):
            with self.subTest(limit=constant), mock.patch.object(kit, constant, 1):
                with self.assertRaises(kit.KitError):
                    kit.build(self.root)
                self.assert_no_outputs()

    def test_replay_marker_missing_or_duplicated_refuses(self) -> None:
        path = self.root.joinpath(*kit.GUIDE.split("/"))
        original = path.read_bytes()
        for body in (original.replace(kit.REPLAY_MARKER, b"(missing.md)"),
                     original + b"\n[Duplicate]" + kit.REPLAY_MARKER + b"\n"):
            path.write_bytes(body)
            self.commit("invalid marker")
            with self.assertRaisesRegex(kit.KitError, "exactly one replay"):
                kit.build(self.root)
            self.assert_no_outputs()

    def test_new_commit_changes_manifest_and_guide_not_executable_payload(self) -> None:
        first, _, first_manifest = kit.prepare(self.root)
        self.git("commit", "--allow-empty", "-m", "new revision")
        second, _, second_manifest = kit.prepare(self.root)
        self.assertNotEqual(first, second)
        self.assertNotEqual(first_manifest["source_commit"],
                            second_manifest["source_commit"])
        self.assertEqual(first_manifest["source_tree"], second_manifest["source_tree"])
        with zipfile.ZipFile(io.BytesIO(first)) as a, \
                zipfile.ZipFile(io.BytesIO(second)) as b:
            for name in a.namelist():
                if name.endswith(".py"):
                    self.assertEqual(a.read(name), b.read(name))
            self.assertNotEqual(a.read(kit.GUIDE), b.read(kit.GUIDE))

    def test_revision_change_during_buffering_refuses_before_output(self) -> None:
        original_archive = kit._archive

        def changed(payload: dict, manifest: dict) -> bytes:
            body = original_archive(payload, manifest)
            self.git("commit", "--allow-empty", "-m", "changed during buffering")
            return body

        with mock.patch.object(kit, "_archive", side_effect=changed):
            with self.assertRaisesRegex(kit.KitError, "revision changed"):
                kit.build(self.root)
        self.assert_no_outputs()

    def test_raw_change_during_buffering_refuses_even_if_status_is_clean(self) -> None:
        self.git("update-index", "--assume-unchanged", "decide_episode.py")
        original_archive = kit._archive

        def changed(payload: dict, manifest: dict) -> bytes:
            body = original_archive(payload, manifest)
            path = self.root / "decide_episode.py"
            path.write_bytes(path.read_bytes() + b"# changed after capture\n")
            return body

        with mock.patch.object(kit, "_archive", side_effect=changed):
            with self.assertRaisesRegex(kit.KitError, "raw source changed"):
                kit.build(self.root)
        self.assert_no_outputs()

    def test_second_write_failure_propagates_with_context_and_no_success(self) -> None:
        original_open = Path.open

        def refused(path: Path, *args, **kwargs):
            if path.name == kit.SIDECAR_NAME and args and args[0] == "wb":
                raise OSError("second output refused")
            return original_open(path, *args, **kwargs)

        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(Path, "open", refused), \
                mock.patch.object(kit, "ROOT", self.root):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(kit.main(), 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("kit output write failed", stderr.getvalue())
        self.assertTrue((self.root / "_site" / kit.ZIP_NAME).is_file())
        self.assertFalse((self.root / "_site" / kit.SIDECAR_NAME).exists())

    def test_nonordinary_output_is_refused_without_replacing_it(self) -> None:
        output = self.root / "_site"
        output.mkdir()
        collision = output / kit.ZIP_NAME
        collision.mkdir()
        with self.assertRaisesRegex(kit.KitError, "ordinary single-link"):
            kit.build(self.root)
        self.assertTrue(collision.is_dir())

    def test_owned_external_destination_preserves_exact_outputs_and_source(
        self,
    ) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="mcts-example-kit-output-")
        destination = Path(temporary.name).absolute()
        try:
            self.assertEqual(destination.parent, self.temp_parent)
            names = self.git("ls-files", "-z").decode().split("\0")
            before = {name: self.root.joinpath(*name.split("/")).read_bytes()
                      for name in names if name}
            archive, sidecar, manifest = kit.prepare(self.root)
            sentinel = destination / "unrelated.txt"
            sentinel.write_bytes(b"preserve unrelated output\n")
            result = kit.build(self.root, output_directory=destination)
            self.assertEqual(result["manifest"], manifest)
            self.assertEqual((destination / kit.ZIP_NAME).read_bytes(), archive)
            self.assertEqual((destination / kit.SIDECAR_NAME).read_bytes(), sidecar)
            self.assertEqual(sentinel.read_bytes(), b"preserve unrelated output\n")
            self.assertEqual({path.name for path in destination.iterdir()},
                             kit.OUTPUT_NAMES | {"unrelated.txt"})
            self.assert_no_outputs()
            for name, body in before.items():
                self.assertEqual(self.root.joinpath(*name.split("/")).read_bytes(),
                                 body)
            self.assertEqual(self.git("status", "--porcelain"), b"")
        finally:
            # Verify the actual recursive cleanup target before removing it.
            resolved = Path(temporary.name).resolve()
            self.assertEqual(resolved, destination)
            self.assertEqual(resolved.parent, self.temp_parent)
            self.assertTrue(resolved.name.startswith("mcts-example-kit-output-"))
            temporary.cleanup()

    def test_actual_cli_refusal_is_contextual_with_empty_stdout(self) -> None:
        (self.root / "untracked.txt").write_bytes(b"untracked\n")
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-B",
             str(self.root / "tools" / "build_episode_examples.py")],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
            shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"Example kit: source must", result.stderr)
        self.assert_no_outputs()

    def test_site_link_and_generated_inventory(self) -> None:
        page = Links()
        page.feed((kit.ROOT / "site" / "index.html").read_text(encoding="utf-8"))
        by_target = {link.get("href"): link for link in page.links}
        self.assertIn(kit.ZIP_NAME, by_target)
        self.assertIn("download", by_target[kit.ZIP_NAME])
        self.assertIn(kit.SIDECAR_NAME, by_target)
        self.assertIn("https://github.com/T92T1914/mcts-combat-engine/blob/main/"
                      "docs/episode-example-kit.md", by_target)
        source = ast.parse((kit.ROOT / "tools" / "build_site.py").read_text())
        generated = next(node.value for node in source.body
                         if isinstance(node, ast.Assign) and any(
                             isinstance(target, ast.Name) and target.id == "GENERATED"
                             for target in node.targets))
        self.assertIsInstance(generated, ast.BinOp)
        self.assertEqual(ast.unparse(generated),
                         "{'appearance.css', 'presentation.json'} | OUTPUT_NAMES")
        calls = [node for node in ast.walk(source) if isinstance(node, ast.Call)]
        self.assertTrue(any(isinstance(node.func, ast.Name) and
                            node.func.id == "build_episode_examples" for node in calls))
        provenance = next(node for node in source.body
                          if isinstance(node, ast.FunctionDef)
                          and node.name == "provenance")
        self.assertTrue(any(isinstance(node, ast.Name) and node.id == "OUTPUT_NAMES"
                            for node in ast.walk(provenance)))

    def test_site_and_kit_provenance_ignore_foreign_git_context(self) -> None:
        sources = {
            "parallel-scaling-results.json": "parallel fixture",
            "same-forest-results.json": "forest fixture",
            "same-forest-repeatability-public-receipts.json": "repeat fixture",
        }
        for name, revision in sources.items():
            body = {"source": {"revision": revision}}
            (self.root / "docs" / name).write_text(json.dumps(body), encoding="utf-8")
        self.commit("retained provenance fixtures")
        expected_commit = self.git("rev-parse", "HEAD").decode().strip()
        output = self.root / "_site"
        output.mkdir()
        (output / "saved.txt").write_bytes(b"retained public body\n")
        (output / "appearance.css").write_bytes(b"/* retained style */\n")
        foreign = output / "foreign"
        foreign.mkdir()
        self.git("-C", str(foreign), "init", "--initial-branch=main",
                 "--object-format=sha1")
        self.git("-C", str(foreign), "commit", "--allow-empty", "-m", "foreign")
        tree = ast.parse((kit.ROOT / "tools" / "build_site.py").read_text())
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef)
                        and node.name == "provenance")
        namespace: dict = {
            "ROOT": self.root, "OUT": output, "FILES": {"saved": "saved.txt"},
            "OUTPUT_NAMES": kit.OUTPUT_NAMES, "source_git": kit._git,
            "hashlib": hashlib, "json": json,
            "load_tokens": lambda: {"source": "retained token fixture"},
        }
        # Execute the actual metadata function, without importing site renderers.
        exec(compile(ast.Module(body=[function], type_ignores=[]),
                     "site provenance fixture", "exec"), namespace)
        overrides = {
            "GIT_DIR": str(foreign / ".git"), "GIT_WORK_TREE": str(self.root),
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.untrackedCache",
            "GIT_CONFIG_VALUE_0": "true",
        }
        with mock.patch.dict(os.environ, overrides):
            generated = kit.build(self.root)
            observed = namespace["provenance"]({"source_commit": "stored fixture"})
        self.assertEqual(generated["manifest"]["source_commit"], expected_commit)
        self.assertEqual(observed["presentation_revision"], expected_commit)
        self.assertFalse(observed["presentation_worktree_dirty"])
        self.assertEqual(observed["recorded_source_revision"], "stored fixture")
        self.assertEqual(observed["parallel_study_source_revision"], "parallel fixture")
        self.assertEqual(observed["same_forest_source_revision"], "forest fixture")
        self.assertEqual(observed["same_forest_repeatability_source_revision"],
                         "repeat fixture")
        self.assertEqual(observed["tokens"], "retained token fixture")
        self.assertFalse(observed["evaluation_rerun"])
        self.assertEqual(observed["files"], {
            name: hashlib.sha256((output / name).read_bytes()).hexdigest()
            for name in {"saved.txt", "appearance.css"} | kit.OUTPUT_NAMES
        })
        (self.root / "decide_episode.py").write_bytes(b"# changed source\n")
        self.assertTrue(namespace["provenance"]({"source_commit": "stored fixture"})[
            "presentation_worktree_dirty"])


if __name__ == "__main__":
    unittest.main()
