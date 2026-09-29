"""Profile a bounded serial search without changing its work or random stream."""

from __future__ import annotations

import argparse
import cProfile
import dataclasses
import datetime as dt
import hashlib
import json
import os
import pickle
import platform
import pstats
import random
import subprocess
import sys
import sysconfig
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.mcts import MCTS  # noqa: E402
from game.content import SCENARIOS  # noqa: E402
from tools.run_parallel_scaling import digest, write_record  # noqa: E402

PROTOCOL = ROOT / "docs/serial-profile-protocol.json"


def validate_protocol(protocol):
    expected = {
        "schema_version": 1,
        "id": "serial-hotspot-profile-v1",
        "scenarios": ["duel", "gauntlet", "boss"],
        "environment_seed": 300,
        "search_seed": 42,
        "horizon_rounds": 5,
        "max_simulations": 3000,
        "max_transitions": 15000,
        "time_budget_ms": 60000,
        "priors": None,
        "design_size": {"conditions": 3, "executions": 6},
    }
    if any(type(protocol.get(k)) is not type(v) or protocol.get(k) != v
           for k, v in expected.items()):
        raise ValueError("Controls changed. Review a separate protocol and runner")


def source_identity():
    status = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    ).strip()
    if status:
        raise ValueError("Commit and review the implementation and protocol first")
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    paths = [PROTOCOL, Path(__file__), ROOT / "tools/run_parallel_scaling.py"]
    for directory, pattern in (("engine", "*.py"), ("game", "*.py"),
                               ("data", "*.json")):
        paths.extend(sorted((ROOT / directory).glob(pattern)))
    return {
        "revision": revision,
        "worktree_clean": True,
        "hash_method": "UTF-8 text normalized to LF without BOM",
        "sha256": {p.relative_to(ROOT).as_posix(): digest(p) for p in paths},
    }


def object_digest(value):
    return hashlib.sha256(pickle.dumps(value, protocol=5)).hexdigest()


def safe_filename(filename):
    """Retain useful source identity without exporting local account paths."""
    if filename in {"~", "<string>"} or filename.startswith("<"):
        return filename
    path = Path(filename).resolve()
    for base, label in ((ROOT, ""),
                        (Path(sysconfig.get_path("stdlib")), "python/")):
        try:
            return label + path.relative_to(base).as_posix()
        except ValueError:
            pass
    return "external/" + path.name


def profile_rows(profiler):
    stats = pstats.Stats(profiler)
    rows = []
    for (filename, line, name), (primitive, calls, own, cumulative, _) in (
        stats.stats.items()
    ):
        rows.append({
            "file": safe_filename(filename), "line": line, "function": name,
            "primitive_calls": primitive, "calls": calls,
            "self_s": own, "cumulative_s": cumulative,
        })
    return sorted(rows, key=lambda row: (-row["self_s"], row["file"],
                                         row["line"], row["function"]))


def execute(root, protocol, cell):
    engine = MCTS(
        horizon_rounds=protocol["horizon_rounds"],
        max_sims=protocol["max_simulations"],
        max_transitions=protocol["max_transitions"],
        rng=random.Random(protocol["search_seed"]),
    )
    before = object_digest(root)
    profiler = cProfile.Profile() if cell["mode"] == "profiled" else None
    start = time.perf_counter()
    try:
        if profiler:
            profiler.enable()
        ranked = engine.search(root, time_budget_ms=protocol["time_budget_ms"])
        if profiler:
            profiler.disable()
        cell["elapsed_s"] = time.perf_counter() - start
        cell["computation"] = {
            "simulations": engine.last_sims,
            "transitions": engine.last_transitions,
            "unused_transitions": engine.last_unused_transitions,
            "stop_reasons": list(engine.last_stop_reasons),
            "root_statistics": [
                {"action": dataclasses.asdict(a), "visits": n, "value_sum": v}
                for a, n, v in engine.last_root_statistics
            ],
            "ranked": [dataclasses.asdict(row) for row in ranked],
            "rng_sha256": object_digest(engine.rng.getstate()),
        }
        cell["root_unchanged"] = object_digest(root) == before
        if not cell["root_unchanged"]:
            raise RuntimeError("RootMutation")
        if engine.last_sims != protocol["max_simulations"]:
            raise RuntimeError("IncompleteFixedWork")
        cell["status"] = "completed"
    except BaseException as exc:
        cell["status"] = "failed" if isinstance(exc, Exception) else "interrupted"
        cell["error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        if profiler:
            profiler.disable()
        if cell.get("elapsed_s") is None:
            cell["elapsed_s"] = time.perf_counter() - start
        cell["observed_simulations"] = engine.last_sims
        cell["observed_transitions"] = engine.last_transitions
        cell["profile"] = profile_rows(profiler) if profiler else []


def run(path, conditions):
    if path.exists() or path.with_name(path.name + ".tmp").exists():
        raise ValueError("Refusing to replace a retained attempt or temporary file")
    if not conditions.strip():
        raise ValueError("Record the observed resource conditions")
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    validate_protocol(protocol)
    source = source_identity()
    record = {
        "schema_version": 1, "protocol": protocol["id"],
        "protocol_sha256": digest(PROTOCOL), "source": source,
        "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "environment": {"python": sys.version, "platform": platform.platform(),
                        "logical_cpus": os.cpu_count(), "conditions": conditions},
        "status": "running", "cells": [], "comparisons": [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, allow_nan=False)
        stream.write("\n")
    try:
        for scenario in protocol["scenarios"]:
            root, _ = SCENARIOS[scenario](random.Random(protocol["environment_seed"]))
            root.player.pips = 7
            group = []
            for mode in ("control", "profiled"):
                cell = {
                    "scenario": scenario, "mode": mode, "status": "running",
                    "root_sha256": object_digest(root), "error": None,
                    "elapsed_s": None,
                }
                record["cells"].append(cell)
                group.append(cell)
                write_record(path, record)
                execute(root, protocol, cell)
                write_record(path, record)
                print(scenario, mode, cell["status"], flush=True)
            matched = group[0]["computation"] == group[1]["computation"]
            record["comparisons"].append({"scenario": scenario, "matched": matched})
            if not matched:
                raise RuntimeError("Instrumentation changed computational receipt")
        record["status"] = "complete"
    except BaseException as exc:
        record["status"] = "failed" if isinstance(exc, Exception) else "interrupted"
        record["error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        try:
            record["source_unchanged_at_end"] = source_identity() == source
        except Exception as exc:
            record["source_unchanged_at_end"] = False
            record["source_verification_error"] = type(exc).__name__
        if not record["source_unchanged_at_end"]:
            record["status"] = "source_changed"
        record["ended_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        write_record(path, record)
    if not record["source_unchanged_at_end"]:
        raise RuntimeError("Source changed during collection")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--conditions", required=True)
    args = parser.parse_args()
    run(args.output, args.conditions)


if __name__ == "__main__":
    main()
