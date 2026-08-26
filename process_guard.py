"""Exact child-process identity and Windows kill-on-parent-close protection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import time


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    executable: str
    started_ticks: int

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, payload):
        return cls(
            pid=int(payload["pid"]),
            executable=str(payload["executable"]),
            started_ticks=int(payload["started_ticks"]),
        )


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _SYNCHRONIZE = 0x00100000
    _STILL_ACTIVE = 259
    _WAIT_OBJECT_0 = 0
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

    class _FILETIME(ctypes.Structure):
        _fields_ = (("low", wintypes.DWORD), ("high", wintypes.DWORD))

    class _BASIC_LIMIT(ctypes.Structure):
        _fields_ = (
            ("per_process_time", ctypes.c_longlong),
            ("per_job_time", ctypes.c_longlong),
            ("limit_flags", wintypes.DWORD),
            ("minimum_working_set", ctypes.c_size_t),
            ("maximum_working_set", ctypes.c_size_t),
            ("active_process_limit", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority_class", wintypes.DWORD),
            ("scheduling_class", wintypes.DWORD),
        )

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = tuple((name, ctypes.c_ulonglong) for name in (
            "read_operations", "write_operations", "other_operations",
            "read_bytes", "write_bytes", "other_bytes",
        ))

    class _EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = (
            ("basic", _BASIC_LIMIT),
            ("io", _IO_COUNTERS),
            ("process_memory_limit", ctypes.c_size_t),
            ("job_memory_limit", ctypes.c_size_t),
            ("peak_process_memory", ctypes.c_size_t),
            ("peak_job_memory", ctypes.c_size_t),
        )

    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE

    def _open_process(pid: int, access: int):
        return _kernel32.OpenProcess(access, False, int(pid))

    def _close(handle):
        if handle:
            _kernel32.CloseHandle(handle)

    def get_process_identity(pid: int) -> ProcessIdentity | None:
        handle = _open_process(pid, _PROCESS_QUERY_LIMITED_INFORMATION)
        if not handle:
            return None
        try:
            exit_code = wintypes.DWORD()
            if not _kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return None
            if exit_code.value != _STILL_ACTIVE:
                return None
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not _kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)
            ):
                return None
            created, exited, kernel, user = _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
            if not _kernel32.GetProcessTimes(
                handle, ctypes.byref(created), ctypes.byref(exited),
                ctypes.byref(kernel), ctypes.byref(user),
            ):
                return None
            ticks = (int(created.high) << 32) | int(created.low)
            return ProcessIdentity(int(pid), str(Path(buffer.value).resolve()), ticks)
        finally:
            _close(handle)

    def terminate_exact_process(identity: ProcessIdentity, timeout: float = 5.0) -> bool:
        current = get_process_identity(identity.pid)
        if current is None:
            return False
        if (
            current.started_ticks != identity.started_ticks
            or os.path.normcase(current.executable) != os.path.normcase(identity.executable)
        ):
            raise RuntimeError("进程 PID 已被其他程序复用，拒绝终止")
        handle = _open_process(
            identity.pid,
            _PROCESS_TERMINATE | _SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION,
        )
        if not handle:
            raise RuntimeError("无法取得孤儿进程终止权限")
        try:
            if not _kernel32.TerminateProcess(handle, 1):
                raise RuntimeError("Windows 拒绝终止已验证的孤儿进程")
            milliseconds = max(1, int(float(timeout) * 1000.0))
            return _kernel32.WaitForSingleObject(handle, milliseconds) == _WAIT_OBJECT_0
        finally:
            _close(handle)

    class ChildJobGuard:
        """Place a child in a kernel job that dies if this handle disappears."""

        def __init__(self, process):
            self._handle = _kernel32.CreateJobObjectW(None, None)
            self.assigned = False
            if not self._handle:
                return
            limits = _EXTENDED_LIMIT()
            limits.basic.limit_flags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not _kernel32.SetInformationJobObject(
                self._handle,
                _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ):
                self.close()
                return
            process_handle = wintypes.HANDLE(int(process._handle))
            if not _kernel32.AssignProcessToJobObject(self._handle, process_handle):
                self.close()
                return
            self.assigned = True

        def close(self):
            if self._handle:
                _close(self._handle)
                self._handle = None

else:
    def get_process_identity(pid: int) -> ProcessIdentity | None:
        proc = Path("/proc") / str(int(pid))
        try:
            executable = str((proc / "exe").resolve())
            fields = (proc / "stat").read_text(encoding="utf-8").split()
            return ProcessIdentity(int(pid), executable, int(fields[21]))
        except (OSError, ValueError, IndexError):
            return None

    def terminate_exact_process(identity: ProcessIdentity, timeout: float = 5.0) -> bool:
        current = get_process_identity(identity.pid)
        if current is None:
            return False
        if current != identity:
            raise RuntimeError("进程 PID 已被其他程序复用，拒绝终止")
        import signal

        os.kill(identity.pid, signal.SIGTERM)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if get_process_identity(identity.pid) is None:
                return True
            time.sleep(0.05)
        return False

    class ChildJobGuard:
        def __init__(self, process):
            self.assigned = False

        def close(self):
            return None


__all__ = [
    "ChildJobGuard", "ProcessIdentity", "get_process_identity",
    "terminate_exact_process",
]
