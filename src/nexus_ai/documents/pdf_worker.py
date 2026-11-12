"""Timed, bounded, POSIX-resource-limited PDF extraction worker.

The parent runner refuses platforms where this implementation cannot enforce
address-space and CPU limits. Windows callers must use a separately reviewed
Job Object implementation before processing untrusted PDFs.
"""
from __future__ import annotations

import json
import math
import os
import selectors
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from nexus_ai.documents.types import ExtractedPage, ExtractionResult


class PdfIsolationUnavailableError(RuntimeError):
    """The OS cannot enforce the configured PDF worker isolation boundary."""


class PdfWorkerTimeoutError(RuntimeError):
    """PDF parsing exceeded the enforced wall-clock deadline."""


class PdfWorkerOutputLimitError(RuntimeError):
    """The worker attempted to return more than the bounded result size."""


class PdfWorkerExtractionError(ValueError):
    """A controlled parse error returned by the isolated worker."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        messages = {
            "encrypted": "encrypted PDFs are not supported",
            "page_limit": "PDF exceeds the configured page limit",
            "page_char_limit": "PDF page exceeds the extracted-text limit",
            "total_char_limit": "PDF exceeds the total extracted-text limit",
            "corrupt": "PDF is corrupted or could not be extracted",
            "dependency_missing": "PDF extraction requires the optional pypdf package",
            "no_pages": "PDF contains no pages",
        }
        super().__init__(messages.get(reason_code, "PDF extraction failed"))


class IsolatedPdfExtractor:
    """Run pypdf in a child process with wall, address-space, CPU, and output caps."""

    isolation_enforced = True
    name = "pypdf-isolated"
    version = "1"
    media_type = "application/pdf"

    def __init__(
        self,
        *,
        max_pages: int = 500,
        max_page_chars: int = 2_000_000,
        max_total_chars: int = 10_000_000,
        max_input_bytes: int = 25 * 1024 * 1024,
        timeout_seconds: float = 60.0,
        memory_limit_bytes: int = 1024 * 1024 * 1024,
        cpu_limit_seconds: int = 30,
        worker_script: str | Path | None = None,
        python_executable: str | None = None,
    ) -> None:
        for name, value in (("max_pages", max_pages), ("max_page_chars", max_page_chars),
                            ("max_total_chars", max_total_chars), ("max_input_bytes", max_input_bytes),
                            ("cpu_limit_seconds", cpu_limit_seconds),
                            ("memory_limit_bytes", memory_limit_bytes)):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a positive finite number")
        if not math.isfinite(timeout_seconds):
            raise ValueError("timeout_seconds must be a positive finite number")
        self.max_pages = max_pages
        self.max_page_chars = max_page_chars
        self.max_total_chars = max_total_chars
        self.max_input_bytes = max_input_bytes
        self.timeout_seconds = float(timeout_seconds)
        self.memory_limit_bytes = memory_limit_bytes
        self.cpu_limit_seconds = cpu_limit_seconds
        self.worker_script = Path(worker_script or __file__).resolve(strict=True)
        self.python_executable = python_executable or sys.executable
        self.max_output_bytes = max_total_chars * 6 + max_pages * 160 + 4096

    def extract(self, content: bytes, *, source_path: str) -> ExtractionResult:
        if not isinstance(content, bytes):
            raise TypeError("PDF worker input must be bytes")
        if len(content) > self.max_input_bytes:
            raise ValueError("PDF input exceeds the configured byte limit")
        _require_platform_limits()
        command = [
            self.python_executable,
            str(self.worker_script),
            "--worker",
            "--max-pages", str(self.max_pages),
            "--max-page-chars", str(self.max_page_chars),
            "--max-total-chars", str(self.max_total_chars),
            "--memory-limit-bytes", str(self.memory_limit_bytes),
            "--cpu-limit-seconds", str(self.cpu_limit_seconds),
        ]
        output = _run_bounded_process(
            command,
            content,
            timeout_seconds=self.timeout_seconds,
            max_output_bytes=self.max_output_bytes,
        )
        try:
            payload = json.loads(output.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PdfWorkerExtractionError("corrupt") from exc
        if not isinstance(payload, dict):
            raise PdfWorkerExtractionError("corrupt")
        error = payload.get("error")
        if error is not None:
            if not isinstance(error, str):
                raise PdfWorkerExtractionError("corrupt")
            raise PdfWorkerExtractionError(error)
        try:
            raw_pages = payload["pages"]
            warnings = payload["warnings"]
            parser_version = payload["parser_version"]
            if not isinstance(raw_pages, list) or not isinstance(warnings, list):
                raise TypeError
            pages = tuple(
                ExtractedPage(page_number=row["page_number"], text=row["text"])
                for row in raw_pages
                if isinstance(row, dict) and type(row.get("page_number")) is int and isinstance(row.get("text"), str)
            )
            if len(pages) != len(raw_pages) or not all(isinstance(warning, str) for warning in warnings):
                raise TypeError
            if not isinstance(parser_version, str) or not parser_version:
                raise TypeError
        except (KeyError, TypeError, ValueError) as exc:
            raise PdfWorkerExtractionError("corrupt") from exc
        return ExtractionResult(
            self.name,
            parser_version,
            self.media_type,
            pages,
            tuple(warnings),
            offsets_reliable=True,
        )


def _require_platform_limits() -> None:
    if os.name != "posix":
        raise PdfIsolationUnavailableError(
            "isolated PDF ingestion is disabled: enforceable Windows Job Object limits are not configured"
        )
    try:
        import resource
    except ImportError as exc:
        raise PdfIsolationUnavailableError("POSIX RLIMIT_AS and RLIMIT_CPU are required") from exc
    if not hasattr(resource, "RLIMIT_AS") or not hasattr(resource, "RLIMIT_CPU"):
        raise PdfIsolationUnavailableError("POSIX RLIMIT_AS and RLIMIT_CPU are required")


def _run_bounded_process(
    command: list[str],
    input_bytes: bytes,
    *,
    timeout_seconds: float,
    max_output_bytes: int,
) -> bytes:
    """Stream child I/O with a hard output cap; never use unbounded communicate()."""
    _require_platform_limits()
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        bufsize=0,
    )
    assert process.stdin is not None and process.stdout is not None
    selector = selectors.DefaultSelector()
    output = bytearray()
    input_offset = 0
    input_fd = process.stdin.fileno()
    output_fd = process.stdout.fileno()
    os.set_blocking(input_fd, False)
    os.set_blocking(output_fd, False)
    selector.register(input_fd, selectors.EVENT_WRITE, "stdin")
    selector.register(output_fd, selectors.EVENT_READ, "stdout")
    deadline = time.monotonic() + timeout_seconds
    output_closed = False
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PdfWorkerTimeoutError("PDF parser exceeded its wall-clock limit")
            for key, _ in selector.select(timeout=min(remaining, 0.1)):
                if key.data == "stdin":
                    if input_offset >= len(input_bytes):
                        selector.unregister(input_fd)
                        process.stdin.close()
                        continue
                    try:
                        written = os.write(input_fd, input_bytes[input_offset:input_offset + 64 * 1024])
                        input_offset += written
                    except BrokenPipeError:
                        selector.unregister(input_fd)
                        process.stdin.close()
                else:
                    block = os.read(output_fd, 64 * 1024)
                    if not block:
                        selector.unregister(output_fd)
                        output_closed = True
                        process.stdout.close()
                    else:
                        output.extend(block)
                        if len(output) > max_output_bytes:
                            raise PdfWorkerOutputLimitError("PDF parser result exceeded the configured output limit")
            if process.poll() is not None and output_closed:
                break
        try:
            exit_code = process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise PdfWorkerTimeoutError("PDF parser exceeded its wall-clock limit") from exc
        if exit_code != 0 and not output:
            raise PdfWorkerExtractionError("corrupt")
        return bytes(output)
    except BaseException:
        if process.poll() is None:
            process.kill()
        process.wait()
        raise
    finally:
        selector.close()
        for stream in (process.stdin, process.stdout):
            if stream is not None and not stream.closed:
                stream.close()


def _apply_worker_limits(memory_limit_bytes: int, cpu_limit_seconds: int) -> None:
    """Apply hard process limits before importing pypdf or parsing input."""
    if os.name != "posix":
        raise RuntimeError("POSIX process limits unavailable")
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (memory_limit_bytes, memory_limit_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit_seconds, cpu_limit_seconds))
    if hasattr(resource, "RLIMIT_CORE"):
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _worker(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--max-pages", type=int, required=True)
    parser.add_argument("--max-page-chars", type=int, required=True)
    parser.add_argument("--max-total-chars", type=int, required=True)
    parser.add_argument("--memory-limit-bytes", type=int, required=True)
    parser.add_argument("--cpu-limit-seconds", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        _apply_worker_limits(args.memory_limit_bytes, args.cpu_limit_seconds)
    except Exception:
        _write_result({"error": "corrupt"})
        return 2
    try:
        from io import BytesIO
        try:
            import pypdf
        except ImportError:
            _write_result({"error": "dependency_missing"})
            return 2
        content = sys.stdin.buffer.read()
        reader = pypdf.PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            _write_result({"error": "encrypted"})
            return 2
        if len(reader.pages) > args.max_pages:
            _write_result({"error": "page_limit"})
            return 2
        pages = []
        warnings = []
        total_chars = 0
        for number, page in enumerate(reader.pages, start=1):
            text = page.extract_text()
            if text is None:
                text = ""
                warnings.append(f"page {number} produced no extractable text")
            if not isinstance(text, str):
                _write_result({"error": "corrupt"})
                return 2
            if len(text) > args.max_page_chars:
                _write_result({"error": "page_char_limit"})
                return 2
            total_chars += len(text)
            if total_chars > args.max_total_chars:
                _write_result({"error": "total_char_limit"})
                return 2
            pages.append({"page_number": number, "text": text})
        if not pages:
            _write_result({"error": "no_pages"})
            return 2
        _write_result({"pages": pages, "warnings": warnings, "parser_version": pypdf.__version__})
        return 0
    except BaseException:
        _write_result({"error": "corrupt"})
        return 2


def _write_result(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(_worker(sys.argv[1:]))
