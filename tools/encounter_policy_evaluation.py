"""Capture paired complete encounters through the existing bounded recorder.

One hidden serial child owns each trial. The parent records failures, keeps the
full declared inventory, and never substitutes a failed trial's outcome or work.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Protocol

from game import episode_record as records

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ["duel", "gauntlet", "boss"]
POLICIES = {"uct", "sequential_halving"}
PROTOCOL_BYTES = 2_097_152
DIAGNOSTIC_BYTES = 65_536
REPORT_BYTES = 67_108_864


class _ReadSeekStream(Protocol):
    def seek(self, offset: int, whence: int = 0, /) -> int: ...

    def read(self, size: int = -1, /) -> bytes: ...


class CaptureControl(Protocol):
    """The explicit managed entry supplies enforced execution and writes."""

    def write_bytes(self, path: Path, data: bytes) -> None: ...

    def before_trial(self, trial: dict, protocol: dict, directory: Path) -> None: ...

    def child(self, command: list[str], timeout: float, directory: Path) -> dict: ...


class EncounterRuntimeError(RuntimeError):
    """A declared evaluation cannot retain its complete capture accounting."""


class EncounterRetirementError(EncounterRuntimeError):
    """The owned child could not be reaped, so another trial cannot start."""

    def __init__(self, message: str, transport: dict):
        super().__init__(message)
        self.transport = transport


def validate_protocol(value: Any) -> dict:
    """Admit fixed settings and paired blocks before any child is started."""
    obj = records._object(value, "protocol", {
        "schema_version", "scenarios", "rounds", "sims", "horizon",
        "trial_timeout_seconds", "collection_timeout_seconds", "seed_blocks",
    }, {"format", "metadata"})
    records.integer(obj["schema_version"], "protocol/schema_version", 1, 1)
    if "format" in obj:
        records._choice(obj["format"], "protocol/format",
                        {"mcts-encounter-policy-protocol"})
    if not records._equal(obj["scenarios"], SCENARIOS):
        records._error("protocol/scenarios", "use duel, gauntlet, boss in that order")
    for name, required in (("rounds", 30), ("sims", 32), ("horizon", 1)):
        records.integer(obj[name], "protocol/" + name, required, required)
    records._number(obj["trial_timeout_seconds"], "protocol/trial_timeout_seconds",
                    0.01, 300)
    records._number(obj["collection_timeout_seconds"],
                    "protocol/collection_timeout_seconds", 0.01, 1800)
    if "metadata" in obj and not isinstance(obj["metadata"], dict):
        records._error("protocol/metadata", "must be an object")
    blocks = records._array(obj["seed_blocks"], "protocol/seed_blocks", 1, 4096)
    names: set[str] = set()
    for index, block in enumerate(blocks):
        path = f"protocol/seed_blocks/{index}"
        block = records._object(block, path, {
            "name", "environment_seed", "search_seed", "policy_order",
        })
        name = records._string(block["name"], path + "/name")
        if name in names:
            records._error(path, "duplicate block name")
        names.add(name)
        for field in ("environment_seed", "search_seed"):
            records.integer(block[field], path + "/" + field,
                            records.SEED_MIN, records.SEED_MAX)
        if abs(block["environment_seed"]) == abs(block["search_seed"]):
            records._error(path, "environment and search seed magnitudes overlap")
        order = block["policy_order"]
        if not (isinstance(order, list) and len(order) == 2
                and all(isinstance(policy, str) for policy in order)
                and set(order) == POLICIES):
            records._error(path + "/policy_order", "declare each policy once")
    return obj


def _identity(data: bytes) -> dict:
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _source_identity() -> dict:
    return {"episode": records.observed_identity(), "capture_files": {
        name: _identity((ROOT / name).read_bytes())
        for name in ("benchmark.py", "tools/encounter_policy_evaluation.py")
    }}


def _write_bytes(path: Path, data: bytes) -> None:
    pending = path.with_name(path.name + ".pending")
    with pending.open("wb") as sink:
        if sink.write(data) != len(data):
            raise EncounterRuntimeError("incomplete capture artifact write")
    pending.replace(path)


def _write_json(path: Path, value: dict) -> None:
    data = records.canonical(value) + b"\n"
    if len(data) > REPORT_BYTES:
        raise EncounterRuntimeError("capture report exceeds 67108864 bytes")
    _write_bytes(path, data)


def _read_transport(stream: _ReadSeekStream, limit: int) -> tuple[bytes, int]:
    size = stream.seek(0, os.SEEK_END)
    stream.seek(0)
    return stream.read(min(size, limit)), size


def _child(command: list[str], timeout: float) -> dict:
    """Run the known serial recorder without unbounded in-memory pipe capture.

    Its successful producer bounds stdout before publication. Temporary files
    retain raw failure output, and parent reads are capped independently.
    An unreaped child refuses further trial admission.
    """
    environment = dict(os.environ, PYTHONNOUSERSITE="1",
                       PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    environment.pop("PYTHONPATH", None)
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        started = time.perf_counter()
        process = subprocess.Popen(
            command, cwd=ROOT, env=environment, shell=False,
            stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        timeout_diagnostics = None
        retirement_errors = []

        def retire() -> None:
            try:
                process.kill()
            except OSError as cleanup:
                retirement_errors.append("kill: " + str(cleanup)[:2048])
            try:
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired) as cleanup:
                retirement_errors.append("reap: " + str(cleanup)[:2048])

        interrupted = None
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            timeout_diagnostics = {
                "timeout_seconds": timeout, "message": str(error)[:2048],
                "kill_requested": True, "reaped": False,
            }
            retire()
            timeout_diagnostics["reaped"] = not retirement_errors
        except BaseException as error:
            interrupted = error
            retire()
        elapsed = time.perf_counter() - started
        output, output_size = _read_transport(stdout, records.RECORD_BYTES)
        diagnostic, diagnostic_size = _read_transport(stderr, DIAGNOSTIC_BYTES)
        result = {
            "returncode": process.returncode, "elapsed_subprocess_seconds": elapsed,
            "timeout_diagnostics": timeout_diagnostics,
            "stdout": output, "stderr": diagnostic,
            "stdout_observed_bytes": output_size,
            "stderr_observed_bytes": diagnostic_size,
            "stdout_truncated": output_size > records.RECORD_BYTES,
            "stderr_truncated": diagnostic_size > DIAGNOSTIC_BYTES,
        }
        if retirement_errors:
            result["retirement_errors"] = retirement_errors
            raise EncounterRetirementError("owned recorder retirement failed", result)
        if interrupted is not None:
            raise interrupted
        return result


def _inventory(protocol: dict) -> list[dict]:
    trials: list[dict] = []
    for block_index, block in enumerate(protocol["seed_blocks"]):
        for scenario in protocol["scenarios"]:
            for policy in block["policy_order"]:
                index = len(trials)
                trials.append({
                    "index": index, "block_index": block_index,
                    "block_name": block["name"], "scenario": scenario,
                    "policy": policy, "environment_seed": block["environment_seed"],
                    "search_seed": block["search_seed"], "status": "not_attempted",
                    "receipt": f"trials/{index:05d}/receipt.json",
                    "terminal_result": None, "termination": None, "score": None,
                    "rounds": None, "work": None,
                })
    return trials


def _summary(trials: list[dict]) -> dict:
    summary = {}
    for policy in ("uct", "sequential_halving"):
        selected = [trial for trial in trials if trial["policy"] == policy]
        completed = [trial for trial in selected if trial["status"] == "complete"]
        wins = sum(trial["terminal_result"] == 1 for trial in completed)
        unknown = len(selected) - len(completed)
        summary[policy] = {
            "intended_trials": len(selected), "complete_trials": len(completed),
            "terminal_wins_by_round_cap": wins,
            "terminal_losses": sum(trial["terminal_result"] == 0
                                   for trial in completed),
            "round_limit_nonwins": sum(trial["termination"] == "round_limit"
                                       for trial in completed),
            "unknown_outcomes": unknown,
            "terminal_win_count_bounds": [wins, wins + unknown],
            "known_simulations": sum(trial["work"]["simulations"]
                                     for trial in completed),
            "known_transitions": sum(trial["work"]["transitions"]
                                     for trial in completed),
            "unobserved_failed_trial_work": unknown,
        }
    return summary


def _admit_episode(data: bytes, trial: dict, protocol: dict,
                   content: dict, implementation: dict) -> dict:
    record = records.validate_record(records._parse(
        data, "trial episode", 200_000, 10**300))
    if record["schema_version"] != 2:
        raise EncounterRuntimeError("trial recorder did not emit explicit schema 2")
    expected_config = records._configuration(
        protocol["rounds"], protocol["sims"], protocol["horizon"],
        trial["search_seed"], trial["policy"])
    if (not records._equal(record["configuration"], expected_config)
            or record["scenario"]["name"] != trial["scenario"]
            or record["scenario"]["environment_seed"] != trial["environment_seed"]
            or not records._equal(record["content"], content)
            or not records._equal(record["implementation"], implementation)):
        raise EncounterRuntimeError(
            "trial settings, content or implementation mismatch")
    return record


def _trial(trial: dict, protocol: dict, directory: Path,
           content: dict, implementation: dict, *,
           timeout: float | None = None,
           control: CaptureControl | None = None) -> dict:
    command = [sys.executable, str(ROOT / "episode.py"), "record", trial["scenario"],
               "--environment-seed", str(trial["environment_seed"]),
               "--search-seed", str(trial["search_seed"]),
               "--rounds", str(protocol["rounds"]), "--sims", str(protocol["sims"]),
               "--horizon", str(protocol["horizon"]),
               "--root-allocation", trial["policy"]]
    receipt: dict[str, Any] = {
        "format": "mcts-encounter-trial-receipt", "schema_version": 1,
        "trial": {key: trial[key] for key in (
            "index", "block_index", "block_name", "scenario", "policy",
            "environment_seed", "search_seed")},
        "status": "error", "elapsed_subprocess_seconds": None,
        "transport": None, "episode": None, "error": None, "outcome": None,
        "work": None,
    }

    def retain_transport(transport: dict) -> bytes:
        stdout, stderr = transport.pop("stdout"), transport.pop("stderr")
        if control is None:
            (directory / "stdout.raw").write_bytes(stdout)
            (directory / "stderr.raw").write_bytes(stderr)
        else:
            control.write_bytes(directory / "stdout.raw", stdout)
            control.write_bytes(directory / "stderr.raw", stderr)
        receipt["transport"] = {**transport,
                                "stdout": {"path": "stdout.raw", **_identity(stdout)},
                                "stderr": {"path": "stderr.raw", **_identity(stderr)}}
        receipt["elapsed_subprocess_seconds"] = transport["elapsed_subprocess_seconds"]
        return stdout

    try:
        allowed = protocol["trial_timeout_seconds"] if timeout is None else timeout
        transport = (_child(command, allowed) if control is None else
                     control.child(command, allowed, directory))
        stdout = retain_transport(transport)
        if control is not None:
            owner = transport.get("owner", {})
            if not owner.get("cleanup", {}).get("retired", False):
                receipt["status"] = "retirement_failure"
                raise EncounterRuntimeError("managed recorder retirement unresolved")
            failure = owner.get("failure_kind")
            if failure is not None:
                if failure == "cancelled":
                    receipt["status"] = "cancelled"
                elif failure == "timeout":
                    receipt["status"] = "timeout"
                raise EncounterRuntimeError("managed recorder: " + str(failure))
        if transport["timeout_diagnostics"] is not None:
            receipt["status"] = "timeout"
            raise EncounterRuntimeError("trial exceeded its external timeout")
        if transport["returncode"] != 0:
            raise EncounterRuntimeError("recorder exited with status " +
                                        str(transport["returncode"]))
        if transport["stdout_truncated"] or transport["stderr_truncated"]:
            raise EncounterRuntimeError(
                "recorder transport exceeded its read allowance")
        record = _admit_episode(stdout, trial, protocol, content, implementation)
        episode_data = records.output_bytes(record)
        # Only fully admitted successful stdout becomes an episode artifact.
        if control is None:
            _write_bytes(directory / "episode.json", episode_data)
        else:
            control.write_bytes(directory / "episode.json", episode_data)
        final = record["final"]
        work = [step["work"] for step in record["steps"]]
        diagnostics = [step["search_diagnostics"] for step in record["steps"]]
        receipt.update({
            "status": "complete",
            "episode": {"path": "episode.json", **_identity(episode_data)},
            "outcome": {name: final[name] for name in (
                "terminal_result", "termination", "score", "rounds")},
            "work": {
                "decision_records": work,
                "decision_diagnostics": diagnostics,
                "simulations": sum(row["simulations"] for row in work),
                "transitions": sum(row["transitions"] for row in work),
                "unused_transitions": sum(row["unused_transitions"] for row in work),
                "shortfalls": [],
                "uniform_fallback_decisions": sum(
                    row["allocation_mode"] == "uniform_fallback"
                    for row in diagnostics),
            },
        })
    except EncounterRetirementError as error:
        retain_transport(error.transport)
        receipt["status"] = "retirement_failure"
        receipt["error"] = {"type": type(error).__name__, "message": str(error)[:2048]}
    except (EncounterRuntimeError, OSError, ValueError, TypeError,
            ArithmeticError) as error:
        receipt["error"] = {"type": type(error).__name__, "message": str(error)[:2048]}
    return receipt


def run_evaluation(protocol_path: Path, output_directory: Path, *,
                   process_tree_bound: str,
                   control: CaptureControl | None = None) -> dict:
    """Retain intended slots and failures without supplying statistical analysis."""
    records._string(process_tree_bound, "process-tree bound", high=2048)
    if not process_tree_bound.strip():
        records._error("process-tree bound",
                       "record the caller's external owner receipt")
    started = time.monotonic()
    captured = records._read(protocol_path, "protocol", PROTOCOL_BYTES)
    protocol = validate_protocol(records._parse(captured, "protocol", 100_000, 10**300))
    if control is not None and len(protocol["seed_blocks"]) != 1:
        records._error("protocol/seed_blocks", "managed capture admits one block")

    def write_bytes(path: Path, body: bytes) -> None:
        if control is None:
            _write_bytes(path, body)
        else:
            control.write_bytes(path, body)

    def write_json(path: Path, value: dict) -> None:
        if control is None:
            _write_json(path, value)
        else:
            body = records.canonical(value) + b"\n"
            if len(body) > REPORT_BYTES:
                raise EncounterRuntimeError("capture report exceeds its allowance")
            control.write_bytes(path, body)
    _, content = records.load_content()
    implementation = _source_identity()
    freeze = protocol.get("metadata", {}).get("freeze")
    if freeze is not None:
        if (not isinstance(freeze, dict)
                or not records._equal(freeze.get("implementation"), implementation)
                or not records._equal(freeze.get("content"), content)):
            records._error("protocol/metadata/freeze",
                           "source or content freeze mismatch")
    trials = _inventory(protocol)
    report: dict = {
        "format": "mcts-encounter-policy-evaluation", "schema_version": 1,
        "status": "incomplete",
        "protocol": {"path": "protocol.json", **_identity(captured)},
        "implementation": implementation, "content": content,
        "settings": {key: protocol[key] for key in (
            "scenarios", "rounds", "sims", "horizon", "trial_timeout_seconds")},
        "trials": trials, "summary": _summary(trials), "failure": None,
        "elapsed_capture_seconds": None,
        "timing_scope": "subprocess wall time includes interpreter startup, content, "
                        "recording, search, environment execution and close",
        "process_tree_bound": process_tree_bound,
        "process_tree_bound_verified_by_collector": False,
        "transport_scope": "reads retain at most 8MiB stdout and 64KiB stderr "
                           "per trial, "
                           "temporary transport files have no independent disk quota",
    }
    if control is not None:
        report["transport_scope"] = (
            "managed pipe prefixes and every collector artifact write are bounded; "
            "see the separate managed owner receipt; not an OS disk quota")
    # Check the complete inventory's report bound before starting any child.
    if len(records.canonical(report)) + 1 > REPORT_BYTES:
        records._error("protocol", "declared inventory exceeds report allowance")
    output_directory = output_directory.resolve()
    output_directory.mkdir(parents=True, exist_ok=False)
    write_bytes(output_directory / "protocol.json", captured)
    (output_directory / "trials").mkdir()
    report_path = output_directory / "results.json"
    write_json(report_path, report)
    deadline = started + protocol["collection_timeout_seconds"]
    for trial in trials:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            report["failure"] = {"stage": "collection_deadline",
                                 "trial_index": trial["index"],
                                 "message": "no further trials admitted after deadline"}
            break
        directory = output_directory / "trials" / f"{trial['index']:05d}"
        directory.mkdir()
        if control is not None:
            control.before_trial(trial, report["protocol"], directory)
        receipt = _trial(trial, protocol, directory, content, implementation["episode"],
                         timeout=min(protocol["trial_timeout_seconds"], remaining),
                         control=control)
        write_json(directory / "timing.json", {
            "elapsed_subprocess_seconds": receipt["elapsed_subprocess_seconds"],
            "transport": receipt["transport"],
        })
        write_json(directory / "work.json", {"work": receipt["work"]})
        write_json(directory / "error.json", {"error": receipt["error"]})
        receipt["artifacts"] = {
            "timing": "timing.json", "work": "work.json", "error": "error.json",
        }
        write_json(directory / "receipt.json", receipt)
        trial["status"] = receipt["status"]
        trial["receipt_identity"] = _identity((directory / "receipt.json").read_bytes())
        trial["episode"] = receipt["episode"]
        trial["elapsed_subprocess_seconds"] = receipt["elapsed_subprocess_seconds"]
        if receipt["status"] == "complete":
            trial.update(receipt["outcome"])
            trial["work"] = {name: receipt["work"][name] for name in (
                "simulations", "transitions", "unused_transitions",
                "uniform_fallback_decisions")}
        if receipt["status"] == "retirement_failure":
            report["failure"] = {"stage": "retirement", "trial_index": trial["index"],
                                 "message": receipt["error"]["message"]}
            break
        if control is not None and receipt["status"] != "complete":
            report["failure"] = {
                "stage": "managed_trial_failure", "trial_index": trial["index"],
                "message": "managed capture stops after an incomplete attempt"}
            break
    if not records._equal(implementation, _source_identity()):
        report["failure"] = {"stage": "finalization",
                             "message": "source identity changed"}
    if (all(trial["status"] == "complete" for trial in trials)
            and report["failure"] is None):
        report["status"] = "complete"
    report["summary"] = _summary(trials)
    report["elapsed_capture_seconds"] = time.monotonic() - started
    write_json(report_path, report)
    return report
