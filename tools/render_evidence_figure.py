"""Render retained PR55 search timing without running a search or experiment."""

import argparse
import hashlib
import json
import math
import statistics
import struct
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from .presentation import load_tokens
    from .render_decision_figure import FACES, font_files
except ImportError:
    from render_decision_figure import FACES, font_files

    from presentation import load_tokens

ROOT = Path(__file__).resolve().parents[1]
DATA = "docs/request-edge-reuse/results.json"
MANIFEST = "docs/request-edge-reuse-figure.json"
STEM = "request-edge-reuse"
REVISION = "56120034dcb34a9c1321eec5fc27437e5bc4deca"
SOURCE_SHA256 = "e59a979ce0bd1dd3f64fbad8a1c718ac6ec3fb03355d6c05dea081bc8fcf7871"
REPOSITORY = "T92T1914/mcts-combat-engine"
GUIDE = f"https://github.com/{REPOSITORY}/blob/{REVISION}/docs/request-edge-reuse.md"
INPUTS = (
    DATA,
    "presentation/tokens.json",
    "tools/presentation.py",
    "tools/render_decision_figure.py",
    "tools/render_evidence_figure.py",
)
WIDTH, HEIGHT, DPI = 1440, 1000, 120
SVG = "http://www.w3.org/2000/svg"
DC = "http://purl.org/dc/elements/1.1/"
NS = {"s": SVG}
TITLE = "MCTS.search timing"
DESCRIPTION = (
    "Six retained PR55 condition indices, each 100 divided by its median "
    "paired baseline/candidate search-time ratio. Baseline is 100. The "
    "declared aggregate is 11.75% lower search time on one shared host. "
    "Two of thirty pairs were slower. Not CLI latency or stronger play."
)


def digest(path, text=False):
    data = path.read_text(encoding="utf-8").encode() if text else path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def source_record():
    return {
        "repository": REPOSITORY,
        "revision": REVISION,
        "path": DATA,
        "url": f"https://github.com/{REPOSITORY}/blob/{REVISION}/{DATA}",
        "sha256": digest(ROOT / DATA, text=True),
    }


def load_values():
    if digest(ROOT / DATA, text=True) != SOURCE_SHA256:
        raise ValueError("Retained PR55 source changed; review before rendering")
    data = json.loads((ROOT / DATA).read_text(encoding="utf-8"))
    expected = [
        (name, horizon)
        for name in ("duel", "gauntlet", "boss")
        for horizon in (3, 6)
    ]
    if len(data["conditions"]) != len(expected):
        raise ValueError("The six retained timing conditions are required")
    rows, medians, adverse = [], [], 0
    for condition, (name, horizon) in zip(data["conditions"], expected, strict=True):
        controls = condition["controls"]
        if controls["scenario"] != name or controls["horizon"] != horizon:
            raise ValueError("Retained condition identity or order changed")
        pairs = condition["pairs"]
        if len(pairs) != 5:
            raise ValueError("Five retained pairs per condition are required")
        ratios = [p["baseline_seconds"] / p["candidate_seconds"] for p in pairs]
        if not all(math.isfinite(r) and r > 0 for r in ratios):
            raise ValueError("Timing ratios must be finite and positive")
        median = statistics.median(ratios)
        if median != condition["median_paired_baseline_over_candidate"]:
            raise ValueError("Saved median differs from its retained timing pairs")
        medians.append(median)
        adverse += sum(r < 1 for r in ratios)
        rows.append(
            {
                "condition": f"{name.title()}, horizon {horizon}",
                "median_baseline_over_candidate": median,
                "relative_search_time": 100 / median,
            }
        )
    aggregate = math.exp(sum(math.log(r) for r in medians) / len(medians))
    if (
        aggregate
        != data["geometric_mean_condition_median_paired_baseline_over_candidate"]
    ):
        raise ValueError("Retained geometric aggregate differs")
    if adverse != len(data["adverse_individual_pairs"]) or adverse != 2:
        raise ValueError("Adverse timing observations must remain included")
    return {
        "conditions": rows,
        "baseline": 100,
        "aggregate_ratio": aggregate,
        "lower_search_time_percent": 100 * (1 - 1 / aggregate),
        "individual_timing_pairs": 30,
        "adverse_individual_pairs": adverse,
    }


def add_svg_accessibility(path):
    ET.register_namespace("", SVG)
    tree = ET.parse(path)
    root = tree.getroot()
    root.set("role", "img")
    root.set("aria-labelledby", "evidence-title evidence-description")
    ET.SubElement(root, f"{{{SVG}}}title", {"id": "evidence-title"}).text = TITLE
    ET.SubElement(root, f"{{{SVG}}}desc", {"id": "evidence-description"}).text = (
        DESCRIPTION
    )
    group = root.find(".//s:g[@id='source-link']", NS)
    if group is None:
        raise ValueError("The visible source link is missing")
    anchor = ET.Element(f"{{{SVG}}}a", {"href": GUIDE})
    for child in list(group):
        group.remove(child)
        anchor.append(child)
    group.append(anchor)
    # Receipts bind delivered bytes, including line endings on every host.
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    path.write_bytes(payload.replace(b"\r\n", b"\n"))


def draw(values, tokens, mode, files, output):
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import rc_context
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.font_manager import FontProperties
    from matplotlib.lines import Line2D
    from matplotlib.patches import Rectangle

    roles = tokens["themes"][mode]
    fonts = {
        name: FontProperties(
            fname=str(path),
            family=["Inter", "Arial", "sans-serif"],
            weight={"Regular": 400, "SemiBold": 600, "Bold": 700}.get(name, 400),
        )
        for name, path in files.items()
    }
    with rc_context({"svg.fonttype": "none", "svg.hashsalt": "mcts-pr55-evidence-v1"}):
        fig = Figure(
            figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor=roles["canvas"]
        )
        labels = []

        def label(x, y, text, size=24, face="Regular", gid=None, **kwargs):
            item = fig.text(
                x, y, text, fontsize=size, fontproperties=fonts[face],
                color=roles["text"], va="center", gid=gid, **kwargs
            )
            labels.append(item)

        label(0.04, 0.945, TITLE, 38, "Bold")
        label(0.04, 0.865, "Same declared work. Retained PR55 results.", 25)
        left, scale = 0.34, 0.51
        baseline = left + scale * values["baseline"] / 112
        fig.add_artist(
            Line2D(
                (baseline, baseline), (0.255, 0.77), transform=fig.transFigure,
                color=roles["warning"], linewidth=2, linestyle="--",
            )
        )
        label(baseline, 0.795, "100 baseline", 22, "SemiBold", ha="center")
        for index, row in enumerate(values["conditions"]):
            y = 0.705 - index * 0.081
            name, horizon = row["condition"].split(", horizon ")
            label(0.04, y, f"{name} H{horizon}", 30, "SemiBold")
            width = scale * row["relative_search_time"] / 112
            fig.add_artist(
                Rectangle(
                    (left, y - 0.023), width, 0.046, transform=fig.transFigure,
                    facecolor=roles["accent"], gid=f"condition-bar-{index}",
                )
            )
            label(
                0.96, y, f"{row['relative_search_time']:.2f}",
                30, "Bold", gid=f"condition-value-{index}", ha="right",
            )
        label(0.04, 0.225, "Index = 100 / median paired ratio. H = horizon.", 22)
        label(
            0.04, 0.165,
            f"{values['lower_search_time_percent']:.2f}% lower by declared aggregate",
            27, "SemiBold",
        )
        label(0.04, 0.105, "Two of 30 pairs were slower. One shared host.", 22)
        label(
            0.04, 0.05, "Search only. Source and limits: guide", 22, gid="source-link"
        )
        canvas = FigureCanvasAgg(fig)
        canvas.draw()
        bounds = [item.get_window_extent(canvas.get_renderer()) for item in labels]
        if any(
            b.x0 < 0 or b.y0 < 0 or b.x1 > WIDTH or b.y1 > HEIGHT for b in bounds
        ):
            raise ValueError("A retained-evidence label extends outside the canvas")
        for extension in ("png", "svg"):
            metadata = {"Description": json.dumps(values, sort_keys=True)}
            if extension == "svg":
                metadata["Date"] = None
            path = output / f"{STEM}-{mode}.{extension}"
            fig.savefig(path, metadata=metadata)
            if extension == "svg":
                add_svg_accessibility(path)
        fig.clear()


def check_outputs():
    """Check retained source and committed exports without a plotting dependency."""
    record = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
    values = load_values()
    if (
        record["schema_version"] != 1 or record["source_commit"] != REVISION
        or record["source"] != source_record() or record["values"] != values
        or record["source_sha256_lf"]
        != {name: digest(ROOT / name, text=True) for name in INPUTS}
        or set(record["editions"]) != {"clair", "obscur"}
    ):
        raise ValueError("Retained figure source, values or renderer changed")
    themes = load_tokens()["themes"]
    if (
        record["rendering"]["theme_roles"] != themes
        or record["rendering"]["new_measurement"] is not False
        or record["typography"]["font_binaries_distributed"] is not False
        or set(record["typography"]["files"]) != set(FACES)
    ):
        raise ValueError("Figure appearance or font provenance changed")
    for face, (weight, italic) in FACES.items():
        evidence = record["typography"]["files"][face]
        checksum = evidence["sha256"]
        if (
            evidence["postscript"] != f"Inter-{face}"
            or evidence["weight"] != weight or evidence["italic"] is not italic
            or len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum)
        ):
            raise ValueError("Validated static Inter identity changed")
    for mode, edition in record["editions"].items():
        if set(edition) != {"png", "svg"}:
            raise ValueError("Both PNG and SVG exports are required")
        for extension, item in edition.items():
            name = f"docs/{STEM}-{mode}.{extension}"
            path = ROOT / name
            if item["path"] != name or digest(path) != item["sha256"]:
                raise ValueError(f"Retained export changed: {name}")
            if extension == "png":
                raw = path.read_bytes()
                if raw[:8] != b"\x89PNG\r\n\x1a\n":
                    raise ValueError("Invalid PNG signature")
                if struct.unpack_from(">II", raw, 16) != (WIDTH, HEIGHT):
                    raise ValueError("PNG dimensions changed")
                if (item["width"], item["height"]) != (WIDTH, HEIGHT):
                    raise ValueError("Manifest PNG dimensions changed")
                offset, descriptions = 8, []
                while offset + 12 <= len(raw):
                    length = struct.unpack_from(">I", raw, offset)[0]
                    end = offset + length + 12
                    if end > len(raw):
                        raise ValueError("Truncated PNG chunk")
                    if raw[offset + 4:offset + 8] == b"tEXt":
                        key, text = raw[offset + 8:end - 4].split(b"\0", 1)
                        if key == b"Description":
                            descriptions.append(json.loads(text.decode("latin-1")))
                    offset = end
                if descriptions != [values]:
                    raise ValueError("PNG retained values changed")
            else:
                svg = ET.parse(path).getroot()
                box = [float(v) for v in svg.attrib["viewBox"].split()]
                if box != [0, 0, WIDTH * 72 / DPI, HEIGHT * 72 / DPI]:
                    raise ValueError("SVG dimensions changed")
                if (
                    svg.get("width") != f"{WIDTH * 72 / DPI:g}pt"
                    or svg.get("height") != f"{HEIGHT * 72 / DPI:g}pt"
                    or svg.get("role") != "img"
                    or svg.get("aria-labelledby")
                    != "evidence-title evidence-description"
                ):
                    raise ValueError("SVG dimensions or accessible role changed")
                if (
                    svg.find("s:title", NS).text != TITLE
                    or svg.find("s:desc", NS).text != DESCRIPTION
                    or not svg.findall(".//s:text", NS)
                    or svg.find(".//s:a", NS).get("href") != GUIDE
                    or json.loads(svg.find(f".//{{{DC}}}description").text) != values
                ):
                    raise ValueError("SVG accessible text or retained values changed")
                for index, row in enumerate(values["conditions"]):
                    group = svg.find(f".//s:g[@id='condition-value-{index}']", NS)
                    if group is None or "".join(group.itertext()).strip() != (
                        f"{row['relative_search_time']:.2f}"
                    ):
                        raise ValueError("Visible SVG condition index changed")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font-dir", type=Path, help="Six official static Inter TTFs")
    parser.add_argument("--check", action="store_true", help="Check without rendering")
    args = parser.parse_args()
    if args.check:
        check_outputs()
        print("Both PR55 editions match retained source and exported values")
        return
    if args.font_dir is None:
        parser.error("--font-dir is required; fonts are never downloaded")
    values, tokens = load_values(), load_tokens()
    files, evidence = font_files(args.font_dir)
    with tempfile.TemporaryDirectory(prefix="mcts-evidence-") as directory:
        output = Path(directory)
        for mode in ("clair", "obscur"):
            draw(values, tokens, mode, files, output)
        import matplotlib

        editions = {}
        for mode in ("clair", "obscur"):
            editions[mode] = {}
            for extension in ("png", "svg"):
                path = output / f"{STEM}-{mode}.{extension}"
                item = {"path": "docs/" + path.name, "sha256": digest(path)}
                if extension == "png":
                    item.update(width=WIDTH, height=HEIGHT)
                editions[mode][extension] = item
                (ROOT / item["path"]).write_bytes(path.read_bytes())
        record = {
            "schema_version": 1,
            "source": source_record(), "source_commit": REVISION, "values": values,
            "source_sha256_lf": {n: digest(ROOT / n, text=True) for n in INPUTS},
            "editions": editions,
            "rendering": {
                "renderer": "tools/render_evidence_figure.py", "version": 1,
                "matplotlib": matplotlib.__version__, "backend": "Agg",
                "new_measurement": False, "series_role": "accent",
                "baseline_role": "warning", "axis": [0, 112],
                "token_revision": tokens["source"]["revision"],
                "theme_roles": {mode: tokens["themes"][mode] for mode in editions},
            },
            "typography": {
                "source": "Six official static Inter faces supplied by --font-dir",
                "files": evidence, "painted_faces": ["Regular", "SemiBold", "Bold"],
                "png": "Rasterized from the validated static Inter files",
                "svg": "Real text; visitor resolves local Inter or browser fallback",
                "font_binaries_distributed": False,
            },
        }
        (ROOT / MANIFEST).write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    check_outputs()
    print("Rendered both PR55 editions from retained data with validated Inter")


if __name__ == "__main__":
    main()
