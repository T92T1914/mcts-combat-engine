"""Build a public site from an explicit list of public example files."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

try:
    from .presentation import appearance_css, load_tokens
except ImportError:
    from presentation import appearance_css, load_tokens

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "_site"
FILES = {
    "site/index.html": "index.html",
    "site/style.css": "style.css",
    "site/appearance.js": "appearance.js",
    "site/app.js": "app.js",
    "site/selection-state.mjs": "selection-state.mjs",
    "docs/visual-example-data.json": "data.json",
    "docs/mcts-decision-example.svg": "example.svg",
    "site/parallel-scaling.html": "parallel-scaling.html",
    "docs/parallel-scaling-results.json": "parallel-scaling-results.json",
    "docs/parallel-scaling-protocol.json": "parallel-scaling-protocol.json",
    "docs/parallel-scaling-results.md": "parallel-scaling-results.md",
}
GENERATED = {"appearance.css", "presentation.json"}


def provenance(data):
    """Rendering a saved decision does not collect another experiment."""
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        ).strip()
    )
    return {
        "schema_version": 1,
        "presentation_revision": revision,
        "presentation_worktree_dirty": dirty,
        "recorded_source_revision": data["source_commit"],
        "parallel_study_source_revision": json.loads(
            (ROOT / "docs/parallel-scaling-results.json").read_text()
        )["source"]["revision"],
        "evaluation_rerun": False,
        "tokens": load_tokens()["source"],
        "files": {
            target: hashlib.sha256((OUT / target).read_bytes()).hexdigest()
            for target in sorted(set(FILES.values()) | {"appearance.css"})
        },
    }


def main():
    data = json.loads((ROOT / "docs/visual-example-data.json").read_text())
    if not data.get("source_commit"):
        raise ValueError("Example data must retain its source revision.")
    OUT.mkdir(exist_ok=True)
    unexpected = {p.name for p in OUT.iterdir()} - set(FILES.values()) - GENERATED
    if unexpected:
        raise ValueError("Unexpected site output files: " + str(sorted(unexpected)))
    for source, target in FILES.items():
        path = ROOT / source
        if not path.is_file() or path.is_symlink():
            raise ValueError("Expected a regular source file: " + source)
        shutil.copyfile(path, OUT / target)
    (OUT / "appearance.css").write_text(appearance_css(load_tokens()), encoding="utf-8")
    (OUT / "presentation.json").write_text(
        json.dumps(provenance(data), indent=2) + "\n", encoding="utf-8"
    )
    print("Built", len(FILES) + len(GENERATED), "public files in", OUT)


if __name__ == "__main__":
    main()
