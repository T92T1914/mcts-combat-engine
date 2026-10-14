"""Public managed capture for the known local companion.

The Windows helper adapts public process ownership ideas from the Solver.
No private supervisor or cross repository runtime dependency is used.
"""
from __future__ import annotations

import hashlib
import os
import sys
import threading
from pathlib import Path
from typing import Any

from game import episode_record as records
from tools import encounter_policy_evaluation as capture
from tools.encounter_process import EnforcementUnavailable, run_owned

ROOT = Path(__file__).resolve().parents[1]
MIB = 1_048_576
CONTROL_RESERVE = 524_288
CONTROL_FILE_BYTES = 65_536
CONTROL_STREAM_BYTES = 65_536
EXECUTION_FILES = (
    "managed_encounters.py", "tools/managed_encounter.py",
    "tools/encounter_process.py", "tools/encounter_policy_evaluation.py",
)
BOOTSTRAP = (
    "import runpy,sys;from pathlib import Path;"
    "sys.argv=sys.argv[1:];"
    "sys.path.insert(0,str(Path(sys.argv[0]).resolve().parent));"
    "runpy.run_path(sys.argv[0],run_name='__main__')"
)


class ArtifactLimit(capture.EncounterRuntimeError):
    """The next content write has no reservation."""


def _identity(body: bytes) -> dict:
    return {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


def _encoded(value: dict, limit: int = CONTROL_FILE_BYTES) -> bytes:
    body = records.canonical(value) + b"\n"
    if len(body) > limit:
        raise ArtifactLimit("control record exceeds its reserved allowance")
    return body


def _new(path: Path, body: bytes) -> None:
    with path.open("xb") as stream:
        if stream.write(body) != len(body):
            raise OSError("incomplete control file write")
        stream.flush()
        os.fsync(stream.fileno())


def _execution_identity() -> dict:
    return {name: _identity((ROOT / name).read_bytes()) for name in EXECUTION_FILES}


class ArtifactBudget:
    """Reserve cumulative file content writes, including replacements."""

    def __init__(self, root: Path, limit: int):
        self.root = root.resolve()
        self.limit = limit
        self.used = 0
        self.lock = threading.Lock()

    def _path(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise ArtifactLimit("artifact path leaves the admitted capture")
        if path.is_symlink():
            raise ArtifactLimit("artifact path is a symbolic link")
        return resolved

    def _reserve(self, amount: int) -> None:
        if amount < 0 or amount > self.limit - self.used:
            raise ArtifactLimit("collector artifact write allowance exhausted")
        self.used += amount

    def write_bytes(self, path: Path, data: bytes) -> None:
        path = self._path(path)
        with self.lock:
            self._reserve(len(data))
            pending = path.with_name(path.name + ".pending")
            _new(pending, data)
            pending.replace(path)

    def append(self, path: Path, data: bytes) -> None:
        path = self._path(path)
        with self.lock:
            self._reserve(len(data))
            with path.open("ab", buffering=0) as stream:
                if stream.write(data) != len(data):
                    raise OSError("incomplete managed spool write")


class ManagedControl:
    def __init__(self, root: Path, limit: int, memory: int, cleanup: float,
                 cancel: Path):
        self.budget = ArtifactBudget(root, limit)
        self.memory = memory
        self.cleanup = cleanup
        self.cancel = cancel

    def write_bytes(self, path: Path, data: bytes) -> None:
        self.budget.write_bytes(path, data)

    def before_trial(self, trial: dict, protocol: dict, directory: Path) -> None:
        if self.cancel.exists():
            raise capture.EncounterRuntimeError(
                "cancellation requested before admission")
        intent = {
            "format": "mcts-encounter-trial-intent", "schema_version": 1,
            "trial": {key: trial[key] for key in (
                "index", "block_index", "block_name", "scenario", "policy",
                "environment_seed", "search_seed")},
            "protocol": {name: protocol[name] for name in ("bytes", "sha256")},
        }
        self.write_bytes(directory / "admission-intent.json", _encoded(intent))

    def child(self, command: list[str], timeout: float, directory: Path) -> dict:
        # Both streams reserve through one lock before appending. Prefixes survive
        # collector interruption; the later ordinary copies are also charged.
        def spool(name: str, body: bytes) -> None:
            self.budget.append(directory / (name + ".raw"), body)

        isolated = [command[0], "-I", "-B", "-c", BOOTSTRAP, *command[1:]]
        return run_owned(
            isolated, cwd=ROOT, wall_seconds=timeout,
            cleanup_seconds=self.cleanup, memory_bytes=self.memory,
            stdout_limit=records.RECORD_BYTES, stderr_limit=capture.DIAGNOSTIC_BYTES,
            cancel_path=self.cancel, on_chunk=spool,
        )


def run_worker(plan_path: Path) -> int:
    """Internal fixed worker, reached through the managed controller."""
    raw = records._read(plan_path, "managed plan", CONTROL_FILE_BYTES)
    plan = records._parse(raw, "managed plan", 20_000, 10**300)
    plan = records._object(plan, "managed plan", {
        "format", "schema_version", "protocol_path", "capture_path",
        "artifact_allowance", "memory_bytes", "cleanup_seconds", "cancel_path",
        "protocol_identity", "execution_identity",
    })
    records._choice(plan["format"], "managed plan", {"mcts-managed-worker-plan"})
    records.integer(plan["schema_version"], "managed plan/schema", 1, 1)
    records.integer(plan["artifact_allowance"], "managed artifacts", 1, 128 * MIB)
    records.integer(plan["memory_bytes"], "managed memory", 64 * MIB, 512 * MIB)
    records._number(plan["cleanup_seconds"], "managed cleanup", 0.1, 5)
    if not records._equal(plan["execution_identity"], _execution_identity()):
        raise capture.EncounterRuntimeError("managed source changed before worker")
    protocol_path = Path(plan["protocol_path"])
    captured = records._read(protocol_path, "managed protocol", capture.PROTOCOL_BYTES)
    if not records._equal(_identity(captured), plan["protocol_identity"]):
        raise capture.EncounterRuntimeError("managed protocol snapshot changed")
    directory = Path(plan["capture_path"])
    control = ManagedControl(directory, plan["artifact_allowance"],
                             plan["memory_bytes"], plan["cleanup_seconds"],
                             Path(plan["cancel_path"]))
    result = capture.run_evaluation(
        protocol_path, directory,
        process_tree_bound="delivered managed Job owner; see ../managed-result.json",
        control=control,
    )
    if not records._equal(plan["execution_identity"], _execution_identity()):
        raise capture.EncounterRuntimeError("managed source changed during capture")
    if not records._equal(_identity(records._read(
            protocol_path, "managed protocol", capture.PROTOCOL_BYTES)),
                          plan["protocol_identity"]):
        raise capture.EncounterRuntimeError("managed protocol changed during capture")
    summary = {
        "format": "mcts-managed-worker-result", "schema_version": 1,
        "status": result["status"],
        "artifact_content_bytes_written": control.budget.used,
        "artifact_content_allowance": control.budget.limit,
        "intended_trials": len(result["trials"]),
        "complete_trials": sum(row["status"] == "complete" for row in result["trials"]),
        "scientific_validity": "not established by capture completion",
    }
    sys.stdout.buffer.write(_encoded(summary))
    return 0 if result["status"] == "complete" else 1


def run_managed(protocol_path: Path, output: Path, *, wall_seconds: float = 60,
                cleanup_seconds: float = 5, memory_mib: int = 256,
                artifact_mib: int = 32,
                cancel_path: Path | None = None) -> tuple[dict, int]:
    """Establish controls for one fixed block, without a private supervisor."""
    # Refuse this full guarantee before directory creation or worker admission.
    if sys.platform != "win32":
        raise EnforcementUnavailable(
            "managed capture requires qualified Windows10+ Job enforcement; "
            "no Linux memory or lifecycle fallback is supplied")
    records._number(wall_seconds, "managed wall seconds", 0.1, 300)
    records._number(cleanup_seconds, "managed cleanup seconds", 0.1, 5)
    records.integer(memory_mib, "managed memory MiB", 64, 512)
    records.integer(artifact_mib, "managed artifact MiB", 4, 128)
    if protocol_path.is_symlink():
        records._error("protocol", "symbolic link input is not admitted")
    captured = records._read(protocol_path, "protocol", capture.PROTOCOL_BYTES)
    protocol = capture.validate_protocol(records._parse(
        captured, "protocol", 100_000, 10**300))
    if len(protocol["seed_blocks"]) != 1:
        records._error("protocol/seed_blocks", "managed capture admits one block")
    before = _execution_identity()
    collection = capture._source_identity()
    _, content = records.load_content()
    freeze = protocol.get("metadata", {}).get("freeze")
    if freeze is not None:
        if (not isinstance(freeze, dict)
                or not records._equal(freeze.get("implementation"), collection)
                or not records._equal(freeze.get("content"), content)):
            records._error("protocol/metadata/freeze",
                           "source or content freeze mismatch")
    output = output.resolve()
    if output.is_relative_to(ROOT):
        records._error("output", "use a new directory outside the companion")
    cancellation = (output / "cancel.request" if cancel_path is None
                    else cancel_path.resolve())
    allowance = artifact_mib * MIB
    delegated = allowance - CONTROL_RESERVE - len(captured)
    if delegated <= 0:
        records._error("managed artifacts", "no collector allowance after reservations")
    output.mkdir(parents=True, exist_ok=False)
    snapshot = output / "protocol-input.json"
    _new(snapshot, captured)
    plan = {
        "format": "mcts-managed-worker-plan", "schema_version": 1,
        "protocol_path": str(snapshot), "capture_path": str(output / "capture"),
        "artifact_allowance": delegated, "memory_bytes": memory_mib * MIB,
        "cleanup_seconds": cleanup_seconds, "cancel_path": str(cancellation),
        "protocol_identity": _identity(captured), "execution_identity": before,
    }
    plan_body = _encoded(plan)
    _new(output / "worker-plan.json", plan_body)
    start = {
        "format": "mcts-managed-encounter-start", "schema_version": 1,
        "status": "requested", "protocol": _identity(captured),
        "execution_identity": before, "collection_identity": collection,
        "content": content, "plan": _identity(plan_body),
        "requested_controls": {
            "wall_seconds": wall_seconds, "cleanup_seconds": cleanup_seconds,
            "wall_scope": "owned collector launch and execution; excludes controller "
                          "admission, finalization and the separate cleanup allowance",
            "job_committed_memory_bytes": memory_mib * MIB,
            "artifact_cumulative_content_bytes": allowance,
            "controller_reserved_bytes": CONTROL_RESERVE,
            "protocol_snapshot_bytes": len(captured),
            "collector_artifact_allowance": delegated,
        },
        "memory_scope": "owned collector and recorder tree; excludes controller",
        "artifact_scope": "known capture content writes; not an OS disk quota",
        "cancellation_request_path": str(cancellation),
        "final_owner_attestation": "pending; absence is not successful cleanup",
    }
    _new(output / "managed-start.json", _encoded(start))

    def spool(name: str, body: bytes) -> None:
        # The owner enforces a separate 64KiB cap for each controller stream.
        path = output / ("controller." + name + ".raw")
        with path.open("ab", buffering=0) as stream:
            if stream.write(body) != len(body):
                raise OSError("incomplete controller spool")

    transport = run_owned(
        [sys.executable, "-I", "-B", str(ROOT / "managed_encounters.py"),
         "_worker", str(output / "worker-plan.json")],
        cwd=ROOT, wall_seconds=wall_seconds, cleanup_seconds=cleanup_seconds,
        memory_bytes=memory_mib * MIB, stdout_limit=CONTROL_STREAM_BYTES,
        stderr_limit=CONTROL_STREAM_BYTES, cancel_path=cancellation, on_chunk=spool,
    )
    worker = None
    parse_error = None
    if transport["returncode"] == 0:
        try:
            worker = records._parse(transport["stdout"], "managed worker", 20_000,
                                    10**300)
            if (not isinstance(worker, dict)
                    or worker.get("format") != "mcts-managed-worker-result"
                    or worker.get("status") != "complete"
                    or worker.get("intended_trials") != 6
                    or worker.get("complete_trials") != 6):
                raise ValueError("worker did not retain six complete trials")
            written = worker["artifact_content_bytes_written"]
            records.integer(written, "worker artifact count", 0, delegated)
        except (ValueError, TypeError, KeyError) as error:
            parse_error = str(error)[:2048]
    owner = transport["owner"]
    unchanged = records._equal(before, _execution_identity())
    original_unchanged = False
    try:
        original_unchanged = records._equal(_identity(records._read(
            protocol_path, "original protocol", capture.PROTOCOL_BYTES)),
            _identity(captured))
    except (OSError, ValueError):
        pass
    clean = (owner.get("established") is True
             and owner.get("failure_kind") is None
             and owner.get("cleanup", {}).get("retired") is True)
    complete = (clean and worker is not None and parse_error is None
                and unchanged and original_unchanged)
    outcome: dict[str, Any] = {
        "format": "mcts-managed-encounter-result", "schema_version": 1,
        "status": "complete" if complete else "incomplete",
        "protocol": _identity(captured), "owner": owner, "worker": worker,
        "worker_result_error": parse_error, "execution_identity_unchanged": unchanged,
        "original_input_unchanged": original_unchanged,
        "controller_transport": {name: _identity(transport[name])
                                 for name in ("stdout", "stderr")},
        "artifact_scope": {
            "cumulative_allowance": allowance,
            "controller_reservation": CONTROL_RESERVE,
            "protocol_snapshot_bytes": len(captured),
            "collector_allowance": delegated,
            "collector_used": None if worker is None else
            worker.get("artifact_content_bytes_written"),
            "overshoot_policy": "no unreserved known artifact content writes",
            "not_supplied": "OS quota over arbitrary child filesystem writes",
        },
        "recovery": "inspect capture with recover_encounters.py; no automatic rerun",
        "scientific_validity": "not established by operational completion",
    }
    _new(output / "managed-result.json", _encoded(outcome))
    interrupted = owner.get("failure_kind") in {"cancelled", "interrupted"}
    status = 0 if complete else (130 if interrupted else 1)
    return outcome, status
