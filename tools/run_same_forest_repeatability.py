"""Collect the declared repeated-process supplement without changing search."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import run_same_forest as original  # noqa: E402
from tools.render_same_forest import validate_receipt  # noqa: E402
from tools.run_parallel_scaling import digest, write_record  # noqa: E402

PROTOCOL = ROOT / "docs/same-forest-repeatability-protocol.json"
CONDITIONS = [(s, n) for s in ("duel", "gauntlet", "boss") for n in (2, 4)]


def validate_protocol(protocol):
    """This runner implements one reviewed design, not an adaptive search."""
    expected = {
        "schema_version": 1,
        "id": "same-forest-repeatability-v1",
        "base_revision": "344947cf8aaff3ed6980702e4d0a98aba76e4a1b",
        "conditions": [{"scenario": s, "roots": n} for s, n in CONDITIONS],
        "fresh_process_blocks": 6,
        "iterations_per_condition_per_block": 2,
        "environment_seed": 300,
        "search_seed": 42,
        "horizon_rounds": 5,
        "max_simulations": 12000,
        "max_transitions": 60000,
        "priors": None,
        "worker_timeout_s": 60,
        "design_size": {"triplets": 72, "executions": 216,
                        "executions_per_phase": 72},
        "stopping": {"rule": "maximum-cost", "max_collection_wall_s": 300,
                     "admission_reserve_s": 70, "planned_blocks": 6,
                     "retry_failed_or_partial_block": False},
    }
    for key, value in expected.items():
        if key not in protocol or original.differing_paths(protocol[key], value):
            raise ValueError(f"Declared repeatability control changed: {key}")


def schedule(block):
    if type(block) is not int or not 0 <= block < 6:
        raise ValueError("Block index must be an integer from 0 through 5")
    rows = []
    for iteration in range(2):
        shift = (block + iteration) % 6
        for c in list(range(6))[shift:] + list(range(6))[:shift]:
            scenario, roots = CONDITIONS[c]
            rows.append({"iteration": iteration, "scenario": scenario,
                         "roots": roots,
                         "order": list(original.ORDERS[(block + iteration + c) % 6])})
    return rows


def source_identity():
    result = original.source_identity()
    paths = [PROTOCOL, Path(__file__), ROOT / "tools/render_same_forest.py",
             ROOT / "tools/render_same_forest_repeatability.py"]
    result["sha256"].update({p.relative_to(ROOT).as_posix(): digest(p) for p in paths})
    result["retained_first_attempt_sha256"] = hashlib.sha256(
        (ROOT / "docs/same-forest-results.json").read_bytes()
    ).hexdigest()
    return result


def verify_source(source):
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    return revision == source["revision"] and all(
        digest(ROOT / name) == value for name, value in source["sha256"].items()
    )


def environment(conditions):
    return {"python": sys.version, "platform": platform.platform(),
            "interpreter_sha256": hashlib.sha256(Path(sys.executable).read_bytes())
            .hexdigest(), "logical_cpus": os.cpu_count(), "start_method": "spawn",
            "conditions": conditions}


def collect_block(path, block, deadline):
    """One fresh controller, with nested repetitions and persistent partial cells."""
    import random

    from game.content import SCENARIOS

    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    validate_protocol(protocol)
    planned = schedule(block)
    source = source_identity()
    record = {"schema_version": 1, "protocol": protocol["id"],
              "protocol_sha256": digest(PROTOCOL), "source": source,
              "block": block, "schedule": planned, "pid": os.getpid(),
              "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "status": "running", "cells": [], "comparisons": []}
    with path.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, allow_nan=False)
        stream.write("\n")
    try:
        for condition in record["schedule"]:
            root, _ = SCENARIOS[condition["scenario"]](
                random.Random(protocol["environment_seed"])
            )
            root.player.pips = 7
            group = []
            for phase in condition["order"]:
                if deadline - time.monotonic() < 70:
                    record["status"] = "maximum-cost"
                    return record
                cell = original.new_cell(condition, phase, protocol, root)
                cell.update(block=block, iteration=condition["iteration"],
                            complete_call_s=None)
                group.append(cell)
                record["cells"].append(cell)
                write_record(path, record)
                start = time.perf_counter()
                try:
                    original.execute(root, protocol, cell)
                finally:
                    cell["complete_call_s"] = time.perf_counter() - start
                    write_record(path, record)
                print(block, condition["iteration"], condition["scenario"],
                      condition["roots"], phase, cell["status"], flush=True)
                if cell["status"] != "completed":
                    record["status"] = "incomplete"
                    return record
                # The unchanged producer retains dataclass tuple fields in memory.
                # Validate the JSON representation used by retained receipt files.
                validate_receipt(json.loads(json.dumps(cell, allow_nan=False)))
            comparison = original.compare_condition(group)
            comparison.update(block=block, iteration=condition["iteration"])
            record["comparisons"].append(comparison)
            if not comparison["matched"]:
                record["status"] = "mismatch"
                return record
        record["status"] = "complete"
    except BaseException as exc:
        record["status"] = "interrupted"
        record["interruption"] = type(exc).__name__
        raise
    finally:
        record["source_unchanged_at_end"] = verify_source(source)
        record["ended_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        write_record(path, record)
    return record


def run(directory, conditions, process_tree_bound):
    """No retry, overwrite or independent-call pseudo replication."""
    if not conditions.strip() or not process_tree_bound.strip():
        raise ValueError("Record conditions and the external process-tree bound")
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    validate_protocol(protocol)
    if (os.cpu_count() or 1) < 4:
        raise ValueError("At least four logical CPUs required for this control")
    source = source_identity()
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "attempt.json"
    started = time.monotonic()
    record = {"schema_version": 1, "protocol": protocol["id"],
              "protocol_sha256": digest(PROTOCOL), "source": source,
              "environment": environment(conditions),
              "process_tree_bound": process_tree_bound,
              "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "status": "running", "blocks": []}
    write_record(path, record)
    try:
        for block in range(6):
            if time.monotonic() - started > 230:
                record["status"] = "maximum-cost"
                break
            output = directory / f"block-{block}.json"
            log = directory / f"block-{block}.log"
            item = {"block": block, "status": "running", "returncode": None,
                    "controller_wall_s": None, "record": None}
            record["blocks"].append(item)
            write_record(path, record)
            command = [sys.executable, str(Path(__file__).resolve()),
                       "--block-output", str(output), "--block-index", str(block),
                       "--deadline", str(started + 300)]
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            start = time.perf_counter()
            # The required outer job owns timeout/descendant retirement. Killing
            # only this controller on a timeout could leave search workers alive.
            with log.open("xb") as stream:
                completed = subprocess.run(command, cwd=ROOT, stdout=stream,
                                           stderr=subprocess.STDOUT,
                                           creationflags=flags, check=False)
            item["controller_wall_s"] = time.perf_counter() - start
            item["returncode"] = completed.returncode
            item["log_sha256"] = hashlib.sha256(log.read_bytes()).hexdigest()
            if output.exists():
                item["record"] = json.loads(output.read_text(encoding="utf-8"))
                item["record_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
            item["status"] = "complete" if (
                completed.returncode == 0 and item["record"] is not None
                and item["record"]["status"] == "complete"
                and item["record"]["source_unchanged_at_end"] is True
                and item["record"]["source"] == source
            ) else "incomplete"
            write_record(path, record)
            print("Block", block, item["status"], flush=True)
            if item["status"] != "complete":
                record["status"] = "incomplete"
                break
        else:
            record["status"] = "complete"
    except BaseException as exc:
        record["status"] = "interrupted"
        record["interruption"] = type(exc).__name__
        raise
    finally:
        record["source_unchanged_at_end"] = verify_source(source)
        record["collection_wall_s"] = time.monotonic() - started
        record["ended_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        write_record(path, record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--conditions")
    parser.add_argument("--process-tree-bound")
    parser.add_argument("--block-output", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--block-index", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--deadline", type=float, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.block_output is not None:
        if args.block_index is None or args.deadline is None:
            parser.error("Internal block requires index and deadline")
        result = collect_block(args.block_output, args.block_index, args.deadline)
    else:
        if (args.output is None or args.conditions is None
                or args.process_tree_bound is None):
            parser.error("Require output, conditions and process-tree-bound")
        result = run(args.output, args.conditions, args.process_tree_bound)
    if result["status"] != "complete" or result["source_unchanged_at_end"] is not True:
        raise SystemExit("Attempt retained without complete stable-source evidence")


if __name__ == "__main__":
    main()
