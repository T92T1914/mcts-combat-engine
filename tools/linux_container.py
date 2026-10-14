"""Own bounded trusted companion work on an explicitly selected Linux daemon.

Container charges exclude the controller, clients, daemon and image acquisition.
This is resource ownership for trusted public payloads, not a hostile code sandbox.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import math
import os
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import time
import uuid
from pathlib import Path

from . import linux_ownership_probe as native

MEMORY = 268_435_456
PIDS = 64
TMPFS = 33_554_432
BUNDLE_BYTES = 16_777_216
FILE_COUNT = 256
ARTIFACT_BYTES = 2_097_152
ARTIFACT_ENVELOPE = 3_145_728
RECEIPT_BYTES = 131_072
LABEL = "mcts.owned-container"
INSPECT = native.INSPECT.replace(native.LABEL, LABEL).replace(
    '"running":{{json .State.Running}},',
    '"running":{{json .State.Running}},"exit_code":{{json .State.ExitCode}},'
    '"oom_killed":{{json .State.OOMKilled}},',
)
INFO = (
    '{"os":{{json .OSType}},"version":{{json .CgroupVersion}},'
    '"driver":{{json .CgroupDriver}},"memory":{{json .MemoryLimit}},'
    '"swap":{{json .SwapLimit}},"pids":{{json .PidsLimit}}}'
)
UNPACK = """
import pathlib,sys,tarfile
root=pathlib.Path('/tmp/payload');root.mkdir()
pathlib.Path('/tmp/results').mkdir()
count=total=0
with tarfile.open(fileobj=sys.stdin.buffer,mode='r|') as archive:
 for member in archive:
  parts=member.name.split('/')
  count+=1;total+=member.size
  if (not member.isfile() or count>256 or total>16777216 or
      any(part in ('','.','..') or '\\\\' in part for part in parts)):
   raise ValueError('unsupported payload member')
  destination=root.joinpath(*parts);destination.parent.mkdir(parents=True,exist_ok=True)
  with archive.extractfile(member) as source,destination.open('xb') as output:
   while True:
    chunk=source.read(32768)
    if not chunk:break
    output.write(chunk)
"""
ARTIFACT_READER = """
import base64,hashlib,json,os,pathlib,stat,sys
result={};total=0
def stamp(value):
 return (value.st_dev,value.st_ino,value.st_mode,value.st_size,
         value.st_mtime_ns,value.st_ctime_ns)
for name in json.loads(sys.argv[1]):
 path=pathlib.Path('/tmp/results')
 if not stat.S_ISDIR(path.lstat().st_mode):raise ValueError('artifact root')
 for component in name.split('/')[:-1]:
  path/=component
  if not stat.S_ISDIR(path.lstat().st_mode):raise ValueError('artifact parent')
 path/=name.split('/')[-1]
 before=path.lstat()
 if not stat.S_ISREG(before.st_mode):raise ValueError('artifact type')
 total+=before.st_size
 if total>2097152:raise ValueError('artifact allowance')
 with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW),'rb') as stream:
  if stamp(os.fstat(stream.fileno()))!=stamp(before):
   raise ValueError('artifact changed')
  data=stream.read(before.st_size+1)
  if len(data)!=before.st_size or stamp(os.fstat(stream.fileno()))!=stamp(before):
   raise ValueError('artifact changed')
 result[name]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
               'base64':base64.b64encode(data).decode('ascii')}
print(json.dumps(result,sort_keys=True))
"""


class LinuxContainerError(RuntimeError):
    """Required bounded input, ownership or execution evidence is unavailable."""

    def __init__(self, message, status="error"):
        super().__init__(message)
        self.status = status


def require(condition, message):
    if not condition:
        raise LinuxContainerError(message)


def stream(
    docker,
    arguments,
    *,
    deadline,
    stdout_limit=65_536,
    stderr_limit=16_384,
    output_limit=81_920,
    data=None,
    cancel=None,
    on_started=None,
    observe=None,
):
    """Reap one client while retaining prefixes and counting only read bytes."""
    result = {
        "stdout": bytearray(),
        "stderr": bytearray(),
        "returncode": None,
        "observed": {"stdout": 0, "stderr": 0},
        "stop": None,
    }
    if cancel is not None and cancel.is_set():
        result["stop"] = "cancelled"
        return result
    process = subprocess.Popen(
        [docker, "--host", native.ENDPOINT, *arguments],
        stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
    )
    selector = selectors.DefaultSelector()
    sent = 0
    try:
        for role in ("stdout", "stderr"):
            channel = getattr(process, role)
            os.set_blocking(channel.fileno(), False)
            selector.register(channel, selectors.EVENT_READ, role)
        if data is not None:
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
        if on_started is not None:
            on_started()
        while selector.get_map():
            if time.monotonic() >= deadline:
                result["stop"] = "timeout"
                break
            if cancel is not None and cancel.is_set():
                result["stop"] = "cancelled"
                break
            if observe is not None:
                observe()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                result["stop"] = "timeout"
                break
            for key, _ in selector.select(min(0.05, remaining)):
                if key.data == "stdin":
                    try:
                        sent += os.write(key.fd, memoryview(data)[sent : sent + 32768])
                    except BrokenPipeError:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                        continue
                    if sent == len(data):
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                    continue
                try:
                    chunk = os.read(key.fd, 8192)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                role = key.data
                result["observed"][role] += len(chunk)
                limit = stdout_limit if role == "stdout" else stderr_limit
                available = min(
                    limit - len(result[role]),
                    output_limit - len(result["stdout"]) - len(result["stderr"]),
                )
                result[role].extend(chunk[: max(0, available)])
                if (
                    result["observed"][role] > limit
                    or sum(result["observed"].values()) > output_limit
                ):
                    result["stop"] = "output_limit"
                    break
            if result["stop"]:
                break
    except Exception as error:
        result["stop"] = "error"
        result["error"] = type(error).__name__
    finally:
        selector.close()
        if process.poll() is None:
            if result["stop"] is not None:
                process.kill()
            else:
                try:
                    process.wait(timeout=max(0.001, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    result["stop"] = "timeout"
                    process.kill()
        result["returncode"] = process.wait(timeout=2)
        for role in ("stdin", "stdout", "stderr"):
            channel = getattr(process, role)
            if channel is not None:
                channel.close()
    result["stdout"], result["stderr"] = (
        bytes(result["stdout"]),
        bytes(result["stderr"]),
    )
    return result


def command(docker, arguments, *, timeout=10, deadline=None, data=None, cancel=None):
    end = (
        min(time.monotonic() + timeout, deadline)
        if deadline is not None
        else time.monotonic() + timeout
    )
    result = stream(docker, arguments, deadline=end, data=data, cancel=cancel)
    if result["stop"] is not None:
        raise LinuxContainerError("bounded Docker request stopped", result["stop"])
    require(result["returncode"] == 0, "bounded Docker diagnostic failed")
    return result["stdout"]


def environment():
    require(
        sys.platform == "linux" and os.getuid() == os.geteuid() == 1001,
        "only the qualified ordinary Linux actor is supported",
    )
    require(
        "DOCKER_HOST" not in os.environ and "DOCKER_CONTEXT" not in os.environ,
        "alternate Docker endpoint selection is unsupported",
    )
    socket = Path("/var/run/docker.sock")
    require(
        stat.S_ISSOCK(socket.stat().st_mode) and os.access(socket, os.R_OK | os.W_OK),
        "local daemon access is unavailable",
    )
    docker = shutil.which("docker")
    require(docker is not None, "Docker client is unavailable")
    root = native.mount_root()
    info = json.loads(command(docker, ["info", "--format", INFO]))
    require(
        info.get("os") == "linux"
        and str(info.get("version")) == "2"
        and info.get("driver") in ("systemd", "cgroupfs")
        and all(info.get(key) is True for key in ("memory", "swap", "pids")),
        "daemon controls are unsupported",
    )
    return docker, root


def acquire_image():
    """Acquire the declared public image separately from admission accounting."""
    docker, _ = environment()
    command(docker, ["pull", "--quiet", native.IMAGE], timeout=90)
    image = json.loads(
        command(docker, ["image", "inspect", "--format", "{{json .Id}}", native.IMAGE])
    )
    require(
        type(image) is str
        and image.startswith("sha256:")
        and native.HEX_ID.fullmatch(image[7:]),
        "immutable image identity is unavailable",
    )
    return image


def inspect(docker, target, *, deadline=None):
    value = json.loads(
        command(docker, ["inspect", "--format", INSPECT, target], deadline=deadline)
    )
    require(type(value) is dict, "container inspection is not an object")
    return value


def configuration(value, request):
    require(
        value.get("image") == request["image_id"]
        and value.get("user") == "1001:1001"
        and value.get("cmd") == ["python3", "-I", "-c", native.INIT]
        and value.get("entrypoint") in (None, []),
        "container execution identity differs",
    )
    host = value.get("host", {})
    expected = {
        "Memory": request["memory"],
        "MemorySwap": request["memory_swap"],
        "PidsLimit": request["pids"],
        "NanoCpus": 1_000_000_000,
        "Privileged": False,
        "ReadonlyRootfs": True,
        "NetworkMode": "none",
        "CgroupnsMode": "private",
    }
    require(
        all(host.get(key) == item for key, item in expected.items()),
        "container control configuration differs",
    )
    require(
        host.get("CapDrop") == ["ALL"]
        and not host.get("CapAdd")
        and host.get("SecurityOpt") == ["no-new-privileges"]
        and not any(
            host.get(key)
            for key in ("Binds", "Mounts", "CgroupParent", "Sysctls", "GroupAdd")
        ),
        "container has an unsupported host or privilege relationship",
    )
    mounts = value.get("mounts")
    require(
        type(mounts) is list
        and all(
            type(mount) is dict
            and mount.get("Type") == "tmpfs"
            and mount.get("Destination") == "/tmp"
            and not mount.get("Source")
            for mount in mounts
        ),
        "host mounts are unsupported",
    )
    require(
        host.get("Tmpfs") == {"/tmp": f"rw,noexec,nosuid,nodev,size={TMPFS}"}
        and host.get("LogConfig", {}).get("Type") == "none"
        and host.get("RestartPolicy", {}).get("Name") in ("", "no")
        and host.get("Init") in (None, False),
        "container temporary filesystem or logs differ",
    )


def controls(directory, request):
    values = {
        key: native.read(directory / key).strip()
        for key in ("memory.max", "memory.swap.max", "pids.max", "cpu.max")
    }
    cpu = values["cpu.max"].split()
    require(
        values["memory.max"] == str(request["memory"])
        and values["memory.swap.max"] == "0"
        and values["pids.max"] == str(request["pids"])
        and len(cpu) == 2
        and cpu[0].isdigit()
        and cpu[1].isdigit()
        and int(cpu[0]) == int(cpu[1]) > 0,
        "literal cgroup limits differ",
    )
    return values


def sample(directory):
    result = {"monotonic": time.monotonic()}
    for key in ("memory.events", "memory.events.local", "pids.events", "cgroup.events"):
        try:
            result[key] = {
                name: int(value)
                for name, value in (
                    line.split() for line in native.read(directory / key).splitlines()
                )
            }
        except FileNotFoundError:
            result[key] = None
    for key in ("memory.current", "memory.peak", "pids.current"):
        try:
            result[key] = int(native.read(directory / key).strip())
        except FileNotFoundError:
            result[key] = None
    result["members"] = [
        int(value) for value in native.read(directory / "cgroup.procs").split()
    ]
    return result


def pin(docker, root, receipt, *, verify_inside=True):
    request = receipt["request"]
    cid = receipt["ownership"]["container_id"]
    value = inspect(docker, cid)
    native.owned(value, request["container_name"], request["nonce"], cid)
    configuration(value, request)
    pid = value.get("pid")
    require(
        value.get("running") is True and type(pid) is int and pid > 1,
        "running root process is unavailable",
    )
    descriptor = os.pidfd_open(pid, 0)
    try:
        require(not native.exited(descriptor), "root process already exited")
        identity = native.starttime(pid)
        relative, components = native.hierarchy(
            native.read(Path(f"/proc/{pid}/cgroup"))
        )
        require(cid in relative, "root cgroup does not bind the exact container")
        directory = native.cgroup_path(root, components)
        stamp = directory.stat()
        literal = controls(directory, request)
        controller = native.hierarchy(native.read(Path("/proc/self/cgroup")))[0]
        members = sample(directory)["members"]
        require(
            pid in members
            and os.getpid() not in members
            and controller != relative
            and not controller.startswith(relative + "/"),
            "root membership or controller exclusion differs",
        )
        namespaces = {
            key: Path(f"/proc/{pid}/ns/{key}").stat().st_ino
            for key in ("pid", "cgroup", "mnt")
        }
        require(
            namespaces["pid"] != Path("/proc/self/ns/pid").stat().st_ino
            and namespaces["cgroup"] != Path("/proc/self/ns/cgroup").stat().st_ino,
            "private namespaces are unavailable",
        )
        observed = {
            "host_pid": pid,
            "starttime": identity,
            "cgroup": relative,
            "stamp": [stamp.st_dev, stamp.st_ino],
            "controller_excluded": True,
            "controls": literal,
            "namespaces": namespaces,
        }
        if verify_inside:
            inside = json.loads(
                command(docker, ["exec", cid, "python3", "-I", "-c", native.METADATA])
            )
            require(
                inside.get("euid") == 1001
                and inside.get("pid1_uid") == ["1001"] * 4
                and inside.get("pid1_starttime") == identity
                and inside.get("namespaces") == namespaces
                and inside.get("controls") == literal
                and inside.get("pid1_cgroup") == "0::/\n"
                and inside.get("self_cgroup") == "0::/\n"
                and inside.get("pid1_no_new_privs") == 1
                and inside.get("pid1_cap_effective") == 0,
                "container namespace observations do not reconcile",
            )
            handlers = inside.get("pid1_signal_handlers")
            require(
                type(handlers) is int
                and all(
                    handlers & (1 << (number - 1))
                    for number in (signal.SIGALRM, signal.SIGTERM)
                ),
                "independent lifetime handlers are unavailable",
            )
            observed["inside"] = inside
        final = inspect(docker, cid)
        native.owned(final, request["container_name"], request["nonce"], cid)
        configuration(final, request)
        require(
            final.get("id") == cid
            and final.get("pid") == pid
            and final.get("running") is True
            and native.starttime(pid) == identity
            and not native.exited(descriptor)
            and controls(directory, request) == literal,
            "root identity or limits changed during admission",
        )
        return observed, descriptor, directory
    except BaseException:
        os.close(descriptor)
        raise


def ordinary_name(name):
    return (
        type(name) is str
        and 0 < len(name) <= 240
        and "\\" not in name
        and all(part not in ("", ".", "..") for part in name.split("/"))
    )


def fingerprint(value):
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def payload_bundle(root):
    root = root.absolute()
    for parent in (*reversed(root.parents), root):
        require(stat.S_ISDIR(parent.lstat().st_mode), "payload parent is not ordinary")
    contents = io.BytesIO()
    manifest, stamps = [], {}
    with tarfile.open(fileobj=contents, mode="w") as archive:
        for directory, children, files in os.walk(root, followlinks=False):
            for name in children:
                require(
                    stat.S_ISDIR((Path(directory) / name).lstat().st_mode),
                    "payload directory is not ordinary",
                )
                require(
                    name not in (".git", ".ssh", ".aws", ".docker"),
                    "private configuration is not a public payload",
                )
            for name in sorted(files):
                path = Path(directory) / name
                relative = path.relative_to(root).as_posix()
                require(
                    ordinary_name(relative) and len(manifest) < FILE_COUNT,
                    "payload names or file count exceed allowance",
                )
                require(
                    not set(relative.split("/"))
                    & {".git", ".hg", ".svn", ".ssh", ".aws", ".docker", "credentials"},
                    "private metadata is not a public payload",
                )
                before = path.lstat()
                require(
                    stat.S_ISREG(before.st_mode)
                    and before.st_size <= BUNDLE_BYTES - contents.tell(),
                    "payload type or bytes exceed allowance",
                )
                with os.fdopen(
                    os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb"
                ) as stream_:
                    require(
                        fingerprint(os.fstat(stream_.fileno())) == fingerprint(before),
                        "payload changed before read",
                    )
                    data = stream_.read(before.st_size + 1)
                    require(
                        len(data) == before.st_size
                        and fingerprint(os.fstat(stream_.fileno()))
                        == fingerprint(before),
                        "payload changed during read",
                    )
                member = tarfile.TarInfo(relative)
                member.size, member.mode = len(data), 0o444
                archive.addfile(member, io.BytesIO(data))
                stamps[relative] = fingerprint(before)
                manifest.append(
                    {
                        "path": relative,
                        "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                )
                require(
                    contents.tell() <= BUNDLE_BYTES, "payload bundle exceeds allowance"
                )
    require(
        manifest and contents.tell() <= BUNDLE_BYTES, "payload bundle exceeds allowance"
    )
    return root, contents.getvalue(), manifest, stamps


def unchanged(root, stamps, manifest):
    current = {
        path.relative_to(root).as_posix(): fingerprint(path.lstat())
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    require(current == stamps, "original payload inventory or bytes metadata changed")
    for item in manifest:
        path = root / item["path"]
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as source:
            data = source.read(item["bytes"] + 1)
        require(
            len(data) == item["bytes"]
            and hashlib.sha256(data).hexdigest() == item["sha256"]
            and fingerprint(path.lstat()) == stamps[item["path"]],
            "original payload bytes or modification time changed",
        )


def add_sample(receipt, point):
    receipt["samples_total"] += 1
    if len(receipt["samples"]) == 64:
        receipt["samples"].pop(1)
    receipt["samples"].append(point)
    receipt["samples_discarded"] = receipt["samples_total"] - len(receipt["samples"])


def refresh_events(receipt):
    if len(receipt["samples"]) < 2:
        return
    baseline, final = receipt["samples"][0], receipt["samples"][-1]
    deltas = {
        key: {
            name: value - baseline[key][name]
            for name, value in final[key].items()
            if name in baseline[key]
        }
        for key in ("memory.events", "memory.events.local", "pids.events")
        if baseline.get(key) is not None and final.get(key) is not None
    }
    receipt["event_deltas"] = deltas
    if receipt["outcome"]["status"] in (
        "complete",
        "error",
        "memory_pressure",
        "process_pressure",
    ):
        memory = deltas.get("memory.events", {})
        if memory.get("oom", 0) > 0 or memory.get("oom_kill", 0) > 0:
            receipt["outcome"]["status"] = "memory_pressure"
        elif deltas.get("pids.events", {}).get("max", 0) > 0:
            receipt["outcome"]["status"] = "process_pressure"


def notify(receipt, callback):
    snapshot = {
        key: value
        for key, value in receipt.items()
        if key not in ("streams", "artifacts")
    }
    while (
        len(json.dumps(snapshot, ensure_ascii=True, allow_nan=False)) > RECEIPT_BYTES
        and len(receipt["samples"]) > 2
    ):
        receipt["samples"].pop(1)
        receipt["samples_discarded"] += 1
        snapshot["samples_discarded"] = receipt["samples_discarded"]
    require(
        len(json.dumps(snapshot, ensure_ascii=True, allow_nan=False)) <= RECEIPT_BYTES,
        "receipt envelope exceeds allowance",
    )
    if callback is not None:
        callback(copy.deepcopy(snapshot))


def retire(docker, receipt, descriptor, directory, *, deadline=None):
    deadline = deadline or time.monotonic() + 10
    result = {
        "complete": False,
        "pidfd_signalled": False,
        "container_absent": False,
        "cgroup_empty_or_absent": False,
    }
    request, ownership = receipt["request"], receipt["ownership"]
    cid = ownership.get("container_id")
    try:
        value = inspect(docker, cid or request["container_name"], deadline=deadline)
        cid = native.owned(value, request["container_name"], request["nonce"], cid)
        ownership["container_id"] = cid
        if descriptor is not None:
            configuration(value, request)
            observed = ownership["native"]
            if value.get("running") is True:
                require(
                    value.get("pid") == observed["host_pid"]
                    and native.starttime(observed["host_pid"]) == observed["starttime"]
                    and not native.exited(descriptor),
                    "live root changed before retirement",
                )
                relative = native.hierarchy(
                    native.read(Path(f"/proc/{observed['host_pid']}/cgroup"))
                )[0]
                stamp = directory.lstat()
                require(
                    relative == observed["cgroup"]
                    and [stamp.st_dev, stamp.st_ino] == observed["stamp"]
                    and controls(directory, request) == observed["controls"],
                    "live cgroup changed before retirement",
                )
            else:
                require(
                    value.get("pid") == 0 and native.exited(descriptor),
                    "stopped object contradicts pinned root exit",
                )
        if value.get("running") is True:
            command(docker, ["kill", cid], deadline=deadline)
        command(docker, ["rm", cid], deadline=deadline)
        absent = command(
            docker,
            [
                "container",
                "ls",
                "--all",
                "--no-trunc",
                "--filter",
                "id=" + cid,
                "--format",
                "{{json .ID}}",
            ],
            deadline=deadline,
        )
        result["container_absent"] = not absent.strip()
        if descriptor is not None:
            result["pidfd_signalled"] = native.exited(
                descriptor, max(0, int((deadline - time.monotonic()) * 1000))
            )
        if directory is not None:
            try:
                stamp = directory.lstat()
            except FileNotFoundError:
                result["cgroup_empty_or_absent"] = True
                result["cgroup_disposition"] = "absent"
            else:
                require(
                    [stamp.st_dev, stamp.st_ino] == ownership["native"]["stamp"],
                    "owned cgroup identity changed during retirement",
                )
                final = sample(directory)
                result["final_sample"] = final
                result["cgroup_empty_or_absent"] = (
                    final["cgroup.events"].get("populated") == 0
                    and not final["members"]
                )
                result["cgroup_disposition"] = "empty"
        result["complete"] = all(
            result[key]
            for key in ("pidfd_signalled", "container_absent", "cgroup_empty_or_absent")
        )
    except Exception as error:
        result["error"] = (
            str(error)
            if isinstance(error, (LinuxContainerError, native.ProbeError))
            else type(error).__name__
        )
    return result


def run_owned_container(
    payload,
    argv,
    *,
    image_id,
    receipt_callback=None,
    cancel=None,
    wall_seconds=30.0,
    stdout_limit=8_388_608,
    stderr_limit=65_536,
    output_limit=8_388_608,
    artifact_names=(),
    memory_bytes=MEMORY,
    pids_max=PIDS,
):
    """Run declared trusted bytes only after exact native ownership admission."""
    nonce = uuid.uuid4().hex
    empty_output = {
        "observed_bytes": 0,
        "retained_bytes": 0,
        "sha256": hashlib.sha256(b"").hexdigest(),
        "truncated": False,
    }
    request = {
        "nonce": nonce,
        "container_name": "mcts-owned-" + nonce,
        "image_id": image_id,
        "memory": memory_bytes,
        "memory_swap": memory_bytes,
        "pids": pids_max,
        "cpus": 1,
        "tmpfs": TMPFS,
        "wall": wall_seconds,
        "cleanup": 10,
        "lifetime": 60,
        "argv": argv,
        "artifact_names": list(artifact_names),
        "input_manifest": [],
        "stdout_limit": stdout_limit,
        "stderr_limit": stderr_limit,
        "output_limit": output_limit,
        "artifact_limit": ARTIFACT_BYTES,
        "artifact_envelope": ARTIFACT_ENVELOPE,
        "bundle_limit": BUNDLE_BYTES,
        "file_limit": FILE_COUNT,
    }
    receipt = {
        "format": "mcts-linux-owned-container",
        "schema_version": 1,
        "phase": "before_create",
        "request": request,
        "ownership": {"container_id": None, "native": None},
        "work_admitted": False,
        "work_started": False,
        "work_member_observed": False,
        "outcome": {"status": "pending", "reason": None, "returncode": None},
        "cleanup": {"complete": False},
        "samples": [],
        "samples_total": 0,
        "samples_discarded": 0,
        "output": {
            "stdout": dict(empty_output),
            "stderr": dict(empty_output),
            "combined_observed_bytes": 0,
            "unread_bytes_unknown": False,
            "scope": "Bytes read from client pipes, not generated workload bytes",
        },
        "streams": {"stdout": b"", "stderr": b""},
        "artifacts": {},
        "artifact_identities": {},
    }
    descriptor = directory = root_payload = stamps = None
    attempted = False
    docker = None
    try:
        require(
            type(image_id) is str
            and image_id.startswith("sha256:")
            and native.HEX_ID.fullmatch(image_id[7:]),
            "an immutable image ID is required",
        )
        require(
            type(argv) is list
            and 1 <= len(argv) <= 32
            and all(
                type(item) is str and 0 < len(item) <= 4096 and "\x00" not in item
                for item in argv
            )
            and sum(len(item) for item in argv) <= 16_384,
            "bounded argument strings are required",
        )
        require(
            type(wall_seconds) in (int, float)
            and math.isfinite(wall_seconds)
            and 0 < wall_seconds <= 30
            and type(memory_bytes) is int
            and 67_108_864 <= memory_bytes <= MEMORY
            and type(pids_max) is int
            and 16 <= pids_max <= PIDS,
            "requested controls exceed the qualified domain",
        )
        require(
            all(
                type(value) is int and 0 < value <= limit
                for value, limit in (
                    (stdout_limit, 8_388_608),
                    (stderr_limit, 65_536),
                    (output_limit, 8_388_608),
                )
            ),
            "output allowances are unsupported",
        )
        require(
            type(artifact_names) in (list, tuple)
            and len(artifact_names) <= 16
            and len(set(artifact_names)) == len(artifact_names)
            and all(ordinary_name(name) for name in artifact_names),
            "artifact names are unsupported",
        )
        docker, root = environment()
        official = json.loads(
            command(
                docker, ["image", "inspect", "--format", "{{json .Id}}", native.IMAGE]
            )
        )
        require(
            official == image_id, "image differs from resolved declared public image"
        )
        root_payload, bundle, manifest, stamps = payload_bundle(Path(payload))
        request["input_manifest"] = manifest
        controller = native.hierarchy(native.read(Path("/proc/self/cgroup")))[0]
        receipt["controller"] = {
            "pid": os.getpid(),
            "starttime": native.starttime(os.getpid()),
            "cgroup": controller,
        }
        notify(receipt, receipt_callback)
        attempted = True
        created = (
            command(
                docker,
                [
                    "create",
                    "--pull=never",
                    "--name",
                    request["container_name"],
                    "--label",
                    LABEL + "=" + nonce,
                    "--memory",
                    str(memory_bytes),
                    "--memory-swap",
                    str(memory_bytes),
                    "--pids-limit",
                    str(pids_max),
                    "--cpus",
                    "1",
                    "--user",
                    "1001:1001",
                    "--cap-drop",
                    "ALL",
                    "--restart=no",
                    "--init=false",
                    "--security-opt",
                    "no-new-privileges",
                    "--network",
                    "none",
                    "--read-only",
                    "--cgroupns",
                    "private",
                    "--log-driver",
                    "none",
                    "--tmpfs",
                    f"/tmp:rw,noexec,nosuid,nodev,size={TMPFS}",
                    image_id,
                    "python3",
                    "-I",
                    "-c",
                    native.INIT,
                ],
            )
            .decode()
            .strip()
        )
        require(native.HEX_ID.fullmatch(created), "container identity is not exact")
        receipt["ownership"]["container_id"] = created
        value = inspect(docker, created)
        native.owned(value, request["container_name"], nonce, created)
        configuration(value, request)
        started = time.monotonic()
        command(docker, ["start", created])
        observed, descriptor, directory = pin(docker, root, receipt)
        receipt["ownership"]["native"] = observed
        require(
            time.monotonic() - started + wall_seconds + 10 < 59,
            "root lifetime cannot cover requested admission and cleanup",
        )
        add_sample(receipt, sample(directory))
        receipt["phase"] = "before_admission"
        notify(receipt, receipt_callback)
        deadline = time.monotonic() + wall_seconds
        receipt["work_admitted"] = True
        command(
            docker,
            ["exec", "-i", created, "python3", "-I", "-c", UNPACK],
            deadline=deadline,
            data=bundle,
            timeout=30,
            cancel=cancel,
        )
        last_sample = 0.0

        def observe():
            nonlocal last_sample
            if time.monotonic() - last_sample < 0.2:
                return
            last_sample = time.monotonic()
            point = sample(directory)
            add_sample(receipt, point)
            others = [pid for pid in point["members"] if pid != observed["host_pid"]]
            if others and not receipt["work_member_observed"]:
                receipt["work_member_observed"] = True
                receipt["observed_work_members"] = others
                notify(receipt, receipt_callback)

        def admitted():
            receipt["phase"] = "admitted"
            receipt["work_started"] = True
            notify(receipt, receipt_callback)

        result = stream(
            docker,
            ["exec", "--workdir", "/tmp/payload", created, *argv],
            deadline=deadline,
            stdout_limit=stdout_limit,
            stderr_limit=stderr_limit,
            output_limit=output_limit,
            cancel=cancel,
            on_started=admitted,
            observe=observe,
        )
        receipt["streams"] = {role: result[role] for role in ("stdout", "stderr")}
        for role in ("stdout", "stderr"):
            data = result[role]
            receipt["output"][role] = {
                "observed_bytes": result["observed"][role],
                "retained_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "truncated": result["observed"][role] > len(data),
            }
        receipt["output"].update(
            combined_observed_bytes=sum(result["observed"].values()),
            unread_bytes_unknown=result["stop"] is not None,
            scope="Bytes read from client pipes, not all generated workload bytes",
        )
        receipt["outcome"] = {
            "status": result["stop"]
            or ("complete" if result["returncode"] == 0 else "error"),
            "reason": result["stop"],
            "returncode": result["returncode"],
        }
        add_sample(receipt, sample(directory))
        refresh_events(receipt)
        if artifact_names and result["stop"] is None:
            artifacts = stream(
                docker,
                [
                    "exec",
                    created,
                    "python3",
                    "-I",
                    "-c",
                    ARTIFACT_READER,
                    json.dumps(list(artifact_names)),
                ],
                deadline=deadline,
                stdout_limit=ARTIFACT_ENVELOPE,
                output_limit=ARTIFACT_ENVELOPE + 16_384,
                cancel=cancel,
            )
            if artifacts["stop"] is not None:
                raise LinuxContainerError(
                    "artifact collection stopped", artifacts["stop"]
                )
            require(artifacts["returncode"] == 0, "artifact collection failed")
            values = json.loads(artifacts["stdout"])
            require(set(values) == set(artifact_names), "artifact inventory differs")
            total = 0
            for name, value in values.items():
                data = base64.b64decode(value["base64"], validate=True)
                total += len(data)
                require(
                    len(data) == value["bytes"]
                    and hashlib.sha256(data).hexdigest() == value["sha256"]
                    and total <= ARTIFACT_BYTES,
                    "artifact bytes or identity differ",
                )
                receipt["artifacts"][name] = data
                receipt["artifact_identities"][name] = {
                    key: value[key] for key in ("bytes", "sha256")
                }
    except Exception as error:
        receipt["outcome"]["status"] = (
            error.status
            if (receipt["work_admitted"] and isinstance(error, LinuxContainerError))
            else "error"
            if receipt["work_admitted"]
            else "refused"
        )
        receipt["outcome"]["reason"] = (
            str(error)
            if isinstance(error, (LinuxContainerError, native.ProbeError))
            else type(error).__name__
        )
    finally:
        if directory is not None:
            try:
                add_sample(receipt, sample(directory))
            except (OSError, ValueError, native.ProbeError) as error:
                receipt["precleanup_sample_unavailable"] = type(error).__name__
            refresh_events(receipt)
        if attempted:
            receipt["cleanup"] = retire(docker, receipt, descriptor, directory)
            if not receipt["cleanup"]["complete"]:
                receipt["outcome"]["status"] = "retirement_failure"
        if descriptor is not None:
            os.close(descriptor)
        if root_payload is not None:
            try:
                unchanged(root_payload, stamps, request["input_manifest"])
                receipt["input_files_unchanged"] = True
            except (OSError, LinuxContainerError) as error:
                receipt["input_files_unchanged"] = False
                receipt["outcome"].update(status="error", reason=type(error).__name__)
        receipt["phase"] = "final"
        notify(receipt, receipt_callback)
    return receipt


def admitted_receipt(value):
    require(
        type(value) is dict
        and len(json.dumps(value, allow_nan=False)) <= RECEIPT_BYTES,
        "recovery requires a bounded JSON receipt",
    )
    require(
        value.get("format") == "mcts-linux-owned-container"
        and value.get("schema_version") == 1,
        "unsupported ownership receipt",
    )
    receipt = copy.deepcopy(value)
    request, ownership = receipt.get("request"), receipt.get("ownership")
    require(
        type(request) is dict and type(ownership) is dict,
        "ownership request is unavailable",
    )
    nonce, cid = request.get("nonce"), ownership.get("container_id")
    require(
        type(nonce) is str
        and len(nonce) == 32
        and all(char in "0123456789abcdef" for char in nonce)
        and request.get("container_name") == "mcts-owned-" + nonce
        and type(cid) is str
        and native.HEX_ID.fullmatch(cid),
        "exact labelled container identity is unavailable",
    )
    image = request.get("image_id")
    require(
        type(image) is str
        and image.startswith("sha256:")
        and native.HEX_ID.fullmatch(image[7:]),
        "recorded image identity is unavailable",
    )
    require(
        type(request.get("memory")) is int
        and 67_108_864 <= request["memory"] <= MEMORY
        and request.get("memory_swap") == request["memory"]
        and type(request.get("pids")) is int
        and 16 <= request["pids"] <= PIDS
        and request.get("cpus") == 1
        and request.get("tmpfs") == TMPFS
        and request.get("cleanup") == 10
        and request.get("lifetime") == 60,
        "recorded control scope is unsupported",
    )
    observed = ownership.get("native")
    require(
        type(observed) is dict
        and type(observed.get("host_pid")) is int
        and observed["host_pid"] > 1
        and type(observed.get("starttime")) is int
        and type(observed.get("stamp")) is list
        and len(observed["stamp"]) == 2
        and all(type(item) is int and item >= 0 for item in observed["stamp"])
        and observed.get("controller_excluded") is True,
        "recorded native identity is unavailable",
    )
    relative, _ = native.hierarchy("0::" + observed.get("cgroup", "") + "\n")
    require(cid in relative, "recorded cgroup does not bind exact container identity")
    literal = observed.get("controls")
    require(
        type(literal) is dict
        and literal.get("memory.max") == str(request["memory"])
        and literal.get("memory.swap.max") == "0"
        and literal.get("pids.max") == str(request["pids"]),
        "recorded literal limits contradict the request",
    )
    cpu = literal.get("cpu.max", "").split()
    require(
        len(cpu) == 2
        and all(item.isdigit() for item in cpu)
        and int(cpu[0]) == int(cpu[1]) > 0,
        "recorded CPU quota differs",
    )
    namespaces = observed.get("namespaces")
    require(
        type(namespaces) is dict
        and set(namespaces) == {"pid", "cgroup", "mnt"}
        and all(type(item) is int and item > 0 for item in namespaces.values()),
        "recorded namespaces are unavailable",
    )
    inside = observed.get("inside")
    require(
        type(inside) is dict
        and inside.get("pid1_starttime") == observed["starttime"]
        and inside.get("namespaces") == namespaces
        and inside.get("controls") == literal
        and inside.get("pid1_uid") == ["1001"] * 4
        and inside.get("euid") == 1001
        and inside.get("pid1_no_new_privs") == 1
        and inside.get("pid1_cap_effective") == 0
        and inside.get("pid1_cgroup") == "0::/\n"
        and inside.get("self_cgroup") == "0::/\n",
        "recorded namespace evidence contradicts native identity",
    )
    return receipt


def stopped_group(root, recorded):
    _, components = native.hierarchy("0::" + recorded["cgroup"] + "\n")
    path = root.joinpath(*components)
    try:
        stamp = path.lstat()
    except FileNotFoundError:
        return {"cgroup_disposition": "absent", "cgroup_empty_or_absent": True}
    require(
        stat.S_ISDIR(stamp.st_mode)
        and [stamp.st_dev, stamp.st_ino] == recorded["stamp"],
        "stopped cgroup identity differs",
    )
    final = sample(path)
    require(
        final["cgroup.events"].get("populated") == 0 and not final["members"],
        "stopped owned cgroup remains populated",
    )
    return {
        "cgroup_disposition": "empty",
        "cgroup_empty_or_absent": True,
        "sample": final,
    }


def inspect_current_owned(receipt):
    """Check current agreement with a receipt, without authenticating its author."""
    receipt = admitted_receipt(receipt)
    docker, root = environment()
    request, ownership = receipt["request"], receipt["ownership"]
    absent = command(
        docker,
        [
            "container",
            "ls",
            "--all",
            "--no-trunc",
            "--filter",
            "id=" + ownership["container_id"],
            "--format",
            "{{json .ID}}",
        ],
    )
    if not absent.strip():
        return {
            "disposition": "already_retired",
            "container_absent": True,
            "historical_root_exit_not_newly_observed": True,
            **stopped_group(root, ownership["native"]),
        }
    value = inspect(docker, ownership["container_id"])
    native.owned(
        value, request["container_name"], request["nonce"], ownership["container_id"]
    )
    configuration(value, request)
    recorded = ownership["native"]
    if value.get("running") is True:
        current, descriptor, directory = pin(docker, root, receipt)
        os.close(descriptor)
        require(
            all(
                current[key] == recorded[key]
                for key in (
                    "host_pid",
                    "starttime",
                    "cgroup",
                    "stamp",
                    "controls",
                    "namespaces",
                )
            ),
            "live ownership contradicts recorded native identity",
        )
        return {
            "disposition": "live_owned",
            "container": value["id"],
            "native": current,
            "sample": sample(directory),
        }
    require(value.get("pid") == 0, "stopped container has a live PID claim")
    return {
        "disposition": "stopped_owned",
        "container": value["id"],
        "exit_code": value.get("exit_code"),
        "oom_killed": value.get("oom_killed"),
        "historical_root_exit_not_newly_observed": True,
        **stopped_group(root, recorded),
    }


def recover_owned_container(receipt):
    """Retire only current exact agreement after an explicit cleanup request."""
    try:
        receipt = admitted_receipt(receipt)
        current = inspect_current_owned(receipt)
        if current["disposition"] == "already_retired":
            return {
                "status": "already_retired",
                "cleanup": {
                    "complete": True,
                    "container_absent": True,
                    "cgroup_empty_or_absent": True,
                    "historical_root_exit_not_newly_observed": True,
                },
                "prior_observation": current,
            }
        docker, root = environment()
        if current["disposition"] == "live_owned":
            observed, descriptor, directory = pin(docker, root, receipt)
            try:
                recorded = receipt["ownership"]["native"]
                require(
                    all(
                        observed[key] == recorded[key]
                        for key in (
                            "host_pid",
                            "starttime",
                            "cgroup",
                            "stamp",
                            "controls",
                            "namespaces",
                        )
                    ),
                    "live root changed between recovery observations",
                )
                result = retire(docker, receipt, descriptor, directory)
            finally:
                os.close(descriptor)
        else:
            request = receipt["request"]
            cid = receipt["ownership"]["container_id"]
            deadline = time.monotonic() + 10
            value = inspect(docker, cid, deadline=deadline)
            native.owned(value, request["container_name"], request["nonce"], cid)
            configuration(value, request)
            require(
                value.get("running") is False and value.get("pid") == 0,
                "stopped container changed before cleanup",
            )
            stopped_group(root, receipt["ownership"]["native"])
            command(docker, ["rm", cid], deadline=deadline)
            absent = command(
                docker,
                [
                    "container",
                    "ls",
                    "--all",
                    "--no-trunc",
                    "--filter",
                    "id=" + cid,
                    "--format",
                    "{{json .ID}}",
                ],
                deadline=deadline,
            )
            result = {
                "complete": not absent.strip(),
                "container_absent": not absent.strip(),
                "cgroup_empty_or_absent": True,
                "historical_root_exit_not_newly_observed": True,
            }
        return {
            "status": "retired" if result["complete"] else "retirement_failure",
            "cleanup": result,
            "prior_observation": current,
        }
    except Exception as error:
        return {
            "status": "refused",
            "cleanup": {"complete": False},
            "reason": str(error)
            if isinstance(error, (LinuxContainerError, native.ProbeError))
            else type(error).__name__,
        }
