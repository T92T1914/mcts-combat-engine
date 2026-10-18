"""Build a public site from an explicit list of public example files."""

import hashlib
import json
import shutil
import sys
from pathlib import Path

try:
    from .build_episode_companion import OUTPUT_NAMES as COMPANION_OUTPUT_NAMES
    from .build_episode_companion import build as build_episode_companion
    from .build_episode_examples import OUTPUT_NAMES
    from .build_episode_examples import _git as source_git
    from .build_episode_examples import build as build_episode_examples
    from .presentation import appearance_css, load_tokens
    from .render_decision_figure import check_outputs
    from .render_same_forest import check_outputs as check_execution_report
except ImportError:
    from build_episode_companion import OUTPUT_NAMES as COMPANION_OUTPUT_NAMES
    from build_episode_companion import build as build_episode_companion
    from build_episode_examples import OUTPUT_NAMES
    from build_episode_examples import _git as source_git
    from build_episode_examples import build as build_episode_examples
    from render_decision_figure import check_outputs
    from render_same_forest import check_outputs as check_execution_report

    from presentation import appearance_css, load_tokens

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "_site"
FILES = {
    "site/share-preview.png": "share-preview.png",
    "docs/mcts-decision-clair-wide.png": "decision-clair-wide.png",
    "docs/mcts-decision-clair-wide.svg": "decision-clair-wide.svg",
    "docs/mcts-decision-obscur-wide.png": "decision-obscur-wide.png",
    "docs/mcts-decision-obscur-wide.svg": "decision-obscur-wide.svg",
    "site/index.html": "index.html",
    "site/style.css": "style.css",
    "site/appearance.js": "appearance.js",
    "site/app.js": "app.js",
    "site/selection-state.mjs": "selection-state.mjs",
    "docs/visual-example-data.json": "data.json",
    "docs/mcts-decision-example.svg": "example.svg",
    "docs/mcts-decision-clair.png": "decision-clair.png",
    "docs/mcts-decision-obscur.png": "decision-obscur.png",
    "docs/mcts-decision-clair.svg": "decision-clair.svg",
    "docs/mcts-decision-obscur.svg": "decision-obscur.svg",
    "docs/mcts-decision-figure.json": "decision-figure.json",
    "site/parallel-scaling.html": "parallel-scaling.html",
    "docs/parallel-scaling-results.json": "parallel-scaling-results.json",
    "docs/parallel-scaling-protocol.json": "parallel-scaling-protocol.json",
    "docs/parallel-scaling-results.md": "parallel-scaling-results.md",
    "site/same-forest.html": "same-forest.html",
    "docs/same-forest-results.json": "same-forest-results.json",
    "docs/same-forest-protocol.json": "same-forest-protocol.json",
    "docs/same-forest-results.md": "same-forest-results.md",
    "site/same-forest-repeatability.html": "same-forest-repeatability.html",
    "docs/episode-companion.md": "episode-companion.md",
    "docs/managed-encounters.md": "managed-encounters.md",
    "docs/model-compatibility.md": "model-compatibility.md",
    "docs/bounded-assurance.md": "bounded-assurance.md",
    "docs/linux-managed-episode.md": "linux-managed-episode.md",
    "docs/episode-record-replay.md": "episode-record-replay.md",
    "docs/episode-inspection.md": "episode-inspection.md",
    "docs/episode-decision.md": "episode-decision.md",
    "docs/episode-stability.md": "episode-stability.md",
    "docs/episode-reference.md": "episode-reference.md",
    "docs/episode-adaptive-reference.md": "episode-adaptive-reference.md",
    "docs/two-round-horizon.md": "two-round-horizon.md",
    **{"docs/two-round-horizon/" + name + ".json":
       "two-round-horizon/" + name + ".json"
       for name in ("protocol", "inputs", "seeds", "exploratory", "deciding")},
    "examples/adaptive-state.json": "adaptive-state.json",
    "docs/episode-search-allowance.md": "episode-search-allowance.md",
    "docs/request-edge-reuse.md": "request-edge-reuse.md",
    "docs/root-allocation.md": "root-allocation.md",
    **{"docs/root-allocation/" + name: "root-allocation/" + name
       for name in ("results.json", "inputs.json", "protocol.json",
                    "candidate-contract.json")},
    "docs/request-edge-reuse/protocol.json": "request-edge-reuse/protocol.json",
    "docs/request-edge-reuse/results.json": "request-edge-reuse/results.json",
    "docs/request-edge-reuse-figure.json": "request-edge-reuse-figure.json",
    **{
        f"docs/request-edge-reuse-{mode}.{extension}":
        f"request-edge-reuse-{mode}.{extension}"
        for mode in ("clair", "obscur") for extension in ("png", "svg")
    },
    **{
        "docs/search-allowance/" + name: "search-allowance/" + name
        for name in (
            "cards.json", "scenarios.json", "protocol.json", "results.json",
            *(f"{case}.{kind}.json"
              for case in ("E1", "E2", "D1", "D2", "D3", "D4")
              for kind in ("episode", "replay")),
            *(f"{case}.seed-{301 if case.startswith('E') else 2001}."
              f"sims-{sims}.{kind}.json"
              for case in ("E1", "E2", "D1", "D2", "D3", "D4")
              for sims in (8, 64) for kind in ("decision", "reference")),
        )
    },
    **{
        "docs/" + name: name
        for name in (
            "same-forest-repeatability-public-receipts.json",
            "same-forest-repeatability-public-failed-attempt.json",
            "same-forest-repeatability-public-fields.json",
            "same-forest-repeatability-protocol.json",
            "same-forest-repeatability-provenance.json",
            "same-forest-repeatability-results.md",
            "same-forest-repeatability-figure.json",
            *(f"same-forest-repeatability-{metric}-{mode}.{extension}"
              for metric in ("search", "complete") for mode in ("clair", "obscur")
              for extension in ("png", "svg")),
        )
    },
}
GENERATED = ({"appearance.css", "presentation.json"} | OUTPUT_NAMES |
             COMPANION_OUTPUT_NAMES)


def provenance(data):
    """Rendering a saved decision does not collect another experiment."""
    revision = source_git(ROOT, "rev-parse", "HEAD").decode("ascii").strip()
    dirty = bool(source_git(ROOT, "status", "--porcelain").strip())
    return {
        "schema_version": 1,
        "presentation_revision": revision,
        "presentation_worktree_dirty": dirty,
        "recorded_source_revision": data["source_commit"],
        "parallel_study_source_revision": json.loads(
            (ROOT / "docs/parallel-scaling-results.json").read_text()
        )["source"]["revision"],
        "evaluation_rerun": False,
        "same_forest_source_revision": json.loads(
            (ROOT / "docs/same-forest-results.json").read_text()
        )["source"]["revision"],
        "same_forest_repeatability_source_revision": json.loads(
            (ROOT / "docs/same-forest-repeatability-public-receipts.json").read_text()
        )["source"]["revision"],
        "tokens": load_tokens()["source"],
        "files": {
            target: hashlib.sha256((OUT / target).read_bytes()).hexdigest()
            for target in sorted(set(FILES.values()) | {"appearance.css"} |
                                 OUTPUT_NAMES | COMPANION_OUTPUT_NAMES)
        },
    }


def main():
    from tools.render_evidence_figure import check_outputs as check_evidence_figure
    from tools.render_same_forest_repeatability_figure import (
        check_outputs as check_repeatability_figure,
    )
    from tools.render_share_preview import check as check_share_preview

    check_share_preview()
    data = json.loads((ROOT / "docs/visual-example-data.json").read_text())
    if not data.get("source_commit"):
        raise ValueError("Example data must retain its source revision.")
    check_outputs()
    check_execution_report()
    check_repeatability_figure()
    check_evidence_figure()
    if OUT.is_symlink():
        raise ValueError("Site output directory must not be a symlink.")
    OUT.mkdir(exist_ok=True)
    expected_files = set(FILES.values()) | GENERATED
    expected_directories = {
        parent.as_posix()
        for name in expected_files for parent in Path(name).parents
        if parent != Path(".")
    }
    unexpected = {
        path.relative_to(OUT).as_posix()
        for path in OUT.rglob("*")
        if path.is_symlink() or not (
            path.is_file() and path.relative_to(OUT).as_posix() in expected_files
            or path.is_dir()
            and path.relative_to(OUT).as_posix() in expected_directories
        )
    }
    if unexpected:
        raise ValueError("Unexpected site output files: " + str(sorted(unexpected)))
    for source, target in FILES.items():
        path = ROOT / source
        if not path.is_file() or path.is_symlink():
            raise ValueError("Expected a regular source file: " + source)
        destination = OUT / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    (OUT / "appearance.css").write_text(appearance_css(load_tokens()), encoding="utf-8")
    build_episode_examples(ROOT, output_directory=OUT)
    build_episode_companion(ROOT, output_directory=OUT)
    (OUT / "presentation.json").write_text(
        json.dumps(provenance(data), indent=2) + "\n", encoding="utf-8"
    )
    print("Built", len(FILES) + len(GENERATED), "public files in", OUT)


if __name__ == "__main__":
    main()
