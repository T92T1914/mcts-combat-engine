"""Compare sequential and process execution of the same committed forests."""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import math
import os
import platform
import random
import subprocess
import sys
import time
from multiprocessing.reduction import ForkingPickler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.parallel import ParallelMCTS, ParallelSearchError  # noqa: E402
from game.content import SCENARIOS  # noqa: E402
from tools.render_parallel_scaling import computational  # noqa: E402
from tools.run_parallel_scaling import digest, write_record  # noqa: E402

PROTOCOL = ROOT / "docs/same-forest-protocol.json"
ORDERS = (
    ("sequential", "cold", "warm"),
    ("cold", "warm", "sequential"),
    ("warm", "sequential", "cold"),
    ("sequential", "warm", "cold"),
    ("warm", "cold", "sequential"),
    ("cold", "sequential", "warm"),
)


def validate_protocol(protocol):
    conditions = [
        {"scenario": scenario, "roots": roots, "order": list(order)}
        for (scenario, roots), order in zip(
            ((s, w) for s in ("duel", "gauntlet", "boss") for w in (2, 4)),
            ORDERS,
            strict=True,
        )
    ]
    if (
        protocol.get("id") != "same-forest-execution-v1"
        or protocol["schema_version"] != 1
        or protocol["conditions"] != conditions
        or protocol["environment_seed"] != 300
        or protocol["search_seed"] != 42
        or protocol["horizon_rounds"] != 5
        or protocol["max_simulations"] != 12000
        or protocol["max_transitions"] != 60000
        or protocol["priors"] is not None
        or protocol["worker_timeout_s"] != 60
        or protocol["design_size"]
        != {"conditions": 6, "executions": 18, "executions_per_phase": 6}
    ):
        raise ValueError("Controls changed. Review a separate protocol and runner")
    if (os.cpu_count() or 1) < 4:
        raise ValueError("The process control requires at least four logical CPUs")


def source_identity():
    status = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    ).strip()
    if status:
        raise ValueError("Commit and review the implementation and protocol first")
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    paths = [
        PROTOCOL,
        Path(__file__),
        ROOT / "tools/run_parallel_scaling.py",
        ROOT / "tools/render_parallel_scaling.py",
    ]
    for directory, pattern in (
        ("engine", "*.py"),
        ("game", "*.py"),
        ("data", "*.json"),
    ):
        paths.extend(sorted((ROOT / directory).glob(pattern)))
    return {
        "revision": revision,
        "worktree_clean": True,
        "hash_method": "UTF-8 text normalized to LF without BOM",
        "sha256": {p.relative_to(ROOT).as_posix(): digest(p) for p in paths},
    }


def differing_paths(left, right, path="identity"):
    """Keep exact semantic mismatches, including numeric type changes."""
    if type(left) is not type(right):
        return [path]
    if isinstance(left, dict):
        differences = []
        for key in sorted(set(left) | set(right)):
            nested = f"{path}.{key}"
            if key not in left or key not in right:
                differences.append(nested)
            else:
                differences.extend(differing_paths(left[key], right[key], nested))
        return differences
    if isinstance(left, (list, tuple)):
        if len(left) != len(right):
            return [path + ".length"]
        return [
            p
            for i, (a, b) in enumerate(zip(left, right, strict=True))
            for p in differing_paths(a, b, f"{path}[{i}]")
        ]
    return [] if left == right else [path]


def compare_condition(cells):
    """Compare every worker and merged result, excluding only recorded timing."""
    by_phase = {cell["phase"]: cell for cell in cells}
    if (
        len(cells) != 3
        or set(by_phase) != {"sequential", "cold", "warm"}
        or any(
            c["status"] != "completed"
            or c["error"] is not None
            or not c["report"]["complete"]
            for c in cells
        )
    ):
        raise ValueError("Three complete executions are required for comparison")
    if any(
        type(c["elapsed_s"]) not in (int, float)
        or not math.isfinite(c["elapsed_s"])
        or c["elapsed_s"] <= 0
        for c in cells
    ):
        raise ValueError("Positive finite wall times are required for comparison")

    def identity(cell):
        return {
            "computation": computational(cell),
            **{
                key: cell[key]
                for key in (
                    "scenario",
                    "roots",
                    "search_seed",
                    "environment_seed",
                    "root_pickle_sha256",
                )
            },
        }

    reference = identity(by_phase["sequential"])
    differences = {
        phase: differing_paths(reference, identity(by_phase[phase]))
        for phase in ("cold", "warm")
    }
    matched = not any(differences.values())
    ratios = None
    if matched:
        ratios = {
            phase: by_phase["sequential"]["elapsed_s"] / by_phase[phase]["elapsed_s"]
            for phase in ("cold", "warm")
        }
    return {
        "scenario": cells[0]["scenario"],
        "roots": cells[0]["roots"],
        "matched": matched,
        "differing_paths": differences,
        "sequential_wall_ratio": ratios,
    }


def root_digest(root):
    return hashlib.sha256(ForkingPickler.dumps(root)).hexdigest()


def execute(root, protocol, cell):
    """One execution, with owned pool cleanup even on caller interruption."""
    engine = None
    start = None
    phase = cell["phase"]
    try:
        preparation_start = time.perf_counter()
        if phase != "warm":
            start = preparation_start
        engine = ParallelMCTS(protocol["horizon_rounds"], workers=cell["roots"])
        if phase == "warm":
            ready = engine.warmup()
            cell["prepared_pool_startup_s"] = engine.last_pool_startup_s
            cell["preparation_s"] = time.perf_counter() - preparation_start
            if not ready:
                cell["error"] = "WarmupFailed"
                cell["status"] = "failed"
                return
            start = time.perf_counter()
        ranked = engine.search(
            root,
            mode="fixed",
            seed=protocol["search_seed"],
            max_sims=protocol["max_simulations"],
            max_transitions=protocol["max_transitions"],
            priors=protocol["priors"],
            worker_timeout_s=protocol["worker_timeout_s"],
            execution="sequential" if phase == "sequential" else "process",
        )
        cell["elapsed_s"] = time.perf_counter() - start
        cell["ranked"] = [dataclasses.asdict(row) for row in ranked]
        if (
            engine.last_report is None
            or not engine.last_report.complete
            or engine.last_report.simulations != protocol["max_simulations"]
        ):
            raise RuntimeError("Missing or incomplete fixed work report")
        if root_digest(root) != cell["root_pickle_sha256"]:
            cell["error"] = "RootMutation"
            cell["status"] = "failed"
        else:
            cell["status"] = "completed"
    except Exception as exc:
        cell["status"] = "failed"
        cell["error"] = type(exc).__name__
        if isinstance(exc, ParallelSearchError):
            cell["report"] = dataclasses.asdict(exc.report)
    except BaseException as exc:
        cell["status"] = "interrupted"
        cell["error"] = type(exc).__name__
        raise
    finally:
        if phase == "warm" and start is None:
            cell["preparation_s"] = time.perf_counter() - preparation_start
        if start is not None and cell["elapsed_s"] is None:
            cell["elapsed_s"] = time.perf_counter() - start
        if engine is not None:
            if engine.last_report is not None:
                cell["report"] = dataclasses.asdict(engine.last_report)
            engine.close()


def new_cell(condition, phase, protocol, root):
    return {
        "scenario": condition["scenario"],
        "roots": condition["roots"],
        "phase": phase,
        "search_seed": protocol["search_seed"],
        "environment_seed": protocol["environment_seed"],
        "root_pickle_sha256": root_digest(root),
        "status": "running",
        "error": None,
        "report": None,
        "ranked": [],
        "elapsed_s": None,
        "preparation_s": 0.0,
        "prepared_pool_startup_s": 0.0,
    }


def run(path, conditions):
    if path.exists() or path.with_name(path.name + ".tmp").exists():
        raise ValueError("Refusing to replace a retained attempt or interrupted write")
    if not conditions.strip():
        raise ValueError("Record the observed resource conditions")
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    validate_protocol(protocol)
    source = source_identity()
    record = {
        "schema_version": 1,
        "protocol": protocol["id"],
        "protocol_sha256": digest(PROTOCOL),
        "source": source,
        "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "logical_cpus": os.cpu_count(),
            "start_method": "spawn",
            "conditions": conditions,
        },
        "status": "running",
        "cells": [],
        "comparisons": [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents a concurrently created attempt being replaced.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, allow_nan=False)
        stream.write("\n")
    try:
        for condition in protocol["conditions"]:
            root, _ = SCENARIOS[condition["scenario"]](
                random.Random(protocol["environment_seed"])
            )
            root.player.pips = 7
            group = []
            for phase in condition["order"]:
                cell = new_cell(condition, phase, protocol, root)
                group.append(cell)
                record["cells"].append(cell)
                write_record(path, record)
                execute(root, protocol, cell)
                write_record(path, record)
                print(
                    condition["scenario"],
                    condition["roots"],
                    phase,
                    cell["status"],
                    cell["elapsed_s"],
                    flush=True,
                )
                if cell["status"] != "completed":
                    break
            if len(group) != 3 or any(c["status"] != "completed" for c in group):
                record["status"] = "incomplete"
                break
            comparison = compare_condition(group)
            record["comparisons"].append(comparison)
            write_record(path, record)
            if not comparison["matched"]:
                record["status"] = "mismatch"
                break
        else:
            record["status"] = "complete"
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        unchanged = revision == source["revision"] and all(
            digest(ROOT / name) == expected
            for name, expected in source["sha256"].items()
        )
        record["source_unchanged_at_end"] = unchanged
        if not unchanged:
            raise RuntimeError("Source changed during collection")
    except BaseException as exc:
        record["status"] = "interrupted"
        record["interruption"] = type(exc).__name__
        raise
    finally:
        record["ended_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        write_record(path, record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--conditions",
        required=True,
        help="Observed resource conditions, without personal data",
    )
    args = parser.parse_args()
    record = run(args.output, args.conditions)
    if record["status"] != "complete":
        raise SystemExit("Execution control retained with incomplete or unequal work")


if __name__ == "__main__":
    main()
