"""Render the retained decision example without running another search."""

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = "docs/visual-example-data.json"
MANIFEST = "docs/mcts-decision-figure.json"
INPUTS = (DATA, "presentation/tokens.json", "tools/render_decision_figure.py")
FACES = {
    "Regular": (400, False),
    "SemiBold": (600, False),
    "Bold": (700, False),
    "Italic": (400, True),
    "SemiBoldItalic": (600, True),
    "BoldItalic": (700, True),
}
ACTIONS = {"Spark": "warning", "Pass": "accent", "Weakness Mark": "muted"}


def digest(path, text=False):
    data = path.read_text(encoding="utf-8").encode() if text else path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def load_data():
    data = json.loads((ROOT / DATA).read_text(encoding="utf-8"))
    expected = [
        {"name": "Spark", "reward": 0.532, "visits": 5724},
        {"name": "Pass", "reward": 0.506, "visits": 2445},
        {"name": "Weakness Mark", "reward": 0.495, "visits": 1831},
    ]
    if (
        data["source_commit"] != "a82e1a6"
        or data["source"] != "demo.py boss --sims 10000 --seed 7 --horizon 6"
        or data["conditions"]
        != "Fixed initial deal seed 7, search seed 7, horizon 6, single process, "
        "10000 simulations; safety cap not reached"
        or data["precision"]
        != "Reward rounded to three decimal places as printed by the public demo"
        or data["units"] != "Mean shaped reward; not a win probability"
        or data["actions"] != expected
        or any(type(row["visits"]) is not int for row in data["actions"])
    ):
        raise ValueError("The figure requires the retained decision values and source")
    return data


def font_files(directory):
    """Require actual static Inter faces, without a fallback or font download."""
    from fontTools.ttLib import TTFont

    files, evidence = {}, {}
    for name, (weight, italic) in FACES.items():
        path = directory / f"Inter-{name}.ttf"
        with TTFont(path) as font:
            postscript = font["name"].getDebugName(6)
            if (
                postscript != f"Inter-{name}"
                or font["OS/2"].usWeightClass != weight
                or bool(font["OS/2"].fsSelection & 1) != italic
                or not set(range(32, 127)).issubset(font.getBestCmap())
            ):
                raise ValueError(
                    f"Incorrect Inter face or missing Latin glyphs: {path.name}"
                )
            evidence[name] = {
                "sha256": digest(path),
                "postscript": postscript,
                "weight": weight,
                "italic": italic,
            }
        files[name] = path
    return files, evidence


def semantic_record(data):
    return {
        "retained_decision": data,
        "search_rerun": False,
        "reward_axis": [0, 0.6],
        "chosen_action": "Spark",
        "series_roles": ACTIONS,
        "visits": "Exact search visits, not confidence intervals",
        "parallel_scaling_study": "Separate evidence, not this historical decision",
    }


def draw(data, tokens, mode, files, output, wide=False):
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import rc_context
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.font_manager import FontProperties
    from matplotlib.patches import Rectangle

    roles = tokens["themes"][mode]
    fonts = {name: FontProperties(fname=str(path)) for name, path in files.items()}
    with rc_context({"svg.fonttype": "path", "svg.hashsalt": "mcts-decision-v1"}):
        fig = Figure(
            figsize=(9, 5.8) if wide else (4.8, 9.8), dpi=200, facecolor=roles["canvas"]
        )
        labels = []

        def label(x, y, text, size=13, face="Regular", color=None, **kwargs):
            item = fig.text(
                x,
                y,
                text,
                fontsize=size,
                fontproperties=fonts[face],
                color=color or roles["text"],
                va="top",
                linespacing=1.3,
                **kwargs,
            )
            labels.append(item)
            return item

        if wide:
            label(0.055, 0.96, "MCTS COMBAT ENGINE", 12, "SemiBold", roles["accent"])
            label(0.055, 0.90, "One decision. Three choices.", 27, "Bold")
            label(0.055, 0.80, "10,000 simulations. Seed 7.", 14)
            label(0.055, 0.715, "Mean shaped reward", 14, "SemiBold")
            for index, row in enumerate(data["actions"]):
                top = 0.645 - index * 0.112
                color = roles[ACTIONS[row["name"]]]
                label(0.055, top, row["name"], 14, "SemiBold", color)
                label(0.59, top, f"{row['reward']:.3f}", 14, "Bold", ha="right")
                fig.add_artist(
                    Rectangle(
                        (0.055, top - 0.080),
                        0.535 * row["reward"] / 0.6,
                        0.022,
                        transform=fig.transFigure,
                        facecolor=color,
                        gid=f"reward-{index}",
                    )
                )
            for value in [0, 0.2, 0.4, 0.6]:
                label(
                    0.055 + 0.535 * value / 0.6,
                    0.321,
                    f"{value:.1f}",
                    12,
                    color=roles["muted"],
                    ha="center",
                )
            label(0.67, 0.715, "Visits, separate counts", 13, "SemiBold")
            for index, row in enumerate(data["actions"]):
                top = 0.645 - index * 0.112
                label(0.67, top, row["name"], 13)
                label(0.945, top - 0.042, f"{row['visits']:,}", 17, "Bold", ha="right")
            label(0.67, 0.30, "Chosen: Spark", 17, "Bold", roles["warning"])
            label(
                0.055,
                0.235,
                "Trap retaliation puts Weakness Mark below passing in this state.",
                13,
            )
            label(
                0.055,
                0.165,
                "One process. Horizon 6. Safety cap not reached. Source: a82e1a6.",
                12.5,
                color=roles["muted"],
            )
            label(
                0.055,
                0.095,
                "Not a win probability or a universal ranking. "
                "Rewards rounded to three decimals.",
                12.5,
                "Italic",
                roles["muted"],
            )
        else:
            label(0.075, 0.96, "MCTS COMBAT ENGINE", 12, "SemiBold", roles["accent"])
            label(0.075, 0.915, "One decision.\nThree choices.", 27, "Bold")
            label(0.075, 0.80, "10,000 simulations. Seed 7.", 14)
            label(0.075, 0.752, "Mean shaped reward", 14, "SemiBold")
            for index, row in enumerate(data["actions"]):
                top = 0.699 - index * 0.108
                color = roles[ACTIONS[row["name"]]]
                label(0.075, top, row["name"], 14, "SemiBold", color)
                label(0.925, top, f"{row['reward']:.3f}", 14, "Bold", ha="right")
                bar = Rectangle(
                    (0.075, top - 0.049),
                    0.85 * row["reward"] / 0.6,
                    0.021,
                    transform=fig.transFigure,
                    facecolor=color,
                    gid=f"reward-{index}",
                )
                fig.add_artist(bar)
            for value in [0, 0.2, 0.4, 0.6]:
                x = 0.075 + 0.85 * value / 0.6
                label(x, 0.415, f"{value:.1f}", 12, color=roles["muted"], ha="center")
            label(0.075, 0.367, "Visits, shown separately", 14, "SemiBold")
            for index, row in enumerate(data["actions"]):
                y = 0.33 - index * 0.032
                label(0.075, y, row["name"], 13)
                label(0.925, y, f"{row['visits']:,}", 13, "SemiBold", ha="right")
            label(0.075, 0.217, "Chosen action: Spark.", 16, "Bold")
            label(
                0.075,
                0.18,
                "Trap retaliation puts Weakness Mark\nbelow passing in this state.",
                12.5,
            )
            label(
                0.075,
                0.124,
                "One process. Horizon 6. Safety cap not reached.\n"
                "Recorded source: a82e1a6.",
                11.8,
                color=roles["muted"],
            )
            label(
                0.075,
                0.065,
                "Not a win probability or a universal ranking.\n"
                "Rewards rounded to three decimals.",
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
        layout = {
            "width": int(fig.bbox.width),
            "height": int(fig.bbox.height),
            "labels_within_canvas": len(bounds),
            "minimum_font_points": min(item.get_fontsize() for item in labels),
        }
        for ext in ("png", "svg"):
            metadata = {
                "Description": json.dumps(semantic_record(data), sort_keys=True)
            }
            if ext == "svg":
                metadata["Date"] = None
            suffix = "-wide" if wide else ""
            path = output / f"mcts-decision-{mode}{suffix}.{ext}"
            fig.savefig(path, metadata=metadata)
            if ext == "svg":
                path.write_text(
                    "\n".join(
                        line.rstrip()
                        for line in path.read_text(encoding="utf-8").splitlines()
                    )
                    + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
        fig.clear()
        return layout


def check_outputs():
    record = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
    if record["evidence"] != semantic_record(load_data()):
        raise ValueError("Figure evidence is stale")
    for name in INPUTS:
        if record["inputs_sha256_lf"][name] != digest(ROOT / name, text=True):
            raise ValueError(f"Figure input changed: {name}")
    expected = {
        f"docs/mcts-decision-{mode}{suffix}.{ext}"
        for mode in ("clair", "obscur")
        for suffix in ("", "-wide")
        for ext in ("png", "svg")
    }
    if set(record["outputs_sha256"]) != expected:
        raise ValueError("Both PNG and SVG editions are required")
    for name, checksum in record["outputs_sha256"].items():
        if digest(ROOT / name) != checksum:
            raise ValueError(f"Figure output changed: {name}")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--font-dir", type=Path, help="Directory of six official static Inter TTFs"
    )
    parser.add_argument(
        "--check", action="store_true", help="Verify committed output without rendering"
    )
    args = parser.parse_args()
    if args.check:
        check_outputs()
        print("Both editions match the retained decision evidence and renderer")
        return
    if args.font_dir is None:
        parser.error(
            "--font-dir is required for rendering; no font download is performed"
        )
    data = load_data()
    tokens = json.loads((ROOT / "presentation/tokens.json").read_text(encoding="utf-8"))
    files, font_evidence = font_files(args.font_dir)
    with tempfile.TemporaryDirectory() as temp:
        output = Path(temp)
        layouts = {
            mode: draw(data, tokens, mode, files, output)
            for mode in ("clair", "obscur")
        }
        wide_layouts = {
            mode: draw(data, tokens, mode, files, output, wide=True)
            for mode in ("clair", "obscur")
        }
        import matplotlib

        record = {
            "schema_version": 2,
            "evidence": semantic_record(data),
            "renderer": {"matplotlib": matplotlib.__version__, "backend": "Agg"},
            "layout": layouts,
            "wide_layout": wide_layouts,
            "typography": {
                "files": font_evidence,
                "painted_faces": ["Regular", "SemiBold", "Bold", "Italic"],
                "png": "Glyphs rasterized from explicit Inter files",
                "svg": "Labels outlined from the same Inter files. "
                "Selectable text and source data accompany the figure",
            },
            "inputs_sha256_lf": {
                name: digest(ROOT / name, text=True) for name in INPUTS
            },
            "outputs_sha256": {
                "docs/" + p.name: digest(p) for p in sorted(output.iterdir())
            },
        }
        for path in output.iterdir():
            (ROOT / "docs" / path.name).write_bytes(path.read_bytes())
        (ROOT / MANIFEST).write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )
    check_outputs()
    print("Rendered both editions from retained data with verified Inter files")


if __name__ == "__main__":
    main()
