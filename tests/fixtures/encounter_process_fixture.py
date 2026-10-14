"""Bounded hidden process fixtures for the companion's Windows owner tests."""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def observation() -> dict:
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE,
                                      ctypes.POINTER(wintypes.BOOL)]
    kernel.IsProcessInJob.restype = wintypes.BOOL
    member = wintypes.BOOL()
    if not kernel.IsProcessInJob(
            kernel.GetCurrentProcess(), None, ctypes.byref(member)):
        raise ctypes.WinError(ctypes.get_last_error())
    return {"pid": os.getpid(), "in_a_job": bool(member.value)}


def marker(directory: Path, name: str, value: dict) -> None:
    pending = directory / (name + ".pending")
    pending.write_text(json.dumps(value), encoding="utf-8")
    pending.replace(directory / name)


def child(mode: str, directory: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-I", "-B", str(Path(__file__).resolve()), mode,
         str(directory)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)


def main() -> int:
    mode, directory = sys.argv[1], Path(sys.argv[2])
    if mode == "nested-owner":
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from tools.encounter_process import run_owned

        result = run_owned(
            [sys.executable, "-I", "-B", str(Path(__file__).resolve()),
             "descendant", str(directory)], cwd=directory, wall_seconds=4,
            cleanup_seconds=1, memory_bytes=64 * 1024 * 1024,
            stdout_limit=4096, stderr_limit=4096)
        marker(directory, "inner-owner.json", result["owner"])
        print("nested owner returned", flush=True)
        return 0 if result["owner"]["failure_kind"] is None else 31
    if mode == "controller":
        # This is test source discovery, not a consumer import path assertion.
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from tools.encounter_process import run_owned

        def end_controller(name: str, data: bytes) -> None:
            if name == "stdout" and data:
                marker(directory, "controller-ready.json", observation())
                until = time.monotonic() + 3
                while time.monotonic() < until:
                    if (directory / "allow-controller-death").exists():
                        os._exit(29)
                    time.sleep(0.01)

        result = run_owned(
            [sys.executable, "-I", "-B", str(Path(__file__).resolve()),
             "hang-descendant", str(directory)], cwd=directory, wall_seconds=6,
            cleanup_seconds=1, memory_bytes=128 * 1024 * 1024,
            stdout_limit=4096, stderr_limit=4096, on_chunk=end_controller)
        marker(directory, "owner-complete.json", result["owner"])
        return 30
    if mode == "leaf" or mode == "long-leaf":
        marker(directory, "leaf.json", observation())
        time.sleep(0.35 if mode == "leaf" else 5)
        return 0
    if mode in ("descendant", "hang-descendant", "orphan-descendant"):
        marker(directory, "worker.json", observation())
        descendant = child("leaf" if mode == "descendant" else "long-leaf", directory)
        if mode == "orphan-descendant":
            until = time.monotonic() + 1
            while not (directory / "leaf.json").exists() and time.monotonic() < until:
                time.sleep(0.005)
            print("ready", flush=True)
            return 0
        print("ready", flush=True)
        return descendant.wait(timeout=6)
    if mode == "flood-stdout" or mode == "flood-stderr":
        descriptor = 1 if mode == "flood-stdout" else 2
        block = b"x" * 8192
        for _ in range(4):
            os.write(descriptor, block)
        return 0
    if mode == "memory-leaf":
        marker(directory, "memory-leaf.json", observation())
        try:
            allocation = bytearray(24 * 1024 * 1024)
        except MemoryError:
            return 7
        return int(allocation[0])
    if mode == "memory-parent":
        try:
            allocation = bytearray(24 * 1024 * 1024)
        except MemoryError:
            return 6
        marker(directory, "memory-parent.json", observation())
        result = child("memory-leaf", directory).wait(timeout=4)
        print(json.dumps({"child_returncode": result,
                          "retained_parent_bytes": len(allocation)}), flush=True)
        return result
    if mode == "exact":
        os.write(1, b"s" * 16)
        os.write(2, b"e" * 32)
        return 0
    if mode == "sleep":
        marker(directory, "worker.json", observation())
        print("ready", flush=True)
        time.sleep(5)
        return 0
    if mode == "complete":
        value = observation()
        marker(directory, "worker.json", value)
        print(json.dumps(value), flush=True)
        return 0
    raise ValueError("unknown bounded fixture mode")


if __name__ == "__main__":
    raise SystemExit(main())
