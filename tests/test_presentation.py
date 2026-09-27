"""Preserve recorded evidence while changing only its surrounding presentation."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import build_site, presentation


class PresentationTests(unittest.TestCase):
    def test_tokens_match_the_pinned_family_roles(self):
        tokens = presentation.load_tokens()
        self.assertEqual(
            tokens["source"]["revision"],
            "7a57fe750ff50205a17e1d342106a0d3f2777159",
        )
        # Digest of the source's complete theme roles, with lowercase theme keys.
        encoded = json.dumps(
            tokens["themes"], sort_keys=True, separators=(",", ":")
        ).encode()
        self.assertEqual(
            hashlib.sha256(encoded).hexdigest(),
            "d4bff018983dba1c46b19b91111decae07c5eab313e0b12e490561c89d6b9881",
        )

    def test_local_faces_and_no_media_transform(self):
        css = presentation.appearance_css(presentation.load_tokens())
        self.assertEqual(css.count("@font-face"), 6)
        for name in (
            "Inter-Regular",
            "Inter-SemiBold",
            "Inter-Bold",
            "Inter-Italic",
            "Inter-SemiBoldItalic",
            "Inter-BoldItalic",
        ):
            self.assertIn(f'local("{name}")', css)
        self.assertNotIn("url(", css)
        style = (presentation.ROOT / "site/style.css").read_text()
        self.assertNotIn("filter:", style)
        self.assertIn("font-synthesis:none", style)

    def test_build_preserves_recorded_files_and_documents_rendered_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            with patch.object(build_site, "OUT", out):
                build_site.main()
            self.assertEqual(
                {p.name for p in out.iterdir()},
                set(build_site.FILES.values()) | build_site.GENERATED,
            )
            for source, target in build_site.FILES.items():
                self.assertEqual(
                    (out / target).read_bytes(), (build_site.ROOT / source).read_bytes()
                )
            manifest = json.loads((out / "presentation.json").read_text())
            self.assertFalse(manifest["evaluation_rerun"])
            self.assertEqual(manifest["recorded_source_revision"], "a82e1a6")
            self.assertRegex(manifest["presentation_revision"], r"^[a-f0-9]{40}$")
            self.assertEqual(
                set(manifest["files"]),
                set(build_site.FILES.values()) | {"appearance.css"},
            )
            for name, digest in manifest["files"].items():
                self.assertEqual(
                    hashlib.sha256((out / name).read_bytes()).hexdigest(), digest
                )

    def test_unlisted_output_is_refused_before_replacing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            (out / "unrelated.txt").write_text("preserve me")
            (out / "index.html").write_text("previous output")
            with patch.object(build_site, "OUT", out):
                with self.assertRaisesRegex(ValueError, "Unexpected site output"):
                    build_site.main()
            self.assertEqual((out / "index.html").read_text(), "previous output")
            self.assertEqual((out / "unrelated.txt").read_text(), "preserve me")

    def test_text_and_focus_roles_have_readable_contrast(self):
        def luminance(color):
            rgb = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
            linear = [
                v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb
            ]
            return sum(
                v * w for v, w in zip(linear, [0.2126, 0.7152, 0.0722], strict=True)
            )

        for name, roles in presentation.load_tokens()["themes"].items():
            for foreground in ("text", "muted", "accent", "error"):
                for background in ("canvas", "panel", "control"):
                    light, dark = sorted(
                        [luminance(roles[foreground]), luminance(roles[background])],
                        reverse=True,
                    )
                    self.assertGreaterEqual(
                        (light + 0.05) / (dark + 0.05),
                        4.5,
                        (name, foreground, background),
                    )


if __name__ == "__main__":
    unittest.main()
