"""Qualify one trusted empty container through literal native observations.

This is a prerequisite experiment, not a managed MCTS consumer or sandbox.
Only the uniquely named and labelled object created here may be retired.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import select
import shutil
import signal
import stat
import subprocess
import time
import uuid
from pathlib import Path

if __package__:
    from . import linux_enforcement_preflight as preflight
else:
    import linux_enforcement_preflight as preflight

ENDPOINT = "unix:///var/run/docker.sock"
IMAGE = "docker.io/library/python:3.11-slim"
MEMORY = 67_108_864
LABEL = "mcts.ownership-probe"
HEX_ID = re.compile(r"[0-9a-f]{64}\Z")
INIT = (
    "import os,signal,time;"
    "signal.signal(signal.SIGALRM,lambda *_:os._exit(124));"
    "signal.signal(signal.SIGTERM,lambda *_:os._exit(143));"
    "signal.alarm(60);time.sleep(120)"
)
METADATA = """
import json,os,pathlib
p=pathlib.Path('/proc/1')
status=dict(line.split(':',1) for line in (p/'status').read_text().splitlines())
stat_fields=(p/'stat').read_text().rpartition(')')[2].split()
controls={key:(pathlib.Path('/sys/fs/cgroup')/key).read_text().strip()
          for key in ('memory.max','memory.swap.max','pids.max','cpu.max')}
print(json.dumps({'euid':os.geteuid(),'pid1_uid':status['Uid'].split(),
 'pid1_starttime':int(stat_fields[19]),'pid1_cgroup':(p/'cgroup').read_text(),
 'self_cgroup':pathlib.Path('/proc/self/cgroup').read_text(),
 'pid1_signal_handlers':int(status['SigCgt'],16),
 'pid1_no_new_privs':int(status['NoNewPrivs']),
 'pid1_cap_effective':int(status['CapEff'],16),
 'namespaces':{key:(p/'ns'/key).stat().st_ino for key in ('pid','cgroup','mnt')},
 'controls':controls},sort_keys=True))
"""
INSPECT = (
    '{"id":{{json .Id}},"name":{{json .Name}},"image":{{json .Image}},'
    '"pid":{{json .State.Pid}},"running":{{json .State.Running}},'
    '"label":{{json (index .Config.Labels "mcts.ownership-probe")}},'
    '"user":{{json .Config.User}},"cmd":{{json .Config.Cmd}},'
    '"entrypoint":{{json .Config.Entrypoint}},"mounts":{{json .Mounts}},'
    '"host":{{json .HostConfig}}}'
)


class ProbeError(RuntimeError):
    """An explicitly required observation could not be established."""


def require(condition, message):
    if not condition:
        raise ProbeError(message)


def emit(value):
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=True)
    require(len(encoded) <= 65_536, "selected report exceeds output allowance")
    print(encoded, flush=True)


def run(docker, arguments, timeout=10, *, allow_failure=False):
    try:
        result = subprocess.run([docker, "--host", ENDPOINT, *arguments],
                                stdin=subprocess.DEVNULL, capture_output=True,
                                timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        raise ProbeError("selected Docker request timed out") from error
    require(len(result.stdout) <= 65_536 and len(result.stderr) <= 16_384,
            "selected Docker diagnostic exceeds retention allowance")
    if not allow_failure:
        require(result.returncode == 0, "selected Docker request failed")
    return result


def inspect(docker, target, timeout=10):
    value = json.loads(run(docker, ["inspect", "--format", INSPECT, target],
                           timeout).stdout)
    require(isinstance(value, dict), "container inspection is not an object")
    return value


def owned(value, name, nonce, cid=None):
    require(isinstance(value.get("id"), str) and HEX_ID.fullmatch(value["id"]),
            "container identity is not exact")
    require(value.get("name") == "/" + name and value.get("label") == nonce,
            "container name or label differs from this request")
    require(cid is None or value["id"] == cid, "container identity changed")
    return value["id"]


def configuration(value, image):
    require(value.get("image") == image, "container image differs")
    require(value.get("user") == "1001:1001", "container user differs")
    require(value.get("cmd") == ["python3", "-I", "-c", INIT] and
            value.get("entrypoint") in (None, []), "container command differs")
    host = value.get("host")
    require(isinstance(host, dict), "container controls are unavailable")
    expected = {"Memory": MEMORY, "MemorySwap": MEMORY, "PidsLimit": 16,
                "NanoCpus": 1_000_000_000, "Privileged": False,
                "ReadonlyRootfs": True, "NetworkMode": "none",
                "CgroupnsMode": "private"}
    require(all(host.get(key) == item for key, item in expected.items()),
            "container control configuration differs")
    require(host.get("CapDrop") == ["ALL"] and not host.get("CapAdd") and
            host.get("SecurityOpt") == ["no-new-privileges"],
            "container privilege restrictions differ")
    mounts = value.get("mounts")
    require(isinstance(mounts, list) and all(
        mount.get("Type") == "tmpfs" and mount.get("Destination") == "/tmp" and
        not mount.get("Source") for mount in mounts),
        "container has an unsupported mounted filesystem")
    require(not host.get("Binds") and not host.get("Mounts") and
            not host.get("CgroupParent") and
            not host.get("Sysctls") and not host.get("GroupAdd"),
            "container has an unsupported host relationship")
    require(host.get("LogConfig", {}).get("Type") == "none" and
            host.get("Tmpfs") == {"/tmp": "rw,noexec,nosuid,nodev,size=1048576"},
            "container output or temporary filesystem configuration differs")


def read(path, maximum=4096):
    require(stat.S_ISREG(path.lstat().st_mode), "metadata is not an ordinary file")
    with path.open("rb") as stream:
        body = stream.read(maximum + 1)
    require(len(body) <= maximum, "metadata exceeds read allowance")
    return body.decode("ascii")


def hierarchy(text):
    lines = text.splitlines()
    require(len(lines) == 1 and lines[0].startswith("0::/"),
            "a single unified cgroup relationship is required")
    relative = lines[0][3:]
    components = relative[1:].split("/") if relative != "/" else []
    require(all(component not in ("", ".", "..") and
                "\\" not in component for component in components),
            "cgroup path has unsupported components")
    return relative, components


def mount_root():
    mounts = []
    for line in read(Path("/proc/self/mountinfo"), 1_048_576).splitlines():
        left, separator, right = line.partition(" - ")
        if separator and right.split()[0] == "cgroup2":
            fields = left.split()
            require(len(fields) >= 6, "cgroup mount description is incomplete")
            root, point = fields[3:5]
            if point == "/sys/fs/cgroup":
                mounts.append((root, point))
    require(mounts == [("/", "/sys/fs/cgroup")],
            "this probe requires the full host cgroup mount")
    root = Path(mounts[0][1])
    require(stat.S_ISDIR(root.lstat().st_mode), "cgroup root is not ordinary")
    return root


def cgroup_path(root, components):
    current = root
    for component in components:
        current /= component
        require(stat.S_ISDIR(current.lstat().st_mode),
                "cgroup directory is not ordinary")
    require(current.resolve(strict=True).is_relative_to(root.resolve(strict=True)),
            "cgroup directory escapes selected mount")
    return current


def starttime(pid):
    fields = read(Path(f"/proc/{pid}/stat")).rpartition(")")[2].split()
    require(len(fields) > 19, "process identity is incomplete")
    return int(fields[19])


def exited(descriptor, wait_ms=0):
    observer = select.poll()
    observer.register(descriptor, select.POLLIN | select.POLLHUP | select.POLLERR)
    return bool(observer.poll(wait_ms))


def controls(directory):
    values = {key: read(directory / key).strip() for key in
              ("memory.max", "memory.swap.max", "pids.max", "cpu.max")}
    require(values["memory.max"] == str(MEMORY) and
            values["memory.swap.max"] == "0" and values["pids.max"] == "16",
            "literal memory, swap or process limit differs")
    cpu = values["cpu.max"].split()
    require(len(cpu) == 2 and cpu[0].isdigit() and cpu[1].isdigit() and
            int(cpu[0]) == int(cpu[1]) > 0, "literal CPU quota is not one CPU")
    return values


def cleanup(docker, name, nonce, cid, descriptor, directory, stamp):
    result = {"complete": False, "pidfd_signalled": False,
              "container_absent": False, "cgroup_empty_or_absent": False}
    deadline = time.monotonic() + 10

    def remaining():
        value = deadline - time.monotonic()
        require(value > 0, "cleanup deadline reached")
        return min(value, 3)

    try:
        value = inspect(docker, cid or name, remaining())
        cid = owned(value, name, nonce, cid)
        result["container_id"] = cid
        if value.get("running") is True:
            run(docker, ["kill", cid], remaining())
        run(docker, ["rm", cid], remaining())
        absent = run(docker, ["container", "ls", "--all", "--no-trunc",
                              "--filter", "id=" + cid, "--format", "{{json .ID}}"],
                     remaining()).stdout
        result["container_absent"] = not absent.strip()
        if descriptor is not None:
            result["pidfd_signalled"] = exited(
                descriptor, max(0, int((deadline - time.monotonic()) * 1000)))
        if directory is not None:
            try:
                now = directory.lstat()
            except FileNotFoundError:
                result["cgroup_empty_or_absent"] = True
                result["cgroup_disposition"] = "absent"
            else:
                require((now.st_dev, now.st_ino) == stamp,
                        "owned cgroup identity changed during cleanup")
                events = dict(line.split() for line in
                              read(directory / "cgroup.events").splitlines())
                procs = read(directory / "cgroup.procs").split()
                result["cgroup_events"] = events
                result["remaining_cgroup_procs"] = procs
                result["cgroup_empty_or_absent"] = events.get("populated") == "0" \
                    and not procs
                result["cgroup_disposition"] = "empty"
        result["complete"] = all(result[key] for key in
                                 ("pidfd_signalled", "container_absent",
                                  "cgroup_empty_or_absent"))
    except Exception as error:
        result["error"] = str(error) if isinstance(error, ProbeError) \
            else type(error).__name__
    return result


def main():
    report = {"format": "mcts-linux-ownership-prerequisite", "schema_version": 1,
              "candidate_only": True, "policy_workload_admitted": False,
              "ownership_qualified": False, "qualification_process_started": False}
    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured):
            preflight.main()
        gate = json.loads(captured.getvalue())
    except Exception as error:
        report.update(disposition="prerequisite_refused", error=type(error).__name__)
        emit(report)
        return 1
    report["preflight_disposition"] = gate["disposition"]
    if gate["disposition"] != "existing_docker_candidate":
        report["disposition"] = "prerequisite_refused"
        emit(report)
        return 0
    docker = shutil.which("docker")
    if docker is None or gate.get("effective_uid") != 1001:
        report.update(disposition="prerequisite_refused",
                      error="the predeclared local actor is unavailable")
        emit(report)
        return 1
    nonce = uuid.uuid4().hex
    name = "mcts-own-" + nonce
    report.update(nonce=nonce, container_name=name)
    descriptor = directory = stamp = cid = None
    attempted_create = False
    qualified = False
    try:
        root = mount_root()
        controller, _ = hierarchy(read(Path("/proc/self/cgroup")))
        emit({"format": report["format"], "phase": "before_acquisition",
              "nonce": nonce, "container_name": name, "image_selector": IMAGE})
        run(docker, ["pull", "--quiet", IMAGE], 90)
        image = json.loads(run(docker, ["image", "inspect", "--format", "{{json .Id}}",
                                        IMAGE]).stdout)
        require(isinstance(image, str) and image.startswith("sha256:") and
                HEX_ID.fullmatch(image[7:]), "immutable image identity is unavailable")
        report["image_id"] = image
        emit({"format": report["format"], "phase": "before_create", "nonce": nonce,
              "container_name": name, "image_id": image})
        attempted_create = True
        created = run(docker, ["create", "--pull=never", "--name", name,
                              "--label", LABEL + "=" + nonce, "--memory", str(MEMORY),
                              "--memory-swap", str(MEMORY), "--pids-limit", "16",
                              "--cpus", "1", "--user", "1001:1001", "--cap-drop", "ALL",
                              "--security-opt", "no-new-privileges",
                              "--network", "none", "--read-only",
                              "--cgroupns", "private", "--log-driver", "none",
                              "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=1048576",
                              image, "python3", "-I", "-c", INIT])
        created = created.stdout.decode().strip()
        require(HEX_ID.fullmatch(created), "created container identity is not exact")
        cid = owned(inspect(docker, created), name, nonce, created)
        report["container_id"] = cid
        configuration(inspect(docker, cid), image)
        emit({"format": report["format"], "phase": "created", "container_id": cid,
              "nonce": nonce, "container_name": name})
        run(docker, ["start", cid])
        report["qualification_process_started"] = True
        value = inspect(docker, cid)
        owned(value, name, nonce, cid)
        configuration(value, image)
        pid = value.get("pid")
        require(value.get("running") is True and type(pid) is int and pid > 1,
                "running host process identity is unavailable")
        descriptor = os.pidfd_open(pid, 0)
        require(not exited(descriptor), "container root process already exited")
        identity = starttime(pid)
        relative, components = hierarchy(read(Path(f"/proc/{pid}/cgroup")))
        require(cid in relative, "host PID cgroup does not bind the exact container")
        directory = cgroup_path(root, components)
        value = directory.lstat()
        stamp = value.st_dev, value.st_ino
        literal = controls(directory)
        members = [int(item) for item in read(directory / "cgroup.procs").split()]
        require(pid in members and os.getpid() not in members and
                controller != relative and not controller.startswith(relative + "/"),
                "root membership or controller exclusion differs")
        namespaces = {key: Path(f"/proc/{pid}/ns/{key}").stat().st_ino
                      for key in ("pid", "cgroup", "mnt")}
        require(namespaces["pid"] != Path("/proc/self/ns/pid").stat().st_ino and
                namespaces["cgroup"] != Path("/proc/self/ns/cgroup").stat().st_ino,
                "private namespaces are unavailable")
        inside = json.loads(run(docker, ["exec", cid, "python3", "-I", "-c",
                                        METADATA]).stdout)
        require(inside.get("euid") == 1001 and inside.get("pid1_uid") == ["1001"] * 4
                and inside.get("pid1_starttime") == identity and
                inside.get("namespaces") == namespaces and
                inside.get("pid1_no_new_privs") == 1 and
                inside.get("pid1_cap_effective") == 0 and
                inside.get("pid1_cgroup") == "0::/\n" and
                inside.get("self_cgroup") == "0::/\n" and
                inside.get("controls") == literal,
                "container namespace observations do not reconcile with host PID")
        handlers = inside.get("pid1_signal_handlers")
        require(type(handlers) is int and all(handlers & (1 << (number - 1))
                for number in (signal.SIGALRM, signal.SIGTERM)),
                "finite root process signal handlers are unavailable")
        final = inspect(docker, cid)
        owned(final, name, nonce, cid)
        configuration(final, image)
        current = directory.lstat()
        require(final.get("running") is True and final.get("pid") == pid and
                starttime(pid) == identity and not exited(descriptor) and
                (current.st_dev, current.st_ino) == stamp and
                controls(directory) == literal and
                pid in [int(item) for item in read(directory / "cgroup.procs").split()],
                "root process changed during qualification")
        report["native"] = {"host_pid": pid, "host_pid_starttime": identity,
                            "cgroup": relative, "cgroup_identity": list(stamp),
                            "controller_cgroup": controller,
                            "controller_excluded": True,
                            "root_membership_verified": True, "controls": literal,
                            "namespaces": namespaces, "inside": inside}
        qualified = True
        emit({"format": report["format"], "phase": "native_observed",
              "container_id": cid, "native": report["native"]})
    except Exception as error:
        report["error"] = str(error) if isinstance(error, ProbeError) \
            else type(error).__name__
    finally:
        if attempted_create:
            report["cleanup"] = cleanup(docker, name, nonce, cid, descriptor,
                                         directory, stamp)
        if descriptor is not None:
            os.close(descriptor)
    report["ownership_qualified"] = bool(
        qualified and report.get("cleanup", {}).get("complete"))
    report["disposition"] = "native_prerequisite_observed" \
        if report["ownership_qualified"] else "native_prerequisite_unqualified"
    report["scope"] = (
        "One trusted empty qualification process. No policy, failure experiment, "
        "installed consumer or hostile code sandbox. Memory is cgroup accounting. "
        "Image, daemon, CLI and controller costs are excluded. A controller loss "
        "leaves a recorded container object; its explicit alarm limits root lifetime.")
    emit(report)
    return 0 if report["ownership_qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
