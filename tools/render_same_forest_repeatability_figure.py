"""Plot retained paired intervals without executing another search."""

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.presentation import load_tokens  # noqa: E402
from tools.render_decision_figure import font_files  # noqa: E402
from tools.render_same_forest_repeatability import DATA  # noqa: E402
from tools.render_same_forest_repeatability import (  # noqa: E402
    check_outputs as check_report,
)

MANIFEST = ROOT / "docs/same-forest-repeatability-figure.json"
AXIS = [0.5, 5.0]
INPUTS = (
    "docs/same-forest-repeatability-public-receipts.json",
    "docs/same-forest-repeatability-protocol.json",
    "presentation/tokens.json",
    "tools/render_same_forest_repeatability.py",
    "tools/render_same_forest_repeatability_figure.py",
)


def digest(path, text=False):
    data = (
        path.read_text(encoding="utf-8").encode("utf-8") if text else path.read_bytes()
    )
    return hashlib.sha256(data).hexdigest()


def evidence(record, summary):
    return {
        "measured_revision": record["source"]["revision"],
        "public_receipts_sha256": digest(DATA),
        "original_private_sha256": record["publication_derivative"][
            "original_private_identity"
        ]["sha256"],
        "search_rerun": False,
        "x_axis": AXIS,
        "ratio": "sequential wall time / process wall time",
        "baseline": 1,
        "phase_markers": {"cold": "circle", "warm": "square"},
        "series_roles": {"cold": "accent", "warm": "warning"},
        "interval": "Individual approximate 95-percent Student-t intervals "
        "on six controller-block log-ratio means, df 5",
        "values": [
            {
                key: row[key]
                for key in (
                    "scenario",
                    "roots",
                    "metric",
                    "phase",
                    "geometric_mean_ratio",
                    "approximate_95_interval",
                    "sampling_units",
                    "degrees_of_freedom",
                )
            }
            for row in summary
        ],
    }


def draw(summary, tokens, mode, metric, files, output):
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import rc_context
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.font_manager import FontProperties

    roles = tokens["themes"][mode]
    fonts = {name: FontProperties(fname=str(path)) for name, path in files.items()}
    rows = [row for row in summary if row["metric"] == metric]
    if any(
        not AXIS[0] <= bound <= AXIS[1]
        for row in rows
        for bound in row["approximate_95_interval"]
    ):
        raise ValueError("An interval lies outside the declared axis")
    name = "search" if metric == "elapsed_s" else "complete"
    title = "Search interval" if name == "search" else "Complete call"
    with rc_context(
        {"svg.fonttype": "path", "svg.hashsalt": "same-forest-repeatability-v1"}
    ):
        fig = Figure(figsize=(5, 5.8), dpi=200, facecolor=roles["canvas"])
        labels = []

        def label(x, y, text, size=12, face="Regular", color=None, **kwargs):
            item = fig.text(
                x,
                y,
                text,
                fontsize=size,
                fontproperties=fonts[face],
                color=color or roles["text"],
                va="top",
                **kwargs,
            )
            labels.append(item)
            return item

        label(0.055, 0.96, "SAME FOREST EXECUTION", 11.8, "SemiBold", roles["accent"])
        label(0.055, 0.90, title, 24, "Bold")
        label(0.055, 0.81, "Above 1 favors process execution.", 12)
        axis = fig.add_axes((0.285, 0.26, 0.645, 0.455), facecolor=roles["panel"])
        axis.set_xlim(*AXIS)
        axis.set_ylim(-0.55, 5.55)
        axis.set_yticks([])
        axis.set_xticks([1, 2, 3, 4, 5])
        axis.tick_params(colors=roles["muted"], labelsize=12)
        for tick in axis.get_xticklabels():
            tick.set_fontproperties(fonts["Regular"])
            tick.set_fontsize(12)
        for spine in axis.spines.values():
            spine.set_color(roles["divider"])
        axis.axvline(1, color=roles["muted"], linestyle="--", linewidth=1.3)
        axis.grid(axis="x", color=roles["divider"], linewidth=0.65)
        conditions = list(
            dict.fromkeys((row["scenario"], row["roots"]) for row in rows)
        )
        for index, (scenario, roots) in enumerate(conditions):
            y = 5 - index
            label(
                0.055,
                0.715 - (index + 0.28) * 0.455 / 6.1,
                f"{scenario}\n{roots} roots",
                11.8,
                "SemiBold",
            )
            for phase, offset, marker, role in (
                ("cold", 0.13, "o", "accent"),
                ("warm", -0.13, "s", "warning"),
            ):
                row = next(
                    row
                    for row in rows
                    if (row["scenario"], row["roots"], row["phase"])
                    == (scenario, roots, phase)
                )
                value = row["geometric_mean_ratio"]
                low, high = row["approximate_95_interval"]
                axis.errorbar(
                    value,
                    y + offset,
                    xerr=[[value - low], [high - value]],
                    fmt=marker,
                    color=roles[role],
                    capsize=3.0,
                    markersize=4.5,
                    linewidth=1.5,
                    gid=f"{scenario}-{roots}-{phase}",
                )
        label(0.055, 0.755, "Cold: circle", 11.8, "SemiBold", roles["accent"])
        label(0.52, 0.755, "Warm: square", 11.8, "SemiBold", roles["warning"])
        label(0.5, 0.205, "Sequential / process wall time", 12, "SemiBold", ha="center")
        label(
            0.055,
            0.145,
            "Individual approximate 95% intervals.\n"
            "Six block means, three states and one seed.",
            11.8,
            color=roles["muted"],
        )
        label(
            0.055,
            0.065,
            "Warm preparation excluded."
            if name == "search"
            else "Preparation and cleanup included.",
            11.8,
            "Italic",
            roles["muted"],
        )
        canvas = FigureCanvasAgg(fig)
        canvas.draw()
        bounds = [item.get_window_extent(canvas.get_renderer()) for item in labels]
        if any(
            b.x0 < 0 or b.y0 < 0 or b.x1 > fig.bbox.width or b.y1 > fig.bbox.height
            for b in bounds
        ):
            raise ValueError("A figure label extends outside the canvas")
        for extension in ("png", "svg"):
            path = output / f"same-forest-repeatability-{name}-{mode}.{extension}"
            metadata = {
                "Description": "Paired retained ratios and individual intervals"
            }
            if extension == "svg":
                metadata["Date"] = None
            fig.savefig(path, metadata=metadata)
            if extension == "svg":
                path.write_text(
                    "\n".join(
                        line.rstrip() for line in path.read_text("utf-8").splitlines()
                    )
                    + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
        fig.clear()
        return {
            "width": 1000,
            "height": 1160,
            "labels_within_canvas": len(bounds),
            "minimum_font_points": 11.8,
            "condition_count": len(conditions),
        }


def check_outputs():
    record, summary = check_report()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest["evidence"] != evidence(record, summary):
        raise ValueError("Figure values or evidence differ")
    for name in INPUTS:
        if manifest["inputs_sha256"][name] != digest(
            ROOT / name,
            text=name != "docs/same-forest-repeatability-public-receipts.json",
        ):
            raise ValueError("Figure input changed: " + name)
    expected = {
        f"docs/same-forest-repeatability-{metric}-{mode}.{extension}"
        for metric in ("search", "complete")
        for mode in ("clair", "obscur")
        for extension in ("png", "svg")
    }
    if set(manifest["outputs_sha256"]) != expected:
        raise ValueError("Both figures and appearances are required")
    for name, sha256 in manifest["outputs_sha256"].items():
        if digest(ROOT / name) != sha256:
            raise ValueError("Figure output changed: " + name)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font-dir", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        check_outputs()
        print("Retained ratios, uncertainty and figure byte identities match")
        return
    if args.font_dir is None:
        parser.error("--font-dir is required; no fonts are downloaded")
    record, summary = check_report()
    files, font_evidence = font_files(args.font_dir)
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)
        layouts = {
            f"{metric}-{mode}": draw(
                summary, load_tokens(), mode, metric, files, output
            )
            for metric in ("elapsed_s", "complete_call_s")
            for mode in ("clair", "obscur")
        }
        import matplotlib

        manifest = {
            "schema_version": 1,
            "evidence": evidence(record, summary),
            "renderer": {"matplotlib": matplotlib.__version__, "backend": "Agg"},
            "layout": layouts,
            "typography": {
                "files": font_evidence,
                "painted_faces": ["Regular", "SemiBold", "Bold", "Italic"],
                "png": "Glyphs rasterized from explicit Inter files",
                "svg": "Labels outlined from the same Inter files. "
                "Selectable tables accompany the plots",
            },
            "inputs_sha256": {
                name: digest(
                    ROOT / name,
                    text=name != "docs/same-forest-repeatability-public-receipts.json",
                )
                for name in INPUTS
            },
            "outputs_sha256": {
                "docs/" + path.name: digest(path) for path in sorted(output.iterdir())
            },
        }
        for path in output.iterdir():
            (ROOT / "docs" / path.name).write_bytes(path.read_bytes())
        MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    check_outputs()
    print("Rendered retained intervals in both appearances without running search")


if __name__ == "__main__":
    main()
