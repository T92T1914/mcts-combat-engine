"""Execute finite installed and native acceptance against the selected Linux owner.

This is an acceptance driver, not a companion payload or scientific study.
Expected dispositions are fixed before admission. Native counters and retirement
observations supply the pressure evidence; command exit codes do not.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import select
import shutil
import stat
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import linux_container as owner
from tools import linux_episode_worker as worker

MIB = 1_048_576
EVIDENCE_BYTES = 524_288
EVIDENCE_FILE_BYTES = 131_072
EVIDENCE_FILES = 64
EXPECTED = {
    "complete": "complete",
    "memory": "memory_pressure",
    "pids": "process_pressure",
    "escape": "complete",
    "output": "output_limit",
    "wall": "timeout",
    "cancel": "cancelled",
    "controller_loss": "alarm_exit_124_then_explicit_recovery",
    "control": "complete",
    "error": "error",
    "refusal": "refused",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def encoded(value: dict) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def write(path: Path, body: bytes) -> None:
    require(len(body) <= 2 * MIB, "acceptance artifact exceeds 2 MiB")
    with path.open("xb") as sink:
        require(sink.write(body) == len(body), "incomplete acceptance write")


def snapshot(path: Path) -> dict:
    value = path.lstat()
    require(
        stat.S_ISREG(value.st_mode) and value.st_size <= 16 * MIB,
        "acceptance input is not an ordinary bounded file",
    )
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "bytes": value.st_size,
        "sha256": digest,
        "device": value.st_dev,
        "inode": value.st_ino,
        "mtime_ns": value.st_mtime_ns,
    }


def retain(path: Path, value: dict) -> None:
    pending = path.with_suffix(".pending")
    write(pending, encoded(value))
    os.replace(pending, path)


def emit_retained_evidence(root: Path, acceptance: dict) -> None:
    """Publish only bounded known public evidence before ephemeral files vanish."""
    envelope = {
        "format": "mcts-linux-native-evidence",
        "schema_version": 1,
        "retention_status": "complete",
        "file_limit": EVIDENCE_FILES,
        "file_bytes_limit": EVIDENCE_FILE_BYTES,
        "encoded_bytes_limit": EVIDENCE_BYTES,
        "json_files": {},
        "raw_streams": {},
    }
    paths = {
        "acceptance.json",
        "expected.json",
        "complete/consumer-output/ownership.json",
        "complete/consumer-output/record.json",
        "complete/consumer-output/replay.json",
        "complete/consumer-output/consumer.json",
        "escape/observed-members.json",
        "controller-loss/ownership.json",
        "controller-loss/alarm-observation.json",
        "controller-loss/explicit-recovery.json",
    }
    fixture_cases = (
        "refusal",
        "control",
        "error",
        "memory",
        "pids",
        "escape",
        "output",
        "wall",
        "cancel",
    )
    paths.update(name + "/ownership.json" for name in fixture_cases)
    streams = {
        "complete/cli.stdout",
        "complete/cli.stderr",
        "complete/consumer-output/stdout.log",
        "complete/consumer-output/stderr.log",
    }
    streams.update(
        name + "/" + role + ".raw"
        for name in fixture_cases
        for role in ("stdout", "stderr")
    )
    parsed_stdout = {
        name + "/stdout.raw"
        for name in fixture_cases
        if name not in {"refusal", "output"}
    }
    count = 0
    read_bytes = 0

    def existing_body(relative: str) -> bytes | None:
        nonlocal count, read_bytes
        path = root
        for component in relative.split("/")[:-1]:
            path = path / component
            try:
                require(
                    stat.S_ISDIR(path.lstat().st_mode),
                    "evidence ancestor is not an ordinary directory",
                )
            except FileNotFoundError:
                return None
        path = path / relative.split("/")[-1]
        try:
            before = path.lstat()
        except FileNotFoundError:
            return None
        require(
            stat.S_ISREG(before.st_mode) and before.st_size <= EVIDENCE_FILE_BYTES,
            "known retained evidence is not an ordinary bounded file",
        )
        count += 1
        read_bytes += before.st_size
        require(
            count <= EVIDENCE_FILES and read_bytes <= EVIDENCE_BYTES,
            "retained evidence read allowance exceeded",
        )
        with path.open("rb") as source:
            body = source.read(EVIDENCE_FILE_BYTES + 1)
        after = path.lstat()
        require(
            len(body) == before.st_size
            and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
            "retained evidence changed during inspection",
        )
        return body

    failure = None
    try:
        for relative in sorted(paths):
            body = existing_body(relative)
            if body is not None:
                envelope["json_files"][relative] = {
                    **worker.identity(body),
                    "value": json.loads(body),
                }
        for relative in sorted(streams):
            body = existing_body(relative)
            if body is not None:
                observed = worker.identity(body)
                if relative in parsed_stdout:
                    observed["parsed_rows"] = []
                    observed["parse_errors"] = []
                    for index, line in enumerate(
                        body.decode("utf-8", "replace").splitlines()
                    ):
                        try:
                            observed["parsed_rows"].append(json.loads(line))
                        except ValueError:
                            # A killed producer may leave a partial public JSON
                            # line. Preserve that observation without inventing
                            # a parsed row or dropping its ownership evidence.
                            observed["parse_errors"].append(
                                {
                                    "line": index,
                                    "public_prefix": line[:512],
                                    "prefix_truncated": len(line) > 512,
                                }
                            )
                envelope["raw_streams"][relative] = observed
        envelope.update(observed_files=count, read_bytes=read_bytes)
        emitted = encoded(envelope)
        require(
            len(emitted) + 48 <= EVIDENCE_BYTES,
            "encoded evidence envelope exceeds allowance",
        )
    except Exception as error:
        failure = {"type": type(error).__name__, "message": str(error)[:2048]}
        acceptance["status"] = "retention_failed"
        acceptance["retention_error"] = failure
        retain(root / "acceptance.json", acceptance)
        # Preserve the actual dispositions and error even when full evidence
        # cannot be emitted. This smaller envelope cannot claim acceptance.
        envelope = {
            "format": "mcts-linux-native-evidence",
            "schema_version": 1,
            "retention_status": "failed",
            "retention_error": failure,
            "acceptance": acceptance,
            "observed_files": count,
            "read_bytes": read_bytes,
            "full_evidence_retained": False,
        }
        emitted = encoded(envelope)
        if len(emitted) + 48 > EVIDENCE_BYTES:
            emitted = encoded(
                {
                    "format": "mcts-linux-native-evidence",
                    "schema_version": 1,
                    "retention_status": "failed",
                    "retention_error": failure,
                    "full_evidence_retained": False,
                }
            )
    print("G4_NATIVE_EVIDENCE_BEGIN", flush=True)
    print(emitted.decode("utf-8"), end="", flush=True)
    print("G4_NATIVE_EVIDENCE_END", flush=True)
    if failure is not None:
        raise ValueError("native evidence retention failed: " + failure["message"])


def lines(body: bytes) -> list[dict]:
    return [json.loads(line) for line in body.decode().splitlines() if line]


def events(receipt: dict, key: str, counter: str) -> tuple[int, int]:
    rows = receipt["samples"]
    require(len(rows) >= 2, "native pressure evidence lacks baseline and final samples")
    observed = [row[key][counter] for row in rows]
    require(
        all(type(value) is int and value >= 0 for value in observed),
        "native event sample is not an explicit nonnegative integer",
    )
    return observed[0], max(observed)


def retired(receipt: dict) -> None:
    require(
        receipt["cleanup"]["complete"] is True
        and receipt["cleanup"]["container_absent"] is True
        and receipt["cleanup"]["cgroup_empty_or_absent"] is True
        and receipt["cleanup"]["pidfd_signalled"] is True,
        "native retirement is incomplete",
    )


def retain_result(directory: Path, receipt: dict) -> dict:
    for name, body in receipt.pop("streams", {}).items():
        require(name in {"stdout", "stderr"}, "unexpected native stream")
        write(directory / (name + ".raw"), body)
    for name, body in receipt.pop("artifacts", {}).items():
        require(name in worker.ARTIFACT_NAMES, "unexpected native artifact")
        write(directory / name, body)
    retain(directory / "ownership.json", receipt)
    return receipt


class MemberWitness:
    """Pin observed members of only the already verified owned subtree."""

    def __init__(self, native: dict):
        self.native = native
        self.stop = threading.Event()
        self.members: dict[int, tuple[dict, int]] = {}
        self.errors: list[str] = []
        self.thread = threading.Thread(target=self.observe, daemon=True)
        self.thread.start()

    def observe(self) -> None:
        try:
            _, components = owner.native.hierarchy("0::" + self.native["cgroup"] + "\n")
            directory = owner.native.cgroup_path(owner.native.mount_root(), components)
            for _ in range(100):
                if self.stop.is_set() or not directory.exists():
                    return
                stamp = directory.stat()
                require(
                    [stamp.st_dev, stamp.st_ino] == self.native["stamp"],
                    "observed cgroup identity changed",
                )
                for pid in owner.sample(directory)["members"]:
                    if pid == self.native["host_pid"] or pid in self.members:
                        continue
                    try:
                        status = dict(
                            line.split(":", 1)
                            for line in Path(f"/proc/{pid}/status")
                            .read_text()
                            .splitlines()
                        )
                        relative = Path(f"/proc/{pid}/cgroup").read_text()
                        namespace = Path(f"/proc/{pid}/ns/pid").stat().st_ino
                        starttime = owner.native.starttime(pid)
                        descriptor = os.pidfd_open(pid)
                    except (FileNotFoundError, ProcessLookupError):
                        continue
                    try:
                        require(
                            relative == "0::" + self.native["cgroup"] + "\n"
                            and namespace == self.native["namespaces"]["pid"]
                            and owner.native.starttime(pid) == starttime,
                            "observed member identity changed",
                        )
                        row = {
                            "host_pid": pid,
                            "namespace_pid": int(status["NSpid"].split()[-1]),
                            "starttime": starttime,
                            "cgroup": self.native["cgroup"],
                            "pid_namespace": namespace,
                        }
                        self.members[pid] = (row, descriptor)
                    except Exception:
                        os.close(descriptor)
                        raise
                self.stop.wait(0.02)
        except FileNotFoundError:
            # Normal owner retirement can remove the already pinned cgroup
            # between samples. Member pidfds remain the exit observations.
            return
        except Exception as error:
            self.errors.append(type(error).__name__ + ": " + str(error)[:240])

    def finish(self) -> dict:
        self.stop.set()
        self.thread.join(timeout=1)
        result = {
            "errors": self.errors,
            "reader_retired": not self.thread.is_alive(),
            "members": [],
        }
        for row, descriptor in self.members.values():
            poll = select.poll()
            poll.register(descriptor, select.POLLIN)
            row["pidfd_signalled"] = bool(poll.poll(0))
            os.close(descriptor)
            result["members"].append(row)
        return result


def complete_case(wheel: Path, archive: Path, root: Path, image_id: str) -> dict:
    directory = root / "complete"
    directory.mkdir()
    with zipfile.ZipFile(archive) as source:
        worker_body = source.read("tools/linux_episode_worker.py")
    companion = directory / "relocated-companion"
    manifest = worker.unpack(archive, companion, worker_body)
    working = directory / "unrelated-working-directory"
    working.mkdir()
    output = directory / "consumer-output"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(companion / "linux_episode.py"),
            "--wheel",
            str(wheel),
            "--companion",
            str(archive),
            "--output",
            str(output),
            "--image-id",
            image_id,
            "--wall-seconds",
            "30",
        ],
        cwd=working,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=55,
        shell=False,
    )
    write(directory / "cli.stdout", result.stdout)
    write(directory / "cli.stderr", result.stderr)
    receipt = json.loads((output / "ownership.json").read_bytes())
    require(
        result.returncode == 0 and receipt["outcome"]["status"] == "complete",
        "public installed consumer did not complete",
    )
    retired(receipt)
    require(receipt["input_files_unchanged"] is True, "public consumer inputs changed")
    consumer = json.loads((output / "consumer.json").read_bytes())
    record_body = (output / "record.json").read_bytes()
    replay_body = (output / "replay.json").read_bytes()
    record = json.loads(record_body)
    replay = json.loads(replay_body)
    require(
        consumer["engine_files"] == manifest["reference_engine"]["files"]
        and consumer["source_commit"] == manifest["source_commit"]
        and consumer["source_tree"] == manifest["source_tree"]
        and consumer["record"] == worker.identity(record_body)
        and consumer["replay"] == worker.identity(replay_body),
        "installed consumer source or retained record identities differ",
    )
    require(
        consumer["inputs_before"] == consumer["inputs_after"]
        and consumer["actual_rounds"] == 2
        and consumer["actual_simulations"] == 4
        and consumer["actual_transitions"] == 4
        and consumer["search_guarded_replay"] is True,
        "fixed installed consumer disposition differs",
    )
    require(
        Path(consumer["engine_origin"]).is_relative_to(consumer["purelib"])
        and all(
            Path(path).is_relative_to(Path(consumer["companion_origin"]) / "game")
            for path in consumer["game_module_origins"].values()
        )
        and len(consumer["game_module_origins"]) == 4,
        "actual installed/relocated origins differ",
    )
    require(
        record["schema_version"] == 2
        and len(record["steps"]) == 2
        and sum(step["work"]["simulations"] for step in record["steps"]) == 4
        and sum(step["work"]["transitions"] for step in record["steps"]) == 4
        and replay["status"] == "environment_replay_verified"
        and replay["search_recomputed"] is False,
        "retained record/replay did not meet the independent allowance oracle",
    )
    return {
        "expected": EXPECTED["complete"],
        "observed": receipt["outcome"],
        "receipt": str(output / "ownership.json"),
        "source_commit": manifest["source_commit"],
        "rounds": 2,
        "simulations": 4,
        "transitions": 4,
    }


def refusal_case(payload: Path, root: Path, image_id: str) -> dict:
    directory = root / "refusal"
    directory.mkdir()
    result = owner.run_owned_container(
        payload,
        ["python3", "-I", "-B", "/tmp/payload/fixture.py", "hold"],
        image_id=image_id,
        memory_bytes=32 * MIB,
    )
    receipt = retain_result(directory, result)
    require(
        receipt["outcome"]["status"] == "refused"
        and receipt["work_admitted"] is False
        and receipt["ownership"]["container_id"] is None
        and receipt["ownership"]["native"] is None,
        "unsupported requested limit was not refused before creation/admission",
    )
    return {
        "expected": EXPECTED["refusal"],
        "observed": receipt["outcome"],
        "scope": "unsupported requested limit on the qualified host",
        "receipt": str(directory / "ownership.json"),
    }


def fixture_case(name: str, payload: Path, root: Path, image_id: str) -> dict:
    directory = root / name
    directory.mkdir()
    action = "hold" if name in {"wall", "cancel"} else name
    kwargs = {
        "wall_seconds": 20,
        "stdout_limit": 65_536,
        "stderr_limit": 65_536,
        "output_limit": 131_072,
    }
    cancellation = threading.Event()
    timer = None
    member_witness = None

    def callback(receipt: dict) -> None:
        nonlocal timer, member_witness
        retain(directory / "ownership.json", receipt)
        if (
            name == "escape"
            and receipt.get("phase") == "admitted"
            and member_witness is None
        ):
            member_witness = MemberWitness(receipt["ownership"]["native"])
        if name == "cancel" and receipt.get("phase") == "admitted" and timer is None:
            timer = threading.Timer(0.5, cancellation.set)
            timer.daemon = True
            timer.start()

    if name == "memory":
        kwargs["memory_bytes"] = 128 * MIB
    elif name == "control":
        kwargs.update(
            memory_bytes=128 * MIB,
            pids_max=16,
            stdout_limit=4096,
            stderr_limit=4096,
            output_limit=8192,
        )
    elif name == "pids":
        kwargs["pids_max"] = 16
    elif name == "output":
        kwargs.update(stdout_limit=4096, stderr_limit=4096, output_limit=8192)
    elif name == "wall":
        kwargs["wall_seconds"] = 2
    try:
        result = owner.run_owned_container(
            payload,
            ["python3", "-I", "-B", "/tmp/payload/fixture.py", action],
            image_id=image_id,
            receipt_callback=callback,
            cancel=cancellation,
            **kwargs,
        )
    finally:
        if timer is not None:
            timer.cancel()
            timer.join(timeout=1)
        members = member_witness.finish() if member_witness is not None else None
        if members is not None:
            write(directory / "observed-members.json", encoded(members))
    stdout = result["streams"]["stdout"]
    receipt = retain_result(directory, result)
    require(
        receipt["outcome"]["status"] == EXPECTED[name],
        name + " disposition differs from the predeclared expectation",
    )
    require(receipt["work_admitted"] is True, name + " was not actually admitted")
    retired(receipt)
    evidence = {
        "expected": EXPECTED[name],
        "observed": receipt["outcome"],
        "receipt": str(directory / "ownership.json"),
    }
    if name == "memory":
        deltas = {}
        for counter in ("max", "oom_kill"):
            baseline, maximum = events(receipt, "memory.events", counter)
            require(
                maximum > baseline, "memory pressure lacks owned " + counter + " growth"
            )
            deltas[counter] = maximum - baseline
        reports = lines(stdout)
        require(
            any(
                row.get("per_child_target_bytes") == 80 * MIB
                and row.get("combined_target_bytes") == 160 * MIB
                and len(row.get("children", [])) == 2
                for row in reports
            ),
            "aggregate touched allocation fixture was not observed",
        )
        evidence["event_deltas"] = deltas
    elif name == "pids":
        baseline, maximum = events(receipt, "pids.events", "max")
        require(
            maximum > baseline
            and any(
                row.get("eagain_observed") is True and row.get("created", 0) > 0
                for row in lines(stdout)
            ),
            "PID pressure lacks native max growth and its EAGAIN control",
        )
        evidence["event_deltas"] = {"max": maximum - baseline}
    elif name in {"control", "error"}:
        for key, counters in (
            ("memory.events", ("max", "oom", "oom_kill")),
            ("pids.events", ("max",)),
        ):
            for counter in counters:
                baseline, maximum = events(receipt, key, counter)
                require(maximum == baseline, "negative control caused native pressure")
        if name == "control":
            require(
                any(
                    row.get("created_children") == 2
                    and row.get("child_returncodes") == [0, 0]
                    and row.get("combined_touched_bytes") == 16 * MIB
                    for row in lines(stdout)
                ),
                "benign control did not complete",
            )
        else:
            require(
                receipt["outcome"]["returncode"] == 7,
                "ordinary nonzero exit was confused with native pressure",
            )
    elif name == "escape":
        reports = lines(stdout)
        orphan = next(row for row in reports if "orphan_pid" in row)
        parent = next(row for row in reports if "worker_pid" in row)
        require(
            orphan["parent_pid"] == 1
            and orphan["session"] != parent["session"]
            and orphan["private_cgroup"] == parent["private_cgroup"],
            "session/orphan fixture did not retain the private membership control",
        )
        require(
            any(row["pids.current"] >= 3 for row in receipt["samples"]),
            "native samples did not observe the extra owned descendant",
        )
        require(
            members is not None
            and members["reader_retired"] is True
            and not members["errors"]
            and any(
                row["namespace_pid"] == orphan["orphan_pid"]
                and row["cgroup"] == receipt["ownership"]["native"]["cgroup"]
                and row["pidfd_signalled"] is True
                for row in members["members"]
            ),
            "orphan lacked actual host membership and pinned exit evidence",
        )
        evidence["orphan"] = orphan
    elif name == "output":
        require(len(stdout) <= 4096, "overflow retained more than its declared prefix")
        evidence["retained_stdout_bytes"] = len(stdout)
    elif name in {"wall", "cancel"}:
        require(
            any(row.get("started") is True for row in lines(stdout)),
            "stopped fixture was not observed after actual workload launch",
        )
    return evidence


def controller_child(payload: Path, journal: Path, image_id: str) -> None:
    result = owner.run_owned_container(
        payload,
        ["python3", "-I", "-B", "/tmp/payload/fixture.py", "hold"],
        image_id=image_id,
        wall_seconds=30,
        stdout_limit=65_536,
        stderr_limit=65_536,
        output_limit=131_072,
        receipt_callback=lambda value: retain(journal, value),
    )
    result.pop("streams", None)
    result.pop("artifacts", None)
    retain(journal, result)


def controller_loss(payload: Path, root: Path, image_id: str) -> dict:
    directory = root / "controller-loss"
    directory.mkdir()
    journal = directory / "ownership.json"
    process = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-B",
            str(Path(__file__).resolve()),
            "--controller-loss-child",
            str(payload),
            str(journal),
            image_id,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pin = None
    try:
        deadline = time.monotonic() + 25
        receipt = None
        while time.monotonic() < deadline and process.poll() is None:
            if journal.exists():
                candidate = json.loads(journal.read_bytes())
                if (
                    candidate.get("phase") == "admitted"
                    and candidate["work_admitted"] is True
                    and candidate["work_started"] is True
                    and candidate["work_member_observed"] is True
                ):
                    receipt = candidate
                    break
            time.sleep(0.05)
        require(receipt is not None, "controller-loss workload was not admitted")
        native = receipt["ownership"]["native"]
        pid = native["host_pid"]
        starttime = int(
            Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[19]
        )
        require(
            starttime == native["starttime"], "controller-loss init identity changed"
        )
        pin = os.pidfd_open(pid)
        require(
            owner.native.starttime(pid) == native["starttime"]
            and not owner.native.exited(pin),
            "pinned controller-loss init identity changed",
        )
        _, components = owner.native.hierarchy("0::" + native["cgroup"] + "\n")
        group = owner.native.cgroup_path(owner.native.mount_root(), components)
        group_stamp = (group.stat().st_dev, group.stat().st_ino)
        require(
            list(group_stamp) == native["stamp"],
            "controller-loss cgroup differs from the recorded native identity",
        )
        poll = select.poll()
        poll.register(pin, select.POLLIN)
        # Only the freshly created acceptance controller is killed. The owner
        # cannot perform ordinary cleanup after this point.
        process.kill()
        process.wait(timeout=5)
        killed = time.monotonic()
        deadline = killed + 65
        signalled = False
        while time.monotonic() < deadline:
            if poll.poll(1000):
                signalled = True
                break
        require(signalled, "independent init alarm did not retire its pinned process")
        if group.exists():
            require(
                (group.stat().st_dev, group.stat().st_ino) == group_stamp,
                "original cgroup identity changed",
            )
            values = dict(
                line.split()
                for line in (group / "cgroup.events").read_text().splitlines()
            )
            require(
                values.get("populated") == "0",
                "controller-loss subtree remains populated",
            )
        docker = shutil.which("docker")
        require(docker is not None, "qualified Docker CLI disappeared")
        inspection = subprocess.run(
            [
                docker,
                "--host",
                "unix:///var/run/docker.sock",
                "inspect",
                "--format",
                '{"id":{{json .Id}},"state":{{json .State}}}',
                receipt["ownership"]["container_id"],
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=10,
            shell=False,
        )
        require(
            inspection.returncode == 0 and len(inspection.stdout) <= 65_536,
            "stopped exact container inspection failed",
        )
        stopped = json.loads(inspection.stdout)
        require(
            stopped["id"] == receipt["ownership"]["container_id"]
            and stopped["state"]["Running"] is False
            and stopped["state"]["ExitCode"] == 124,
            "controller loss did not observe the trusted init alarm exit",
        )
        observation = {
            "expected": EXPECTED["controller_loss"],
            "pin_signalled": True,
            "container_id": stopped["id"],
            "stopped_state": stopped["state"],
            "original_group": str(group),
            "original_group_stamp": list(group_stamp),
            "group_empty_or_absent": True,
            "observed_seconds_after_controller_kill": time.monotonic() - killed,
        }
        write(directory / "alarm-observation.json", encoded(observation))
        recovery = owner.recover_owned_container(receipt)
        write(directory / "explicit-recovery.json", encoded(recovery))
        require(
            recovery["cleanup"]["complete"] is True,
            "explicit exact-container recovery did not complete",
        )
        observation["explicit_recovery"] = str(directory / "explicit-recovery.json")
        return observation
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if pin is not None:
            os.close(pin)


def main() -> None:
    if sys.argv[1:2] == ["--controller-loss-child"]:
        require(len(sys.argv) == 5, "unsupported controller-loss child request")
        controller_child(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--companion", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--image-id", help="separately acquired immutable official image"
    )
    args = parser.parse_args()
    require(
        sys.platform == "linux" and os.geteuid() != 0,
        "native acceptance requires qualified ordinary Linux",
    )
    image_id = args.image_id or owner.acquire_image()
    wheel = args.wheel.resolve(strict=True)
    archive = args.companion.resolve(strict=True)
    before = {str(path): snapshot(path) for path in (wheel, archive)}
    root = args.output.absolute()
    root.mkdir(exist_ok=False)
    declared = {
        "image_id": image_id,
        "expected_dispositions": EXPECTED,
        "operational_seeds": worker.REQUEST,
        "memory_case": {
            "memory_bytes": 128 * MIB,
            "members": 2,
            "per_child_target_bytes": 80 * MIB,
        },
        "pids_case": {"pids_max": 16, "fork_attempts_upper_bound": 100},
        "boundaries": {"scientific_inference": False, "origin_authenticated": False},
    }
    write(root / "expected.json", encoded(declared))
    payload = root / "fixture-payload"
    payload.mkdir()
    fixture = (
        Path(__file__).resolve().parents[1]
        / "tests/fixtures/linux_container_fixture.py"
    )
    write(payload / "fixture.py", fixture.read_bytes())
    evidence = {
        "format": "mcts-installed-linux-acceptance",
        "schema_version": 1,
        "status": "incomplete",
        "expected": declared,
        "cases": {},
        "inputs_before": before,
        "error": None,
    }
    retain(root / "acceptance.json", evidence)
    try:
        evidence["cases"]["refusal"] = refusal_case(payload, root, image_id)
        evidence["cases"]["complete"] = complete_case(wheel, archive, root, image_id)
        for name in (
            "control",
            "error",
            "memory",
            "pids",
            "escape",
            "output",
            "wall",
            "cancel",
        ):
            evidence["cases"][name] = fixture_case(name, payload, root, image_id)
            retain(root / "acceptance.json", evidence)
        evidence["cases"]["controller_loss"] = controller_loss(payload, root, image_id)
        after = {str(path): snapshot(path) for path in (wheel, archive)}
        require(before == after, "original wheel/companion bytes or mtimes changed")
        evidence.update(status="complete", inputs_after=after, originals_unchanged=True)
    except Exception as error:
        evidence["error"] = {"type": type(error).__name__, "message": str(error)[:2048]}
        raise
    finally:
        retain(root / "acceptance.json", evidence)
        emit_retained_evidence(root, evidence)


if __name__ == "__main__":
    main()
