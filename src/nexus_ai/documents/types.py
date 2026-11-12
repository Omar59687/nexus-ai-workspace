"""Immutable document, extraction, and index records for the RAG service."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ExtractedPage:
    """Text emitted by one source page; PDF pages are one-based."""

    page_number: int | None
    text: str


@dataclass(frozen=True)
class ExtractionResult:
    extractor_name: str
    extractor_version: str
    media_type: str
    pages: tuple[ExtractedPage, ...]
    warnings: tuple[str, ...] = ()
    offsets_reliable: bool = True


@dataclass(frozen=True)
class SourceChunk:
    chunk_id: str
    document_id: str
    version_id: str
    source_path: str
    source_sha256: str
    extractor_name: str
    extractor_version: str
    page_number: int | None
    start_char: int | None
    end_char: int | None
    start_line: int | None
    end_line: int | None
    text: str
    heading_path: tuple[str, ...]
    offsets_reliable: bool
    chunker_version: str


@dataclass(frozen=True)
class DocumentVersion:
    workspace_id: str
    document_id: str
    version_id: str
    processing_id: str
    source_path: str
    content_sha256: str
    media_type: str
    extractor_name: str
    extractor_version: str
    chunker_version: str
    pages: tuple[ExtractedPage, ...]
    warnings: tuple[str, ...]
    offsets_reliable: bool


@dataclass(frozen=True)
class IndexedWindow:
    window_id: str
    chunk_id: str
    page_number: int | None
    start_char: int | None
    end_char: int | None
    local_start: int
    local_end: int
    text: str
    vector: tuple[float, ...]


@dataclass(frozen=True)
class IndexedDocument:
    document: DocumentVersion
    chunks: tuple[SourceChunk, ...]
    windows: tuple[IndexedWindow, ...]
    embedding_model_id: str
    embedding_revision: str
    embedding_dimensions: int
    index_generation_id: str
    window_chars: int
    window_overlap_chars: int
    preprocessing_id: str


@dataclass(frozen=True)
class IngestionResult:
    document_id: str
    version_id: str
    content_sha256: str
    chunk_count: int
    window_count: int
    activated: bool
    idempotent: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class IngestionFailure:
    workspace_id: str
    source_path: str
    error_type: str


@dataclass(frozen=True)
class RetrievalFilters:
    document_id: str | None = None
    page_number: int | None = None


@dataclass(frozen=True)
class RetrievalMatch:
    chunk: SourceChunk
    score: float
    score_type: str
    strategy: str
    matched_window_id: str | None = None
    matched_window_start_char: int | None = None
    matched_window_end_char: int | None = None
