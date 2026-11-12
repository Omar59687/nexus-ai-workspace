"""Explicit-root file opening with bounded reads and reparse-point checks."""
from __future__ import annotations

import errno
import os
import stat
from pathlib import Path, PureWindowsPath


ALLOWED_SUFFIXES = {".txt", ".md", ".pdf"}


class UnsafeDocumentPath(ValueError):
    """Raised when a source path is outside or unsafe beneath the approved root."""


def read_approved_file(root: str | Path, relative_path: str | Path, *, max_bytes: int) -> tuple[bytes, Path]:
    """Read one explicitly named file beneath root, refusing links and traversal.

    POSIX uses descriptor-relative no-follow opens. The Windows stdlib fallback
    checks every reparse component and compares identities around the read; a
    concurrent same-user directory replacement remains a platform limitation.
    """
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    relative_text = os.fspath(relative_path)
    if not isinstance(relative_text, str):
        raise UnsafeDocumentPath("source path must be text")
    win_path = PureWindowsPath(relative_text)
    relative = Path(relative_text)
    if relative.is_absolute() or relative.anchor or win_path.drive or win_path.root or ".." in relative.parts:
        raise UnsafeDocumentPath("source path must be relative and contain no traversal")
    if not relative.parts or any(part in ("", ".") for part in relative.parts):
        raise UnsafeDocumentPath("source path must name a file")
    if relative.suffix.casefold() not in ALLOWED_SUFFIXES:
        raise UnsafeDocumentPath("unsupported file type; use UTF-8 .txt, .md, or .pdf")

    approved_root = Path(root).resolve(strict=True)
    if not approved_root.is_dir():
        raise UnsafeDocumentPath("approved workspace root must be a directory")
    _assert_no_reparse_components(approved_root, relative)
    candidate = approved_root / relative
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(approved_root):
        raise UnsafeDocumentPath("source path resolves outside approved root")
    _assert_regular_file(resolved)

    fd = _open_beneath(approved_root, relative)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise UnsafeDocumentPath("source must be a regular file")
        if opened.st_size > max_bytes:
            raise UnsafeDocumentPath("source exceeds the byte limit")
        data = bytearray()
        with os.fdopen(fd, "rb", buffering=0) as stream:
            fd = -1
            while True:
                block = stream.read(min(64 * 1024, max_bytes - len(data) + 1))
                if not block:
                    break
                data.extend(block)
                if len(data) > max_bytes:
                    raise UnsafeDocumentPath("source exceeds the byte limit")
        if os.name != "posix":
            _assert_no_reparse_components(approved_root, relative)
            current = (approved_root / relative).resolve(strict=True)
            if not current.is_relative_to(approved_root):
                raise UnsafeDocumentPath("source changed outside approved root while reading")
            current_stat = current.stat()
            if (opened.st_dev, opened.st_ino) != (current_stat.st_dev, current_stat.st_ino):
                raise UnsafeDocumentPath("source changed while being read")
        return bytes(data), relative
    except BaseException:
        if fd >= 0:
            os.close(fd)
        raise


def _open_beneath(root: Path, relative: Path) -> int:
    if _supports_dir_fd():
        nofollow = os.O_NOFOLLOW
        directory = os.O_DIRECTORY
        current = os.open(root, os.O_RDONLY | directory | nofollow)
        try:
            for part in relative.parts[:-1]:
                child = os.open(part, os.O_RDONLY | directory | nofollow, dir_fd=current)
                os.close(current)
                current = child
            return os.open(relative.parts[-1], os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0), dir_fd=current)
        except BaseException:
            os.close(current)
            raise
        finally:
            # The returned file descriptor is separate from this directory handle.
            if current >= 0:
                try:
                    os.close(current)
                except OSError:
                    pass
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    try:
        return os.open(root / relative, flags)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise UnsafeDocumentPath("source path contains a link or non-directory component") from exc
        raise


def _supports_dir_fd() -> bool:
    return (os.name == "posix" and bool(getattr(os, "O_NOFOLLOW", 0))
            and bool(getattr(os, "O_DIRECTORY", 0)) and os.open in os.supports_dir_fd)


def _assert_regular_file(path: Path) -> None:
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise UnsafeDocumentPath("source must be a regular file")


def _assert_no_reparse_components(root: Path, relative: Path) -> None:
    current = root
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    for part in relative.parts:
        current = current / part
        info = current.lstat()
        is_junction = getattr(current, "is_junction", None)
        if current.is_symlink() or (callable(is_junction) and is_junction()):
            raise UnsafeDocumentPath("source path contains a symlink or reparse-point component")
        if os.name == "nt" and getattr(info, "st_file_attributes", 0) & reparse:
            raise UnsafeDocumentPath("source path contains a symlink or reparse-point component")
