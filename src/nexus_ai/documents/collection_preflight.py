"""Explicit, bounded, model-free collection inventory for future batch ingestion.

Only files named in an owner-provided manifest are opened. No directory walking,
embedding, model calls, database writes, or persistent index changes.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from nexus_ai.documents.filesystem import read_approved_file

MAX_DOCUMENTS = 150
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_MANIFEST_BYTES = 512 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
_ALLOWED_TYPES = (".pdf", ".md", ".txt")
_COMPANY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}$")


class CollectionManifestError(ValueError):
    """Invalid manifest; source content and absolute paths are not exposed."""


def _manifest_entries(data: Any) -> list[dict[str, object]]:
    if not isinstance(data, dict) or set(data) != {"documents"}:
        raise CollectionManifestError("manifest must contain only a documents array")
    entries = data["documents"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_DOCUMENTS:
        raise CollectionManifestError("documents must contain 1 to 150 entries")
    validated = []
    seen = set()
    for ordinal, entry in enumerate(entries, 1):
        if not isinstance(entry, dict) or set(entry) != {"path", "company", "year"}:
            raise CollectionManifestError(f"entry {ordinal}: expected path, company and year")
        relative, company, year = entry["path"], entry["company"], entry["year"]
        if not isinstance(relative, str) or not relative or len(relative) > 500:
            raise CollectionManifestError(f"entry {ordinal}: invalid path")
        if not isinstance(company, str) or not _COMPANY.fullmatch(company):
            raise CollectionManifestError(f"entry {ordinal}: invalid company label")
        if type(year) is not int or not 1900 <= year <= 2100:
            raise CollectionManifestError(f"entry {ordinal}: invalid year")
        # No filename-derived company or year guesses.
        from pathlib import PurePosixPath, PureWindowsPath
        posix = PurePosixPath(relative)
        win = PureWindowsPath(relative)
        if (posix.is_absolute() or win.is_absolute() or win.drive or win.root
                or "\\" in relative or relative.startswith("/")
                or any(part in ("", ".", "..") for part in relative.split("/"))
                or posix.suffix.casefold() not in _ALLOWED_TYPES):
            raise CollectionManifestError(f"entry {ordinal}: unsafe or unsupported relative path")
        key = relative.casefold()
        if key in seen:
            raise CollectionManifestError(f"entry {ordinal}: duplicate path")
        seen.add(key)
        validated.append({"path": relative, "company": company, "year": year})
    return validated


def load_collection_manifest(path: Path) -> list[dict[str, object]]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise CollectionManifestError("manifest unavailable or exceeds byte limit")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise CollectionManifestError("manifest must be valid UTF-8 JSON") from exc
    return _manifest_entries(data)


def preflight_collection(
    approved_root: Path,
    entries: list[dict[str, object]],
    *,
    max_file_bytes: int = MAX_FILE_BYTES,
    max_total_bytes: int = MAX_TOTAL_BYTES,
) -> dict[str, object]:
    """Read only explicitly listed files; report file IDs and safe failure codes."""
    if type(max_file_bytes) is not int or not 1 <= max_file_bytes <= MAX_FILE_BYTES:
        raise CollectionManifestError("invalid per-file byte limit")
    if type(max_total_bytes) is not int or not 1 <= max_total_bytes <= MAX_TOTAL_BYTES:
        raise CollectionManifestError("invalid total byte limit")
    checked = _manifest_entries({"documents": entries})
    root = approved_root.resolve(strict=True)
    if not root.is_dir():
        raise CollectionManifestError("approved root must be a directory")
    rows: list[dict[str, object]] = []
    digest_owner: dict[str, str] = {}
    total_bytes = 0
    for entry in checked:
        path = str(entry["path"])
        row: dict[str, object] = {
            "path": path, "company": entry["company"], "year": entry["year"]
        }
        try:
            # Existing file gate rejects traversal, links, unsupported files
            # and changes during opening. Never print underlying exception text.
            remaining = max_total_bytes - total_bytes
            if remaining <= 0:
                raise CollectionManifestError("collection byte budget exhausted")
            content, _ = read_approved_file(
                root, path, max_bytes=min(max_file_bytes, remaining)
            )
            file_hash = hashlib.sha256(content).hexdigest()
            total_bytes += len(content)
            row.update({
                "status": "ready", "bytes": len(content), "sha256": file_hash,
                "duplicate_of": digest_owner.get(file_hash),
            })
            digest_owner.setdefault(file_hash, path)
        except (OSError, ValueError) as exc:
            row.update({
                "status": "blocked",
                "reason": (
                    "collection_byte_budget_exhausted"
                    if isinstance(exc, CollectionManifestError)
                    else "unreadable_unsafe_or_oversized"
                ),
            })
        rows.append(row)
    return {
        "kind": "model_free_collection_preflight_v1",
        "status": "PASS" if all(row["status"] == "ready" for row in rows) else "PARTIAL",
        "document_count": len(rows),
        "ready_count": sum(row["status"] == "ready" for row in rows),
        "blocked_count": sum(row["status"] == "blocked" for row in rows),
        "duplicate_content_count": sum(
            bool(row.get("duplicate_of")) for row in rows
        ),
        "total_read_bytes": total_bytes,
        "documents": rows,
        "scope": {
            "model_calls": "NONE", "embeddings": "NONE",
            "database_writes": "NONE", "index_writes": "NONE",
            "directory_crawling": "NONE",
        },
        "limitations": [
            "This inventories listed source files; it does not validate PDF extraction.",
            "Financial facts, citations, and retrieval accuracy are not evaluated.",
            "A successful preflight does not certify batch ingestion readiness.",
        ],
    }
