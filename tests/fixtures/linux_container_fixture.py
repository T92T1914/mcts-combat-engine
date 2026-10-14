"""Fixed trusted native pressure witnesses, separate from scientific inputs.

Exit codes and local messages do not prove enforcement. The external acceptance
driver requires actual cgroup event changes, membership and observed retirement.
"""

from __future__ import annotations

import errno
import json
import os
import signal
import sys
import time
from pathlib import Path

MIB = 1_048_576
ACTIONS = {"memory", "pids", "escape", "output", "hold", "control", "error"}


def emit(value: dict) -> None:
    print(json.dumps(value, sort_keys=True), flush=True)


def retire(children: list[int]) -> list[dict]:
    results = []
    for child in children:
        try:
            os.kill(child, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for child in children:
        try:
            _, status = os.waitpid(child, 0)
            results.append(
                {"pid": child, "returncode": os.waitstatus_to_exitcode(status)}
            )
        except ChildProcessError:
            pass
    return results


def memory() -> None:
    children = []
    for _ in range(2):
        child = os.fork()
        if child == 0:
            blocks = []
            for index in range(20):
                block = bytearray(4 * MIB)
                block[::4096] = b"x" * (len(block) // 4096)
                blocks.append(block)
                if index in (0, 9, 19):
                    emit(
                        {
                            "action": "memory",
                            "pid": os.getpid(),
                            "touched_bytes": sum(map(len, blocks)),
                        }
                    )
                time.sleep(0.01)
            time.sleep(30)
            os._exit(0)
        children.append(child)
    emit(
        {
            "action": "memory",
            "children": children,
            "per_child_target_bytes": 80 * MIB,
            "combined_target_bytes": 160 * MIB,
            "allocations_overlap": True,
        }
    )
    deadline = time.monotonic() + 12
    observed = []
    live = list(children)
    while live and time.monotonic() < deadline:
        for child in list(live):
            pid, status = os.waitpid(child, os.WNOHANG)
            if pid:
                live.remove(child)
                observed.append(
                    {"pid": child, "returncode": os.waitstatus_to_exitcode(status)}
                )
        if observed:
            break
        time.sleep(0.02)
    observed.extend(retire(live))
    emit(
        {
            "action": "memory",
            "observed_children": observed,
            "native_event_oracle_required": True,
        }
    )


def pids() -> None:
    children = []
    observed_errno = None
    try:
        for _ in range(100):
            try:
                child = os.fork()
            except OSError as error:
                observed_errno = error.errno
                break
            if child == 0:
                time.sleep(30)
                os._exit(0)
            children.append(child)
        emit(
            {
                "action": "pids",
                "attempted_upper_bound": 100,
                "created": len(children),
                "observed_errno": observed_errno,
                "eagain_observed": observed_errno == errno.EAGAIN,
                "native_event_oracle_required": True,
            }
        )
    finally:
        retire(children)


def escape() -> None:
    child = os.fork()
    if child == 0:
        os.setsid()
        orphan = os.fork()
        if orphan:
            os._exit(0)
        # The original parent has exited. Retain the same private cgroup and
        # session witness, then close inherited output so it cannot hold the
        # controller's transport open.
        time.sleep(0.1)
        emit(
            {
                "action": "escape",
                "orphan_pid": os.getpid(),
                "parent_pid": os.getppid(),
                "session": os.getsid(0),
                "process_group": os.getpgrp(),
                "private_cgroup": Path("/proc/self/cgroup").read_text().strip(),
            }
        )
        descriptor = os.open("/dev/null", os.O_RDWR)
        for stream in (0, 1, 2):
            os.dup2(descriptor, stream)
        if descriptor > 2:
            os.close(descriptor)
        time.sleep(120)
        os._exit(0)
    os.waitpid(child, 0)
    time.sleep(0.3)
    emit(
        {
            "action": "escape",
            "worker_pid": os.getpid(),
            "session": os.getsid(0),
            "private_cgroup": Path("/proc/self/cgroup").read_text().strip(),
        }
    )


def output() -> None:
    block = b"overflow-witness:" + b"x" * (65_536 - 17)
    for _ in range(256):
        os.write(1, block)


def hold() -> None:
    emit({"action": "hold", "started": True, "pid": os.getpid()})
    time.sleep(120)


def control() -> None:
    children = []
    for _ in range(2):
        child = os.fork()
        if child == 0:
            block = bytearray(8 * MIB)
            block[::4096] = b"x" * (len(block) // 4096)
            time.sleep(0.1)
            os._exit(0)
        children.append(child)
    codes = []
    for child in children:
        _, status = os.waitpid(child, 0)
        codes.append(os.waitstatus_to_exitcode(status))
    emit(
        {
            "action": "control",
            "created_children": len(children),
            "child_returncodes": codes,
            "per_child_touched_bytes": 8 * MIB,
            "combined_touched_bytes": 16 * MIB,
            "bounded_output": True,
        }
    )


def error() -> None:
    emit({"action": "error", "ordinary_exit": 7})
    raise SystemExit(7)


def main() -> None:
    if sys.platform != "linux" or os.geteuid() == 0:
        raise ValueError("fixed witness requires admitted nonroot Linux")
    if len(sys.argv) != 2 or sys.argv[1] not in ACTIONS:
        raise ValueError("select one fixed trusted native witness")
    {
        "memory": memory,
        "pids": pids,
        "escape": escape,
        "output": output,
        "hold": hold,
        "control": control,
        "error": error,
    }[sys.argv[1]]()


if __name__ == "__main__":
    main()
