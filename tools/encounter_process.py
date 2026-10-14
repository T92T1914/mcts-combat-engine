"""Own a known companion process tree with bounded retained transport.

The Windows Job/accounting design builds on the public Solver process owner at
T92T1914/exact-blackjack-solver c5fa104375fca65404cfdf2ddda015d9eb6a54a2,
bj/_calculation_process.py. Creation Job assignment and suspended launch are new.
See Microsoft Job Objects, CreateProcessW, UpdateProcThreadAttribute and
ResumeThread. This owner is a local workload limit, not a hostile code sandbox.
"""
from __future__ import annotations

import ctypes
import math
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

CHUNK_BYTES = 8192
STDOUT_BYTES = 8_388_608
STDERR_BYTES = 65_536
JOB_FLAGS = 0x2000 | 0x200 | 0x400
CREATE_FLAGS = 0x4 | 0x08000000 | 0x400 | 0x80000
HANDLE_LIST = 0x20002
JOB_LIST = 0x2000D
MEMBER_LIMIT = 64


class EnforcementUnavailable(RuntimeError):
    """The strict process ownership mechanism is unavailable before launch."""

    receipt: dict | None = None


def _supported_platform() -> None:
    if os.name != "nt":
        raise EnforcementUnavailable(
            "managed execution requires Windows 10 or newer Job ownership; "
            "no weaker process group or memory fallback is selected")
    if sys.getwindowsversion().major < 10:
        raise EnforcementUnavailable(
            "managed execution requires Windows 10 creation Job assignment")


def _message(error: BaseException) -> str:
    return type(error).__name__ + ": " + str(error)[:1024]


class _WindowsProcess:
    """Keep the sole Job handle and all launch handles outside the worker."""

    def __init__(self) -> None:
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD), ("minimum_ws", ctypes.c_size_t),
                ("maximum_ws", ctypes.c_size_t), ("active_limit", wintypes.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "read_ops", "write_ops", "other_ops", "read_bytes",
                "write_bytes", "other_bytes")]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("basic", BasicLimits), ("io", IoCounters),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t),
                ("peak_job_memory", ctypes.c_size_t),
            ]

        class Accounting(ctypes.Structure):
            _fields_ = [(name, ctypes.c_int64) for name in (
                "user_time", "kernel_time", "period_user", "period_kernel")]
            _fields_ += [(name, wintypes.DWORD) for name in (
                "page_faults", "total_processes", "active_processes", "terminated")]

        class StartupInfo(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("reserved", wintypes.LPWSTR),
                ("desktop", wintypes.LPWSTR), ("title", wintypes.LPWSTR),
                ("x", wintypes.DWORD), ("y", wintypes.DWORD),
                ("x_size", wintypes.DWORD), ("y_size", wintypes.DWORD),
                ("x_chars", wintypes.DWORD), ("y_chars", wintypes.DWORD),
                ("fill", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("show", wintypes.WORD), ("reserved_bytes", wintypes.WORD),
                ("reserved_pointer", ctypes.c_void_p),
                ("stdin", wintypes.HANDLE), ("stdout", wintypes.HANDLE),
                ("stderr", wintypes.HANDLE),
            ]

        class StartupInfoEx(ctypes.Structure):
            _fields_ = [("startup", StartupInfo), ("attributes", ctypes.c_void_p)]

        class ProcessInfo(ctypes.Structure):
            _fields_ = [
                ("process", wintypes.HANDLE), ("thread", wintypes.HANDLE),
                ("pid", wintypes.DWORD), ("thread_id", wintypes.DWORD),
            ]

        class ProcessIds(ctypes.Structure):
            _fields_ = [("assigned", wintypes.DWORD), ("listed", wintypes.DWORD),
                        ("ids", ctypes.c_size_t * MEMBER_LIMIT)]

        self.kernel: Any = ctypes.WinDLL("kernel32", use_last_error=True)
        specifications = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": (
                [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
                wintypes.BOOL),
            "QueryInformationJobObject": (
                [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                 ctypes.c_void_p], wintypes.BOOL),
            "IsProcessInJob": (
                [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)],
                wintypes.BOOL),
            "GetHandleInformation": (
                [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "TerminateProcess": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "WaitForSingleObject": (
                [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            "GetExitCodeProcess": (
                [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
            "OpenProcess": (
                [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "InitializeProcThreadAttributeList": (
                [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                 ctypes.POINTER(ctypes.c_size_t)], wintypes.BOOL),
            "UpdateProcThreadAttribute": (
                [ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p,
                 ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p], wintypes.BOOL),
            "DeleteProcThreadAttributeList": ([ctypes.c_void_p], None),
            "CreateProcessW": (
                [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                 wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
                 ctypes.POINTER(StartupInfoEx), ctypes.POINTER(ProcessInfo)],
                wintypes.BOOL),
        }
        for name, (arguments, result) in specifications.items():
            function = getattr(self.kernel, name)
            function.argtypes, function.restype = arguments, result
        self.wintypes = wintypes
        self.extended_type = ExtendedLimits
        self.accounting_type = Accounting
        self.startup_type = StartupInfoEx
        self.process_type = ProcessInfo
        self.process_ids_type = ProcessIds
        self.job: int | None = None
        self.process: int | None = None
        self.thread: int | None = None
        self.pid: int | None = None
        self.returncode: int | None = None
        self.reaped = False
        self.memory_bytes = 0
        self.readers: dict[str, int] = {}
        self.child_fds: list[int] = []
        self.member_handles: dict[int, int] = {}
        self.verified_members: set[int] = set()
        self.observed_member_pids: list[int] = []
        self.attribute_buffer: Any = None
        self.attribute_initialized = False
        self.launch: dict[str, Any] = {
            "assignment_method": "creation_job_list", "created_suspended": False,
            "membership_verified_before_resume": False,
            "limits_verified_before_resume": False, "primary_thread_resumed": False,
            "job_handle_noninheritable": False,
            "process_handles_noninheritable": False,
            "stdio_handle_list_only": False,
        }

    def _check(self, result: Any) -> None:
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())

    def _noninheritable(self, handle: int) -> None:
        flags = self.wintypes.DWORD()
        self._check(self.kernel.GetHandleInformation(handle, ctypes.byref(flags)))
        if flags.value & 1:
            raise OSError("an ownership handle was unexpectedly inheritable")

    def prepare(self, memory_bytes: int) -> None:
        self.memory_bytes = memory_bytes
        handle = self.kernel.CreateJobObjectW(None, None)
        self._check(handle)
        self.job = int(handle)
        self._noninheritable(self.job)
        self.launch["job_handle_noninheritable"] = True
        limits = self.extended_type()
        limits.basic.flags = JOB_FLAGS
        limits.job_memory = memory_bytes
        self._check(self.kernel.SetInformationJobObject(
            self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
        self.verify_limits()

    def verify_limits(self) -> dict:
        limits = self.extended_type()
        self._check(self.kernel.QueryInformationJobObject(
            self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits), None))
        if limits.job_memory != self.memory_bytes or limits.basic.flags != JOB_FLAGS:
            raise OSError("Windows Job limits differ from the selected policy")
        return {"flags": int(limits.basic.flags),
                "aggregate_commit_bytes": int(limits.job_memory),
                "peak_job_memory_used_bytes": int(limits.peak_job_memory)}

    def active_count(self) -> int:
        counters = self.accounting_type()
        self._check(self.kernel.QueryInformationJobObject(
            self.job, 1, ctypes.byref(counters), ctypes.sizeof(counters), None))
        return int(counters.active_processes)

    def _signaled(self, handle: int) -> bool:
        result = self.kernel.WaitForSingleObject(handle, 0)
        if result == 0:
            return True
        if result == 0x102:
            return False
        raise ctypes.WinError(ctypes.get_last_error())

    def capture_members(self) -> None:
        """Pin only process IDs returned by this owned Job, never a global list."""
        if self.job is None:
            return
        listed = self.process_ids_type()
        if not self.kernel.QueryInformationJobObject(
                self.job, 3, ctypes.byref(listed), ctypes.sizeof(listed), None):
            code = ctypes.get_last_error()
            if code == 234:  # ERROR_MORE_DATA, including an inventory over the cap.
                raise OSError("owned Job process inventory exceeds 64 entries")
            raise ctypes.WinError(code)
        if listed.assigned > MEMBER_LIMIT or listed.listed > MEMBER_LIMIT:
            raise OSError("owned Job process inventory exceeds 64 entries")
        for value in listed.ids[:listed.listed]:
            pid = int(value)
            if pid == self.pid:
                continue  # The exact CreateProcessW handle supplies direct reaping.
            if pid not in self.member_handles:
                if len(self.member_handles) >= MEMBER_LIMIT - 1:
                    raise OSError("observed Job members exceed 64 retained entries")
                # QUERY_LIMITED_INFORMATION | SYNCHRONIZE, without termination.
                handle = self.kernel.OpenProcess(0x101000, False, pid)
                self._check(handle)
                self.member_handles[pid] = int(handle)
                self._noninheritable(int(handle))
            handle = self.member_handles[pid]
            member = self.wintypes.BOOL()
            self._check(self.kernel.IsProcessInJob(handle, self.job,
                                                  ctypes.byref(member)))
            # A new nonmember may be a recycled PID, even if already signaled.
            # Only a previously membership-verified handle proves that an exit
            # racing this query belongs to the observed owned process object.
            if not member.value:
                if pid not in self.verified_members or not self._signaled(handle):
                    raise OSError("listed process has no verified owned membership")
            elif pid not in self.verified_members:
                self.verified_members.add(pid)
                self.observed_member_pids.append(pid)

    def members_signaled(self) -> bool:
        return all(self._signaled(handle) for handle in self.member_handles.values())

    def close_member_handles(self) -> None:
        errors = []
        for pid, handle in list(self.member_handles.items()):
            if self.kernel.CloseHandle(handle):
                del self.member_handles[pid]
            else:
                errors.append(str(ctypes.WinError(ctypes.get_last_error())))
        if errors:
            raise OSError("owned member handle closure failed: "
                          + "; ".join(errors)[:1024])

    def _attributes(self, handles: list[int]) -> None:
        size = ctypes.c_size_t()
        # The first call obtains the required size and normally returns false.
        self.kernel.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
        if size.value <= 0 or size.value > 65_536:
            raise EnforcementUnavailable("creation attribute sizing is unavailable")
        self.attribute_buffer = ctypes.create_string_buffer(size.value)
        self._check(self.kernel.InitializeProcThreadAttributeList(
            self.attribute_buffer, 2, 0, ctypes.byref(size)))
        self.attribute_initialized = True
        inherited = (self.wintypes.HANDLE * len(handles))(*handles)
        jobs = (self.wintypes.HANDLE * 1)(self.job)
        # Attribute values must outlive the attribute list.
        self.attribute_values = inherited, jobs
        self._check(self.kernel.UpdateProcThreadAttribute(
            self.attribute_buffer, 0, HANDLE_LIST, ctypes.byref(inherited),
            ctypes.sizeof(inherited), None, None))
        if not self.kernel.UpdateProcThreadAttribute(
                self.attribute_buffer, 0, JOB_LIST, ctypes.byref(jobs),
                ctypes.sizeof(jobs), None, None):
            raise EnforcementUnavailable(
                "Windows creation Job assignment is unavailable: "
                + str(ctypes.WinError(ctypes.get_last_error())))

    def create_suspended(self, command: list[str], cwd: Path) -> None:
        import msvcrt

        for name in ("stdout", "stderr"):
            read_fd, write_fd = os.pipe()
            self.readers[name] = read_fd
            self.child_fds.append(write_fd)
        input_fd = os.open(os.devnull, os.O_RDONLY | os.O_BINARY)
        self.child_fds.append(input_fd)
        std_handles = [msvcrt.get_osfhandle(fd) for fd in (
            input_fd, self.child_fds[0], self.child_fds[1])]
        for handle in std_handles:
            os.set_handle_inheritable(handle, True)
        self._attributes(std_handles)
        startup = self.startup_type()
        startup.startup.cb = ctypes.sizeof(startup)
        startup.startup.flags = 0x100 | 0x1  # USESTDHANDLES | USESHOWWINDOW.
        startup.startup.show = 0
        startup.startup.stdin = std_handles[0]
        startup.startup.stdout = std_handles[1]
        startup.startup.stderr = std_handles[2]
        startup.attributes = ctypes.cast(self.attribute_buffer, ctypes.c_void_p)
        info = self.process_type()
        environment = {key: value for key, value in os.environ.items()
                       if key.upper() not in ("PYTHONPATH", "PYTHONHOME")}
        environment.update(PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1",
                           PYTHONUTF8="1")
        environment_text = "\0".join(
            key + "=" + value for key, value in sorted(
                environment.items(), key=lambda row: row[0].upper())) + "\0\0"
        environment_buffer = ctypes.create_unicode_buffer(environment_text)
        command_buffer = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
        self._check(self.kernel.CreateProcessW(
            command[0], command_buffer, None, None, True, CREATE_FLAGS,
            environment_buffer, str(cwd), ctypes.byref(startup), ctypes.byref(info)))
        self.process, self.thread = int(info.process), int(info.thread)
        self.pid = int(info.pid)
        self.launch["created_suspended"] = True
        self.launch["stdio_handle_list_only"] = True
        self.close_child_fds()
        self._noninheritable(self.process)
        self._noninheritable(self.thread)
        self.launch["process_handles_noninheritable"] = True
        member = self.wintypes.BOOL()
        self._check(self.kernel.IsProcessInJob(self.process, self.job,
                                              ctypes.byref(member)))
        if not member.value:
            raise OSError("suspended worker is outside the configured Job")
        self.launch["membership_verified_before_resume"] = True
        self.verify_limits()
        self.launch["limits_verified_before_resume"] = True

    def resume(self) -> None:
        previous = self.kernel.ResumeThread(self.thread)
        if previous == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        if previous != 1:
            raise OSError("primary thread suspension count was not exactly one")
        self.launch["primary_thread_resumed"] = True

    def read(self, name: str, amount: int) -> bytes:
        return os.read(self.readers[name], amount)

    def poll(self) -> int | None:
        if self.reaped or self.process is None:
            return self.returncode
        result = self.kernel.WaitForSingleObject(self.process, 0)
        if result == 0x102:  # WAIT_TIMEOUT.
            return None
        if result != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = self.wintypes.DWORD()
        self._check(self.kernel.GetExitCodeProcess(self.process, ctypes.byref(code)))
        self.returncode, self.reaped = int(code.value), True
        return self.returncode

    def terminate(self) -> None:
        if self.job is not None:
            self._check(self.kernel.TerminateJobObject(self.job, 1))

    def terminate_direct(self) -> None:
        # Only the direct handle returned by this creation is eligible.
        if self.process is not None and not self.reaped:
            self._check(self.kernel.TerminateProcess(self.process, 1))

    def _close_handle(self, name: str) -> None:
        handle = getattr(self, name)
        if handle is not None:
            self._check(self.kernel.CloseHandle(handle))
            setattr(self, name, None)

    def close_worker_handles(self) -> None:
        self._close_handle("thread")
        if self.reaped:
            self._close_handle("process")

    def close_child_fds(self) -> None:
        while self.child_fds:
            fd = self.child_fds[-1]
            os.close(fd)
            self.child_fds.pop()

    def close_reader_fds(self) -> None:
        for name in list(self.readers):
            os.close(self.readers[name])
            del self.readers[name]

    def close_job(self) -> None:
        self._close_handle("job")

    def delete_attributes(self) -> None:
        if self.attribute_initialized:
            self.kernel.DeleteProcThreadAttributeList(self.attribute_buffer)
            self.attribute_initialized = False
        self.attribute_buffer = None

    def handles_closed(self) -> bool:
        return (self.job is None and self.process is None and self.thread is None
                and not self.readers and not self.child_fds
                and not self.member_handles
                and not self.attribute_initialized)


def _positive(value: float, name: str) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= 0):
        raise ValueError(name + " must be a finite positive number")
    return float(value)


def run_owned(command: list[str], *, cwd: Path, wall_seconds: float,
              cleanup_seconds: float, memory_bytes: int,
              stdout_limit: int = STDOUT_BYTES, stderr_limit: int = STDERR_BYTES,
              cancel_path: Path | None = None,
              on_chunk: Callable[[str, bytes], None] | None = None) -> dict:
    """Return bounded bytes and ownership observations, never episode validity.

    The callback is serialized and runs before the corresponding retained buffer
    append. It must perform only the caller's bounded local spool write. A stuck
    callback remains an unresolved reader at the cleanup deadline.
    """
    if (not isinstance(command, list) or not command
            or any(not isinstance(item, str) or "\0" in item for item in command)
            or not command[0] or not Path(command[0]).is_absolute()
            or len(subprocess.list2cmdline(command)) >= 32_767):
        raise ValueError("use a bounded argument list with an absolute executable")
    wall_seconds = _positive(wall_seconds, "wall_seconds")
    cleanup_seconds = _positive(cleanup_seconds, "cleanup_seconds")
    if (isinstance(memory_bytes, bool) or not isinstance(memory_bytes, int)
            or not 1 <= memory_bytes <= 2**40):
        raise ValueError("memory_bytes must be a positive bounded integer")
    for name, value, maximum in (("stdout_limit", stdout_limit, STDOUT_BYTES),
                                 ("stderr_limit", stderr_limit, STDERR_BYTES)):
        if (isinstance(value, bool) or not isinstance(value, int)
                or not 0 <= value <= maximum):
            raise ValueError(name + " is outside its retained byte allowance")
    cwd = Path(cwd).resolve()
    if not cwd.is_dir():
        raise ValueError("cwd must be an existing directory")
    _supported_platform()
    started = time.monotonic()
    deadline = started + wall_seconds
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    states = {name: {"observed_bytes": 0, "eof": False} for name in buffers}
    limits = {"stdout": stdout_limit, "stderr": stderr_limit}
    stream_failure: list[tuple[str, str]] = []
    signal = threading.Event()
    state_lock = threading.Lock()
    callback_lock = threading.Lock()
    threads: list[threading.Thread] = []
    native = None
    failure_kind, error = None, None
    timeout_diagnostics = None
    unavailable = None
    established = False
    returned = False
    max_active = 0
    last_active = None
    observed_limits = None
    maximum_queried_peak = 0
    cleanup_errors: list[str] = []

    def cancelled() -> bool:
        return cancel_path is not None and cancel_path.exists()

    def query_limits() -> dict:
        nonlocal maximum_queried_peak
        selected = native.verify_limits()
        maximum_queried_peak = max(
            maximum_queried_peak, selected["peak_job_memory_used_bytes"])
        return selected

    def read(name: str) -> None:
        try:
            while True:
                with state_lock:
                    room = limits[name] - len(buffers[name])
                # Read only the remaining room, then one byte to detect excess.
                # Each reader holds at most one transient chunk outside retention.
                chunk = native.read(name, min(CHUNK_BYTES, room) if room else 1)
                with state_lock:
                    states[name]["observed_bytes"] += len(chunk)
                if not chunk:
                    with state_lock:
                        states[name]["eof"] = True
                    return
                if not room:
                    with state_lock:
                        stream_failure.append(("transport_limit",
                                               name + " exceeded its cap"))
                    signal.set()
                    return
                if on_chunk is not None:
                    try:
                        with callback_lock:
                            on_chunk(name, chunk)
                    except BaseException as caught:
                        with state_lock:
                            stream_failure.append(("artifact_failure",
                                                   _message(caught)))
                        signal.set()
                        return
                with state_lock:
                    buffers[name].extend(chunk)
        except BaseException as caught:
            with state_lock:
                stream_failure.append(("transport_failure", _message(caught)))
            signal.set()

    try:
        if cancelled():
            failure_kind = "cancelled"
        else:
            native = _WindowsProcess()
            native.prepare(memory_bytes)
            if cancelled():
                failure_kind = "cancelled"
            elif time.monotonic() >= deadline:
                failure_kind = "timeout"
            else:
                native.create_suspended(command, cwd)
                observed_limits = query_limits()
                last_active = native.active_count()
                max_active = max(max_active, last_active)
                if last_active != 1:
                    raise OSError(
                        "new suspended Job does not contain exactly its worker")
                established = True
                if maximum_queried_peak > memory_bytes:
                    failure_kind = "memory_limit_observation"
                elif cancelled():
                    failure_kind = "cancelled"
                elif time.monotonic() >= deadline:
                    failure_kind = "timeout"
                else:
                    for name in buffers:
                        thread = threading.Thread(
                            target=read, args=(name,), daemon=True)
                        threads.append(thread)
                        thread.start()
                    native.resume()
                    while True:
                        if cancelled():
                            failure_kind = "cancelled"
                            break
                        if time.monotonic() >= deadline:
                            failure_kind = "timeout"
                            break
                        if signal.is_set():
                            with state_lock:
                                failure_kind, error = stream_failure[0]
                            break
                        native.capture_members()
                        code = native.poll()
                        if code is not None:
                            if code != 0:
                                failure_kind = "worker_failed"
                                break
                        last_active = native.active_count()
                        max_active = max(max_active, last_active)
                        if (code is not None and last_active == 0
                                and all(not thread.is_alive() for thread in threads)
                                and native.members_signaled()):
                            returned = True
                            break
                        signal.wait(min(0.01, max(0.0, deadline - time.monotonic())))
    except EnforcementUnavailable as caught:
        unavailable = caught
        failure_kind, error = "unsupported", _message(caught)
    except BaseException as caught:
        if isinstance(caught, (KeyboardInterrupt, SystemExit)):
            failure_kind = "interrupted"
        else:
            failure_kind = "supervision_failure" if established else "setup_failure"
        error = _message(caught)
    finally:
        cleanup_deadline = time.monotonic() + cleanup_seconds

        def remaining() -> float:
            return max(0.0, cleanup_deadline - time.monotonic())

        def clean(action: Callable[[], Any]) -> bool:
            try:
                action()
                return True
            except BaseException as caught:
                cleanup_errors.append(_message(caught))
                return False

        if native is not None:
            if native.pid is not None and not returned:
                clean(native.capture_members)
                job_termination_requested = clean(native.terminate)
                # Successful Job termination already covers the direct worker.
                # Poll its exact handle before any fallback: a second terminate
                # can race completed exit and report ACCESS_DENIED.
                clean(native.poll)
                if not job_termination_requested and not native.reaped:
                    clean(native.terminate_direct)
            clean(native.close_child_fds)
            if native.pid is not None:
                while not native.reaped and remaining() > 0:
                    try:
                        native.poll()
                    except BaseException as caught:
                        cleanup_errors.append(_message(caught))
                        break
                    if not native.reaped:
                        time.sleep(min(0.01, remaining()))
            clean(native.close_worker_handles)
            for thread in threads:
                if thread.ident is not None:
                    thread.join(timeout=remaining())
            readers_retired = all(not thread.is_alive() for thread in threads)
            if readers_retired:
                clean(native.close_reader_fds)
            job_empty = None
            if native.job is not None:
                try:
                    while True:
                        last_active = native.active_count()
                        max_active = max(max_active, last_active)
                        if last_active == 0 or remaining() <= 0:
                            break
                        time.sleep(min(0.01, remaining()))
                    job_empty = last_active == 0
                    observed_limits = query_limits()
                except BaseException as caught:
                    cleanup_errors.append(_message(caught))
                    job_empty = False
            member_handles_signaled = False
            try:
                while True:
                    member_handles_signaled = native.members_signaled()
                    if member_handles_signaled or remaining() <= 0:
                        break
                    time.sleep(min(0.01, remaining()))
            except BaseException as caught:
                cleanup_errors.append(_message(caught))
            clean(native.close_member_handles)
            clean(native.delete_attributes)
            # Last handle closure is a final kill fallback, not proof of emptiness.
            clean(native.close_job)
            worker_reaped = native.pid is None or native.reaped
            handles_closed = native.handles_closed()
        else:
            worker_reaped = readers_retired = handles_closed = True
            member_handles_signaled = True
            job_empty = None
        retired = (worker_reaped and readers_retired and handles_closed
                   and member_handles_signaled
                   and job_empty is not False and not cleanup_errors)
        if not retired:
            if failure_kind is None:
                failure_kind = "retirement_failure"
            returned = False
        if failure_kind == "timeout":
            timeout_diagnostics = {
                "timeout_seconds": wall_seconds, "kill_requested": native is not None,
                "reaped": worker_reaped, "tree_retired": retired,
            }
    with state_lock:
        # A final reader can signal between the loop's signal check and its
        # natural completion observation. Retirement does not erase that fault.
        if stream_failure and failure_kind is None:
            failure_kind, error = stream_failure[0]
            returned = False
        output = {name: bytes(buffer) for name, buffer in buffers.items()}
        observations = {name: dict(state) for name, state in states.items()}
    prior_failure = None
    if maximum_queried_peak > memory_bytes:
        if failure_kind != "memory_limit_observation":
            prior_failure = {"failure_kind": failure_kind, "error": error}
        failure_kind = "memory_limit_observation"
        error = ("queried PeakJobMemoryUsed " + str(maximum_queried_peak)
                 + " exceeds requested JobMemoryLimit " + str(memory_bytes)
                 + "; no complete result is admitted")
        returned = False
    owner = {
        "format": "mcts-owned-process", "schema_version": 1,
        "platform": "windows", "established": established,
        "failure_kind": failure_kind, "error": error,
        "prior_failure": prior_failure,
        "assignment_method": "creation_job_list",
        "launch": native.launch if native is not None else None,
        "worker_pid": native.pid if native is not None else None,
        "requested": {"wall_seconds": wall_seconds, "cleanup_seconds": cleanup_seconds,
                      "memory_bytes": memory_bytes,
                      "stdout_limit": stdout_limit, "stderr_limit": stderr_limit},
        "memory_scope": "aggregate committed virtual memory of the owned tree; "
                        "the calling controller is excluded",
        "observed_limits": observed_limits,
        "memory_observation": {
            "counter": "PeakJobMemoryUsed",
            "maximum_queried_bytes": maximum_queried_peak,
            "exceeds_requested_limit": maximum_queried_peak > memory_bytes,
            "interpretation": "raw Windows counter retained separately from the "
                              "configured committed memory allocation limit; "
                              "no lifetime peak or resident memory bound is inferred",
        },
        "maximum_observed_active_processes": max_active,
        "transport": {
            "streams": {name: {**observations[name],
                               "retained_bytes": len(output[name]),
                               "limit_bytes": limits[name],
                               "observed_is_lower_bound": not observations[name]["eof"]}
                        for name in buffers},
            "transient_read_bytes_per_stream": CHUNK_BYTES,
            "buffer_scope": "one transient read chunk per stream; kernel pipe and "
                            "child interpreter buffers are separate; no disk quota",
        },
        "cleanup": {"retired": retired, "worker_reaped": worker_reaped,
                    "job_empty": job_empty, "final_active_processes": last_active,
                    "member_handles_signaled": member_handles_signaled,
                    "observed_member_pids": (native.observed_member_pids
                                             if native is not None else []),
                    "member_inventory_limit": MEMBER_LIMIT,
                    "member_proof_scope": "waits on pinned observed Job members "
                                          "plus direct reaping and an empty Job; "
                                          "no privileged or hostile containment",
                    "readers_retired": readers_retired,
                    "handles_closed": handles_closed,
                    "errors": cleanup_errors},
    }
    if unavailable is not None:
        unavailable.receipt = owner
        raise unavailable
    return {
        "stdout": output["stdout"], "stderr": output["stderr"],
        "returncode": native.returncode if native is not None else None,
        "elapsed_subprocess_seconds": time.monotonic() - started,
        "timeout_diagnostics": timeout_diagnostics,
        "stdout_observed_bytes": observations["stdout"]["observed_bytes"],
        "stderr_observed_bytes": observations["stderr"]["observed_bytes"],
        "stdout_truncated": observations["stdout"]["observed_bytes"] > stdout_limit,
        "stderr_truncated": observations["stderr"]["observed_bytes"] > stderr_limit,
        "owner": owner,
    }
