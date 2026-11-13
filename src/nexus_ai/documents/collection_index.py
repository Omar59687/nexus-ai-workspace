"""Explicit-file, model-free collection extraction, chunking, and persistence."""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Mapping

from nexus_ai.documents.chunking import ChunkingConfig, SourceAwareChunker
from nexus_ai.documents.collection_preflight import (
    MAX_FILE_BYTES,
    MAX_TOTAL_BYTES,
    CollectionManifestError,
    _manifest_entries,
)
from nexus_ai.documents.collection_types import (
    CollectionIndex,
    CollectionIndexLimits,
    CollectionIndexRepository,
    validate_collection_workspace_id,
)
from nexus_ai.documents.extractors import DocumentExtractor, extractor_for_path
from nexus_ai.documents.filesystem import read_approved_file
from nexus_ai.documents.types import DocumentVersion, IngestionFailure
from nexus_ai.retrieval.identity import (
    stable_document_id,
    stable_processing_id,
    stable_source_version_id,
)


class CollectionIndexService:
    """Persist source text and provenance for only the caller's manifest paths.

    Each document is extracted and activated in its own repository transaction.
    No embedding provider, model, or database connection is created here.
    """

    def __init__(
        self,
        *,
        approved_root: str | Path,
        repository: CollectionIndexRepository,
        extractors: Mapping[str, DocumentExtractor] | None = None,
        chunker: SourceAwareChunker | None = None,
        limits: CollectionIndexLimits = CollectionIndexLimits(),
    ) -> None:
        self.approved_root = Path(approved_root).resolve(strict=True)
        if not self.approved_root.is_dir():
            raise ValueError("approved_root must be a directory")
        self.repository = repository
        self.limits = limits
        self.chunker = chunker or SourceAwareChunker(
            ChunkingConfig(max_chunks=limits.max_chunks_per_document)
        )
        if self.chunker.config.max_chunks > limits.max_chunks_per_document:
            self.chunker = SourceAwareChunker(ChunkingConfig(
                max_chars=self.chunker.config.max_chars,
                overlap_chars=self.chunker.config.overlap_chars,
                max_chunks=limits.max_chunks_per_document,
            ))
        self.extractors = {key.casefold(): value for key, value in (extractors or {}).items()}

    def index(self, workspace_id: str, entries: list[dict[str, object]]) -> dict[str, object]:
        validate_collection_workspace_id(workspace_id)
        checked = _manifest_entries({"documents": entries})
        if len(checked) > self.limits.max_documents:
            raise CollectionManifestError("manifest exceeds configured item limit")
        total_bytes = 0
        rows: list[dict[str, object]] = []

        for entry in checked:
            relative_path = str(entry["path"])
            row: dict[str, object] = {"path": relative_path}
            remaining = self.limits.max_total_bytes - total_bytes
            try:
                if remaining <= 0:
                    raise CollectionManifestError("collection byte budget exhausted")
                content, relative = read_approved_file(
                    self.approved_root,
                    relative_path,
                    max_bytes=min(self.limits.max_file_bytes, remaining),
                )
                total_bytes += len(content)
                source_path = PurePosixPath(*relative.parts).as_posix()
                suffix = Path(source_path).suffix.casefold()
                extractor = self.extractors.get(suffix) or extractor_for_path(
                    source_path,
                    pdf_max_pages=self.limits.max_pdf_pages,
                    pdf_max_page_chars=self.limits.max_pdf_page_chars,
                    pdf_max_total_chars=self.limits.max_total_extracted_chars,
                    pdf_max_input_bytes=self.limits.max_file_bytes,
                )
                if suffix == ".pdf" and not getattr(extractor, "isolation_enforced", False):
                    raise ValueError("PDF extraction requires an isolated parser worker")
                extraction = extractor.extract(content, source_path=source_path)
                if not extraction.pages or len(extraction.pages) > self.limits.max_pdf_pages:
                    raise ValueError("document page count is outside configured limits")
                extracted_chars = sum(len(page.text) for page in extraction.pages)
                if extracted_chars > self.limits.max_total_extracted_chars:
                    raise ValueError("document exceeds max_total_extracted_chars")
                if any(len(page.text) > self.limits.max_pdf_page_chars for page in extraction.pages):
                    raise ValueError("document exceeds max_pdf_page_chars")
                if not any(page.text.strip() for page in extraction.pages):
                    raise ValueError("document contains no extractable text")

                source_sha256 = hashlib.sha256(content).hexdigest()
                document_id = stable_document_id(workspace_id, source_path)
                version_id = stable_source_version_id(document_id, source_sha256)
                chunker_version = self.chunker.fingerprint
                processing_id = stable_processing_id(
                    extractor_name=extraction.extractor_name,
                    extractor_version=extraction.extractor_version,
                    media_type=extraction.media_type,
                    offsets_reliable=extraction.offsets_reliable,
                    chunker_fingerprint=chunker_version,
                )
                chunks = self.chunker.chunk(
                    extraction,
                    document_id=document_id,
                    version_id=version_id,
                    source_path=source_path,
                    source_sha256=source_sha256,
                )
                if len(chunks) > self.limits.max_chunks_per_document:
                    raise ValueError("document exceeds max_chunks_per_document")
                document = DocumentVersion(
                    workspace_id=workspace_id,
                    document_id=document_id,
                    version_id=version_id,
                    processing_id=processing_id,
                    source_path=source_path,
                    content_sha256=source_sha256,
                    media_type=extraction.media_type,
                    extractor_name=extraction.extractor_name,
                    extractor_version=extraction.extractor_version,
                    chunker_version=chunker_version,
                    pages=extraction.pages,
                    warnings=extraction.warnings,
                    offsets_reliable=extraction.offsets_reliable,
                )
                activated = self.repository.activate(CollectionIndex(document, chunks))
                row.update(
                    status="indexed" if activated else "unchanged",
                    document_id=document_id,
                    version_id=version_id,
                    processing_id=processing_id,
                    source_sha256=source_sha256,
                    page_count=len(extraction.pages),
                    extracted_char_count=extracted_chars,
                    chunk_count=len(chunks),
                    warning_count=len(extraction.warnings),
                )
            except Exception as exc:
                error_type = type(exc).__name__
                try:
                    self.repository.record_failure(IngestionFailure(
                        workspace_id=workspace_id,
                        source_path=_safe_failure_path(relative_path),
                        error_type=error_type,
                    ))
                except Exception:
                    # A secondary failure-store problem must not stop later files.
                    pass
                row.update(status="blocked", reason="extraction_or_persistence_failed")
            rows.append(row)

        blocked = sum(row["status"] == "blocked" for row in rows)
        return {
            "kind": "model_free_collection_index_v1",
            "status": "PASS" if blocked == 0 else "PARTIAL",
            "document_count": len(rows),
            "indexed_count": sum(row["status"] == "indexed" for row in rows),
            "unchanged_count": sum(row["status"] == "unchanged" for row in rows),
            "blocked_count": blocked,
            "total_read_bytes": total_bytes,
            "documents": rows,
            "scope": {
                "model_calls": "NONE",
                "embeddings": "NONE",
                "database_migrations": "NONE",
                "directory_crawling": "NONE",
                "company_year_retrieval_filtering": "UNCHANGED",
            },
        }


def _safe_failure_path(value: str) -> str:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        return "<invalid-source-path>"
    return PurePosixPath(*path.parts).as_posix()
