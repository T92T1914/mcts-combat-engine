"""Inspect retained encounter evidence without starting or replacing any work.

This reads a stopped local capture. Hashes bind the observed bytes. They do not
authenticate their author, establish OS containment or validate a study.
"""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any

from game import episode_record as records
from tools import encounter_policy_evaluation as capture

READ_BYTES = 134_217_728
RECEIPT_BYTES = 4_194_304
REPORT_BYTES = 67_108_864
TRIAL_FIELDS = (
    "index", "block_index", "block_name", "scenario", "policy",
    "environment_seed", "search_seed",
)
STATUSES = {"complete", "error", "timeout", "retirement_failure", "cancelled"}
ARTIFACTS = {"timing": "timing.json", "work": "work.json", "error": "error.json"}
TRIAL_FILES = {"receipt.json", "episode.json", "stdout.raw", "stderr.raw",
               "timing.json", "work.json", "error.json", "admission-intent.json"}


class RecoveryRuntimeError(RuntimeError):
    """A bounded, stable and safely scoped inspection cannot be completed."""


class _EvidenceError(ValueError):
    """A retained claim is malformed or contradicts its supporting bytes."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise _EvidenceError(message)


def _identity(data: bytes) -> dict:
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _same(left: Any, right: Any, message: str) -> None:
    _require(records._equal(left, right), message)


def _fingerprint(value: os.stat_result) -> tuple:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns,
            getattr(value, "st_file_attributes", 0))


def _ordinary(path: Path, *, directory: bool) -> os.stat_result:
    try:
        value = path.lstat()
    except OSError as error:
        raise RecoveryRuntimeError(
            "cannot inspect retained path: " + str(error)) from error
    if (stat.S_ISLNK(value.st_mode)
            or getattr(value, "st_file_attributes", 0) & 0x400):
        raise RecoveryRuntimeError(
            "links and reparse points are not admitted: " + path.name)
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(value.st_mode):
        raise RecoveryRuntimeError(
            "retained path has an unsupported file type: " + path.name)
    return value


def _directory(path: Path) -> Path:
    absolute = path.absolute()
    for parent in reversed((absolute, *absolute.parents)):
        _ordinary(parent, directory=True)
    return absolute.resolve(strict=True)


class _Snapshot:
    def __init__(self, root: Path, allowance: int):
        self.root = root
        self.allowance = allowance
        self.read_bytes = 0
        self.files: dict[str, tuple[tuple, dict | None]] = {}
        self.directories: dict[str, tuple[str, ...]] = {}

    def name(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError as error:
            raise RecoveryRuntimeError("inspection path escapes the capture") from error

    def entries(self, directory: Path, maximum: int) -> dict[str, Path]:
        _ordinary(directory, directory=True)
        result: dict[str, Path] = {}
        try:
            with os.scandir(directory) as listing:
                for entry in listing:
                    if len(result) >= maximum:
                        raise RecoveryRuntimeError(
                            "capture directory entry allowance exceeded")
                    path = directory / entry.name
                    value = path.lstat()
                    if (stat.S_ISLNK(value.st_mode)
                            or getattr(value, "st_file_attributes", 0) & 0x400):
                        raise RecoveryRuntimeError(
                            "links and reparse points are not admitted: " +
                            self.name(path))
                    result[entry.name] = path
        except OSError as error:
            raise RecoveryRuntimeError("cannot enumerate retained directory: " +
                                       str(error)) from error
        names = tuple(sorted(result))
        name = self.name(directory)
        previous = self.directories.get(name)
        if previous is not None and previous != names:
            raise RecoveryRuntimeError(
                "capture directory changed during inspection: " + name)
        self.directories[name] = names
        return result

    def read(self, path: Path, limit: int) -> bytes:
        name = self.name(path)
        before = _ordinary(path, directory=False)
        stamp = _fingerprint(before)
        previous = self.files.get(name)
        if previous is not None:
            raise RecoveryRuntimeError("an evidence file was requested twice: " + name)
        self.files[name] = (stamp, None)
        if before.st_size > limit:
            raise _EvidenceError(name + ": file exceeds its byte allowance")
        if before.st_size > self.allowance - self.read_bytes:
            raise RecoveryRuntimeError("capture exceeds the total read allowance")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        chunks: list[bytes] = []
        try:
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "rb") as stream:
                if _fingerprint(os.fstat(stream.fileno())) != stamp:
                    raise RecoveryRuntimeError(
                        "capture file changed before read: " + name)
                remaining = before.st_size
                while remaining:
                    chunk = stream.read(min(8192, remaining))
                    if not chunk:
                        raise RecoveryRuntimeError(
                            "capture file changed during read: " + name)
                    chunks.append(chunk)
                    remaining -= len(chunk)
                    self.read_bytes += len(chunk)
                if _fingerprint(os.fstat(stream.fileno())) != stamp:
                    raise RecoveryRuntimeError(
                        "capture file changed during read: " + name)
        except OSError as error:
            raise RecoveryRuntimeError(
                "cannot read retained artifact: " + name) from error
        data = b"".join(chunks)
        self.files[name] = (stamp, _identity(data))
        return data

    def verify(self) -> None:
        for name, (stamp, _) in self.files.items():
            if _fingerprint(_ordinary(self.root / name, directory=False)) != stamp:
                raise RecoveryRuntimeError(
                    "capture file changed during inspection: " + name)
        for name, names in tuple(self.directories.items()):
            current = self.entries(self.root / name, len(names) + 1)
            if tuple(sorted(current)) != names:
                raise RecoveryRuntimeError(
                    "capture directory changed during inspection: " + name)

    def identities(self) -> dict:
        return {name: identity for name, (_, identity) in self.files.items()
                if identity is not None}


def _json(data: bytes, role: str, *, values: int = 200_000) -> Any:
    return records._parse(data, role, values, 10**300)


def _file_identity(value: Any, *, path: str | None = None) -> dict:
    fields = {"bytes", "sha256"} | ({"path"} if path is not None else set())
    obj = records._object(value, "artifact identity", fields)
    records.integer(obj["bytes"], "artifact bytes", 0, REPORT_BYTES)
    records._digest(obj["sha256"], "artifact digest")
    if path is not None:
        _same(obj["path"], path, "artifact path is not the declared local filename")
    return {key: obj[key] for key in ("bytes", "sha256")}


def _trial_identity(value: Any, expected: dict) -> None:
    obj = records._object(value, "trial identity", set(TRIAL_FIELDS))
    _same(obj, {key: expected[key] for key in TRIAL_FIELDS},
          "trial identity differs from the protocol slot")


def _aggregate(data: bytes, protocol: dict, protocol_identity: dict,
               inventory: list[dict]) -> dict:
    obj = _json(data, "capture aggregate", values=1_000_000)
    _require(isinstance(obj, dict), "aggregate must be an object")
    for field in ("format", "schema_version", "protocol", "implementation", "content",
                  "settings", "trials", "status", "summary", "failure"):
        _require(field in obj, "aggregate is missing " + field)
    _same(obj["format"], "mcts-encounter-policy-evaluation",
          "unsupported aggregate format")
    records.integer(obj["schema_version"], "aggregate schema", 1, 1)
    records._choice(obj["status"], "aggregate status", {"complete", "incomplete"})
    _same(_file_identity(obj["protocol"], path="protocol.json"), protocol_identity,
          "aggregate protocol identity differs from captured protocol bytes")
    records._content_identity(obj["content"])
    implementation = records._object(obj["implementation"], "capture implementation",
                                      {"episode", "capture_files"})
    records._implementation(implementation["episode"])
    files = records._object(implementation["capture_files"], "capture file identities",
                            {"benchmark.py", "tools/encounter_policy_evaluation.py"})
    for value in files.values():
        _file_identity(value)
    _same(obj["settings"], {key: protocol[key] for key in (
        "scenarios", "rounds", "sims", "horizon", "trial_timeout_seconds")},
        "aggregate settings differ from captured protocol")
    trials = records._array(obj["trials"], "aggregate trials",
                            len(inventory), len(inventory))
    for retained, expected in zip(trials, inventory, strict=True):
        _require(isinstance(retained, dict), "aggregate trial must be an object")
        _same({key: retained.get(key) for key in TRIAL_FIELDS},
              {key: expected[key] for key in TRIAL_FIELDS},
              "aggregate trial identity differs from the protocol inventory")
        _same(retained.get("receipt"), expected["receipt"],
              "aggregate receipt path differs")
        records._choice(retained.get("status"), "aggregate trial status",
                        STATUSES | {"not_attempted"})
    freeze = protocol.get("metadata", {}).get("freeze")
    if freeze is not None:
        _require(isinstance(freeze, dict), "protocol source freeze must be an object")
        _same(freeze.get("implementation"), obj["implementation"],
              "protocol and aggregate implementation freeze differ")
        _same(freeze.get("content"), obj["content"],
              "protocol and aggregate content freeze differ")
    return obj


def _transport(receipt: dict, entries: dict[str, Path],
               snapshot: _Snapshot) -> dict | None:
    value = receipt["transport"]
    if value is None:
        _require(receipt["elapsed_subprocess_seconds"] is None,
                 "missing transport has nonnull elapsed time")
        return None
    _require(isinstance(value, dict), "transport must be an object or null")
    required = {"returncode", "elapsed_subprocess_seconds", "timeout_diagnostics",
                "stdout", "stderr", "stdout_observed_bytes", "stderr_observed_bytes",
                "stdout_truncated", "stderr_truncated"}
    _require(required <= set(value), "transport is missing required fields")
    records._number(value["elapsed_subprocess_seconds"], "transport elapsed", 0, 10**12)
    _same(receipt["elapsed_subprocess_seconds"], value["elapsed_subprocess_seconds"],
          "receipt and transport elapsed times differ")
    if value["returncode"] is not None:
        records.integer(value["returncode"], "transport return code", -(2**63), 2**63)
    _require(value["timeout_diagnostics"] is None or
             isinstance(value["timeout_diagnostics"], dict),
             "invalid timeout diagnostics")
    identities = {}
    for role, maximum in (("stdout", records.RECORD_BYTES),
                          ("stderr", capture.DIAGNOSTIC_BYTES)):
        filename = role + ".raw"
        identity = _file_identity(value[role], path=filename)
        _require(filename in entries,
                 "claimed transport artifact is missing: " + filename)
        data = snapshot.read(entries[filename], maximum)
        _same(identity, _identity(data),
              "transport artifact identity differs: " + filename)
        records.integer(value[role + "_observed_bytes"],
                        "observed transport bytes", 0, 2**63)
        records._boolean(value[role + "_truncated"], "transport truncation")
        _require(value[role + "_observed_bytes"] >= len(data),
                 "observed transport bytes are smaller than retained bytes")
        if not value[role + "_truncated"]:
            _same(value[role + "_observed_bytes"], len(data),
                  "untruncated transport size differs from retained artifact")
        identities[role] = identity
    return {"claims": value, "identities": identities}


def _sidecars(receipt: dict, entries: dict[str, Path], snapshot: _Snapshot) -> None:
    _same(receipt.get("artifacts"), ARTIFACTS, "receipt artifact inventory differs")
    expected = {
        "timing": {"elapsed_subprocess_seconds": receipt["elapsed_subprocess_seconds"],
                   "transport": receipt["transport"]},
        "work": {"work": receipt["work"]}, "error": {"error": receipt["error"]},
    }
    for role, filename in ARTIFACTS.items():
        _require(filename in entries, "claimed sidecar is missing: " + filename)
        value = _json(snapshot.read(entries[filename], RECEIPT_BYTES), filename)
        _same(value, expected[role], "sidecar differs from receipt: " + filename)


def _hp_outcome(record: dict) -> int | None:
    state = record["final"]["state"]
    if state["player"]["hp"] <= 0:
        return 0
    if all(enemy["hp"] <= 0 for enemy in state["enemies"]):
        return 1
    return None


def _owner_consistency(value: Any) -> None:
    """Reject explicit failed owner claims without authenticating any OS event."""
    _require(isinstance(value, dict), "managed transport owner must be an object")
    _same(value.get("format"), "mcts-owned-process", "unsupported transport owner")
    records.integer(value.get("schema_version"), "transport owner schema", 1, 1)
    _require(value.get("established") is True and value.get("failure_kind") is None
             and value.get("error") is None,
             "complete receipt contradicts managed owner failure claims")
    launch = value.get("launch")
    _require(isinstance(launch, dict), "managed owner has no launch claims")
    for field in ("created_suspended", "membership_verified_before_resume",
                  "limits_verified_before_resume", "primary_thread_resumed",
                  "job_handle_noninheritable", "process_handles_noninheritable",
                  "stdio_handle_list_only"):
        _require(launch.get(field) is True,
                 "complete receipt contradicts owner launch claim: " + field)
    cleanup = value.get("cleanup")
    _require(isinstance(cleanup, dict), "managed owner has no cleanup claims")
    for field in ("retired", "worker_reaped", "job_empty", "readers_retired",
                  "handles_closed"):
        _require(cleanup.get(field) is True,
                 "complete receipt contradicts owner cleanup claim: " + field)
    if "member_handles_signaled" in cleanup:
        _require(cleanup["member_handles_signaled"] is True,
                 "complete receipt contradicts observed member handle retirement")
    _same(cleanup.get("final_active_processes"), 0,
          "complete receipt has a nonempty owner Job claim")
    _same(cleanup.get("errors"), [], "complete receipt has owner cleanup errors")


def _complete(receipt: dict, trial: dict, protocol: dict, aggregate: dict | None,
              entries: dict[str, Path], snapshot: _Snapshot,
              transport: dict | None) -> tuple[dict, dict]:
    _require(transport is not None, "complete receipt has no transport evidence")
    claims = transport["claims"]
    _require(claims["returncode"] == 0 and claims["timeout_diagnostics"] is None
             and not claims["stdout_truncated"] and not claims["stderr_truncated"]
             and not claims.get("retirement_errors"),
             "complete receipt has failed, incomplete or truncated transport")
    if "owner" in claims:
        _owner_consistency(claims["owner"])
    _require(receipt["error"] is None, "complete receipt has an error")
    identity = _file_identity(receipt["episode"], path="episode.json")
    _require("episode.json" in entries, "claimed episode artifact is missing")
    data = snapshot.read(entries["episode.json"], records.RECORD_BYTES)
    _same(identity, _identity(data), "episode artifact identity differs")
    record = records.validate_record(_json(data, "trial episode"))
    _require(record["schema_version"] == 2,
             "encounter recovery requires schema 2 episodes")
    _same(record["configuration"], records._configuration(
        protocol["rounds"], protocol["sims"], protocol["horizon"],
        trial["search_seed"], trial["policy"]),
        "episode configuration differs from protocol slot")
    _same(record["scenario"]["name"], trial["scenario"], "episode scenario differs")
    _same(record["scenario"]["environment_seed"], trial["environment_seed"],
          "episode environment seed differs")
    if aggregate is not None:
        _same(record["content"], aggregate["content"],
              "episode content differs from collection")
        _same(record["implementation"], aggregate["implementation"]["episode"],
              "episode implementation differs from collection")
    # Successful producer stdout is the same canonical episode envelope. Its
    # independent file hash was checked before the episode was read.
    _same(transport["identities"]["stdout"], _identity(records.output_bytes(record)),
          "successful stdout differs from canonical admitted episode")
    final = record["final"]
    _require(final["terminal_result"] == _hp_outcome(record),
             "stored terminal result contradicts final player or enemy HP")
    outcome = {name: final[name] for name in (
        "terminal_result", "termination", "score", "rounds")}
    _same(receipt["outcome"], outcome, "receipt outcome differs from admitted episode")
    rows = [step["work"] for step in record["steps"]]
    diagnostics = [step["search_diagnostics"] for step in record["steps"]]
    work = {
        "decision_records": rows, "decision_diagnostics": diagnostics,
        "simulations": sum(row["simulations"] for row in rows),
        "transitions": sum(row["transitions"] for row in rows),
        "unused_transitions": sum(row["unused_transitions"] for row in rows),
        "shortfalls": [], "uniform_fallback_decisions": sum(
            row["allocation_mode"] == "uniform_fallback" for row in diagnostics),
    }
    _same(receipt["work"], work, "receipt work differs from admitted episode decisions")
    return outcome, {key: work[key] for key in (
        "simulations", "transitions", "unused_transitions",
        "uniform_fallback_decisions")}


def _initial_trial(retained: dict, expected: dict) -> bool:
    return records._equal(retained, expected)


def _aggregate_claim(retained: dict, expected: dict, receipt: dict,
                      receipt_identity: dict,
                      outcome: dict | None, work: dict | None) -> None:
    if retained["status"] == "not_attempted":
        _require(_initial_trial(retained, expected),
                 "not_attempted aggregate row has noninitial or affirmative claims")
        return  # The exact initial row can be stale after an atomic receipt.
    _same(retained["status"], receipt["status"],
          "aggregate and receipt statuses differ")
    _same(retained.get("receipt_identity"), receipt_identity,
          "aggregate receipt identity differs from retained bytes")
    _same(retained.get("episode"), receipt["episode"],
          "aggregate episode claim differs")
    _same(retained.get("elapsed_subprocess_seconds"),
          receipt["elapsed_subprocess_seconds"],
          "aggregate elapsed claim differs")
    if outcome is not None:
        for key, value in outcome.items():
            _same(retained.get(key), value, "aggregate outcome differs: " + key)
        _same(retained.get("work"), work, "aggregate work differs")


def _slot(trial: dict, protocol: dict, protocol_identity: dict, aggregate: dict | None,
          directory: Path | None, snapshot: _Snapshot) -> dict:
    result = {"trial": {key: trial[key] for key in TRIAL_FIELDS},
              "classification": "no_execution_evidence", "recorded_status": None,
              "start": "unknown", "outcome": None, "work": None,
              "receipt_identity": None, "admission_intent_identity": None,
              "issues": [], "retained_artifacts": []}
    retained = aggregate["trials"][trial["index"]] if aggregate is not None else None
    if directory is None:
        if retained is not None and not _initial_trial(retained, trial):
            result["classification"] = "corrupt_or_contradictory"
            result["issues"].append(
                "Aggregate has affirmative or noninitial claims "
                "without a trial directory.")
            return result
        result["issues"].append(
            "No retained execution evidence. Whether work started is unknown.")
        return result
    result["classification"] = "incomplete_attempt"
    entries = snapshot.entries(directory, 24)
    result["retained_artifacts"] = sorted(entries)
    try:
        if retained is not None and retained["status"] == "not_attempted":
            _require(_initial_trial(retained, trial),
                     "not_attempted aggregate row has noninitial or affirmative claims")
        unknown = (set(entries) - TRIAL_FILES -
                   {name + ".pending" for name in TRIAL_FILES})
        _require(not unknown,
                 "unexpected trial artifacts: " + ", ".join(sorted(unknown)))
        for name, path in entries.items():
            _ordinary(path, directory=False)
            if name.endswith(".pending"):
                snapshot.read(path, records.RECORD_BYTES)
        intent = entries.get("admission-intent.json")
        if intent is not None:
            data = snapshot.read(intent, RECEIPT_BYTES)
            obj = records._object(_json(data, "admission intent"), "admission intent", {
                "format", "schema_version", "trial", "protocol"})
            _same(obj["format"], "mcts-encounter-trial-intent",
                  "unsupported intent format")
            records.integer(obj["schema_version"], "intent schema", 1, 1)
            _trial_identity(obj["trial"], trial)
            _same(_file_identity(obj["protocol"]), protocol_identity,
                  "intent protocol identity differs")
            result["admission_intent_identity"] = _identity(data)
            result["start"] = "admission_intent_retained_execution_unknown"
        path = entries.get("receipt.json")
        if path is None:
            _require(retained is None or _initial_trial(retained, trial),
                     "aggregate has affirmative claims "
                     "without a retained final receipt")
            # Orphan prefixes are useful evidence, but never complete outcomes.
            for name in ("stdout.raw", "stderr.raw", "episode.json", "timing.json",
                         "work.json", "error.json"):
                if name in entries:
                    maximum = (capture.DIAGNOSTIC_BYTES if name == "stderr.raw"
                               else records.RECORD_BYTES)
                    snapshot.read(entries[name], maximum)
            result["issues"].append(
                "Attempt artifacts have no final receipt. "
                "Outcome and work are unknown.")
            return result
        data = snapshot.read(path, RECEIPT_BYTES)
        receipt = _json(data, "trial receipt")
        _require(isinstance(receipt, dict), "trial receipt must be an object")
        required = {"format", "schema_version", "trial", "status",
                    "elapsed_subprocess_seconds", "transport", "episode", "error",
                    "outcome", "work", "artifacts"}
        _require(required <= set(receipt), "receipt is missing required fields")
        _same(receipt["format"], "mcts-encounter-trial-receipt",
              "unsupported receipt format")
        records.integer(receipt["schema_version"], "receipt schema", 1, 1)
        _trial_identity(receipt["trial"], trial)
        records._choice(receipt["status"], "receipt status", STATUSES)
        result["recorded_status"] = receipt["status"]
        result["receipt_identity"] = _identity(data)
        result["start"] = "attempt_receipt_retained_execution_not_authenticated"
        transport = _transport(receipt, entries, snapshot)
        if transport is None:
            for name, maximum in (("stdout.raw", records.RECORD_BYTES),
                                   ("stderr.raw", capture.DIAGNOSTIC_BYTES)):
                if name in entries:
                    snapshot.read(entries[name], maximum)
        _sidecars(receipt, entries, snapshot)
        outcome = work = None
        if receipt["status"] == "complete":
            outcome, work = _complete(receipt, trial, protocol, aggregate,
                                      entries, snapshot, transport)
        else:
            _require(receipt["episode"] is None and receipt["outcome"] is None
                     and receipt["work"] is None,
                     "incomplete receipt claims complete episode, outcome or work")
            _require("episode.json" not in entries,
                     "incomplete receipt has an unclaimed episode artifact")
            _require(receipt["error"] is not None,
                     "incomplete receipt has no error diagnostic")
        if aggregate is not None:
            _aggregate_claim(aggregate["trials"][trial["index"]], trial, receipt,
                              result["receipt_identity"], outcome, work)
        if receipt["status"] == "complete" and aggregate is not None:
            result.update(classification="complete_admitted",
                          outcome=outcome, work=work)
        elif receipt["status"] == "complete":
            result["issues"].append(
                "Complete claims cannot be admitted without retained collection "
                "source and content identity.")
        else:
            result["issues"].append(
                "Incomplete attempt retained. No outcome or work is substituted.")
        return result
    except (_EvidenceError, records.EpisodeInputError,
            records.EpisodeRuntimeError, capture.EncounterRuntimeError) as error:
        result.update(classification="corrupt_or_contradictory",
                      outcome=None, work=None)
        result["issues"].append(str(error)[:2048])
        return result


def _summary(trials: list[dict]) -> dict:
    counts = {name: sum(row["classification"] == name for row in trials) for name in (
        "complete_admitted", "incomplete_attempt", "corrupt_or_contradictory",
        "no_execution_evidence")}
    by_policy = {}
    for policy in ("uct", "sequential_halving"):
        selected = [row for row in trials if row["trial"]["policy"] == policy]
        complete = [row for row in selected
                    if row["classification"] == "complete_admitted"]
        by_policy[policy] = {
            "intended_trials": len(selected), "complete_admitted": len(complete),
            "unknown_or_unadmitted_outcomes": len(selected) - len(complete),
            "terminal_wins": sum(row["outcome"]["terminal_result"] == 1
                                 for row in complete),
            "terminal_losses": sum(row["outcome"]["terminal_result"] == 0
                                   for row in complete),
            "round_limit_nonwins": sum(row["outcome"]["termination"] == "round_limit"
                                        for row in complete),
            "known_simulations": sum(row["work"]["simulations"] for row in complete),
            "known_transitions": sum(row["work"]["transitions"] for row in complete),
        }
    return {"intended_trials": len(trials), "classifications": counts,
            "policies": by_policy}


def _aggregate_summary(trials: list[dict]) -> dict:
    """Recreate the existing aggregate's claims from admitted individual evidence."""
    values = []
    for trial in trials:
        complete = trial["classification"] == "complete_admitted"
        values.append({"policy": trial["trial"]["policy"],
                       "status": "complete" if complete else "unknown",
                       **(trial["outcome"] if complete else {}),
                       "work": trial["work"]})
    return capture._summary(values)


def recover_capture(capture_directory: Path, report_path: Path, *,
                    max_read_bytes: int = READ_BYTES) -> dict:
    """Create a bounded inspection report without changing a retained capture.

    Use a stopped local capture. The report describes a stable observed snapshot,
    not execution authentication, containment, transition replay or valid sampling.
    """
    records.integer(max_read_bytes, "recovery read allowance", 1, READ_BYTES)
    root = _directory(capture_directory)
    output_parent = _directory(report_path.absolute().parent)
    output = output_parent / report_path.name
    if output.is_relative_to(root):
        raise RecoveryRuntimeError("recovery output must be outside the capture")
    if os.path.lexists(output):
        raise RecoveryRuntimeError("recovery output must be a new file")
    snapshot = _Snapshot(root, max_read_bytes)
    entries = snapshot.entries(root, 16)
    if "protocol.json" not in entries:
        raise RecoveryRuntimeError(
            "captured protocol.json is required to reconstruct inventory")
    try:
        captured = snapshot.read(entries["protocol.json"], capture.PROTOCOL_BYTES)
        protocol = capture.validate_protocol(
            _json(captured, "captured protocol", values=100_000))
    except (_EvidenceError, records.EpisodeInputError) as error:
        raise RecoveryRuntimeError(
            "cannot reconstruct the retained inventory: " + str(error)) from error
    protocol_identity = _identity(captured)
    inventory = capture._inventory(protocol)
    issues: list[str] = []
    notices: list[str] = []
    allowed = {"protocol.json", "results.json", "trials", "protocol.json.pending",
               "results.json.pending"}
    unexpected = sorted(set(entries) - allowed)
    if unexpected:
        issues.append("Unexpected capture entries: " + ", ".join(unexpected))
    aggregate = None
    aggregate_identity = None
    if "results.json" in entries:
        try:
            data = snapshot.read(entries["results.json"], REPORT_BYTES)
            aggregate_identity = _identity(data)
            aggregate = _aggregate(data, protocol, protocol_identity, inventory)
        except (_EvidenceError, records.EpisodeInputError) as error:
            issues.append("Aggregate cannot establish collection identity: " +
                          str(error)[:2048])
    else:
        issues.append(
            "Aggregate is missing. Collection source and content identity are unknown.")
    for name in ("protocol.json.pending", "results.json.pending"):
        if name in entries:
            snapshot.read(entries[name], REPORT_BYTES)
            issues.append("Uncommitted aggregate or protocol artifact retained: " +
                          name)
    directories: dict[str, Path] = {}
    if "trials" in entries:
        directories = snapshot.entries(entries["trials"], len(inventory) + 1)
    else:
        issues.append("Trial directory is missing. No execution start is inferred.")
    names = {f"{trial['index']:05d}" for trial in inventory}
    extra = sorted(set(directories) - names)
    if extra:
        issues.append("Trial directories outside the protocol inventory: " +
                      ", ".join(extra))
    trials = [_slot(trial, protocol, protocol_identity, aggregate,
                    directories.get(f"{trial['index']:05d}"), snapshot)
              for trial in inventory]
    if aggregate is not None and aggregate["status"] == "complete":
        if any(row["classification"] != "complete_admitted" for row in trials):
            issues.append(
                "Aggregate claims completion without all intended trials admitted.")
        if not records._equal(aggregate["summary"], _aggregate_summary(trials)):
            issues.append(
                "Complete aggregate summary contradicts admitted trial evidence.")
        if aggregate["failure"] is not None:
            issues.append("Complete aggregate also records a collection failure.")
    elif aggregate is not None:
        initial = (all(_initial_trial(retained, expected)
                       for retained, expected in zip(aggregate["trials"], inventory,
                                                     strict=True))
                   and records._equal(aggregate["summary"], capture._summary(inventory))
                   and aggregate["failure"] is None
                   and aggregate.get("elapsed_capture_seconds") is None)
        if not records._equal(aggregate["summary"], _aggregate_summary(trials)):
            if initial:
                # This exact initial snapshot can precede atomic receipts.
                notices.append("Initial aggregate summary is stale. "
                               "Individual retained evidence is inspected.")
            else:
                issues.append("Incomplete aggregate has affirmative summary claims "
                              "that contradict admitted trial evidence.")
    snapshot.verify()
    summary = _summary(trials)
    report = {
        "format": "mcts-encounter-recovery", "schema_version": 1,
        "status": "inspected", "source_protocol": protocol_identity,
        "source_aggregate": aggregate_identity,
        "collection_identity_available": aggregate is not None,
        "inventory_evidence_consistent": not issues and not
            summary["classifications"]["corrupt_or_contradictory"],
        "summary": summary, "issues": issues, "notices": notices, "trials": trials,
        "observed_inputs": snapshot.identities(),
        "limits": {"max_read_bytes": max_read_bytes, "read_bytes": snapshot.read_bytes,
                   "protocol_bytes": capture.PROTOCOL_BYTES,
                   "episode_bytes": records.RECORD_BYTES,
                   "receipt_bytes": RECEIPT_BYTES,
                   "aggregate_bytes": REPORT_BYTES, "report_bytes": REPORT_BYTES},
        "boundaries": {
            "original_evidence_modified": False, "search_performed": False,
            "replay_performed": False, "retry_performed": False,
            "os_ownership_established": False, "origin_authenticated": False,
            "scientific_validity_established": False,
            "statistical_completeness_established": False,
            "absent_artifacts_prove_never_started": False,
            "scope": "Retained consistency inspection of a stopped known local "
                     "capture. Hashes bind observed bytes. No control or execution "
                     "claim is authenticated.",
        },
    }
    emitted = records.canonical(report) + b"\n"
    if len(emitted) > REPORT_BYTES:
        raise RecoveryRuntimeError("recovery report exceeds its byte allowance")
    try:
        with output.open("xb") as stream:
            if stream.write(emitted) != len(emitted):
                raise RecoveryRuntimeError("recovery report write was incomplete")
            stream.flush()
    except OSError as error:
        raise RecoveryRuntimeError(
            "recovery report could not be created: " + str(error)) from error
    return report
