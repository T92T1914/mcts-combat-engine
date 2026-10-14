"""Mocked contracts and separately labelled actual Windows lifecycle checks."""
from __future__ import annotations

import ctypes
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools import encounter_process as owned

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "encounter_process_fixture.py"
MEMORY = 128 * 1024 * 1024


class FakeProcess:
    """Controlled observations only, with no process creation or OS enforcement."""

    def __init__(self, stdout=b"ok", stderr=b"", *, exitcode=0,
                 waiting=False, stuck_job=False, close_failure=False, fail_at=None,
                 peak=1):
        self.streams = {"stdout": io.BytesIO(stdout), "stderr": io.BytesIO(stderr)}
        self.job = self.process = self.thread = None
        self.pid = self.returncode = None
        self.reaped = False
        self.exitcode, self.waiting = exitcode, waiting
        self.stuck_job, self.close_failure = stuck_job, close_failure
        self.fail_at = fail_at
        self.peak = peak
        self.launch = {"assignment_method": "creation_job_list",
                       "created_suspended": False,
                       "membership_verified_before_resume": False,
                       "limits_verified_before_resume": False,
                       "primary_thread_resumed": False,
                       "job_handle_noninheritable": False,
                       "process_handles_noninheritable": False,
                       "stdio_handle_list_only": False}
        self.events = []
        self.readers_closed = False
        self.observed_member_pids = []

    def prepare(self, memory):
        self.events.append("prepare")
        self.job = 100
        self.memory = memory
        self.launch["job_handle_noninheritable"] = True
        if self.fail_at == "prepare":
            raise OSError("controlled limit refusal")

    def create_suspended(self, command, cwd):
        self.events.append("create_suspended")
        if self.fail_at == "attribute":
            raise owned.EnforcementUnavailable("controlled Job list refusal")
        self.process, self.thread, self.pid = 200, 201, 202
        self.launch.update(created_suspended=True, stdio_handle_list_only=True,
                           process_handles_noninheritable=True)
        if self.fail_at == "membership":
            raise OSError("controlled assignment refusal")
        self.launch["membership_verified_before_resume"] = True
        self.launch["limits_verified_before_resume"] = True

    def verify_limits(self):
        self.events.append("query_limits")
        if self.fail_at == "query":
            raise OSError("controlled limit query refusal")
        return {"flags": owned.JOB_FLAGS, "aggregate_commit_bytes": self.memory,
                "peak_job_memory_used_bytes": self.peak}

    def active_count(self):
        if self.stuck_job:
            return 1
        return int(self.pid is not None and not self.reaped)

    def capture_members(self):
        pass

    def members_signaled(self):
        return True

    def close_member_handles(self):
        pass

    def resume(self):
        self.events.append("resume")
        if self.fail_at == "resume":
            raise OSError("controlled resumption refusal")
        self.launch["primary_thread_resumed"] = True

    def read(self, name, amount):
        return self.streams[name].read(amount)

    def poll(self):
        if self.waiting and not self.reaped:
            return None
        if self.pid is not None and not self.reaped:
            self.returncode, self.reaped = self.exitcode, True
        return self.returncode

    def terminate(self):
        self.events.append("terminate_job")
        if self.pid is not None and not self.reaped:
            self.returncode, self.reaped = 1, True

    def terminate_direct(self):
        self.events.append("terminate_direct")
        if self.pid is not None:
            self.returncode, self.reaped = 1, True

    def close_worker_handles(self):
        self.thread = None
        if self.reaped:
            self.process = None

    def close_child_fds(self):
        pass

    def close_reader_fds(self):
        self.readers_closed = True

    def delete_attributes(self):
        pass

    def close_job(self):
        if self.close_failure:
            raise OSError("controlled handle closure refusal")
        self.job = None

    def handles_closed(self):
        return (self.job is None and self.process is None and self.thread is None
                and self.readers_closed)


class MockedOwnershipTests(unittest.TestCase):
    def invoke(self, fake, directory, **options):
        with patch.object(owned, "_supported_platform"), patch.object(
                owned, "_WindowsProcess", return_value=fake):
            return owned.run_owned(
                [sys.executable, "-I", "-B", "known-fixture"], cwd=directory,
                wall_seconds=options.pop("wall_seconds", 0.5), cleanup_seconds=0.05,
                memory_bytes=MEMORY, **options)

    def test_natural_return_requires_complete_ownership_receipt(self):
        with tempfile.TemporaryDirectory() as raw:
            fake = FakeProcess()
            result = self.invoke(fake, Path(raw))
        owner = result["owner"]
        self.assertEqual(result["stdout"], b"ok")
        self.assertIsNone(owner["failure_kind"])
        self.assertTrue(owner["established"])
        self.assertTrue(owner["cleanup"]["retired"])
        self.assertEqual(owner["cleanup"]["final_active_processes"], 0)
        self.assertEqual(fake.events[:4], ["prepare", "create_suspended",
                                          "query_limits", "resume"])
        self.assertTrue(owner["launch"]["membership_verified_before_resume"])
        self.assertTrue(owner["launch"]["job_handle_noninheritable"])
        json.dumps(owner)  # Bytes are outside the JSON receipt.

    def test_exact_cap_is_not_overflow_and_observation_reaches_eof(self):
        with tempfile.TemporaryDirectory() as raw:
            result = self.invoke(FakeProcess(b"a" * 16, b"b" * 32), Path(raw),
                                 stdout_limit=16, stderr_limit=32)
        self.assertIsNone(result["owner"]["failure_kind"])
        for name, expected in (("stdout", 16), ("stderr", 32)):
            self.assertEqual(len(result[name]), expected)
            self.assertFalse(result[name + "_truncated"])
            stream = result["owner"]["transport"]["streams"][name]
            self.assertTrue(stream["eof"])
            self.assertFalse(stream["observed_is_lower_bound"])

    def test_each_stream_overflow_retains_only_cap_and_one_observed_excess_byte(self):
        for name in ("stdout", "stderr"):
            with self.subTest(stream=name), tempfile.TemporaryDirectory() as raw:
                content = {"stdout": b"", "stderr": b""}
                content[name] = b"a" * 1000
                fake = FakeProcess(**content)
                chunks = []
                def retain(stream, data, sink=chunks):
                    sink.append((stream, data))

                result = self.invoke(fake, Path(raw), stdout_limit=17,
                                     stderr_limit=17, on_chunk=retain)
                self.assertEqual(result["owner"]["failure_kind"], "transport_limit")
                self.assertEqual(len(result[name]), 17)
                self.assertEqual(result[name + "_observed_bytes"], 18)
                self.assertTrue(result[name + "_truncated"])
                retained = sum(len(data) for stream, data in chunks if stream == name)
                self.assertEqual(retained, 17)
                self.assertTrue(result["owner"]["cleanup"]["retired"])

    def test_callback_failure_retires_and_keeps_chunk_out_of_retained_output(self):
        def refuse(name, data):
            raise OSError("controlled artifact budget refusal")

        with tempfile.TemporaryDirectory() as raw:
            result = self.invoke(FakeProcess(), Path(raw), on_chunk=refuse)
        self.assertEqual(result["owner"]["failure_kind"], "artifact_failure")
        self.assertEqual(result["stdout"], b"")
        self.assertEqual(result["stdout_observed_bytes"], 2)
        self.assertTrue(result["owner"]["cleanup"]["retired"])

    def test_callbacks_are_serialized_across_streams(self):
        active = maximum = 0
        guard = threading.Lock()

        def record(name, data):
            nonlocal active, maximum
            with guard:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.002)
            with guard:
                active -= 1

        with tempfile.TemporaryDirectory() as raw:
            result = self.invoke(FakeProcess(b"a" * 20_000, b"b" * 20_000), Path(raw),
                                 on_chunk=record)
        self.assertIsNone(result["owner"]["failure_kind"])
        self.assertEqual(maximum, 1)

    def test_creation_or_query_refusal_never_resumes_worker(self):
        for stage in ("prepare", "membership", "query", "resume"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as raw:
                fake = FakeProcess(fail_at=stage)
                result = self.invoke(fake, Path(raw))
                self.assertIn(result["owner"]["failure_kind"],
                              ("setup_failure", "supervision_failure"))
                self.assertFalse(result["owner"]["launch"]["primary_thread_resumed"])
                self.assertIsNotNone(result["owner"]["error"])

    def test_unavailable_creation_attribute_refuses_before_child_creation(self):
        fake = FakeProcess(fail_at="attribute")
        with tempfile.TemporaryDirectory() as raw, self.assertRaises(
                owned.EnforcementUnavailable) as caught:
            self.invoke(fake, Path(raw))
        self.assertIsNone(fake.pid)
        self.assertEqual(caught.exception.receipt["failure_kind"], "unsupported")
        self.assertTrue(caught.exception.receipt["cleanup"]["retired"])

    def test_cancellation_before_start_never_constructs_native_owner(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            cancel = directory / "cancel"
            cancel.touch()
            with patch.object(owned, "_supported_platform"), patch.object(
                    owned, "_WindowsProcess") as factory:
                result = owned.run_owned(
                    [sys.executable], cwd=directory, wall_seconds=1,
                    cleanup_seconds=1, memory_bytes=MEMORY, cancel_path=cancel)
            factory.assert_not_called()
        self.assertEqual(result["owner"]["failure_kind"], "cancelled")
        self.assertTrue(result["owner"]["cleanup"]["retired"])

    def test_cancellation_observed_after_output_is_not_success(self):
        with tempfile.TemporaryDirectory() as raw:
            cancel = Path(raw) / "cancel"
            result = self.invoke(
                FakeProcess(waiting=True), Path(raw), cancel_path=cancel,
                on_chunk=lambda name, data: cancel.touch())
        self.assertEqual(result["owner"]["failure_kind"], "cancelled")
        self.assertTrue(result["owner"]["cleanup"]["retired"])

    def test_timeout_reaps_and_a_fresh_call_can_complete(self):
        with tempfile.TemporaryDirectory() as raw:
            failed = self.invoke(
                FakeProcess(waiting=True), Path(raw), wall_seconds=0.02)
            following = self.invoke(FakeProcess(), Path(raw))
        self.assertEqual(failed["owner"]["failure_kind"], "timeout")
        self.assertTrue(failed["timeout_diagnostics"]["tree_retired"])
        self.assertIsNone(following["owner"]["failure_kind"])

    def test_job_termination_exit_race_does_not_repeat_direct_termination(self):
        class FinishedByJob(FakeProcess):
            def terminate(self):
                self.events.append("terminate_job")
                self.waiting, self.exitcode = False, 1

            def terminate_direct(self):
                raise PermissionError("controlled already terminated handle")

        fake = FinishedByJob(waiting=True)
        with tempfile.TemporaryDirectory() as raw:
            result = self.invoke(fake, Path(raw), wall_seconds=0.02)
        self.assertEqual(result["owner"]["failure_kind"], "timeout")
        self.assertTrue(result["owner"]["cleanup"]["retired"])
        self.assertEqual(result["owner"]["cleanup"]["errors"], [])
        self.assertEqual(fake.events.count("terminate_job"), 1)

    def test_memory_counter_excess_refuses_without_relabeling_the_metric(self):
        with tempfile.TemporaryDirectory() as raw:
            fake = FakeProcess(peak=MEMORY + 1)
            excess = self.invoke(fake, Path(raw))
            equal = self.invoke(FakeProcess(peak=MEMORY), Path(raw))
        self.assertEqual(excess["owner"]["failure_kind"], "memory_limit_observation")
        self.assertFalse(excess["owner"]["launch"]["primary_thread_resumed"])
        self.assertTrue(excess["owner"]["cleanup"]["retired"])
        observed = excess["owner"]["memory_observation"]
        self.assertEqual(observed["counter"], "PeakJobMemoryUsed")
        self.assertEqual(observed["maximum_queried_bytes"], MEMORY + 1)
        self.assertTrue(observed["exceeds_requested_limit"])
        self.assertIsNone(equal["owner"]["failure_kind"])

    def test_late_memory_counter_excess_withholds_return_and_keeps_prior_failure(self):
        class LatePeak(FakeProcess):
            def verify_limits(self):
                self.peak = MEMORY + 1 if self.reaped else MEMORY
                return super().verify_limits()

        with tempfile.TemporaryDirectory() as raw:
            finished = self.invoke(LatePeak(), Path(raw))
            failed = self.invoke(LatePeak(exitcode=3), Path(raw))
        for result in (finished, failed):
            self.assertTrue(result["owner"]["launch"]["primary_thread_resumed"])
            self.assertEqual(result["owner"]["failure_kind"],
                             "memory_limit_observation")
            self.assertTrue(result["owner"]["cleanup"]["retired"])
            self.assertEqual(result["owner"]["memory_observation"][
                "maximum_queried_bytes"], MEMORY + 1)
        self.assertIsNone(finished["owner"]["prior_failure"]["failure_kind"])
        self.assertEqual(failed["owner"]["prior_failure"]["failure_kind"],
                         "worker_failed")

    def test_nonzero_exit_and_unresolved_cleanup_remain_distinct(self):
        with tempfile.TemporaryDirectory() as raw:
            failed = self.invoke(FakeProcess(exitcode=3), Path(raw))
            unresolved = self.invoke(
                FakeProcess(stuck_job=True), Path(raw), wall_seconds=0.02)
            close_failed = self.invoke(FakeProcess(close_failure=True), Path(raw))
        self.assertEqual(failed["owner"]["failure_kind"], "worker_failed")
        self.assertTrue(failed["owner"]["cleanup"]["retired"])
        self.assertFalse(unresolved["owner"]["cleanup"]["retired"])
        self.assertFalse(unresolved["owner"]["cleanup"]["job_empty"])
        self.assertEqual(close_failed["owner"]["failure_kind"], "retirement_failure")
        self.assertFalse(close_failed["owner"]["cleanup"]["handles_closed"])

    def test_unsignaled_observed_member_withholds_retirement_after_empty_job(self):
        class PendingMember(FakeProcess):
            def members_signaled(self):
                return False

        with tempfile.TemporaryDirectory() as raw:
            result = self.invoke(PendingMember(), Path(raw), wall_seconds=0.02)
        cleanup = result["owner"]["cleanup"]
        self.assertTrue(cleanup["worker_reaped"])
        self.assertTrue(cleanup["job_empty"])
        self.assertFalse(cleanup["member_handles_signaled"])
        self.assertFalse(cleanup["retired"])
        self.assertIsNotNone(result["owner"]["failure_kind"])

    def test_refused_owned_inventory_remains_unresolved_after_empty_job(self):
        class RefusedInventory(FakeProcess):
            def capture_members(self):
                raise OSError("controlled member inventory refusal")

        with tempfile.TemporaryDirectory() as raw:
            result = self.invoke(RefusedInventory(), Path(raw))
        self.assertFalse(result["owner"]["cleanup"]["retired"])
        self.assertTrue(result["owner"]["cleanup"]["errors"])
        self.assertIsNotNone(result["owner"]["failure_kind"])

    def test_new_nonmember_pid_cannot_borrow_a_signaled_recycled_handle(self):
        class Ids(ctypes.Structure):
            _fields_ = [("assigned", ctypes.c_uint32), ("listed", ctypes.c_uint32),
                        ("ids", ctypes.c_size_t * owned.MEMBER_LIMIT)]

        class Kernel:
            def QueryInformationJobObject(self, job, kind, destination, size, length):
                value = destination._obj
                value.assigned = value.listed = 1
                value.ids[0] = 123
                return True

            def OpenProcess(self, rights, inherit, pid):
                if rights != 0x101000 or inherit or pid != 123:
                    raise AssertionError("unexpected observed member access")
                return 900

            def GetHandleInformation(self, handle, flags):
                flags._obj.value = 0
                return True

            def IsProcessInJob(self, handle, job, member):
                member._obj.value = False
                return True

            def WaitForSingleObject(self, handle, milliseconds):
                return 0

            def CloseHandle(self, handle):
                return True

        native = owned._WindowsProcess.__new__(owned._WindowsProcess)
        native.kernel, native.job, native.pid = Kernel(), 100, 200
        native.process_ids_type = Ids
        native.wintypes = SimpleNamespace(BOOL=ctypes.c_int, DWORD=ctypes.c_uint32)
        native.member_handles, native.verified_members = {}, set()
        native.observed_member_pids = []
        with self.assertRaisesRegex(OSError, "no verified owned membership"):
            native.capture_members()
        self.assertEqual(native.observed_member_pids, [])
        self.assertEqual(native.member_handles, {123: 900})
        native.close_member_handles()
        self.assertEqual(native.member_handles, {})
        # The same signaled state is valid only for a retained verified object.
        native.member_handles, native.verified_members = {123: 900}, {123}
        native.observed_member_pids = [123]
        native.capture_members()
        native.close_member_handles()

    def test_invalid_limits_refuse_before_native_setup(self):
        with tempfile.TemporaryDirectory() as raw, patch.object(
                owned, "_WindowsProcess") as factory:
            for value in (True, -1, float("inf")):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    owned.run_owned([sys.executable], cwd=Path(raw), wall_seconds=value,
                                    cleanup_seconds=1, memory_bytes=MEMORY)
            factory.assert_not_called()

    @unittest.skipIf(os.name == "nt", "actual non-Windows refusal only")
    def test_actual_unsupported_platform_refuses_before_native_setup(self):
        with tempfile.TemporaryDirectory() as raw, patch.object(
                owned, "_WindowsProcess") as factory, self.assertRaises(
                    owned.EnforcementUnavailable):
            owned.run_owned([sys.executable], cwd=Path(raw), wall_seconds=1,
                            cleanup_seconds=1, memory_bytes=MEMORY)
        factory.assert_not_called()


@unittest.skipUnless(os.name == "nt", "actual Windows Job lifecycle only")
class ActualWindowsOwnershipTests(unittest.TestCase):
    def invoke(self, mode, directory, **options):
        return owned.run_owned(
            [sys.executable, "-I", "-B", str(FIXTURE), mode, str(directory)],
            cwd=directory,
            wall_seconds=options.pop("wall_seconds", 4), cleanup_seconds=2,
            memory_bytes=options.pop("memory_bytes", MEMORY), **options)

    def assert_retired(self, result):
        cleanup = result["owner"]["cleanup"]
        self.assertTrue(cleanup["retired"], result["owner"])
        self.assertTrue(cleanup["worker_reaped"])
        self.assertTrue(cleanup["readers_retired"])
        self.assertTrue(cleanup["handles_closed"])
        self.assertTrue(cleanup["member_handles_signaled"])
        self.assertTrue(cleanup["job_empty"])
        self.assertEqual(cleanup["final_active_processes"], 0)

    def test_actual_suspended_assignment_hidden_output_and_descendant_retirement(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            result = self.invoke("descendant", directory)
            worker = json.loads((directory / "worker.json").read_text())
            leaf = json.loads((directory / "leaf.json").read_text())
        self.assertIsNone(result["owner"]["failure_kind"], result["owner"])
        self.assertTrue(worker["in_a_job"] and leaf["in_a_job"])
        self.assertGreaterEqual(result["owner"]["maximum_observed_active_processes"], 2)
        self.assertEqual(result["owner"]["assignment_method"], "creation_job_list")
        for value in result["owner"]["launch"].values():
            self.assertTrue(value)
        self.assertLessEqual(result["owner"]["memory_observation"][
            "maximum_queried_bytes"], MEMORY)
        self.assert_retired(result)

    def test_actual_nested_jobs_account_for_inner_worker_and_leaf(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            result = self.invoke("nested-owner", directory)
            inner = json.loads((directory / "inner-owner.json").read_text())
        self.assertIsNone(result["owner"]["failure_kind"], result["owner"])
        self.assertIsNone(inner["failure_kind"], inner)
        self.assertGreaterEqual(result["owner"]["maximum_observed_active_processes"], 3)
        self.assertGreaterEqual(inner["maximum_observed_active_processes"], 2)
        self.assertEqual(inner["cleanup"]["final_active_processes"], 0)
        self.assertTrue(inner["cleanup"]["retired"])
        self.assert_retired(result)

    def test_actual_timeout_and_cancellation_retire_descendants_then_recover(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            timed = self.invoke("hang-descendant", directory, wall_seconds=0.8)
            cancel = directory / "cancel"

            def request_cancel(name, data):
                if name == "stdout" and data:
                    cancel.touch()

            cancelled = self.invoke("hang-descendant", directory, cancel_path=cancel,
                                    on_chunk=request_cancel)
            following = self.invoke("complete", directory)
        self.assertEqual(timed["owner"]["failure_kind"], "timeout")
        self.assertEqual(cancelled["owner"]["failure_kind"], "cancelled")
        self.assertIsNone(following["owner"]["failure_kind"])
        for result in (timed, cancelled, following):
            self.assert_retired(result)

    def test_actual_zero_exit_with_live_descendant_does_not_complete(self):
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handles = []
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)

            def observe_leaf(name, data):
                if name == "stdout" and data:
                    leaf = json.loads((directory / "leaf.json").read_text())
                    handle = kernel.OpenProcess(0x100000, False, leaf["pid"])
                    if not handle:
                        raise ctypes.WinError(ctypes.get_last_error())
                    handles.append(handle)

            try:
                result = self.invoke("orphan-descendant", directory,
                                     wall_seconds=0.8, on_chunk=observe_leaf)
                self.assertEqual(result["returncode"], 0)
                self.assertEqual(result["owner"]["failure_kind"], "timeout")
                self.assertEqual(len(handles), 1)
                self.assertEqual(kernel.WaitForSingleObject(handles[0], 0), 0)
                self.assert_retired(result)
            finally:
                for handle in handles:
                    kernel.CloseHandle(handle)

    def test_actual_stream_caps_limit_spool_bytes_and_exact_cap_succeeds(self):
        for name in ("stdout", "stderr"):
            with self.subTest(stream=name), tempfile.TemporaryDirectory() as raw:
                writes = {"stdout": 0, "stderr": 0}

                def spool(stream, data, sink=writes):
                    sink[stream] += len(data)

                result = self.invoke("flood-" + name, Path(raw), stdout_limit=128,
                                     stderr_limit=128, on_chunk=spool)
                self.assertEqual(result["owner"]["failure_kind"], "transport_limit")
                self.assertEqual(len(result[name]), 128)
                self.assertEqual(writes[name], 128)
                self.assertEqual(result[name + "_observed_bytes"], 129)
                self.assert_retired(result)
        with tempfile.TemporaryDirectory() as raw:
            exact = self.invoke("exact", Path(raw), stdout_limit=16, stderr_limit=32)
        self.assertIsNone(exact["owner"]["failure_kind"])
        self.assert_retired(exact)

    def test_actual_aggregate_commit_refusal_keeps_retirement_visible(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            result = self.invoke(
                "memory-parent", directory, memory_bytes=64 * 1024 * 1024)
            parent = json.loads((directory / "memory-parent.json").read_text())
            leaf = json.loads((directory / "memory-leaf.json").read_text())
            allocation = json.loads(result["stdout"])
        self.assertTrue(parent["in_a_job"] and leaf["in_a_job"])
        self.assertEqual(allocation["retained_parent_bytes"], 24 * 1024 * 1024)
        self.assertEqual(allocation["child_returncode"], 7)
        self.assertEqual(result["returncode"], 7)
        limits = result["owner"]["observed_limits"]
        self.assertEqual(limits["aggregate_commit_bytes"], 64 * 1024 * 1024)
        measured = result["owner"]["memory_observation"]
        self.assertEqual(measured["counter"], "PeakJobMemoryUsed")
        self.assertGreaterEqual(measured["maximum_queried_bytes"],
                                limits["peak_job_memory_used_bytes"])
        if measured["maximum_queried_bytes"] > 64 * 1024 * 1024:
            self.assertEqual(result["owner"]["failure_kind"],
                             "memory_limit_observation")
            self.assertTrue(measured["exceeds_requested_limit"])
        else:
            self.assertEqual(result["owner"]["failure_kind"], "worker_failed")
            self.assertFalse(measured["exceeds_requested_limit"])
        self.assert_retired(result)

    def test_actual_controller_death_terminates_its_known_descendant_handles(self):
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            controller = subprocess.Popen(
                [sys.executable, "-I", "-B", str(FIXTURE), "controller", raw],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            handles = []
            try:
                until = time.monotonic() + 2.5
                paths = [directory / name for name in (
                    "controller-ready.json", "worker.json", "leaf.json")]
                while (not all(path.exists() for path in paths)
                       and time.monotonic() < until):
                    time.sleep(0.01)
                self.assertTrue(all(path.exists() for path in paths))
                for path in paths[1:]:
                    pid = json.loads(path.read_text())["pid"]
                    handle = kernel.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE.
                    self.assertTrue(handle)
                    handles.append(handle)
                (directory / "allow-controller-death").touch()
                self.assertEqual(controller.wait(timeout=2), 29)
                for handle in handles:
                    self.assertEqual(kernel.WaitForSingleObject(handle, 2000), 0)
                # Abrupt controller death cannot supply a completed owner receipt.
                self.assertFalse((directory / "owner-complete.json").exists())
            finally:
                if controller.poll() is None:
                    controller.kill()  # Only this test's direct Popen handle.
                controller.wait(timeout=3)
                controller._handle.Close()
                for handle in handles:
                    kernel.CloseHandle(handle)


if __name__ == "__main__":
    unittest.main()
