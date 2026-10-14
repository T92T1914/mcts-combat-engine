"""Bounded passive consistency reporting for distinct Linux ownership receipts.

An ordinary JSON receipt supplies claims, not authenticated cleanup authority.
The optional cleanup path rechecks only its exact recorded owned container.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import stat
from pathlib import Path

HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX32 = re.compile(r"[0-9a-f]{32}\Z")
MAX_RECEIPT = 131_072


def inspect_receipt(value: object) -> dict:
    errors: list[str] = []

    def problem(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    def object_at(parent: dict, key: str) -> dict:
        item = parent.get(key)
        if not isinstance(item, dict):
            errors.append(key + " must be an object")
            return {}
        return item

    if not isinstance(value, dict):
        return {"consistent": False, "contradictions": ["receipt must be an object"]}
    problem(value.get("format") == "mcts-linux-owned-container" and
            type(value.get("schema_version")) is int and
            value["schema_version"] == 1, "unsupported receipt format or schema")
    phase = value.get("phase")
    problem(phase in ("before_create", "before_admission", "admitted", "final"),
            "unsupported phase")
    admitted = value.get("work_admitted")
    problem(type(admitted) is bool, "work_admitted must be an explicit boolean")
    request = object_at(value, "request")
    nonce = request.get("nonce")
    problem(isinstance(nonce, str) and bool(HEX32.fullmatch(nonce)), "invalid nonce")
    name = request.get("container_name")
    problem(isinstance(name, str) and isinstance(nonce, str) and
            name.endswith(nonce) and bool(re.fullmatch(r"[a-z0-9-]+", name)),
            "container name does not bind its nonce")
    image = request.get("image_id")
    problem(isinstance(image, str) and image.startswith("sha256:") and
            bool(HEX64.fullmatch(image[7:])), "invalid immutable image identity")
    for key in ("memory", "pids", "tmpfs"):
        problem(type(request.get(key)) is int and request[key] > 0,
                key + " must be an explicit positive integer")
    problem(request.get("memory_swap") == request.get("memory") and
            type(request.get("memory_swap")) is int,
            "memory/swap request does not express zero swap")
    ownership = object_at(value, "ownership")
    cid = ownership.get("container_id")
    problem(cid is None or isinstance(cid, str) and bool(HEX64.fullmatch(cid)),
            "invalid exact container identity")
    outcome = object_at(value, "outcome")
    status = outcome.get("status")
    problem(status in ("pending", "refused", "complete", "incomplete", "error",
                       "timeout", "cancelled", "output_limit", "memory_pressure",
                       "process_pressure", "retirement_failure"),
            "unsupported explicit outcome status")
    code = outcome.get("returncode")
    problem(code is None or type(code) is int, "returncode must be integer or null")
    cleanup = object_at(value, "cleanup")
    complete = cleanup.get("complete")
    problem(type(complete) is bool, "cleanup.complete must be an explicit boolean")
    if phase == "before_create":
        problem(admitted is False and ownership.get("native") is None,
                "initial receipt contradicts workload admission")
    if phase == "before_admission":
        problem(admitted is False, "before-admission receipt claims admitted work")
    if phase == "admitted":
        problem(admitted is True, "admitted phase denies workload admission")
    if admitted is True or phase == "before_admission":
        problem(type(request.get("memory")) is int and
                67_108_864 <= request["memory"] <= 268_435_456 and
                type(request.get("pids")) is int and 16 <= request["pids"] <= 64,
                "admitted memory or PID request exceeds the qualified domain")
        problem(type(request.get("tmpfs")) is int and request["tmpfs"] == 33_554_432,
                "admitted temporary filesystem differs from the qualified domain")
        wall = request.get("wall")
        problem(type(wall) in (int, float) and 0 < wall <= 30 and math.isfinite(wall),
                "admitted wall allowance exceeds the qualified domain")
        problem(type(request.get("cleanup")) is int and request["cleanup"] == 10 and
                type(request.get("lifetime")) is int and request["lifetime"] == 60,
                "admitted cleanup or root lifetime differs from the qualified domain")
        problem(isinstance(cid, str) and bool(HEX64.fullmatch(cid)),
                "admission lacks exact container identity")
        native = object_at(ownership, "native")
        problem(native.get("controller_excluded") is True,
                "admission lacks controller exclusion")
        for key in ("host_pid", "starttime"):
            problem(type(native.get(key)) is int and native[key] > 0,
                    "admission lacks pinned " + key)
        group = native.get("cgroup")
        problem(isinstance(group, str) and isinstance(cid, str) and cid in group,
                "admitted cgroup does not bind exact container")
        controls = object_at(native, "controls")
        problem(controls.get("memory.max") == str(request.get("memory")) and
                controls.get("memory.swap.max") == "0" and
                controls.get("pids.max") == str(request.get("pids")),
                "admitted literal kernel limits contradict the request")
        cpu_text = controls.get("cpu.max")
        cpu = cpu_text.split() if isinstance(cpu_text, str) else []
        problem(type(request.get("cpus")) is int and request["cpus"] == 1 and
                len(cpu) == 2 and all(part.isascii() and part.isdigit() and
                                     len(part) <= 16 for part in cpu) and
                int(cpu[0]) == int(cpu[1]) > 0,
                "admitted CPU request and literal quota do not express one CPU")
    if complete is True:
        problem(cleanup.get("container_absent") is True and
                cleanup.get("cgroup_empty_or_absent") is True and
                cleanup.get("pidfd_signalled") is True,
                "cleanup completion lacks its required observations")
    if status == "complete":
        problem(phase == "final" and admitted is True and code == 0 and
                type(code) is int and complete is True,
                "complete outcome contradicts phase, work, exit or cleanup")
        problem(value.get("input_files_unchanged") is True,
                "complete outcome lacks explicit unchanged original input evidence")
    output = object_at(value, "output")
    counts: list[int] = []
    retained: list[int] = []
    for name in ("stdout", "stderr"):
        stream = object_at(output, name)
        seen, kept = stream.get("observed_bytes"), stream.get("retained_bytes")
        valid = type(seen) is int and type(kept) is int and 0 <= kept <= seen
        problem(valid, name + " output counts contradict observed/retained bytes")
        problem(type(stream.get("truncated")) is bool, name + " truncation is unknown")
        if status == "complete":
            problem(stream.get("truncated") is False,
                    "complete outcome contradicts truncated " + name)
        if valid:
            counts.append(seen)
            retained.append(kept)
            limit = request.get(name + "_limit")
            problem(type(limit) is int and limit > 0 and kept <= limit,
                    name + " retained output contradicts its allowance")
            if status == "complete":
                problem(type(limit) is int and seen <= limit,
                        "complete outcome contradicts " + name + " allowance")
            problem(stream.get("truncated") == (seen > kept),
                    name + " truncation contradicts explicit counts")
            if kept == 0:
                problem(stream.get("sha256") == hashlib.sha256(b"").hexdigest(),
                        name + " empty retained bytes have the wrong identity")
        problem(isinstance(stream.get("sha256"), str) and
                bool(HEX64.fullmatch(stream["sha256"])), name + " identity is invalid")
    if len(counts) == 2:
        problem(type(output.get("combined_observed_bytes")) is int and
                output["combined_observed_bytes"] == sum(counts),
                "aggregate output contradicts its streams")
        total_limit = request.get("output_limit")
        problem(type(total_limit) is int and total_limit > 0 and
                sum(retained) <= total_limit,
                "aggregate retained output contradicts its allowance")
        if status == "complete":
            problem(type(total_limit) is int and sum(counts) <= total_limit,
                    "complete outcome contradicts aggregate output allowance")
    artifacts = object_at(value, "artifact_identities")
    names = request.get("artifact_names")
    valid_names = isinstance(names, list) and all(
        isinstance(name, str) for name in names)
    problem(valid_names, "artifact request inventory must be a list of names")
    if valid_names:
        problem(len(names) == len(set(names)) and set(artifacts).issubset(names),
                "artifact inventory repeats or contains an undeclared file")
        if status == "complete":
            problem(set(artifacts) == set(names),
                    "complete outcome lacks its requested artifact inventory")
    total = 0
    for item in artifacts.values():
        if not isinstance(item, dict):
            errors.append("artifact identity must be an object")
            continue
        size, digest = item.get("bytes"), item.get("sha256")
        problem(type(size) is int and size >= 0, "artifact size must be explicit")
        problem(isinstance(digest, str) and bool(HEX64.fullmatch(digest)),
                "artifact digest is invalid")
        if type(size) is int and size >= 0:
            total += size
            if size == 0:
                problem(digest == hashlib.sha256(b"").hexdigest(),
                        "empty artifact contradicts its digest")
    artifact_limit = request.get("artifact_limit")
    problem(type(artifact_limit) is int and 0 < artifact_limit <= 2_097_152 and
            total <= artifact_limit, "artifact aggregate exceeds its allowance")
    if status in ("memory_pressure", "process_pressure"):
        deltas = object_at(value, "event_deltas")
        events = object_at(deltas, "memory.events" if status == "memory_pressure"
                           else "pids.events")
        keys = ("oom", "oom_kill") if status == "memory_pressure" else ("max",)
        problem(any(type(events.get(key)) is int and events[key] > 0 for key in keys),
                "pressure outcome lacks a positive deciding kernel event")
    return {"consistent": not errors, "contradictions": errors,
            "receipt_phase": phase, "claimed_outcome": status,
            "claimed_work_admitted": admitted,
            "authentication": "not established by ordinary receipt JSON",
            "execution_performed": False, "cleanup_performed": False}


def read_receipt(path: Path) -> tuple[dict, bytes]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_RECEIPT:
        raise ValueError("receipt is not an ordinary bounded file")
    with path.open("rb") as stream:
        body = stream.read(MAX_RECEIPT + 1)
    if len(body) > MAX_RECEIPT:
        raise ValueError("receipt exceeds its byte allowance")
    after = path.lstat()
    if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError("receipt changed during its bounded read")
    value = json.loads(body)
    return value, body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--cleanup-owned-container", action="store_true",
                        help="recheck and retire only the exact recorded container")
    args = parser.parse_args(argv)
    try:
        value, original = read_receipt(args.receipt)
        report = inspect_receipt(value)
        cleanup_ok = True
        if args.cleanup_owned_container:
            if not report["consistent"]:
                raise ValueError("contradictory receipt cannot request cleanup")
            from tools.linux_container import recover_owned_container
            report["cleanup_result"] = recover_owned_container(value)
            status = report["cleanup_result"].get("status")
            report["cleanup_requested"] = True
            report["cleanup_performed"] = True if status == "retired" else \
                False if status in ("refused", "already_retired") else None
            cleanup_ok = status in ("retired", "already_retired") and \
                report["cleanup_result"].get("cleanup", {}).get("complete") is True
        if read_receipt(args.receipt)[1] != original:
            raise ValueError("original receipt changed during inspection")
        print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))
        return 0 if report["consistent"] and cleanup_ok else 1
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(json.dumps({"consistent": False, "error": str(error),
                          "execution_performed": False}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
