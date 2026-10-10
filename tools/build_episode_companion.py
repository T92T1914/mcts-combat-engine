"""Package the complete consumer examples separately from the installed engine."""
from __future__ import annotations

import sys
import tomllib
import zipfile
from pathlib import Path

try:
    from . import build_episode_examples as kit
except ImportError:
    import build_episode_examples as kit

ROOT = kit.ROOT
ZIP_NAME = "episode-companion.zip"
SIDECAR_NAME = ZIP_NAME + ".sha256"
OUTPUT_NAMES = {ZIP_NAME, SIDECAR_NAME}
GUIDE = "docs/episode-companion.md"
FIXED_PAYLOAD = kit.FIXED_PAYLOAD | {
    "episode.py", "demo.py", "data/cards.json", "data/scenarios.json",
    "docs/episode-record-replay.md", GUIDE, "docs/episode-stability.md",
    "docs/stability/protocol.json", "docs/stability/exploratory-receipt.json",
    "docs/stability/confirmatory-receipt.json",
    *{"docs/stability/" + name + ".json" for name in (
        "exploratory-duel", "exploratory-gauntlet", "exploratory-boss",
        "confirmatory-duel", "confirmatory-gauntlet", "confirmatory-boss")},
}


def prepare(root: Path) -> tuple[bytes, bytes, dict]:
    """Reuse bounded literal-source capture and deterministic archive construction."""
    try:
        source = kit._source(root, fixed_payload=FIXED_PAYLOAD)
        payload = {name: source.blobs[name] for name in source.payload}
        # The reader builder already checks the reference package and engine.
        # Its guide derivation is deliberately not used in this complete layout.
        reference = kit._emitted(source)[1]["reference_engine"]
        manifest = {
            "format": "mcts-recording-companion", "schema_version": 1,
            "source_commit": source.commit, "source_tree": source.tree,
            "payload_files": {name: kit.identity(body)
                              for name, body in payload.items()},
            "reference_engine": reference,
            "derived_documents": {},
        }
        archive = kit._archive(payload, manifest)
        sidecar = (kit.digest(archive) + "  " + ZIP_NAME + "\n").encode("ascii")
        kit._reobserve(source)
        return archive, sidecar, manifest
    except (OSError, UnicodeError, KeyError, tomllib.TOMLDecodeError) as error:
        raise kit.KitError("companion source could not be captured: " +
                           str(error)) from error


def build(root: Path = ROOT, *, output_directory: Path | None = None) -> dict:
    """Write the separately named archive and sidecar after complete capture."""
    archive, sidecar, manifest = prepare(root)
    try:
        output = kit._output_directory(root, output_directory,
                                       output_names=OUTPUT_NAMES)
        for name, data in ((ZIP_NAME, archive), (SIDECAR_NAME, sidecar)):
            with (output / name).open("wb") as stream:
                kit.require(stream.write(data) == len(data),
                            "incomplete companion output: " + name)
        return {"manifest": manifest, "files": {
            ZIP_NAME: kit.identity(archive), SIDECAR_NAME: kit.identity(sidecar)}}
    except OSError as error:
        raise kit.KitError("companion output write failed: " + str(error)) from error


def main() -> int:
    try:
        build()
    except (kit.KitError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        print("Episode companion: " + str(error), file=sys.stderr)
        return 1
    print("Built " + ZIP_NAME + " and " + SIDECAR_NAME)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
