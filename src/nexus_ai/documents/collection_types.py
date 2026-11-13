"""Model-independent records and repository contract for extracted collections."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from nexus_ai.documents.types import DocumentVersion, IngestionFailure, SourceChunk


@dataclass(frozen=True)
class CollectionIndex:
    """One fully extracted and chunked document generation, with no embeddings."""

    document: DocumentVersion
    chunks: tuple[SourceChunk, ...]


@dataclass(frozen=True)
class CollectionIndexLimits:
    """Per-run limits bounded by the existing collection intake safety policy."""

    max_documents: int = 150
    max_file_bytes: int = 25 * 1024 * 1024
    max_total_bytes: int = 1024 * 1024 * 1024
    max_pdf_pages: int = 500
    max_pdf_page_chars: int = 2_000_000
    max_total_extracted_chars: int = 10_000_000
    max_chunks_per_document: int = 20_000

    def __post_init__(self) -> None:
        maxima = {
            "max_documents": 150,
            "max_file_bytes": 25 * 1024 * 1024,
            "max_total_bytes": 1024 * 1024 * 1024,
            "max_pdf_pages": 500,
            "max_pdf_page_chars": 2_000_000,
            "max_total_extracted_chars": 10_000_000,
            "max_chunks_per_document": 20_000,
        }
        for name, maximum in maxima.items():
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"{name} must be between 1 and {maximum}")


class CollectionIndexRepository(Protocol):
    """Durable implementations must atomically replace one document generation."""

    def activate(self, indexed: CollectionIndex) -> bool: ...
    def get_active(self, workspace_id: str, document_id: str) -> CollectionIndex | None: ...
    def delete(self, workspace_id: str, document_id: str) -> bool: ...
    def record_failure(self, failure: IngestionFailure) -> None: ...


def validate_collection_workspace_id(workspace_id: str) -> None:
    if not isinstance(workspace_id, str) or not workspace_id.strip() or len(workspace_id) > 128:
        raise ValueError("workspace_id must be a non-empty string of at most 128 characters")
