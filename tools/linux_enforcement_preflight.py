"""Inspect existing Linux enforcement candidates without changing host state.

This read-only qualification does not launch a container or prove ownership,
admission, failure or cleanup. No workload may be admitted on its result alone.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path


def command(argv: list[str]) -> dict:
    try:
        result = subprocess.run(argv, capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"available": False, "error": type(error).__name__}
    if len(result.stdout) > 16384 or len(result.stderr) > 4096:
        return {"available": False, "error": "diagnostic output exceeds allowance"}
    if result.returncode:
        return {"available": False, "returncode": result.returncode}
    try:
        return {"available": True, "value": json.loads(result.stdout)}
    except (UnicodeError, ValueError):
        return {"available": False, "error": "invalid diagnostic JSON"}


def main() -> None:
    report = {"format": "mcts-linux-enforcement-preflight", "schema_version": 1,
              "platform": sys.platform, "read_only": True,
              "workload_admitted": False, "ownership_established": False}
    if sys.platform != "linux":
        report["disposition"] = "unsupported_platform"
        print(json.dumps(report, sort_keys=True))
        return
    report["effective_uid"] = os.geteuid()
    root = Path("/sys/fs/cgroup")
    report["cgroup_v2"] = (root / "cgroup.controllers").is_file()
    report["self_cgroup"] = Path("/proc/self/cgroup").read_text()[:4096]
    controllers = root / "cgroup.controllers"
    report["root_controllers"] = (
        controllers.read_text().split() if controllers.is_file() else [])
    report["root_writable"] = os.access(root, os.W_OK)
    report["root_procs_writable"] = os.access(root / "cgroup.procs", os.W_OK)
    docker = shutil.which("docker")
    report["docker_cli_present"] = docker is not None
    report["docker_host_override_present"] = "DOCKER_HOST" in os.environ
    report["docker_context_override_present"] = "DOCKER_CONTEXT" in os.environ
    socket = Path("/var/run/docker.sock")
    try:
        socket_mode = socket.stat().st_mode
    except OSError:
        socket_mode = 0
    report["local_socket_accessible"] = (
        stat.S_ISSOCK(socket_mode) and os.access(socket, os.R_OK | os.W_OK))
    if docker is not None:
        template = (
            '{"os_type":{{json .OSType}},"server_version":{{json .ServerVersion}},'
            '"cgroup_version":{{json .CgroupVersion}},'
            '"cgroup_driver":{{json .CgroupDriver}},'
            '"memory_limit":{{json .MemoryLimit}},'
            '"swap_limit":{{json .SwapLimit}},"pids_limit":{{json .PidsLimit}},'
            '"security_options":{{json .SecurityOptions}},'
            '"authorization_plugins":{{json .Plugins.Authorization}}}')
        context_report = command([
            docker, "context", "inspect", "--format",
            '{{json .Endpoints.docker.Host}}'])
        local = context_report.get("value") == "unix:///var/run/docker.sock"
        report["docker_context"] = {
            "available": context_report["available"], "local_endpoint": local}
        if (local and report["local_socket_accessible"] and
                not report["docker_host_override_present"] and
                not report["docker_context_override_present"]):
            report["docker_info"] = command([
                docker, "--host", "unix:///var/run/docker.sock",
                "info", "--format", template])
        else:
            report["docker_info"] = {"available": False,
                                     "error": "no qualified local endpoint"}
    info = report.get("docker_info", {}).get("value", {})
    context = report.get("docker_context", {}).get("local_endpoint")
    candidate = (
        os.geteuid() != 0 and report["cgroup_v2"] and
        report["local_socket_accessible"] and
        not report["docker_host_override_present"] and
        not report["docker_context_override_present"] and
        context is True and
        isinstance(info, dict) and info.get("os_type") == "linux" and
        str(info.get("cgroup_version")) == "2" and
        info.get("cgroup_driver") in {"systemd", "cgroupfs"} and
        info.get("memory_limit") is True and info.get("swap_limit") is True and
        info.get("pids_limit") is True and not info.get("authorization_plugins"))
    report["disposition"] = ("existing_docker_candidate" if candidate
                             else "no_qualified_candidate")
    report["required_next_evidence"] = (
        "An owned cgroup's literal limits and membership before admission, "
        "native failure/cleanup experiments and an external installed consumer")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
