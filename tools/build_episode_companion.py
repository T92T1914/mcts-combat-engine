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
    "benchmark.py", "tools/encounter_policy_evaluation.py",
    "managed_encounters.py", "recover_encounters.py",
    "tools/managed_encounter.py", "tools/encounter_process.py",
    "tools/encounter_recovery.py", "docs/managed-encounters.md",
    "docs/encounter-policy-evaluation.md",
    "docs/encounter-outcomes.md",
    *{"docs/encounter-study/" + name for name in (
        "protocol.json", "analysis.json", "method-contract.md",
        "paired-outcomes.csv", "manifest.json",
    )},
    "episode.py", "demo.py", "data/cards.json", "data/scenarios.json",
    "docs/episode-record-replay.md", GUIDE, "docs/episode-stability.md",
    "docs/model-compatibility.md",
    "docs/bounded-assurance.md",
    "linux_episode.py", "recover_linux.py", "tools/linux_episode.py",
    "tools/linux_recovery.py", "tools/linux_container.py",
    "tools/linux_episode_worker.py", "tools/linux_enforcement_preflight.py",
    "tools/linux_ownership_probe.py", "docs/linux-managed-episode.md",
    "reference_episode.py", "docs/episode-reference.md",
    "docs/episode-adaptive-reference.md", "examples/adaptive-state.json",
    "reference/__init__.py", "reference/consumer.py", "reference/one_round.py",
    "reference/report.py", "reference/aggregation.py",
    "reference/aggregation_domain.py", "reference/adaptive.py",
    "reference/adaptive_report.py",
    "docs/stability/protocol.json", "docs/stability/exploratory-receipt.json",
    "docs/stability/confirmatory-receipt.json",
    *{"docs/stability/" + name + ".json" for name in (
        "exploratory-duel", "exploratory-gauntlet", "exploratory-boss",
        "confirmatory-duel", "confirmatory-gauntlet", "confirmatory-boss")},
    "docs/episode-search-allowance.md",
    "docs/request-edge-reuse.md", "docs/request-edge-reuse/protocol.json",
    "docs/request-edge-reuse/results.json",
    "docs/root-allocation.md", "docs/root-allocation/results.json",
    "docs/root-allocation/inputs.json", "docs/root-allocation/protocol.json",
    "docs/root-allocation/candidate-contract.json",
    *{"docs/search-allowance/" + name for name in (
        "cards.json", "scenarios.json", "protocol.json", "results.json",
        *(f"{case}.{kind}.json"
          for case in ("E1", "E2", "D1", "D2", "D3", "D4")
          for kind in ("episode", "replay")),
        *(f"{case}.seed-{301 if case.startswith('E') else 2001}."
          f"sims-{sims}.{kind}.json"
          for case in ("E1", "E2", "D1", "D2", "D3", "D4")
          for sims in (8, 64) for kind in ("decision", "reference")),
    )},
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
