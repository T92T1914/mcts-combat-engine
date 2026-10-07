"""Execute the committed, bounded fixed state process scaling protocol."""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import os
import pickle
import platform
import random
import subprocess
import sys
import time
from multiprocessing.reduction import ForkingPickler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.parallel import (  # noqa: E402
    ParallelMCTS,
    ParallelSearchError,
    WorkerJob,
    allocate,
    worker_seed,
)
from game.content import SCENARIOS  # noqa: E402

PROTOCOL = ROOT / "docs/parallel-scaling-protocol.json"


def digest(path):
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_identity():
    status = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
    if status:
        raise ValueError("Commit and review the implementation and protocol first")
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    paths = [PROTOCOL, Path(__file__)]
    for directory, pattern in (("engine", "*.py"), ("game", "*.py"),
                               ("data", "*.json")):
        paths.extend(sorted((ROOT / directory).glob(pattern)))
    return {"revision": revision, "worktree_clean": True,
            "hash_method": "UTF-8 text normalized to LF without BOM",
            "sha256": {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}}


def validate_protocol(protocol):
    if protocol.get("id") != "parallel-fixed-work-scaling-v1":
        raise ValueError("Use the committed parallel fixed work protocol")
    counts = protocol["worker_orders"]
    if (counts != [[1, 2, 4], [2, 4, 1], [4, 1, 2]]
            or protocol["search_seeds"] != [7, 42, 99]
            or protocol["pool_phases"] != ["cold", "warm"]
            or protocol["scenarios"] != ["duel", "gauntlet", "boss"]
            or protocol["max_simulations"] != 12000
            or protocol["max_transitions"] != 60000
            or protocol["environment_seed"] != 300
            or protocol["horizon_rounds"] != 5
            or protocol["worker_timeout_s"] != 60
            or protocol["priors"] is not None):
        raise ValueError("Protocol controls changed. Review a new protocol and runner")
    if (os.cpu_count() or 1) < 4:
        raise ValueError("This protocol requires at least four logical CPUs")


def serialization_probe(root, protocol, workers, seed):
    sims = allocate(protocol["max_simulations"], workers)
    transitions = allocate(protocol["max_transitions"], workers)
    jobs = [WorkerJob(i, root, protocol["horizon_rounds"], worker_seed(seed, i),
                      sims[i], transitions[i], None) for i in range(workers)]
    start = time.perf_counter()
    payloads = [ForkingPickler.dumps(job) for job in jobs]
    encode = time.perf_counter() - start
    start = time.perf_counter()
    for payload in payloads:
        pickle.loads(payload)
    decode = time.perf_counter() - start
    return {"payload_bytes": sum(map(len, payloads)),
            "encode_s": encode, "decode_s": decode,
            "scope": "in-process payload control, not actual IPC latency"}


def write_record(path, record):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(record, indent=2, allow_nan=False) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def run(path, conditions):
    """Preserve a primary failure if owned cleanup also fails; retry no search."""
    if path.exists() or path.with_name(path.name + ".tmp").exists():
        raise ValueError("Refusing to replace a retained study or interrupted write")
    protocol = json.loads(PROTOCOL.read_text())
    validate_protocol(protocol)
    identity = source_identity()
    record = {
        "schema_version": 1, "protocol": protocol["id"],
        "protocol_sha256": digest(PROTOCOL), "source": identity,
        "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "environment": {"python": sys.version, "platform": platform.platform(),
                        "logical_cpus": os.cpu_count(), "start_method": "spawn",
                        "conditions": conditions},
        "status": "running", "cells": [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    write_record(path, record)
    try:
        for scenario in protocol["scenarios"]:
            root, _ = SCENARIOS[scenario](random.Random(protocol["environment_seed"]))
            root.player.pips = 7
            root_id = hashlib.sha256(ForkingPickler.dumps(root)).hexdigest()
            for index, seed in enumerate(protocol["search_seeds"]):
                for workers in protocol["worker_orders"][index]:
                    engine = None
                    failure = None
                    try:
                        for phase in protocol["pool_phases"]:
                            probe = serialization_probe(root, protocol, workers, seed)
                            start = time.perf_counter()
                            if engine is None:
                                engine = ParallelMCTS(
                                    protocol["horizon_rounds"], workers=workers)
                            error = None
                            ranked = []
                            try:
                                ranked = engine.search(
                                    root, mode="fixed", seed=seed,
                                    max_sims=protocol["max_simulations"],
                                    max_transitions=protocol["max_transitions"],
                                    worker_timeout_s=protocol["worker_timeout_s"])
                            except ParallelSearchError as exc:
                                error = type(exc).__name__
                            elapsed = time.perf_counter() - start
                            report = engine.last_report
                            if report is None:
                                raise RuntimeError("No search accounting report")
                            cell = {
                                "scenario": scenario, "search_seed": seed,
                                "environment_seed": protocol["environment_seed"],
                                "root_pickle_sha256": root_id,
                                "workers": workers, "phase": phase,
                                "elapsed_s": elapsed, "error": error,
                                "serialization_probe": probe,
                                "report": dataclasses.asdict(report),
                                "ranked": [dataclasses.asdict(row) for row in ranked],
                            }
                            record["cells"].append(cell)
                            write_record(path, record)
                            print(scenario, seed, workers, phase,
                                  report.simulations, f"{elapsed:.6f}s", flush=True)
                            if error:
                                # A replacement pool is not the warm condition.
                                break
                    except BaseException as exc:
                        failure = exc
                        raise
                    finally:
                        if engine is not None:
                            try:
                                engine.close()
                            except BaseException as cleanup:
                                record["cleanup_error"] = type(cleanup).__name__
                                if failure is None:
                                    raise
                                try:
                                    failure.add_note(
                                        "Owned cleanup also raised "
                                        f"{type(cleanup).__name__}."
                                    )
                                except BaseException:
                                    pass
        record["status"] = ("complete" if len(record["cells"]) == 54
                            and all(c["error"] is None and
                                    c["report"]["simulations"] == 12000
                                    for c in record["cells"])
                            else "incomplete")
        current_revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        source_unchanged = current_revision == identity["revision"] and all(
            digest(ROOT / name) == expected
            for name, expected in identity["sha256"].items())
        record["source_unchanged_at_end"] = source_unchanged
        if not source_unchanged:
            raise RuntimeError("Source changed during the measured study")
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
    parser.add_argument("--conditions", required=True,
                        help="Observed resource conditions, without personal data")
    args = parser.parse_args()
    record = run(args.output, args.conditions)
    if record["status"] != "complete":
        raise SystemExit("Study retained with incomplete or failed conditions")


if __name__ == "__main__":
    main()
