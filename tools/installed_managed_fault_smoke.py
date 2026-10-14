"""Witness direct collector interruption in the relocated installed companion.

This is a controlled fault fixture. Only the calling controller's launch method
is instrumented. The collector and recorder source bytes remain unchanged.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import sys
import sysconfig
import threading
import time
from pathlib import Path
from unittest.mock import patch

import engine


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def identities(root):
    """Hash only the small known fixture tree with explicit evidence bounds."""
    values = {}
    total = 0
    for path in root.rglob("*"):
        require(not path.is_symlink(), "fixture contains a symbolic link")
        if not path.is_file():
            continue
        require(len(values) < 192, "fixture artifact count exceeds its allowance")
        size = path.stat().st_size
        require(size <= 8_388_608, "fixture artifact exceeds its allowance")
        total += size
        require(total <= 67_108_864, "fixture evidence exceeds its allowance")
        body = path.read_bytes()
        require(len(body) == size, "fixture changed while being captured")
        values[path.relative_to(root).as_posix()] = {
            "bytes": size, "sha256": hashlib.sha256(body).hexdigest()}
    return values


def main():
    require(os.name == "nt", "strict Windows fault acceptance only")
    root = Path(sys.argv[1]).resolve()
    companion = root / "relocated-companion"
    acceptance = root / "managed-acceptance"
    protocol = acceptance / "protocol.json"
    output = acceptance / "collector-interrupted"
    require(companion.is_dir() and protocol.is_file(),
            "run installed_managed_smoke.py on this journey first")
    origin = Path(engine.__file__).resolve()
    require(origin.is_relative_to(Path(sysconfig.get_path("purelib")).resolve()),
            "fault fixture requires the separately installed engine")
    require(not output.exists(), "fault capture must use a new directory")
    with protocol.open("rb") as stream:
        before_protocol = stream.read(2_097_153)
    require(len(before_protocol) <= 2_097_152, "fixture protocol exceeds its allowance")
    before_companion = identities(companion)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(companion))
    from game import episode_record as records
    from tools import encounter_process as owned
    from tools import encounter_recovery as recovery
    from tools import managed_encounter as managed

    for module in (records, owned, recovery, managed):
        require(Path(module.__file__).resolve().is_relative_to(companion),
                "fixture imported a helper outside the relocated companion")
    original_create = owned._WindowsProcess.create_suspended
    holder = {}
    observed = {"fixture": "direct_collector_interruption",
                "termination_requested": False, "termination_succeeded": False,
                "second_slot_intent_observed": False, "watcher_errors": [],
                "target": "exact duplicate of the directly created collector handle",
                "pid_lookup_used": False, "member_or_global_kill_used": False,
                "collector_source_modified": False}
    ready = threading.Event()
    stop = threading.Event()

    def retain_collector(native, command, cwd):
        original_create(native, command, cwd)
        require(not holder, "fault fixture unexpectedly observed another launch")
        kernel = native.kernel
        handle_type = native.wintypes.HANDLE
        kernel.GetCurrentProcess.argtypes = []
        kernel.GetCurrentProcess.restype = handle_type
        kernel.DuplicateHandle.argtypes = [
            handle_type, handle_type, handle_type, ctypes.POINTER(handle_type),
            native.wintypes.DWORD, native.wintypes.BOOL, native.wintypes.DWORD,
        ]
        kernel.DuplicateHandle.restype = native.wintypes.BOOL
        current = kernel.GetCurrentProcess()
        duplicate = handle_type()
        if not kernel.DuplicateHandle(current, native.process, current,
                                      ctypes.byref(duplicate), 0, False, 2):
            raise ctypes.WinError(ctypes.get_last_error())
        holder.update(native=native, handle=int(duplicate.value))
        ready.set()

    def interrupt_collector():
        deadline = time.monotonic() + 5
        intent = output / "capture/trials/00001/admission-intent.json"
        try:
            while not stop.is_set() and time.monotonic() < deadline:
                if ready.is_set() and intent.is_file():
                    observed["second_slot_intent_observed"] = True
                    observed["termination_requested"] = True
                    native = holder["native"]
                    if not native.kernel.TerminateProcess(holder["handle"], 71):
                        raise ctypes.WinError(ctypes.get_last_error())
                    observed["termination_succeeded"] = True
                    return
                stop.wait(0.002)
        except BaseException as error:
            observed["watcher_errors"].append(type(error).__name__ + ": " + str(error))

    watcher = threading.Thread(target=interrupt_collector,
                               name="controlled-collector-interruption", daemon=True)
    watcher.start()
    try:
        with patch.object(owned._WindowsProcess, "create_suspended", retain_collector):
            result, status = managed.run_managed(protocol, output, wall_seconds=45)
    finally:
        stop.set()
        watcher.join(timeout=5)
        if holder:
            native = holder["native"]
            handle = holder["handle"]
            try:
                observed["duplicate_signaled"] = (
                    native.kernel.WaitForSingleObject(handle, 0) == 0)
                code = native.wintypes.DWORD()
                if not native.kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                    raise ctypes.WinError(ctypes.get_last_error())
                observed["queried_collector_exit_code"] = int(code.value)
            finally:
                if not native.kernel.CloseHandle(handle):
                    raise ctypes.WinError(ctypes.get_last_error())
                observed["duplicate_closed"] = True
    require(not watcher.is_alive(), "fault watcher did not retire")
    require(observed["termination_succeeded"] and not observed["watcher_errors"],
            "controlled collector interruption was not observed: " + str(observed))
    require(observed["duplicate_signaled"] and
            observed["queried_collector_exit_code"] == 71 and
            observed["duplicate_closed"], "exact collector handle did not retire")
    require(status == 1 and result["status"] == "incomplete" and
            result["owner"]["failure_kind"] == "worker_failed" and
            result["owner"]["cleanup"]["retired"] is True,
            "interrupted collector was presented as complete or not retired")
    require(result["worker"] is None,
            "killed collector supplied a complete worker result")
    saved = identities(output)
    report_path = acceptance / "collector-interrupted-recovery.json"

    def refuse(*arguments, **keywords):
        raise RuntimeError("EXECUTION REACHED DURING RECOVERY")

    with (patch("subprocess.Popen", refuse),
          patch.object(engine.MCTS, "__init__", refuse),
          patch.object(engine, "mcts_decider", refuse),
          patch.object(records, "_record_owner", refuse),
          patch.object(records, "replay_episode", refuse)):
        report = recovery.recover_capture(output / "capture", report_path)
    counts = report["summary"]["classifications"]
    require(report["summary"]["intended_trials"] == 6 and
            1 <= counts["complete_admitted"] < 6,
            "recovery did not retain completed evidence and the original six slots")
    unknown_attempts = [row["trial"]["index"] for row in report["trials"]
                        if row["classification"] == "incomplete_attempt"]
    require(unknown_attempts, "interrupted active attempt did not remain unknown")
    require(identities(output) == saved, "recovery changed interrupted evidence")
    require(protocol.read_bytes() == before_protocol,
            "fault fixture changed its protocol")
    require(identities(companion) == before_companion, "companion source was changed")
    summary = {
        "fixture": observed, "owner_status": result["status"],
        "owner_failure_kind": result["owner"]["failure_kind"],
        "owner_cleanup": result["owner"]["cleanup"],
        "collector_worker_result_present": result["worker"] is not None,
        "recovery": report["summary"], "unknown_attempt_indices": unknown_attempts,
        "originals_unchanged": True, "scientific_data_added": False,
        "interpretation": "Controlled collector interruption fixture. The controller "
                          "launch hook retains an exact handle. Collector and recorder "
                          "source is unchanged. "
                          "This is not an ordinary successful run.",
    }
    receipt = acceptance / "collector-interrupted-fixture.json"
    with receipt.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
