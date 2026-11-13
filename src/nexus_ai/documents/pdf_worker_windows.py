"""Windows Job Object runner for bounded local PDF extraction.

This module limits the worker process tree's lifetime, memory, CPU time, and
process count. A Job Object is not a filesystem, network, or token sandbox.
Only trusted local PDFs should be processed until a stronger OS isolation
boundary is deployed for hostile documents.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import threading
import time
from ctypes import wintypes
from pathlib import Path

from nexus_ai.documents.pdf_worker import (
    PdfIsolationUnavailableError,
    PdfWorkerExtractionError,
    PdfWorkerOutputLimitError,
    PdfWorkerTimeoutError,
)


_JOB_OBJECT_LIMIT_JOB_TIME = 0x00000004
_JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
_JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
_JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_MAX_JOB_PROCESSES = 16
_CREATE_SUSPENDED = 0x00000004
_CREATE_NO_WINDOW = 0x08000000
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_STARTF_USESTDHANDLES = 0x00000100
_PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
_HANDLE_FLAG_INHERIT = 0x00000001
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_WAIT_OBJECT_0 = 0
_WAIT_FAILED = 0xFFFFFFFF


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_ubyte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _StartupInfoEx(ctypes.Structure):
    _fields_ = [("StartupInfo", _StartupInfo), ("lpAttributeList", ctypes.c_void_p)]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD),
    ]


def _win_error(operation: str) -> PdfIsolationUnavailableError:
    error = ctypes.get_last_error()
    return PdfIsolationUnavailableError(f"Windows PDF worker setup failed during {operation} (error {error})")


def _handle_value(handle) -> int:
    return ctypes.cast(handle, ctypes.c_void_p).value or 0


def run_bounded_process(
    command: list[str],
    input_bytes: bytes,
    *,
    timeout_seconds: float,
    max_output_bytes: int,
    memory_limit_bytes: int,
    cpu_limit_seconds: int,
    python_path: str | None = None,
) -> bytes:
    """Start suspended, assign to a constrained Job Object, then stream I/O."""
    if not hasattr(ctypes, "WinDLL"):
        raise PdfIsolationUnavailableError("Windows Job Object APIs are unavailable")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    ]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CreatePipe.argtypes = [
        ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(_SecurityAttributes), wintypes.DWORD,
    ]
    kernel32.CreatePipe.restype = wintypes.BOOL
    kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    kernel32.SetHandleInformation.restype = wintypes.BOOL
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(_SecurityAttributes), wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel32.InitializeProcThreadAttributeList.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    kernel32.UpdateProcThreadAttribute.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p,
        ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
    kernel32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    kernel32.DeleteProcThreadAttributeList.restype = None
    kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
        ctypes.POINTER(_StartupInfoEx), ctypes.POINTER(_ProcessInformation),
    ]
    kernel32.CreateProcessW.restype = wintypes.BOOL
    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel32.ResumeThread.restype = wintypes.DWORD
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel32.WriteFile.restype = wintypes.BOOL

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise _win_error("CreateJobObjectW")
    child_stdin = wintypes.HANDLE()
    parent_stdin = wintypes.HANDLE()
    parent_stdout = wintypes.HANDLE()
    child_stdout = wintypes.HANDLE()
    null_handle = wintypes.HANDLE()
    process_info = _ProcessInformation()
    attribute_buffer = None
    attribute_list = None
    attribute_initialized = False
    process_created = False
    reader = writer = None
    output = bytearray()
    output_lock = threading.Lock()
    output_limit_event = threading.Event()
    io_errors: list[BaseException] = []
    try:
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = (
            _JOB_OBJECT_LIMIT_JOB_TIME
            | _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            | _JOB_OBJECT_LIMIT_PROCESS_MEMORY
            | _JOB_OBJECT_LIMIT_JOB_MEMORY
            | _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        limits.BasicLimitInformation.PerJobUserTimeLimit = int(cpu_limit_seconds * 10_000_000)
        limits.BasicLimitInformation.ActiveProcessLimit = _MAX_JOB_PROCESSES
        limits.ProcessMemoryLimit = memory_limit_bytes
        limits.JobMemoryLimit = memory_limit_bytes
        if not kernel32.SetInformationJobObject(
            job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            raise _win_error("SetInformationJobObject")

        security = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), None, True)
        if not kernel32.CreatePipe(ctypes.byref(child_stdin), ctypes.byref(parent_stdin), ctypes.byref(security), 0):
            raise _win_error("CreatePipe(stdin)")
        if not kernel32.CreatePipe(ctypes.byref(parent_stdout), ctypes.byref(child_stdout), ctypes.byref(security), 0):
            raise _win_error("CreatePipe(stdout)")
        if not kernel32.SetHandleInformation(parent_stdin, _HANDLE_FLAG_INHERIT, 0):
            raise _win_error("SetHandleInformation(stdin)")
        if not kernel32.SetHandleInformation(parent_stdout, _HANDLE_FLAG_INHERIT, 0):
            raise _win_error("SetHandleInformation(stdout)")
        created_null_handle = kernel32.CreateFileW(
            "NUL", _GENERIC_WRITE, _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            ctypes.byref(security), _OPEN_EXISTING, _FILE_ATTRIBUTE_NORMAL, None,
        )
        null_value = _handle_value(created_null_handle) if created_null_handle else 0
        if not null_value or null_value == ctypes.c_void_p(-1).value:
            raise _win_error("CreateFileW(NUL)")
        null_handle = wintypes.HANDLE(null_value)

        attribute_size = ctypes.c_size_t()
        kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(attribute_size))
        if not attribute_size.value:
            raise _win_error("InitializeProcThreadAttributeList(size)")
        attribute_buffer = ctypes.create_string_buffer(attribute_size.value)
        attribute_list = ctypes.cast(attribute_buffer, ctypes.c_void_p)
        if not kernel32.InitializeProcThreadAttributeList(attribute_list, 1, 0, ctypes.byref(attribute_size)):
            raise _win_error("InitializeProcThreadAttributeList")
        attribute_initialized = True
        inherited = (wintypes.HANDLE * 3)(child_stdin, child_stdout, null_handle)
        if not kernel32.UpdateProcThreadAttribute(
            attribute_list, 0, _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
            ctypes.cast(inherited, ctypes.c_void_p), ctypes.sizeof(inherited), None, None,
        ):
            raise _win_error("UpdateProcThreadAttribute(handle list)")

        startup = _StartupInfoEx()
        startup.StartupInfo.cb = ctypes.sizeof(_StartupInfoEx)
        startup.StartupInfo.dwFlags = _STARTF_USESTDHANDLES
        startup.StartupInfo.hStdInput = child_stdin
        startup.StartupInfo.hStdOutput = child_stdout
        startup.StartupInfo.hStdError = null_handle
        startup.lpAttributeList = attribute_list
        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
        safe_environment = {
            key: value for key, value in os.environ.items()
            if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"}
        }
        if python_path:
            inherited_python_path = safe_environment.get("PYTHONPATH", "")
            python_entries = [str(Path(python_path).resolve())]
            python_entries.extend(entry for entry in inherited_python_path.split(os.pathsep) if entry)
            safe_environment["PYTHONPATH"] = os.pathsep.join(python_entries)
        system_root = safe_environment.get("SystemRoot") or safe_environment.get("SYSTEMROOT")
        if not system_root:
            raise PdfIsolationUnavailableError("Windows PDF worker requires a configured SystemRoot")
        environment_text = "\0".join(
            f"{key}={safe_environment[key]}" for key in sorted(safe_environment, key=str.casefold)
        ) + "\0\0"
        environment_buffer = ctypes.create_unicode_buffer(environment_text)
        if not kernel32.CreateProcessW(
            command[0], command_line, None, None, True,
            _CREATE_SUSPENDED | _CREATE_NO_WINDOW | _EXTENDED_STARTUPINFO_PRESENT | _CREATE_UNICODE_ENVIRONMENT,
            ctypes.cast(environment_buffer, ctypes.c_void_p), system_root,
            ctypes.byref(startup), ctypes.byref(process_info),
        ):
            raise _win_error("CreateProcessW")
        process_created = True
        for handle in (child_stdin, child_stdout, null_handle):
            kernel32.CloseHandle(handle)
        child_stdin = child_stdout = null_handle = wintypes.HANDLE()
        kernel32.DeleteProcThreadAttributeList(attribute_list)
        attribute_list = None
        attribute_initialized = False

        if not kernel32.AssignProcessToJobObject(job, process_info.hProcess):
            raise _win_error("AssignProcessToJobObject")
        resume_count = kernel32.ResumeThread(process_info.hThread)
        if resume_count in (0, 0xFFFFFFFF):
            raise _win_error("ResumeThread")
        kernel32.CloseHandle(process_info.hThread)
        process_info.hThread = 0

        def read_output() -> None:
            buffer = ctypes.create_string_buffer(64 * 1024)
            read_count = wintypes.DWORD()
            try:
                while kernel32.ReadFile(parent_stdout, buffer, len(buffer), ctypes.byref(read_count), None):
                    if not read_count.value:
                        return
                    with output_lock:
                        if len(output) + read_count.value > max_output_bytes:
                            output_limit_event.set()
                            return
                        output.extend(buffer.raw[:read_count.value])
            except BaseException as exc:
                io_errors.append(exc)

        def write_input() -> None:
            nonlocal parent_stdin
            offset = 0
            try:
                while offset < len(input_bytes):
                    block = input_bytes[offset:offset + 64 * 1024]
                    block_buffer = ctypes.create_string_buffer(block)
                    written = wintypes.DWORD()
                    if not kernel32.WriteFile(parent_stdin, block_buffer, len(block), ctypes.byref(written), None):
                        return
                    if not written.value:
                        return
                    offset += written.value
            except BaseException as exc:
                io_errors.append(exc)
            finally:
                kernel32.CloseHandle(parent_stdin)
                parent_stdin = wintypes.HANDLE()

        reader = threading.Thread(target=read_output, name="nexus-pdf-stdout", daemon=True)
        writer = threading.Thread(target=write_input, name="nexus-pdf-stdin", daemon=True)
        reader.start()
        writer.start()
        deadline = time.monotonic() + timeout_seconds
        try:
            while True:
                if output_limit_event.is_set():
                    raise PdfWorkerOutputLimitError("PDF parser result exceeded the configured output limit")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PdfWorkerTimeoutError("PDF parser exceeded its wall-clock limit")
                wait_ms = max(1, min(50, int(remaining * 1000)))
                wait_result = kernel32.WaitForSingleObject(process_info.hProcess, wait_ms)
                if wait_result == _WAIT_OBJECT_0:
                    break
                if wait_result == _WAIT_FAILED:
                    raise _win_error("WaitForSingleObject")
            # Kill any helper processes the worker may have created, then let
            # pipe readers observe EOF before returning the collected output.
            kernel32.TerminateJobObject(job, 0)
            reader.join(timeout=2.0)
            writer.join(timeout=2.0)
            if reader.is_alive() or writer.is_alive():
                raise PdfIsolationUnavailableError("PDF worker I/O threads did not stop after job termination")
            if output_limit_event.is_set():
                raise PdfWorkerOutputLimitError("PDF parser result exceeded the configured output limit")
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(process_info.hProcess, ctypes.byref(exit_code)):
                raise _win_error("GetExitCodeProcess")
            if exit_code.value != 0 and not output:
                raise PdfWorkerExtractionError("corrupt")
            if io_errors:
                raise PdfIsolationUnavailableError("PDF worker pipe I/O failed") from io_errors[0]
            return bytes(output)
        except BaseException:
            kernel32.TerminateJobObject(job, 1)
            kernel32.WaitForSingleObject(process_info.hProcess, 2000)
            reader.join(timeout=2.0)
            writer.join(timeout=2.0)
            raise
    finally:
        if attribute_list and attribute_initialized:
            kernel32.DeleteProcThreadAttributeList(attribute_list)
        if process_created:
            kernel32.TerminateJobObject(job, 1)
            kernel32.TerminateProcess(process_info.hProcess, 1)
            kernel32.WaitForSingleObject(process_info.hProcess, 2000)
            if process_info.hThread:
                kernel32.CloseHandle(process_info.hThread)
            kernel32.CloseHandle(process_info.hProcess)
        for handle in (child_stdin, parent_stdin, parent_stdout, child_stdout, null_handle):
            if handle and handle.value:
                kernel32.CloseHandle(handle)
        # KILL_ON_JOB_CLOSE is the final cleanup path for every descendant.
        kernel32.CloseHandle(job)
        for thread in (reader, writer):
            if thread is not None and thread.is_alive():
                thread.join(timeout=2.0)


def process_is_in_job() -> bool:
    """Worker-side guard preventing standalone Windows parser execution."""
    if not hasattr(ctypes, "WinDLL"):
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    in_job = wintypes.BOOL()
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    kernel32.IsProcessInJob.restype = wintypes.BOOL
    if not kernel32.IsProcessInJob(kernel32.GetCurrentProcess(), None, ctypes.byref(in_job)):
        return False
    return bool(in_job.value)
