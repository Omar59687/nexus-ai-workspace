"""Single-file, explicitly rooted ingestion orchestration; no filesystem crawling."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping

from nexus_ai.documents.chunking import ChunkingConfig, SourceAwareChunker
from nexus_ai.documents.extractors import DocumentExtractor, extractor_for_path
from nexus_ai.documents.filesystem import read_approved_file
from nexus_ai.documents.types import (
    DocumentVersion,
    IndexedDocument,
    IndexedWindow,
    IngestionFailure,
    IngestionResult,
)
from nexus_ai.retrieval.embeddings import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_WINDOW_CHARS,
    DEFAULT_WINDOW_OVERLAP,
    MAX_INDEX_WINDOWS,
    EmbeddingProvider,
    create_text_windows,
    embed_windows,
)
from nexus_ai.retrieval.repository import DocumentIndexRepository
from nexus_ai.retrieval.identity import (
    stable_index_generation_id,
    stable_processing_id,
    stable_source_version_id,
)
from nexus_ai.retrieval.embeddings import MAX_EMBEDDING_DIMENSIONS


@dataclass(frozen=True)
class DocumentIngestionLimits:
    """Experimental resource caps; these are not approved production limits."""

    max_file_bytes: int = 25 * 1024 * 1024
    max_total_extracted_chars: int = 10_000_000
    max_pdf_page_chars: int = 2_000_000
    max_pdf_pages: int = 500
    max_chunks: int = 20_000
    max_windows: int = MAX_INDEX_WINDOWS
    window_chars: int = DEFAULT_WINDOW_CHARS
    window_overlap_chars: int = DEFAULT_WINDOW_OVERLAP
    embedding_batch_size: int = DEFAULT_BATCH_SIZE
    max_vector_coordinates: int = 2_000_000
    pdf_timeout_seconds: int = 300
    pdf_memory_limit_bytes: int = 1024 * 1024 * 1024
    pdf_cpu_limit_seconds: int = 300

    MAX_FILE_BYTES = 50 * 1024 * 1024
    MAX_EXTRACTED_CHARS = 40_000_000
    MAX_PDF_PAGE_CHARS = 4_000_000
    MAX_PDF_PAGES = 1_000
    MAX_CHUNKS = 100_000
    MAX_WINDOWS = MAX_INDEX_WINDOWS
    MAX_BATCH_SIZE = 256
    MAX_VECTOR_COORDINATES = 8_000_000
    MAX_PDF_TIMEOUT_SECONDS = 600
    MAX_PDF_MEMORY_BYTES = 2 * 1024 * 1024 * 1024
    MAX_PDF_CPU_SECONDS = 600

    def __post_init__(self) -> None:
        for key, value in self.__dict__.items():
            if type(value) is not int or value <= 0:
                raise ValueError(f"{key} must be a positive integer")
        maxima = {
            "max_file_bytes": self.MAX_FILE_BYTES,
            "max_total_extracted_chars": self.MAX_EXTRACTED_CHARS,
            "max_pdf_page_chars": self.MAX_PDF_PAGE_CHARS,
            "max_pdf_pages": self.MAX_PDF_PAGES,
            "max_chunks": self.MAX_CHUNKS,
            "max_windows": self.MAX_WINDOWS,
            "embedding_batch_size": self.MAX_BATCH_SIZE,
            "max_vector_coordinates": self.MAX_VECTOR_COORDINATES,
            "pdf_timeout_seconds": self.MAX_PDF_TIMEOUT_SECONDS,
            "pdf_memory_limit_bytes": self.MAX_PDF_MEMORY_BYTES,
            "pdf_cpu_limit_seconds": self.MAX_PDF_CPU_SECONDS,
        }
        for key, maximum in maxima.items():
            if getattr(self, key) > maximum:
                raise ValueError(f"{key} exceeds the hard safety ceiling {maximum}")
        if self.window_overlap_chars >= self.window_chars:
            raise ValueError("window_overlap_chars must be less than window_chars")


class DocumentIngestionService:
    def __init__(
        self,
        *,
        approved_root: str | Path,
        repository: DocumentIndexRepository,
        embedder: EmbeddingProvider,
        chunker: SourceAwareChunker | None = None,
        extractors: Mapping[str, DocumentExtractor] | None = None,
        limits: DocumentIngestionLimits = DocumentIngestionLimits(),
    ) -> None:
        self.approved_root = Path(approved_root).resolve(strict=True)
        if not self.approved_root.is_dir():
            raise ValueError("approved_root must be a directory")
        self.repository = repository
        self.embedder = embedder
        self.chunker = chunker or SourceAwareChunker(ChunkingConfig(max_chunks=limits.max_chunks))
        if self.chunker.config.max_chunks > limits.max_chunks:
            self.chunker = SourceAwareChunker(ChunkingConfig(
                max_chars=self.chunker.config.max_chars,
                overlap_chars=self.chunker.config.overlap_chars,
                max_chunks=limits.max_chunks,
            ))
        self.extractors = {key.casefold(): value for key, value in (extractors or {}).items()}
        self.limits = limits

    def ingest(self, workspace_id: str, relative_path: str | Path) -> IngestionResult:
        source_for_failure = _failure_source(relative_path)
        try:
            _validate_workspace_id(workspace_id)
            content, relative = read_approved_file(
                self.approved_root, relative_path, max_bytes=self.limits.max_file_bytes
            )
            source_path = PurePosixPath(*relative.parts).as_posix()
            suffix = Path(source_path).suffix.casefold()
            extractor = self.extractors.get(suffix) or extractor_for_path(
                source_path, pdf_max_pages=self.limits.max_pdf_pages,
                pdf_max_page_chars=self.limits.max_pdf_page_chars,
                pdf_max_total_chars=self.limits.max_total_extracted_chars,
                pdf_max_input_bytes=self.limits.max_file_bytes,
                pdf_timeout_seconds=self.limits.pdf_timeout_seconds,
                pdf_memory_limit_bytes=self.limits.pdf_memory_limit_bytes,
                pdf_cpu_limit_seconds=self.limits.pdf_cpu_limit_seconds,
            )
            if suffix == ".pdf" and not getattr(extractor, "isolation_enforced", False):
                raise ValueError("PDF extraction requires an isolated parser worker")
            source_sha256 = hashlib.sha256(content).hexdigest()
            extraction = extractor.extract(content, source_path=source_path)
            if not extraction.pages or sum(len(page.text) for page in extraction.pages) > self.limits.max_total_extracted_chars:
                raise ValueError("document exceeds max_total_extracted_chars or contains no pages")
            if not any(page.text.strip() for page in extraction.pages):
                raise ValueError("document contains no extractable text")

            document_id = stable_document_id(workspace_id, source_path)
            version_id = stable_source_version_id(document_id, source_sha256)
            processing_id = stable_processing_id(
                extractor_name=extraction.extractor_name,
                extractor_version=extraction.extractor_version,
                media_type=extraction.media_type,
                offsets_reliable=extraction.offsets_reliable,
                chunker_fingerprint=self.chunker.fingerprint,
            )
            chunks = self.chunker.chunk(
                extraction, document_id=document_id, version_id=version_id,
                source_path=source_path, source_sha256=source_sha256,
            )
            if len(chunks) > self.limits.max_chunks:
                raise ValueError("document exceeds max_chunks")
            drafts = create_text_windows(
                chunks, window_chars=self.limits.window_chars,
                overlap_chars=self.limits.window_overlap_chars,
                max_windows=self.limits.max_windows,
            )
            vector_budget = min(
                self.limits.max_vector_coordinates,
                getattr(getattr(self.repository, "limits", None), "max_vector_coordinates", self.limits.max_vector_coordinates),
            )
            expected_dimensions = getattr(self.embedder, "embedding_dimensions", None)
            if expected_dimensions is not None:
                if type(expected_dimensions) is not int or not 1 <= expected_dimensions <= MAX_EMBEDDING_DIMENSIONS:
                    raise ValueError("embedding_dimensions must be between 1 and 4096")
                if len(drafts) * expected_dimensions > vector_budget:
                    raise ValueError("index exceeds max_vector_coordinates before embedding")
            vectors = embed_windows(
                drafts, self.embedder, batch_size=self.limits.embedding_batch_size,
                max_vector_coordinates=vector_budget,
            )
            if len(vectors) != len(drafts):
                raise ValueError("embedding count does not match text-window count")
            dimensions = len(vectors[0]) if vectors else 0
            if not dimensions or any(len(vector) != dimensions for vector in vectors):
                raise ValueError("embedding dimensions are inconsistent")
            windows = tuple(
                IndexedWindow(
                    window_id=draft.window_id, chunk_id=draft.chunk_id,
                    page_number=draft.page_number, start_char=draft.start_char,
                    end_char=draft.end_char, local_start=draft.local_start,
                    local_end=draft.local_end, text=draft.text, vector=vector,
                )
                for draft, vector in zip(drafts, vectors)
            )
            document = DocumentVersion(
                workspace_id=workspace_id, document_id=document_id, version_id=version_id,
                processing_id=processing_id,
                source_path=source_path, content_sha256=source_sha256,
                media_type=extraction.media_type, extractor_name=extraction.extractor_name,
                extractor_version=extraction.extractor_version,
                chunker_version=self.chunker.fingerprint, pages=extraction.pages,
                warnings=extraction.warnings, offsets_reliable=extraction.offsets_reliable,
            )
            indexed = IndexedDocument(
                document=document, chunks=chunks, windows=windows,
                embedding_model_id=self.embedder.model_id,
                embedding_revision=self.embedder.revision,
                embedding_dimensions=dimensions,
                index_generation_id=stable_index_generation_id(
                    document_id=document_id,
                    source_version_id=version_id,
                    processing_id=processing_id,
                    embedding_model_id=self.embedder.model_id,
                    embedding_revision=self.embedder.revision,
                    embedding_dimensions=dimensions,
                    chunker_fingerprint=self.chunker.fingerprint,
                    window_chars=self.limits.window_chars,
                    window_overlap_chars=self.limits.window_overlap_chars,
                    preprocessing_id=_preprocessing_id(self.embedder),
                ),
                window_chars=self.limits.window_chars,
                window_overlap_chars=self.limits.window_overlap_chars,
                preprocessing_id=_preprocessing_id(self.embedder),
            )
            activated = self.repository.activate(indexed)
            return IngestionResult(
                document_id, version_id, source_sha256, len(chunks), len(windows),
                activated=activated, idempotent=not activated, warnings=extraction.warnings,
            )
        except Exception as exc:
            try:
                _validate_workspace_id(workspace_id)
                self.repository.record_failure(IngestionFailure(
                    workspace_id=workspace_id,
                    source_path=source_for_failure,
                    error_type=type(exc).__name__,
                ))
            except Exception:
                # Failure logging must not hide the original ingestion failure.
                pass
            raise


def stable_document_id(workspace_id: str, source_path: str) -> str:
    _validate_workspace_id(workspace_id)
    normalized = PurePosixPath(source_path).as_posix()
    normalized = os.path.normcase(normalized)
    return hashlib.sha256(f"document-v1\0{workspace_id}\0{normalized}".encode("utf-8")).hexdigest()


def stable_version_id(
    document_id: str,
    content_sha256: str,
    extractor_name: str,
    extractor_version: str,
    chunker_version: str,
) -> str:
    """Backward-compatible name for a source-content version identity.

    Processing parameters are intentionally excluded: they belong to
    `processing_id` and `index_generation_id`, so reprocessing unchanged source
    bytes can be activated atomically as a distinct generation.
    """
    return stable_source_version_id(document_id, content_sha256)


def _preprocessing_id(embedder: EmbeddingProvider) -> str:
    value = getattr(embedder, "preprocessing_id", None)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("embedding provider must declare a stable preprocessing_id")
    return value


def _validate_workspace_id(workspace_id: str) -> None:
    if not isinstance(workspace_id, str) or not workspace_id.strip() or len(workspace_id) > 128:
        raise ValueError("workspace_id must be a non-empty string of at most 128 characters")


def _failure_source(path: str | Path) -> str:
    try:
        raw = Path(path)
        if raw.is_absolute() or ".." in raw.parts:
            return "<invalid-source-path>"
        return PurePosixPath(*raw.parts).as_posix()
    except (TypeError, ValueError):
        return "<invalid-source-path>"
