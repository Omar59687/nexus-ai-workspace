"""Bounded, explicitly enumerated, model-free extraction for document collections.

No embeddings, generation, persistent index, database, or directory discovery.
Each PDF is sent through the existing isolated parser-worker boundary.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from nexus_ai.documents.collection_preflight import (
    MAX_FILE_BYTES, MAX_TOTAL_BYTES, _manifest_entries, CollectionManifestError,
)
from nexus_ai.documents.extractors import extractor_for_path
from nexus_ai.documents.chunking import SourceAwareChunker, ChunkingConfig
from nexus_ai.documents.service import stable_document_id
from nexus_ai.retrieval.identity import stable_source_version_id
from nexus_ai.documents.filesystem import read_approved_file


def extract_collection(
    approved_root: Path,
    entries: list[dict[str, object]],
    *,
    max_documents: int = 150,
    max_file_bytes: int = MAX_FILE_BYTES,
    max_total_bytes: int = MAX_TOTAL_BYTES,
    max_pdf_pages: int = 500,
) -> dict[str, object]:
    """Extract listed documents one at a time; keep source text out of report.

    This stage deliberately discards extracted text after each item, preserving
    only verified page counts, text coverage and digests. A later persistence
    milestone is needed for durable collections and cross-document retrieval.
    """
    if type(max_documents) is not int or not 1 <= max_documents <= 150:
        raise CollectionManifestError("max_documents must be between 1 and 150")
    if type(max_file_bytes) is not int or not 1 <= max_file_bytes <= MAX_FILE_BYTES:
        raise CollectionManifestError("invalid per-file limit")
    if type(max_total_bytes) is not int or not 1 <= max_total_bytes <= MAX_TOTAL_BYTES:
        raise CollectionManifestError("invalid aggregate limit")
    if type(max_pdf_pages) is not int or not 1 <= max_pdf_pages <= 500:
        raise CollectionManifestError("invalid page limit")
    checked = _manifest_entries({"documents": entries})
    if len(checked) > max_documents:
        raise CollectionManifestError("manifest exceeds configured item limit")
    root = approved_root.resolve(strict=True)
    if not root.is_dir():
        raise CollectionManifestError("approved root must be a directory")

    rows = []
    chunker = SourceAwareChunker(ChunkingConfig(max_chunks=20_000))
    total_bytes = 0
    seen_digests = {}
    for entry in checked:
        path = str(entry["path"])
        row = {"path": path, "company": entry["company"], "year": entry["year"]}
        remaining = max_total_bytes - total_bytes
        if remaining <= 0:
            row.update(status="blocked", reason="aggregate_byte_limit")
            rows.append(row)
            continue
        try:
            content, _ = read_approved_file(
                root, path, max_bytes=min(max_file_bytes, remaining)
            )
        except (OSError, ValueError):
            row.update(status="blocked", reason="unreadable_unsafe_or_oversized")
            rows.append(row)
            continue
        digest = hashlib.sha256(content).hexdigest()
        total_bytes += len(content)
        if digest in seen_digests:
            row.update(
                status="duplicate", sha256=digest,
                duplicate_of=seen_digests[digest], bytes=len(content),
            )
            rows.append(row)
            continue
        # Only successful extraction can establish a reusable duplicate.
        # A failed first copy must not suppress a second attempted extraction.
        try:
            extractor = extractor_for_path(
                path, pdf_max_pages=max_pdf_pages,
                pdf_max_input_bytes=max_file_bytes,
            )
            if path.casefold().endswith(".pdf") and not getattr(extractor, "isolation_enforced", False):
                raise RuntimeError("isolated PDF worker required")
            extracted = extractor.extract(content, source_path=path)
            if not extracted.pages:
                raise ValueError("empty document")
            nonblank = sum(bool(page.text.strip()) for page in extracted.pages)
            if not nonblank:
                raise ValueError("no extractable text")
            # Preview the same source-aware chunks used by the RAG ingestion
            # service, but do not embed or persist source text.
            document_id = stable_document_id("collection-extraction-preview", path)
            version_id = stable_source_version_id(document_id, digest)
            chunks = chunker.chunk(
                extracted, document_id=document_id, version_id=version_id,
                source_path=path, source_sha256=digest,
            )
            for chunk in chunks:
                if chunk.offsets_reliable:
                    source = next(
                        (page.text for page in extracted.pages
                         if page.page_number == chunk.page_number),
                        None,
                    )
                    if source is None or source[chunk.start_char:chunk.end_char] != chunk.text:
                        raise ValueError("invalid source chunk provenance")
            seen_digests[digest] = path
            row.update(
                status="extracted",
                sha256=digest,
                bytes=len(content),
                page_count=len(extracted.pages),
                text_pages=nonblank,
                extracted_char_count=sum(len(page.text) for page in extracted.pages),
                source_warning_count=len(extracted.warnings),
                chunk_count=len(chunks),
                chunker_fingerprint=chunker.fingerprint,
                chunk_identity_digest=hashlib.sha256(
                    "\\n".join(chunk.chunk_id for chunk in chunks).encode("ascii")
                ).hexdigest(),
                extractor=extracted.extractor_name,
                extractor_version=extracted.extractor_version,
            )
        except Exception:
            # Extractor errors can expose private document content in their
            # messages; only an allowlisted generic code leaves this boundary.
            row.update(status="blocked", reason="extraction_failed_or_no_text")
        rows.append(row)

    failures = sum(row["status"] == "blocked" for row in rows)
    return {
        "kind": "model_free_collection_extraction_v1",
        "status": "PASS" if failures == 0 else "PARTIAL",
        "document_count": len(rows),
        "extracted_count": sum(row["status"] == "extracted" for row in rows),
        "duplicate_count": sum(row["status"] == "duplicate" for row in rows),
        "blocked_count": failures,
        "total_read_bytes": total_bytes,
        "documents": rows,
        "scope": {
            "model_calls": "NONE", "embeddings": "NONE",
            "database_writes": "NONE", "index_writes": "NONE",
            "directory_crawling": "NONE",
        },
        "limitations": [
            "Extracted text and chunks are not persisted; this is not a searchable collection.",
            "Page-level text coverage is not proof of table or financial accuracy.",
            "PDF workers apply existing bounded isolation, not a hostile-PDF sandbox.",
        ],
    }
