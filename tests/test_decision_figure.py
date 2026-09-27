"""Verify the retained values, real figure geometry and public consumers."""

import copy
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from tools import render_decision_figure as figure

NS = {"s": "http://www.w3.org/2000/svg", "dc": "http://purl.org/dc/elements/1.1/"}


class DecisionFigureTests(unittest.TestCase):
    def test_receipt_keeps_historical_decision_separate_from_parallel_study(self):
        record = figure.check_outputs()
        evidence = record["evidence"]
        data = evidence["retained_decision"]
        self.assertEqual(data["source_commit"], "a82e1a6")
        self.assertFalse(evidence["search_rerun"])
        self.assertEqual(evidence["reward_axis"], [0, 0.6])
        self.assertEqual(sum(row["visits"] for row in data["actions"]), 10000)
        self.assertEqual(evidence["chosen_action"], "Spark")
        self.assertIn("Separate evidence", evidence["parallel_scaling_study"])
        self.assertEqual(record["layout"]["clair"], record["layout"]["obscur"])
        for face, (weight, italic) in figure.FACES.items():
            item = record["typography"]["files"][face]
            self.assertEqual(
                (item["postscript"], item["weight"], item["italic"]),
                ("Inter-" + face, weight, italic),
            )
            self.assertRegex(item["sha256"], r"^[a-f0-9]{64}$")

    def test_originals_remain_identical_with_text_checkout_normalization(self):
        for name, checksum, text in (
            (
                "docs/mcts-decision-example.png",
                "1d4eddf87b48674415f85f909edba2a62667d6b22a7f7fc4ebb048453c8b955b",
                False,
            ),
            (
                "docs/mcts-decision-example.svg",
                "e2219632642f024a6ef1217be49040bdeed3a752f4f300e8792846314190561a",
                True,
            ),
            (
                figure.DATA,
                "cd9b5a8cf2f6fe21a46ff8cc9f53b67e99edb494dbd4cc1991a035050d54ed77",
                True,
            ),
        ):
            self.assertEqual(figure.digest(figure.ROOT / name, text=text), checksum)

    def test_svg_bar_lengths_encode_retained_values_with_equal_geometry(self):
        tokens = json.loads(
            (figure.ROOT / "presentation/tokens.json").read_text(encoding="utf-8")
        )
        roots = [
            ET.parse(figure.ROOT / f"docs/mcts-decision-{mode}.svg").getroot()
            for mode in ("clair", "obscur")
        ]
        for index, row in enumerate(figure.load_data()["actions"]):
            paths = [
                root.find(f".//s:g[@id='reward-{index}']/s:path", NS).get("d")
                for root in roots
            ]
            self.assertEqual(paths[0], paths[1])
            coords = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", paths[0])]
            # Read painted bar geometry, independently of the renderer's receipt.
            width = float(roots[0].get("viewBox").split()[2])
            self.assertAlmostEqual(coords[0], width * 0.075, places=5)
            reward = (coords[2] - coords[0]) / (width * 0.85) * 0.6
            self.assertAlmostEqual(reward, row["reward"], places=6)
            for mode, root in zip(("clair", "obscur"), roots, strict=True):
                style = root.find(f".//s:g[@id='reward-{index}']/s:path", NS).get(
                    "style"
                )
                color = tokens["themes"][mode][figure.ACTIONS[row["name"]]]
                self.assertIn(f"fill: {color}", style)
        for root in roots:
            metadata = json.loads(root.find(".//dc:description", NS).text)
            self.assertEqual(metadata, figure.semantic_record(figure.load_data()))

    def test_raster_dimensions_and_metadata_match_the_vector_evidence(self):
        for mode in ("clair", "obscur"):
            raw = (figure.ROOT / f"docs/mcts-decision-{mode}.png").read_bytes()
            self.assertEqual(raw[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", raw[16:24]), (960, 1960))
            offset, description = 8, None
            while offset < len(raw):
                length = struct.unpack(">I", raw[offset : offset + 4])[0]
                kind = raw[offset + 4 : offset + 8]
                content = raw[offset + 8 : offset + 8 + length]
                if kind == b"tEXt" and content.startswith(b"Description\0"):
                    description = json.loads(content.split(b"\0", 1)[1])
                offset += length + 12
            self.assertEqual(description, figure.semantic_record(figure.load_data()))

    def test_real_inter_outlines_and_no_external_glyph_requests(self):
        for mode in ("clair", "obscur"):
            svg = (figure.ROOT / f"docs/mcts-decision-{mode}.svg").read_text(
                encoding="utf-8"
            )
            for face in ("Regular", "SemiBold", "Bold", "Italic"):
                self.assertIn(f'id="Inter-{face}-', svg)
            self.assertNotIn("DejaVu", svg)
            self.assertNotIn("<text", svg)
            self.assertNotIn("@font-face", svg)
            for node in ET.fromstring(svg).iter():
                for name, value in node.attrib.items():
                    if name.endswith("href"):
                        self.assertTrue(value.startswith("#"))

    def test_changed_values_conditions_or_units_are_rejected(self):
        for key in (
            "reward",
            "visits",
            "float_count",
            "conditions",
            "revision",
            "unit",
        ):
            data = copy.deepcopy(figure.load_data())
            if key == "reward":
                data["actions"][0]["reward"] = 0.533
            elif key == "visits":
                data["actions"][0]["visits"] = 5725
            elif key == "float_count":
                data["actions"][0]["visits"] = 5724.0
            elif key == "conditions":
                data["conditions"] = "Parallel process study"
            elif key == "revision":
                data["source_commit"] = "unknown"
            else:
                data["units"] = "Win probability"
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / "docs").mkdir()
                (root / figure.DATA).write_text(json.dumps(data))
                with patch.object(figure, "ROOT", root), self.assertRaises(ValueError):
                    figure.load_data()

    def test_stale_input_or_tampered_output_fails_before_site_publication(self):
        files = [*figure.INPUTS, figure.MANIFEST]
        files += list(figure.check_outputs()["outputs_sha256"])
        for changed in (figure.INPUTS[1], "docs/mcts-decision-clair.png"):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                for name in files:
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(figure.ROOT / name, path)
                with (root / changed).open("ab") as stream:
                    stream.write(b"altered")
                with patch.object(figure, "ROOT", root), self.assertRaises(ValueError):
                    figure.check_outputs()

    def test_render_requires_explicit_fonts(self):
        result = subprocess.run(
            [sys.executable, "tools/render_decision_figure.py"],
            cwd=figure.ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--font-dir is required", result.stderr)

    def test_public_consumers_use_new_editions_and_keep_original(self):
        for name in ("README.md", "docs/visual-example.md"):
            content = (figure.ROOT / name).read_text(encoding="utf-8")
            self.assertIn("<picture>", content)
            for mode in ("clair", "obscur"):
                self.assertIn(f"mcts-decision-{mode}.png", content)
        page = (figure.ROOT / "site/index.html").read_text(encoding="utf-8")
        for mode in ("clair", "obscur"):
            self.assertIn(f'src="decision-{mode}.png"', page)
            self.assertIn(f'href="decision-{mode}.svg" download', page)
        self.assertIn('href="example.svg"', page)


if __name__ == "__main__":
    unittest.main()
